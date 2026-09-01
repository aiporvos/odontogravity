"""YCloud WhatsApp Router - WhatsApp integration."""
import os
import re
import json
import hmac
import time
import hashlib
import logging
import httpx
import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from bot.ai_agent import chat
from backend.database import get_db, SessionLocal
from backend.models.chat_session import ChatSession, ChatMessage, ChatPlatform, MessageRole
from backend.models.config import AppConfig
from backend.services.whatsapp import (
    send_whatsapp_message, send_whatsapp_list, send_whatsapp_buttons,
    normalize_to_e164, ofuscar_telefono,
)

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


# Los mensajes de hace muchas horas no son la misma conversación. Antes se
# cargaban los últimos 20 sin mirar la fecha, así que el bot podía retomar a
# mitad de camino una charla de hace semanas, como si el paciente nunca se
# hubiera ido. La ficha del paciente (quien_me_escribe) da la continuidad que
# de verdad importa; el hilo textual viejo solo confunde.
VENTANA_CONVERSACION = timedelta(hours=6)


def load_history(db: Session, session_id) -> list[dict]:
    # Fetch LATEST N messages, ordered oldest-to-newest for the LLM
    corte = datetime.utcnow() - VENTANA_CONVERSACION
    subquery = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.created_at >= corte,
    ).order_by(ChatMessage.created_at.desc()).limit(HISTORY_LIMIT).all()
    
    # Reverse them to be in chronological order
    subquery.reverse()
    
    # Antes esto hacia print() del contenido de cada mensaje: la conversacion
    # entera del paciente quedaba en stdout del contenedor.
    logger.debug("Historial de %s: %d mensajes", session_id, len(subquery))

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

# ── Autenticacion del webhook ────────────────────────────────────────────────
# Sin esto el endpoint aceptaba cualquier POST y creia el numero que viniera en
# el campo "from". Todo el modelo de identidad del bot (que un paciente solo
# pueda ver y cancelar SUS turnos) se apoya en ese dato, asi que cualquiera que
# conociera la URL podia hacerse pasar por otro paciente.
#
# YCloud firma cada evento con HMAC-SHA256 sobre "{timestamp}.{body}" y lo manda
# en el header YCloud-Signature con el formato "t=<unix>,s=<hex>".
TOLERANCIA_FIRMA = 300  # segundos; descarta reenvios viejos (replay)


