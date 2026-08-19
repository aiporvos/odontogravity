"""WhatsApp Service - Integration with YCloud API."""
import os
import logging
import httpx
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models.config import AppConfig

logger = logging.getLogger(__name__)

def get_config(key: str, default: str = "") -> str:
    """Helper to fetch config from DB AppConfig table or environment variables."""
    db = SessionLocal()
    try:
        conf = db.query(AppConfig).filter(AppConfig.key == key).first()
        if conf and conf.value:
            return conf.value
    except Exception as e:
        logger.warning(f"Error fetching config '{key}' from database: {e}")
    finally:
        db.close()
    return os.getenv(key, default)

def normalize_to_e164(number: str) -> str:
    """Normalizes phone number to strict E.164 format with '+' prefix for YCloud."""
    if not number:
        return ""
        
    # Remove any JID suffix (like @s.whatsapp.net), spaces, dashes, parentheses
    clean_num = number.split("@")[0]
    clean_num = "".join(filter(str.isdigit, clean_num))
    
    if not clean_num:
        return ""
    
    # Argentinian normalization logic:
    # WhatsApp numbers from YCloud/Meta webhooks come as "549341xxxxxxx".
    # Local input might be "0341..." or "15..." or "341..." or "+549...".
    if clean_num.startswith("0"):
        clean_num = clean_num[1:]
    
    # Argentina country code is 54. Mobile prefix is 9.
    # If it does not start with 54, we prepend 549 (assumes primary market is Argentina)
    if not clean_num.startswith("54"):
        clean_num = "549" + clean_num
    elif clean_num.startswith("54") and not clean_num.startswith("549") and len(clean_num) == 12:
        # e.g., 54341xxxxxxx (length 12) -> convert to 549341xxxxxxx
        clean_num = "549" + clean_num[2:]
        
    return f"+{clean_num}"

async def send_whatsapp_message(number: str, text: str):
    """Sends a WhatsApp text message using YCloud API."""
    api_key = get_config("YCLOUD_API_KEY", "")
    from_phone = get_config("YCLOUD_FROM_PHONE", "")
    
    if not api_key:
        # Fallback to check if EVOLUTION config exists for compatibility
        logger.warning("YCLOUD_API_KEY is not configured. Checking for Evolution API fallback...")
        url_base = get_config("EVOLUTION_API_URL", "").rstrip("/")
        evo_key = get_config("EVOLUTION_API_KEY", "")
        instance = get_config("EVOLUTION_INSTANCE_ID", "")
        
        if url_base and evo_key and instance:
            # Fallback legacy Evolution sending
            url = f"{url_base}/message/sendText/{instance}"
            headers = {
                "apikey": evo_key,
                "Content-Type": "application/json"
            }
            # Evolution uses number with JID suffix or plain
            payload = {"number": number, "text": text}
            async with httpx.AsyncClient() as client:
                try:
                    logger.info(f"📤 Fallback Evolution: Sending message to {number} via {url}")
                    r = await client.post(url, json=payload, headers=headers)
                    logger.info(f"📥 Fallback Evolution Response: {r.status_code} - {r.text}")
                    r.raise_for_status()
                except Exception as e:
                    logger.error(f"❌ Fallback Evolution error: {e}")
            return
        
        logger.warning("❌ No WhatsApp configuration found (neither YCloud nor Evolution)!")
        return

    # Prepare YCloud request
    # YCloud requires phone numbers to start with '+'
    to_phone = normalize_to_e164(number)
    from_phone_norm = normalize_to_e164(from_phone)
    
    if not to_phone:
        logger.error(f"❌ Invalid recipient phone number format: {number}")
        return
        
    if not from_phone_norm:
        logger.error(f"❌ Invalid YCLOUD_FROM_PHONE configuration: {from_phone}")
        return

    url = "https://api.ycloud.com/v2/whatsapp/messages"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json"
    }
    payload = {
        "from": from_phone_norm,
        "to": to_phone,
        "type": "text",
        "text": {
            "body": text
        }
    }
    
    async with httpx.AsyncClient() as client:
        try:
            logger.info(f"📤 Sending WhatsApp message via YCloud to {to_phone} from {from_phone_norm}")
            r = await client.post(url, json=payload, headers=headers)
            logger.info(f"📥 YCloud API response: {r.status_code} - {r.text}")
            r.raise_for_status()
        except Exception as e:
            logger.error(f"❌ Failed to send WhatsApp message via YCloud: {e}")


