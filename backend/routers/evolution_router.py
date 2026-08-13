"""YCloud WhatsApp Router - WhatsApp integration."""
import os
import json
import logging
import httpx
import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from bot.ai_agent import chat
from backend.database import get_db, SessionLocal
from backend.models.chat_session import ChatSession, ChatMessage, ChatPlatform, MessageRole
from backend.models.config import AppConfig
from backend.services.whatsapp import send_whatsapp_message, normalize_to_e164

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/whatsapp", tags=["WhatsApp"])

# Global locks to prevent race conditions per user
user_locks = {}

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

# Cantidad de mensajes previos que se le pasan al LLM como contexto.
# Cada mensaje se reenvía en cada llamada, así que subirlo encarece tokens.
# 12 alcanza para mantener el hilo de una conversación de agendado.
HISTORY_LIMIT = 12


def load_history(db: Session, session_id) -> list[dict]:
    # Fetch LATEST N messages, ordered oldest-to-newest for the LLM
    subquery = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at.desc()).limit(HISTORY_LIMIT).all()
    
    # Reverse them to be in chronological order
    subquery.reverse()
    
    print(f"DEBUG: History for {session_id}: {len(subquery)} msgs")
    for m in subquery:
        print(f"  - {m.role.value}: {m.content[:50]}... ({m.created_at})")
        
    return [{"role": m.role.value, "content": m.content} for m in subquery]

def save_message(db: Session, session_id, role: MessageRole, content: str):
    import time
    msg = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(msg)
    db.commit()
    time.sleep(0.02) # Ensure next message has a different timestamp

async def transcribe_audio_url(url: str) -> str:
    """Transcribe audio from URL using OpenAI Whisper."""
    openai_key = get_config("OPENAI_API_KEY")
    if not openai_key:
        logger.warning("⚠️ OpenAI API Key missing! Cannot transcribe audio.")
        return ""
    
    async with httpx.AsyncClient() as client:
        # Check if URL is from YCloud, requiring API key authorization
        headers = {}
        if "ycloud.com" in url:
            api_key = get_config("YCLOUD_API_KEY")
            if api_key:
                headers["X-API-Key"] = api_key
        
        # Download file
        try:
            logger.info(f"📥 Downloading audio from {url}...")
            audio_resp = await client.get(url, headers=headers)
            if audio_resp.status_code != 200:
                logger.error(f"❌ Failed to download audio: status {audio_resp.status_code}")
                return ""
        except Exception as e:
            logger.error(f"❌ Exception downloading audio: {e}")
            return ""
        
        file_path = f"/tmp/wa_audio_{datetime.now().timestamp()}.ogg"
        with open(file_path, "wb") as f:
            f.write(audio_resp.content)
            
        try:
            # Transcribe
            logger.info("🎙️ Sending audio file to Whisper for transcription...")
            openai_headers = {"Authorization": f"Bearer {openai_key}"}
            with open(file_path, "rb") as f:
                trans_files = {"file": ("audio.ogg", f, "audio/ogg"), "model": (None, "whisper-1")}
                trans_url = "https://api.openai.com/v1/audio/transcriptions"
                r = await client.post(trans_url, headers=openai_headers, files=trans_files, timeout=60)
                r.raise_for_status()
                transcribed_text = r.json()["text"]
                logger.info(f"✅ Whisper transcription success: {transcribed_text[:100]}...")
                return transcribed_text
        except Exception as e:
            logger.error(f"❌ WhatsApp transcription error: {e}")
            return ""
        finally:
            if os.path.exists(file_path):
                os.remove(file_path)
    return ""

