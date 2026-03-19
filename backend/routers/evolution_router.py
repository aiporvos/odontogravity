"""Evolution API Router - WhatsApp integration."""
import os
import json
import logging
import httpx
import asyncio
from datetime import datetime
from fastapi import APIRouter, Request, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from bot.ai_agent import chat
from backend.database import get_db, SessionLocal
from backend.models.chat_session import ChatSession, ChatMessage, ChatPlatform, MessageRole
from backend.models.config import AppConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

def get_config(key: str, default: str = ""):
    db = SessionLocal()
    try:
        conf = db.query(AppConfig).filter(AppConfig.key == key).first()
        if conf and conf.value:
            return conf.value
    except Exception:
        pass
    finally:
        db.close()
    return os.getenv(key, default)

# Config will be read at runtime in the send function

def get_or_create_session(db: Session, platform_user_id: str):
    session = db.query(ChatSession).filter(
        ChatSession.platform == ChatPlatform.whatsapp,
        ChatSession.platform_user_id == platform_user_id,
        ChatSession.is_active == True,
    ).first()
    if not session:
        session = ChatSession(
            platform=ChatPlatform.whatsapp,
            platform_user_id=platform_user_id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    return session

def load_history(db: Session, session_id) -> list[dict]:
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at).limit(20).all()
    return [{"role": m.role.value, "content": m.content} for m in messages]

def save_message(db: Session, session_id, role: MessageRole, content: str):
    msg = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(msg)
    db.commit()

async def send_whatsapp_message(number: str, text: str):
    """Send message back through Evolution API."""
    url_base = get_config("EVOLUTION_API_URL", "").rstrip("/")
    api_key = get_config("EVOLUTION_API_KEY", "")
    instance = get_config("EVOLUTION_INSTANCE_ID", "")
    
    logger.info(f"🔍 Audit Config -> URL: {url_base}, KEY: {api_key[:5] if api_key else 'EMPTY'}, INST: {instance}")

    if not url_base or not api_key or not instance:
        logger.warning(f"❌ Evolution API config missing! URL={bool(url_base)}, KEY={bool(api_key)}, INST={bool(instance)}")
        return

    url = f"{url_base}/message/sendText/{instance}"
    headers = {
        "apikey": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "number": number,
        "text": text
    }
    
    async with httpx.AsyncClient() as client:
        try:
            logger.info(f"📤 Enviando mensaje a WA ({number}). URL: {url}")
            r = await client.post(url, json=payload, headers=headers)
            logger.info(f"📥 Respuesta de Evolution API: {r.status_code} - {r.text}")
            r.raise_for_status()
        except Exception as e:
            logger.error(f"❌ Error al enviar mensaje de WhatsApp: {e}")

async def transcribe_audio_url(url: str) -> str:
    """Transcribe audio from URL using OpenAI Whisper."""
    openai_key = get_config("OPENAI_API_KEY")
    if not openai_key:
        return ""
    
    async with httpx.AsyncClient() as client:
        # Download file
        audio_resp = await client.get(url)
        if audio_resp.status_code != 200:
            return ""
        
        file_path = f"/tmp/wa_audio_{datetime.now().timestamp()}.ogg"
        with open(file_path, "wb") as f:
            f.write(audio_resp.content)
            
        try:
            # Transcribe
            headers = {"Authorization": f"Bearer {openai_key}"}
            with open(file_path, "rb") as f:
                trans_files = {"file": ("audio.ogg", f, "audio/ogg"), "model": (None, "whisper-1")}
                trans_url = "https://api.openai.com/v1/audio/transcriptions"
                r = await client.post(trans_url, headers=headers, files=trans_files, timeout=60)
                r.raise_for_status()
                return r.json()["text"]
        except Exception as e:
            logger.error(f"WhatsApp transcription error: {e}")
            return ""
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
    return ""

@router.post("/webhook")
async def evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    """Evolution API Webhook handler."""
    try:
        payload = await request.json()
        logger.info(f"📩 Webhook de Evolution recibido: {json.dumps(payload, indent=2)}")
        print(f"DEBUG: Webhook WA recibido: {payload.get('event')}")
    except Exception:
        logger.error("❌ Error al parsear JSON del webhook")
        print("DEBUG: Error al parsear JSON")
        return {"status": "error", "message": "Invalid JSON"}

    event = payload.get("event")
    if event != "messages.upsert":
        logger.info(f"⏭️ Evento ignorado: {event}")
        return {"status": "ignored"}

    data = payload.get("data", {})
    message = data.get("message", {})
    key = data.get("key", {})
    
    if key.get("fromMe"):
        logger.info("⏭️ Mensaje propio (ignorado)")
        return {"status": "ignored_self"}

    remote_jid = key.get("remoteJid")
    if not remote_jid or ("@s.whatsapp.net" not in remote_jid and "@lid" not in remote_jid):
        logger.info(f"⏭️ JID ignorado (no es chat privado): {remote_jid}")
        print(f"DEBUG: JID ignorado: {remote_jid}")
        return {"status": "ignored_non_private"}

    text = ""
    message_type = data.get("messageType")
    
    logger.info(f"📝 Tipo de mensaje: {message_type} de {remote_jid}")

    if message_type == "conversation":
        text = message.get("conversation")
    elif message_type == "extendedTextMessage":
        text = message.get("extendedTextMessage", {}).get("text")
    elif message_type == "audioMessage":
        audio_url = message.get("audioMessage", {}).get("url")
        if audio_url:
            logger.info("🎙️ Procesando mensaje de audio...")
            background_tasks.add_task(handle_audio_message, remote_jid, audio_url)
            return {"status": "processing_audio"}
    
    if text:
        logger.info(f"🤖 Procesando texto: {text}")
        background_tasks.add_task(handle_text_message, remote_jid, text)
        return {"status": "processing_text"}

    logger.warning("⚠️ Mensaje sin contenido de texto o audio")
    return {"status": "ignored_empty"}

async def handle_text_message(remote_jid: str, text: str):
    db = SessionLocal()
    try:
        session = get_or_create_session(db, remote_jid)
        history = load_history(db, session.id)
        
        save_message(db, session.id, MessageRole.user, text)
        
        logger.info(f"🧠 Consultando a la IA para {remote_jid}...")
        # chat is sync, run in executor to not block event loop (and allow tool calls to this same server)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, chat, text, history)
        logger.info(f"🤖 IA respondió: {response[:50]}...")
        
        save_message(db, session.id, MessageRole.assistant, response)
        
        await send_whatsapp_message(remote_jid, response)
    except Exception as e:
        logger.error(f"Error handling WA text: {e}")
    finally:
        db.close()

async def handle_audio_message(remote_jid: str, url: str):
    text = await transcribe_audio_url(url)
    if text:
        await handle_text_message(remote_jid, f"[Audio Transcrito]: {text}")
    else:
        await send_whatsapp_message(remote_jid, "No pude procesar tu audio. ¿Podrías escribir o intentar de nuevo?")