# ── Mensajes interactivos ────────────────────────────────────────────────────
# Hasta ahora el bot solo mandaba texto plano, asi que el paciente tenia que
# tipear la obra social, el motivo y el horario. De ahi salian cosas como
# "Pami" cargado como motivo de consulta. Con listas y botones elige de
# opciones cerradas y esos errores desaparecen.
#
# Limites de WhatsApp: 10 filas por lista (sumando todas las secciones), 3
# botones, y 20 caracteres por titulo de fila o boton. Si se pasa, la API
# rechaza el mensaje entero, asi que se recorta y se avisa en el log.

MAX_FILAS_LISTA = 10
MAX_BOTONES = 3
MAX_TITULO = 20


async def _enviar_interactivo(number: str, payload_interactivo: dict, texto_fallback: str) -> bool:
    """Manda un mensaje interactivo. Si falla, cae a texto plano.

    Devuelve True si se mando como interactivo. El fallback importa: si YCloud
    rechaza el formato, es preferible que el paciente reciba el texto a que no
    reciba nada.
    """
    api_key = get_config("YCLOUD_API_KEY", "")
    from_phone = get_config("YCLOUD_FROM_PHONE", "")
    to_phone = normalize_to_e164(number)
    from_phone_norm = normalize_to_e164(from_phone)

    if not (api_key and to_phone and from_phone_norm):
        await send_whatsapp_message(number, texto_fallback)
        return False

    payload = {
        "from": from_phone_norm,
        "to": to_phone,
        "type": "interactive",
        "interactive": payload_interactivo,
    }
    async with httpx.AsyncClient() as client:
        try:
            r = await client.post(
                "https://api.ycloud.com/v2/whatsapp/messages",
                json=payload,
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
            )
            if r.status_code >= 400:
                logger.error(f"❌ YCloud rechazó el interactivo ({r.status_code}): {r.text[:300]}")
                await send_whatsapp_message(number, texto_fallback)
                return False
            logger.info(f"📤 Interactivo enviado a {to_phone}")
            return True
        except Exception as e:
            logger.error(f"❌ Error enviando interactivo: {e}")
            await send_whatsapp_message(number, texto_fallback)
            return False


async def send_whatsapp_list(number: str, cuerpo: str, opciones: list[str],
                             boton: str = "Ver opciones", titulo: str | None = None) -> bool:
    """Lista tocable de una sola sección. `opciones` son los textos a elegir."""
    filas = []
    for i, op in enumerate(opciones[:MAX_FILAS_LISTA]):
        filas.append({"id": f"op_{i}", "title": str(op)[:MAX_TITULO]})
    if len(opciones) > MAX_FILAS_LISTA:
        logger.warning(f"Lista recortada de {len(opciones)} a {MAX_FILAS_LISTA} opciones")
    if not filas:
        await send_whatsapp_message(number, cuerpo)
        return False

    interactivo = {
        "type": "list",
        "body": {"text": cuerpo},
        "action": {
            "button": boton[:MAX_TITULO],
            "sections": [{"title": (titulo or "Opciones")[:24], "rows": filas}],
        },
    }
    fallback = cuerpo + "\n\n" + "\n".join(f"• {o}" for o in opciones[:MAX_FILAS_LISTA])
    return await _enviar_interactivo(number, interactivo, fallback)


async def send_whatsapp_buttons(number: str, cuerpo: str, botones: list[str]) -> bool:
    """Hasta 3 botones de respuesta rápida (ej: Sí / No)."""
    acciones = [
        {"type": "reply", "reply": {"id": f"btn_{i}", "title": str(b)[:MAX_TITULO]}}
        for i, b in enumerate(botones[:MAX_BOTONES])
    ]
    if not acciones:
        await send_whatsapp_message(number, cuerpo)
        return False

    interactivo = {
        "type": "button",
        "body": {"text": cuerpo},
        "action": {"buttons": acciones},
    }
    fallback = cuerpo + "\n\n" + " / ".join(botones[:MAX_BOTONES])
    return await _enviar_interactivo(number, interactivo, fallback)