@router.post("/webhook")
async def ycloud_webhook(request: Request, background_tasks: BackgroundTasks):
    """YCloud WhatsApp Webhook handler."""
    try:
        payload = await request.json()
        logger.info(f"📩 Webhook de YCloud recibido: {json.dumps(payload, indent=2)}")
    except Exception:
        logger.error("❌ Error al parsear JSON del webhook")
        return {"status": "error", "message": "Invalid JSON"}

    event_type = payload.get("type")
    if event_type != "whatsapp.inbound_message.received":
        logger.info(f"⏭️ Evento ignorado (no es inbound message): {event_type}")
        return {"status": "ignored"}

    msg_data = payload.get("whatsappInboundMessage", {})
    if not msg_data:
        logger.warning("⚠️ No se encontró whatsappInboundMessage en el payload")
        return {"status": "ignored_no_message_data"}

    from_number = msg_data.get("from")
    to_number = msg_data.get("to")
    
    if not from_number:
        logger.warning("⚠️ Mensaje sin número de origen ('from')")
        return {"status": "ignored_no_sender"}

    # Un mensaje que llega "desde nuestro propio número" es el eco de algo que
    # salió de ESTE número: puede ser el eco del propio bot, o -lo importante-
    # una respuesta que el personal tipeó a mano desde el WhatsApp linkeado a
    # este número. En ese segundo caso el sistema no se enteraba de nada y el
    # bot le seguía respondiendo al paciente por su cuenta, pisándose con lo
    # que el personal ya le había dicho (ver commit de esta fecha).
    #
    # Se habilitan dos palabras clave para que el personal pause/reactive al
    # bot en ESA conversación puntual, sin tocar el resto de los pacientes:
    # "#pausa" y "#reactivar", tipeadas directamente en el chat de WhatsApp.
    from_phone_norm = normalize_to_e164(get_config("YCLOUD_FROM_PHONE"))
    if from_phone_norm and normalize_to_e164(from_number) == from_phone_norm:
        texto_propio = ""
        if msg_data.get("type") == "text":
            texto_propio = (msg_data.get("text", {}).get("body") or "").strip().lower()

        if texto_propio in ("#pausa", "#reactivar"):
            # OJO: en un mensaje "propio", el paciente es el destinatario (to),
            # no el remitente (from, que somos nosotros).
            clean_to = "".join(filter(str.isdigit, to_number or ""))
            if clean_to:
                remote_jid_paciente = f"{clean_to}@s.whatsapp.net"
                background_tasks.add_task(handle_pause_command, remote_jid_paciente, texto_propio)
                return {"status": "pause_command"}

        logger.info("⏭️ Mensaje enviado por nosotros mismos (ignorado)")
        return {"status": "ignored_self"}

    # Formato JID para compatibilidad hacia atrás en la base de datos (ej: 549341xxxxxxx@s.whatsapp.net)
    clean_from = "".join(filter(str.isdigit, from_number))
    remote_jid = f"{clean_from}@s.whatsapp.net"

    text = ""
    message_type = msg_data.get("type")
    logger.info(f"📝 Tipo de mensaje: {message_type} de {remote_jid}")

    if message_type == "text":
        text = msg_data.get("text", {}).get("body", "")
    elif message_type == "audio":
        audio_url = msg_data.get("audio", {}).get("link")
        if audio_url:
            logger.info("🎙️ Procesando mensaje de audio...")
            background_tasks.add_task(handle_audio_message, remote_jid, audio_url)
            return {"status": "processing_audio"}
    elif message_type == "interactive":
        # Manejar respuestas interactivas de botones o listas
        interactive = msg_data.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            text = interactive.get("button_reply", {}).get("title", "")
        elif interactive_type == "list_reply":
            text = interactive.get("list_reply", {}).get("title", "")

    if text:
        logger.info(f"🤖 Procesando texto: {text}")
        background_tasks.add_task(handle_text_message, remote_jid, text)
        return {"status": "processing_text"}

    logger.warning("⚠️ Mensaje sin contenido de texto, interactivo o audio soportado")
    return {"status": "ignored_unsupported_type"}

async def handle_pause_command(remote_jid: str, comando: str):
    """Pausa o reactiva al bot para UN paciente puntual, sin tocar a los demás.

    Se ejecuta como background task, igual que los mensajes normales, para no
    demorar la respuesta al webhook.
    """
    db = SessionLocal()
    try:
        session = get_or_create_session(db, remote_jid)
        if comando == "#pausa":
            # 24hs de margen: si el personal se olvida de escribir "#reactivar",
            # el paciente no se queda sin bot para siempre.
            session.paused_until = datetime.utcnow() + timedelta(hours=24)
            logger.info(f"🔕 Bot pausado para {remote_jid} (24hs o hasta #reactivar)")
        else:
            session.paused_until = None
            logger.info(f"🔔 Bot reactivado para {remote_jid}")
        db.commit()
    finally:
        db.close()


async def handle_text_message(remote_jid: str, text: str):
    # Acquire lock for this user
    if remote_jid not in user_locks:
        user_locks[remote_jid] = asyncio.Lock()
    
    async with user_locks[remote_jid]:
        db = SessionLocal()
        try:
            session = get_or_create_session(db, remote_jid)

            if text.strip().lower() == "reset":
                db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
                db.commit()
                await send_whatsapp_message(remote_jid, "✅ Historial borrado. Empecemos de cero.")
                return

            history = load_history(db, session.id)
            
            save_message(db, session.id, MessageRole.user, text)
            
            if get_config("BOT_IS_ACTIVE", "true") == "false":
                logger.info(f"⏸️ Bot pausado (global). Mensaje de {remote_jid} guardado, pero no se responde.")
                return

            if session.paused_until and session.paused_until > datetime.utcnow():
                logger.info(f"⏸️ Bot pausado en esta conversación hasta {session.paused_until} "
                           f"(personal atendiendo a mano). Mensaje de {remote_jid} guardado, pero no se responde.")
                return
            
            logger.info(f"🧠 Consultando a la IA para {remote_jid}...")
            # Identidad de la conversación: número real de WhatsApp del remitente.
            # Sirve para que el backend verifique que el DNI pertenece a quien escribe.
            requester_phone = normalize_to_e164(remote_jid)
            # chat is sync, run in executor to not block event loop
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, chat, text, history, requester_phone)
            logger.info(f"🤖 IA respondió: {response[:50]}...")
            
            save_message(db, session.id, MessageRole.assistant, response)
            await send_whatsapp_message(remote_jid, response)
        except Exception as e:
            logger.error(f"Error handling WA text: {e}")
            await send_whatsapp_message(remote_jid, "Lo siento, tuve un problema interno al procesar tu mensaje. Por favor, avisale al administrador que revise la configuración de la Inteligencia Artificial (API Keys o Modelos).")
        finally:
            db.close()

async def handle_audio_message(remote_jid: str, url: str):
    text = await transcribe_audio_url(url)
    if text:
        await handle_text_message(remote_jid, f"[Audio Transcrito]: {text}")
    else:
        await send_whatsapp_message(remote_jid, "No pude procesar tu audio. ¿Podrías escribir o intentar de nuevo?")