def _firma_valida(raw: bytes, header: str | None, secreto: str) -> bool:
    if not header:
        return False
    try:
        partes = dict(p.split("=", 1) for p in header.split(","))
        ts, firma = partes["t"], partes["s"]
    except (ValueError, KeyError):
        return False

    try:
        if abs(time.time() - int(ts)) > TOLERANCIA_FIRMA:
            logger.warning("🔒 Webhook con timestamp fuera de tolerancia (posible replay).")
            return False
    except ValueError:
        return False

    esperada = hmac.new(
        secreto.encode(), f"{ts}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(firma, esperada)


def _autenticar_webhook(raw: bytes, header: str | None):
    """Corta el request si no viene firmado por YCloud.

    Si no hay secreto configurado no se puede verificar nada: se deja pasar
    pero se avisa fuerte en el log, para que no quede abierto por olvido.
    ENFORCE existe para poder desactivarlo desde el panel en una emergencia
    sin tener que redesplegar.
    """
    secreto = (get_config("YCLOUD_WEBHOOK_SECRET") or "").strip()
    if not secreto:
        logger.warning(
            "🔓 YCLOUD_WEBHOOK_SECRET sin configurar: el webhook acepta cualquier "
            "origen. Cargalo en Configuración → Integraciones y en el panel de YCloud."
        )
        return
    valida = _firma_valida(raw, header, secreto)

    if (get_config("YCLOUD_WEBHOOK_ENFORCE", "true") or "true").strip().lower() == "false":
        # Modo ensayo: no rechaza nada, pero deja dicho en el log si la firma
        # HABRIA pasado. Sirve para activar la verificacion sin arriesgarse a
        # dejar el bot mudo: se despliega asi, se manda un WhatsApp de prueba,
        # se mira el log y recien despues se pone ENFORCE en true.
        if valida:
            logger.warning(
                "🧪 Verificación en modo ENSAYO (ENFORCE=false). La firma de este "
                "mensaje es VÁLIDA ✅ — el secreto es correcto y ya podés poner "
                "YCLOUD_WEBHOOK_ENFORCE=true."
            )
        else:
            logger.error(
                "🧪 Verificación en modo ENSAYO (ENFORCE=false). La firma de este "
                "mensaje NO valida ❌ — si activaras ENFORCE ahora, el bot dejaría "
                "de responder. Revisá que YCLOUD_WEBHOOK_SECRET sea el secreto del "
                "endpoint en YCloud."
            )
        return

    if not valida:
        logger.error(
            "🔒 Webhook rechazado: firma inválida o ausente. Si el bot dejó de "
            "responder, poné YCLOUD_WEBHOOK_ENFORCE=false para volver al aire "
            "mientras revisás el secreto."
        )
        raise HTTPException(401, "Invalid signature")


@router.post("/webhook")
async def ycloud_webhook(request: Request, background_tasks: BackgroundTasks):
    """YCloud WhatsApp Webhook handler."""
    raw = await request.body()
    _autenticar_webhook(raw, request.headers.get("YCloud-Signature"))

    try:
        payload = json.loads(raw)
        # El payload trae el telefono y el texto del paciente. En INFO eso deja
        # datos de salud en los logs del contenedor, asi que solo va el tipo de
        # evento; el detalle completo queda en DEBUG.
        logger.info(f"📩 Webhook de YCloud: {payload.get('type')}")
        logger.debug(f"Payload completo: {json.dumps(payload, indent=2)}")
    except Exception:
        logger.error("❌ Error al parsear JSON del webhook")
        return {"status": "error", "message": "Invalid JSON"}

    event_type = payload.get("type")

    # La secretaria contestando desde el WhatsApp de la clínica. Este evento
    # llega SOLO cuando el mensaje se escribió a mano desde la app (lo que sale
    # por la API no lo dispara), asi que todo eco es una persona real tomando la
    # conversacion y el bot tiene que correrse.
    #
    # Sin esto el bot no se enteraba y seguia respondiendo en paralelo: paso en
    # vivo con pacientes, con la secretaria teniendo que aclarar "ESTA
    # CONTESTANDO EL ASISTENTE VIRTUAL TAMBIEN JAJA".
    if event_type == "whatsapp.smb.message.echoes":
        eco = payload.get("whatsappMessage", {})
        paciente = "".join(filter(str.isdigit, eco.get("to") or ""))
        texto_humano = (eco.get("text", {}) or {}).get("body", "") or ""
        if paciente:
            background_tasks.add_task(
                _pausar_por_intervencion_humana,
                f"{paciente}@s.whatsapp.net",
                texto_humano,
            )
        return {"status": "human_takeover"}

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
        logger.info(f"📎 Archivo {message_type} recibido de {ofuscar_telefono(remote_jid)}")
        if bot_silenciado(remote_jid):
            return {"status": "silenciado"}
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
        logger.info(f"⏭️ Sticker recibido de {ofuscar_telefono(remote_jid)}, ignorado")
        return {"status": "ignored_sticker"}
    elif message_type in ("location", "contacts"):
        logger.info(f"⏭️ {message_type} recibido de {ofuscar_telefono(remote_jid)}")
        if bot_silenciado(remote_jid):
            return {"status": "silenciado"}
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


def bot_silenciado(remote_jid: str) -> bool:
    """Si el bot NO debe responder nada en esa conversacion, ni siquiera un aviso.

    La pausa se verificaba solo dentro de handle_text_message, asi que las
    respuestas automaticas a archivos, ubicaciones y contactos se disparaban
    igual desde el webhook. Un paciente mando un PDF con el bot pausado y le
    contesto "solo puedo procesar texto y audio", pisandose con la secretaria
    que estaba atendiendo esa conversacion a mano.

    Cubre las dos formas de silencio: el interruptor global del panel y la pausa
    por intervencion humana en esta conversacion puntual.
    """
    if (get_config("BOT_IS_ACTIVE", "true") or "true").strip().lower() == "false":
        logger.info("⏸️ Bot pausado (global): no se responde a %s.",
                    ofuscar_telefono(remote_jid))
        return True

    db = SessionLocal()
    try:
        session = get_or_create_session(db, remote_jid)
        if session.paused_until and session.paused_until > datetime.utcnow():
            logger.info(
                "⏸️ Conversación atendida por una persona hasta %s: no se responde a %s.",
                session.paused_until, ofuscar_telefono(remote_jid),
            )
            return True
        return False
    except Exception as e:
        logger.error(f"Error verificando si el bot está pausado: {e}", exc_info=True)
        return False   # ante la duda, responder: peor es dejar al paciente sin nada
    finally:
        db.close()


def _minutos_de_pausa() -> int:
    """Cuanto se calla el bot cuando alguien de la clinica toma la conversacion.

    Configurable desde el panel: media hora alcanza para una consulta puntual,
    pero si la secretaria se queda atendiendo el caso entero conviene subirlo.
    """
    try:
        return max(1, int((get_config("MINUTOS_PAUSA_HUMANA", "30") or "30").strip()))
    except (TypeError, ValueError):
        return 30


async def _pausar_por_intervencion_humana(remote_jid: str, texto: str):
    """Silencia el bot en esa conversacion y guarda lo que dijo la persona.

    El texto se guarda como parte del historial para que, si el bot vuelve a
    responder cuando venza la pausa, sepa lo que ya le dijeron al paciente en
    vez de arrancar de cero y contradecir a la secretaria.
    """
    db = SessionLocal()
    try:
        session = get_or_create_session(db, remote_jid)
        minutos = _minutos_de_pausa()
        session.paused_until = datetime.utcnow() + timedelta(minutes=minutos)
        db.commit()
        if texto.strip():
            save_message(db, session.id, MessageRole.assistant, texto.strip())
        logger.info(
            "🔕 Alguien de la clínica contestó a mano en %s: el bot se calla %d minutos.",
            ofuscar_telefono(remote_jid), minutos,
        )
    except Exception as e:
        logger.error(f"Error pausando por intervención humana: {e}", exc_info=True)
    finally:
        db.close()


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


# ── Garantías por código sobre lo que responde el modelo ─────────────────────
# El prompt le pide al modelo que no se repita y que no se presente dos veces.
# En producción no lo cumple: se presentaba en CADA mensaje ("¡Buenas noches!
# Soy DentiBot...") y repetía la misma pregunta palabra por palabra cuando la
# respuesta del paciente no le servía. Un prompt es un pedido; esto es una
# garantía.

_PRESENTACION = re.compile(
    r"^[¡!]*\s*(hola|buen[oa]?s?\s+(d[ií]as?|tardes|noches))?[!¡.,\s]*"
    r"soy\s+dentibot[^.!?\n]*[.!?\n]+\s*",
    re.IGNORECASE,
)

# Saludo suelto al principio, con o sin el nombre del paciente detrás:
# "¡Buenas noches, Claudio! 😊", "Hola Claudio,", "Buen día!".
# El modelo lo repetía en cada mensaje de la misma conversación, y la regex
# anterior solo cazaba el caso que además decía "soy DentiBot".
_SALUDO_SUELTO = re.compile(
    r"^[¡!]*\s*(hola|buen[oa]?s?\s+(d[ií]as?|tardes|noches))"
    r"[^.!?\n]{0,40}?[!¡.,]+[\s\U0001F300-\U0001FAFF☀-➿]*",
    re.IGNORECASE,
)


def quitar_presentacion(texto: str) -> str:
    """Saca el saludo inicial cuando la charla ya venía empezada.

    Primero el "Soy DentiBot...", después un saludo suelto si quedó. Se hace por
    código y no por prompt porque el prompt ya lo pedía y el modelo igual
    saludaba de nuevo: pedir no es garantizar.
    """
    limpio = _PRESENTACION.sub("", texto, count=1).lstrip()
    if limpio == texto:
        limpio = _SALUDO_SUELTO.sub("", texto, count=1).lstrip()
    # Si al sacarlo no queda nada útil, se deja el original.
    return limpio if len(limpio) > 15 else texto


def _normalizar(texto: str) -> str:
    return " ".join((texto or "").lower().split())


def es_repeticion(nueva: str, anteriores: list[str]) -> bool:
    """True si el bot está por decir casi lo mismo que ya dijo.

    Compara contra sus últimas respuestas. Sin esto, si el paciente contesta
    algo que el modelo no logra interpretar, se queda haciendo la misma
    pregunta indefinidamente.
    """
    n = _normalizar(nueva)
    if len(n) < 20:
        return False
    for previa in anteriores:
        pv = _normalizar(previa)
        if not pv:
            continue
        if n == pv:
            return True
        # Casi iguales: mismo arranque largo (reformulaciones mínimas).
        corto = min(len(n), len(pv))
        if corto > 60 and n[:60] == pv[:60]:
            return True
    return False


# Que opciones se le ofrecieron en el mensaje anterior. Sirve para distinguir
# "el bot se trabo repitiendo lo mismo" de "el bot repite la frase pero le esta
# mostrando otra cosa", que es progreso legitimo.
CLAVE_ULTIMAS_OPCIONES = "ultimas_opciones"


def _firma_opciones(publicadas: dict | None) -> str:
    if not publicadas:
        return ""
    return "|".join(str(o) for o in (publicadas.get("opciones") or []))


def debe_derivar_por_loop(respuesta: str, anteriores: list[str],
                          opciones: dict | None, estado_previo: dict | None) -> bool:
    """Si el bot esta realmente trabado y conviene pasarle la charla a alguien.

    Repetir el texto no alcanza como sintoma. Si ademas esta ofreciendo opciones
    distintas de las del mensaje anterior, la conversacion avanzo aunque la
    frase se parezca: es lo que pasa al buscar una obra social, donde primero se
    muestran las frecuentes y despues las que matchean las letras que escribio
    el paciente.
    """
    if not es_repeticion(respuesta, anteriores):
        return False
    firma = _firma_opciones(opciones)
    if firma and firma != (estado_previo or {}).get(CLAVE_ULTIMAS_OPCIONES):
        return False
    return True


SALIDA_DE_LOOP = (
    "Perdón, me parece que no nos estamos entendiendo. 🙏\n"
    "Le paso tu consulta a alguien del equipo para que te ayude directamente. "
    "En un rato te escriben."
)


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


async def _responder(remote_jid: str, texto: str, publicadas: dict | None):
    """Manda la respuesta como lista tocable si corresponde, o como texto."""
    if not publicadas:
        await send_whatsapp_message(remote_jid, texto)
        return

    opciones = publicadas.get("opciones") or []
    # Las obras sociales se ofrecen siempre: la gracia es que el paciente no
    # tenga que escribirlas. Los horarios, solo si el texto los menciona.
    ofrecidas = opciones if publicadas.get("siempre") else _respuesta_ofrece(texto, opciones)

    # Eleccion binaria (obra social / particular): botones, que se tocan sin
    # abrir ningun menu.
    if publicadas.get("tipo") == "botones" and 2 <= len(ofrecidas) <= 3:
        if await send_whatsapp_buttons(remote_jid, texto, ofrecidas):
            return

    # Con una sola opcion una lista es mas incomoda que el texto.
    if len(ofrecidas) >= 2:
        enviado = await send_whatsapp_list(
            remote_jid, texto, ofrecidas,
            boton=publicadas.get("boton") or "Elegir horario",
            titulo=publicadas.get("titulo") or "Horarios disponibles",
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

            # Con barra o sin barra: cualquiera escribe "/reset" por
            # costumbre de Telegram, y antes eso se procesaba como un mensaje
            # normal y no reseteaba nada.
            if text.strip().lower().lstrip("/") == "reset":
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

            # 1) Si la charla ya venía empezada, no se vuelve a presentar.
            if history:
                response = quitar_presentacion(response)

            # 2) Si está por repetir lo mismo que ya dijo, se corta y deriva.
            #
            # Salvo que esté ofreciendo opciones DISTINTAS: ahí el texto se
            # parece pero la conversación sí avanzó. Es el caso de las obras
            # sociales, donde el bot primero muestra las frecuentes y después
            # las filtradas por las letras que pasó el paciente: dos mensajes
            # casi iguales con listas diferentes. Sin esta excepción, escribir
            # "sw" para buscar Swiss Medical hacía que el bot se disculpara y
            # se derivara solo a una persona.
            ultimas = [m["content"] for m in history if m["role"] == "assistant"][-2:]
            if debe_derivar_por_loop(response, ultimas, opciones, estado_previo):
                logger.warning(f"🔁 Respuesta repetida para {remote_jid}: se deriva a una persona.")
                session.paused_until = datetime.utcnow() + PAUSA_INTERVENCION_HUMANA
                db.commit()
                response, opciones = SALIDA_DE_LOOP, None

            estado_nuevo = dict(estado_nuevo or {})
            estado_nuevo[CLAVE_ULTIMAS_OPCIONES] = _firma_opciones(opciones)
            _guardar_estado(db, session, estado_nuevo)
            save_message(db, session.id, MessageRole.assistant, response)
            await _responder(remote_jid, response, opciones)
        except Exception as e:
            logger.error(f"Error handling WA text: {e}", exc_info=True)
            # El aviso de error tambien es una respuesta del bot: si algo fallo
            # ANTES de llegar al chequeo de pausa, este mensaje se colaba igual
            # con el bot apagado.
            if not bot_silenciado(remote_jid):
                await send_whatsapp_message(
                    remote_jid,
                    "Lo siento, tuve un problema interno al procesar tu mensaje. "
                    "Por favor, avisale al administrador que revise la configuración "
                    "de la Inteligencia Artificial (API Keys o Modelos).",
                )
        finally:
            db.close()

async def handle_audio_message(remote_jid: str, url: str):
    text = await transcribe_audio_url(url)
    if text:
        await handle_text_message(remote_jid, f"[Audio Transcrito]: {text}")
    elif not bot_silenciado(remote_jid):
        # El aviso de "no pude procesar tu audio" tambien es una respuesta del
        # bot: si esta pausado, tampoco corresponde mandarlo.
        await send_whatsapp_message(
            remote_jid, "No pude procesar tu audio. ¿Podrías escribir o intentar de nuevo?"
        )
