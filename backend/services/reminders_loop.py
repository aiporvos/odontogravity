import asyncio
import httpx
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.database import SessionLocal
from backend.models.appointment import Appointment, AppointmentStatus
from backend.models.patient import Patient
from backend.models.config import AppConfig
import os

logger = logging.getLogger(__name__)

def get_config(db: Session, key: str, default: str = ""):
    conf = db.query(AppConfig).filter(AppConfig.key == key).first()
    if conf and conf.value:
        return conf.value
    return os.getenv(key, default)

from backend.services.whatsapp import (
    send_whatsapp_message, send_whatsapp_template, ofuscar_telefono,
    PLANTILLA_RECORDATORIO, IDIOMA_PLANTILLA,
)


# La ventana de servicio de WhatsApp: 24 h desde el ultimo mensaje DEL PACIENTE.
# Dentro de ella el texto libre es gratis; fuera, WhatsApp lo rechaza y hay que
# usar una plantilla aprobada (que se cobra, pero llega).
VENTANA_SERVICIO = timedelta(hours=24)


def dentro_de_la_ventana(db: Session, telefono: str) -> bool:
    """Si ese paciente escribio en las ultimas 24 horas."""
    from backend.models.chat_session import ChatSession, ChatMessage, MessageRole

    digitos = "".join(filter(str.isdigit, (telefono or "")))
    if len(digitos) < 8:
        return False

    ultimo = (
        db.query(ChatMessage.created_at)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .filter(
            ChatSession.platform_user_id.like(f"%{digitos[-8:]}%"),
            ChatMessage.role == MessageRole.user,
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )
    return bool(ultimo) and (datetime.utcnow() - ultimo[0]) < VENTANA_SERVICIO


async def enviar_recordatorio(db: Session, appt, patient, time_str: str,
                              cancel_link: str, msg: str) -> bool:
    """Manda el recordatorio por el canal que corresponda. Devuelve si llego.

    Dentro de la ventana de servicio va texto libre, que es gratis. Fuera va la
    plantilla, unica forma de reabrir la conversacion. Si la plantilla todavia
    no esta aprobada por Meta, se intenta el texto igual: puede fallar, pero es
    mejor intentarlo que no mandar nada.
    """
    # Una ficha cargada desde la agenda de papel puede no tener telefono. No
    # hay a donde mandar: se informa el fallo en vez de intentar tres envios
    # que van a fallar los tres.
    if not (patient.phone or "").strip():
        logger.warning("⚠️ %s %s no tiene telefono: sin recordatorio (turno %s)",
                       patient.first_name, patient.last_name, appt.id)
        return False

    if dentro_de_la_ventana(db, patient.phone):
        if await send_whatsapp_message(patient.phone, msg):
            return True
        # Estaba en la ventana y aun asi fallo: se intenta la plantilla.

    if await send_whatsapp_template(
        patient.phone, PLANTILLA_RECORDATORIO, IDIOMA_PLANTILLA,
        [patient.first_name, time_str, appt.location or "el consultorio"],
        parametro_boton=str(appt.id),
    ):
        return True

    # Ultimo intento: quiza la plantilla no esta aprobada todavia.
    return await send_whatsapp_message(patient.phone, msg)

async def notify_admins(db: Session, text: str):
    admin_numbers = get_config(db, "ADMIN_NOTIFY_NUMBERS", "")
    if not admin_numbers:
        return
    for number in admin_numbers.split(","):
        number = number.strip()
        if number:
            await send_whatsapp_message(number, text)

async def check_reminders():
    while True:
        try:
            db = SessionLocal()
            hours_val = get_config(db, "REMINDER_HOURS_BEFORE", "24")
            hours_before = int(hours_val) if hours_val else 24
            from backend.services.urls import url_publica
            public_url = url_publica(db)

            # Appointments are stored in Argentina time (UTC-3), so compare in Argentina time
            from backend.services.appointment_service import get_clinic_now
            now = get_clinic_now()
            target_time = now + timedelta(hours=hours_before)

            # 15-minute window to avoid missing appointments between runs
            start_window = target_time
            end_window = target_time + timedelta(minutes=15)
            
            # Note: in a real app it's better to have a 'reminded_at' column to avoid double-sending
            appointments = db.query(Appointment).join(Patient).filter(
                Appointment.status == AppointmentStatus.confirmed,
                Appointment.is_deleted == False,
                Appointment.start_time >= start_window,
                Appointment.start_time < end_window
            ).all()
            
            for appt in appointments:
                patient = appt.patient
                # Appointments stored in Argentina time, display as-is
                time_str = appt.start_time.strftime("%d/%m/%Y a las %H:%M")
                cancel_link = f"{public_url}/api/public/cancel/{appt.id}"

                msg = (
                    f"Hola {patient.first_name}, te recordamos tu turno en Silprodent "
                    f"el {time_str} en nuestra sede de {appt.location}.\n\n"
                    f"Si no podés asistir, por favor cancelálo en el siguiente link:\n{cancel_link}"
                )
                # Antes esto decia "Recordatorio enviado" pasara lo que pasara:
                # send_whatsapp_message se tragaba el rechazo de WhatsApp y el
                # log reportaba un exito que no habia ocurrido.
                if await enviar_recordatorio(db, appt, patient, time_str, cancel_link, msg):
                    logger.info("✅ Recordatorio enviado a %s para el turno %s",
                                ofuscar_telefono(patient.phone), appt.id)
                else:
                    logger.error(
                        "❌ NO se pudo enviar el recordatorio a %s para el turno %s. "
                        "Si la plantilla '%s' todavía no está aprobada por Meta, los "
                        "recordatorios fuera de la ventana de 24 h no van a llegar.",
                        ofuscar_telefono(patient.phone), appt.id, PLANTILLA_RECORDATORIO,
                    )
                
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        finally:
            if 'db' in locals():
                db.close()
        
        await asyncio.sleep(15 * 60) # check every 15 mins

def start_reminders_loop():
    asyncio.create_task(check_reminders())
