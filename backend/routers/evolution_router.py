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
from backend.services.whatsapp import send_whatsapp_message, send_whatsapp_list, normalize_to_e164

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
# 20 cubre una conversación completa de agendado (~10 intercambios) sin
# perder contexto de la obra social o el motivo que se dijo al principio.
HISTORY_LIMIT = 20


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

    # Evitar bucles: Ignorar si el mensaje proviene de nuestro propio número
    from_phone_norm = normalize_to_e164(get_config("YCLOUD_FROM_PHONE"))
    if from_phone_norm and normalize_to_e164(from_number) == from_phone_norm:
        # Un mensaje "propio" puede ser el eco del bot o una respuesta que el
        # personal tipeó a mano desde el WhatsApp de la clínica. En el segundo
        # caso el bot no se enteraba y le seguía respondiendo al paciente por
        # su cuenta, pisándose con lo que la persona ya le había dicho.
        #
        # Se distingue comparando con lo último que mandó el bot: si el texto
        # no coincide, lo escribió una persona y el bot se calla un rato en esa
        # conversación. Sin palabras clave que nadie tenga que recordar.
        texto_propio = ""
        if msg_data.get("type") == "text":
            texto_propio = (msg_data.get("text", {}).get("body") or "").strip()
        clean_to = "".join(filter(str.isdigit, to_number or ""))
        if texto_propio and clean_to:
            background_tasks.add_task(
                _quizas_pausar_por_intervencion_humana,
                f"{clean_to}@s.whatsapp.net",
                texto_propio,
            )
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
    elif message_type == "reaction":
        # Reacciones (👍 a un mensaje) — ignorar silenciosamente
        logger.info(f"⏭️ Reacción recibida de {remote_jid}, ignorada")
        return {"status": "ignored_reaction"}
    elif message_type in ("image", "video", "document"):
        # Imágenes, videos, documentos — avisar que no se pueden procesar
        logger.info(f"📎 Archivo {message_type} recibido de {remote_jid}")
        background_tasks.add_task(
            send_whatsapp_message,
            remote_jid,
            "¡Hola! 🦷 Por el momento solo puedo procesar mensajes de *texto* y *audio*. "
            "No puedo ver imágenes, videos ni documentos. "
            "Si necesitás enviar una radiografía o estudio, te recomiendo comunicarte "
            "directamente con la clínica. ¿En qué puedo ayudarte con texto? 😊",
        )
        return {"status": "replied_unsupported_media"}
    elif message_type == "sticker":
        # Stickers — ignorar silenciosamente (no aportan info)
        logger.info(f"⏭️ Sticker recibido de {remote_jid}, ignorado")
        return {"status": "ignored_sticker"}
    elif message_type in ("location", "contacts"):
        logger.info(f"⏭️ {message_type} recibido de {remote_jid}")
        background_tasks.add_task(
            send_whatsapp_message,
            remote_jid,
            "Gracias, pero no puedo procesar ese tipo de mensaje. "
            "¿Puedo ayudarte a agendar, cancelar o consultar un turno? 😊",
        )
        return {"status": "replied_unsupported_type"}

    if text:
        logger.info(f"🤖 Procesando texto: {text}")
        background_tasks.add_task(handle_text_message, remote_jid, text)
        return {"status": "processing_text"}

    logger.warning(f"⚠️ Tipo de mensaje no soportado: {message_type}")
    return {"status": "ignored_unsupported_type"}

def _cargar_estado(session) -> dict:
    """Datos que el paciente ya dio en esta conversación.

    Se guardan en context_data (que ya existía en el modelo para esto) para que
    el modelo no tenga que re-deducirlos leyendo el historial en cada mensaje.
    """
    if not session.context_data:
        return {}
    try:
        datos = json.loads(session.context_data)
        return datos if isinstance(datos, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _guardar_estado(db: Session, session, estado: dict | None):
    if estado is None:
        return
    try:
        session.context_data = json.dumps(estado, ensure_ascii=False)
        db.commit()
    except Exception as e:
        logger.error(f"No se pudo guardar el estado de la conversación: {e}")


# Cuánto se calla el bot cuando una persona toma la conversación.
PAUSA_INTERVENCION_HUMANA = timedelta(minutes=30)


async def _quizas_pausar_por_intervencion_humana(remote_jid: str, texto: str):
    """Pausa el bot si el mensaje propio NO fue del bot, sino de una persona."""
    db = SessionLocal()
    try:
        session = get_or_create_session(db, remote_jid)
        ultimo_bot = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session.id,
                    ChatMessage.role == MessageRole.assistant)
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        # Si coincide con lo último que dijo el bot, es su propio eco.
        if ultimo_bot and ultimo_bot.content.strip()[:120] == texto[:120]:
            return
        session.paused_until = datetime.utcnow() + PAUSA_INTERVENCION_HUMANA
        db.commit()
        logger.info(
            f"🔕 Una persona respondió a mano en {remote_jid}: el bot se calla "
            f"{int(PAUSA_INTERVENCION_HUMANA.total_seconds() // 60)} minutos."
        )
    except Exception as e:
        logger.error(f"Error evaluando intervención humana: {e}")
    finally:
        db.close()


# Frases con las que el paciente pide hablar con una persona.
_PEDIDOS_DE_HUMANO = (
    "hablar con una persona", "hablar con alguien", "atencion humana",
    "atención humana", "con un humano", "operador", "una persona real",
    "no quiero el bot", "hablar con la clinica", "hablar con la clínica",
    "quiero hablar con", "comunicarme con alguien",
)


def _pide_humano(texto: str) -> bool:
    t = (texto or "").lower()
    return any(f in t for f in _PEDIDOS_DE_HUMANO)


def _respuesta_ofrece(texto: str, opciones: list) -> list:
    """Las opciones que la respuesta realmente esta ofreciendo.

    La tool publica los horarios que encontro, pero el modelo puede haberlos
    consultado y despues decir otra cosa (pedir un dato, aclarar algo). Mandar
    una lista que no se corresponde con el texto seria peor que no mandarla,
    asi que solo se ofrecen las opciones que aparecen mencionadas.
    """
    if not opciones:
        return []
    return [o for o in opciones if str(o) in texto]


async def _responder(remote_jid: str, texto: str, opciones: list | None):
    """Manda la respuesta como lista tocable si corresponde, o como texto."""
    ofrecidas = _respuesta_ofrece(texto, opciones or [])
    # Con una sola opcion una lista es mas incomoda que el texto.
    if len(ofrecidas) >= 2:
        enviado = await send_whatsapp_list(
            remote_jid, texto, ofrecidas,
            boton="Elegir horario", titulo="Horarios disponibles",
        )
        if enviado:
            return
    await send_whatsapp_message(remote_jid, texto)


async def handle_text_message(remote_jid: str, text: str):
    # Acquire lock for this user
    if remote_jid not in user_locks:
        user_locks[remote_jid] = asyncio.Lock()
    
    async with user_locks[remote_jid]:
        db = SessionLocal()
        try:
            session = get_or_create_session(db, remote_jid)

            if text.strip().lower() == "reset":
                # Limpia TODO lo que arrastra la conversación, no solo los
                # mensajes: si quedara el estado (obra social, motivo) el bot
                # seguiría "recordando" datos y no sería un arranque de cero;
                # y si quedara la pausa, no volvería a responder.
                db.query(ChatMessage).filter(ChatMessage.session_id == session.id).delete()
                session.context_data = None
                session.paused_until = None
                db.commit()
                await send_whatsapp_message(
                    remote_jid,
                    "✅ Listo, empezamos de cero: borré el historial, los datos que "
                    "habías dado y reactivé el bot.",
                )
                return

            history = load_history(db, session.id)
            
            save_message(db, session.id, MessageRole.user, text)
            
            if get_config("BOT_IS_ACTIVE", "true") == "false":
                logger.info(f"⏸️ Bot pausado (global). Mensaje de {remote_jid} guardado, sin responder.")
                return

            # Alguien de la clínica está atendiendo esta conversación a mano.
            if session.paused_until and session.paused_until > datetime.utcnow():
                logger.info(
                    f"⏸️ Conversación atendida por una persona hasta {session.paused_until}. "
                    f"Mensaje de {remote_jid} guardado, sin responder."
                )
                return

            # El paciente pide hablar con alguien: el bot se corre y avisa.
            if _pide_humano(text):
                session.paused_until = datetime.utcnow() + PAUSA_INTERVENCION_HUMANA
                db.commit()
                logger.info(f"🙋 {remote_jid} pidió hablar con una persona.")
                await send_whatsapp_message(
                    remote_jid,
                    "Dale, aviso a la clínica para que te contacten. 😊 "
                    "En breve te responde una persona del equipo.",
                )
                return
            
            logger.info(f"🧠 Consultando a la IA para {remote_jid}...")
            # Identidad de la conversación: número real de WhatsApp del remitente.
            # Sirve para que el backend verifique que el DNI pertenece a quien escribe.
            requester_phone = normalize_to_e164(remote_jid)
            # chat is sync, run in executor to not block event loop
            loop = asyncio.get_event_loop()
            estado_previo = _cargar_estado(session)
            response, opciones, estado_nuevo = await loop.run_in_executor(
                None, chat, text, history, requester_phone, estado_previo
            )
            logger.info(f"🤖 IA respondió: {response[:50]}...")

            _guardar_estado(db, session, estado_nuevo)
            save_message(db, session.id, MessageRole.assistant, response)
            await _responder(remote_jid, response, opciones)
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
