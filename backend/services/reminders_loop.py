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

from backend.services.whatsapp import send_whatsapp_message

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
                await send_whatsapp_message(patient.phone, msg)
                logger.info(f"Recordatorio enviado a {patient.phone} para turno {appt.id}")
                
        except Exception as e:
            logger.error(f"Reminder loop error: {e}")
        finally:
            if 'db' in locals():
                db.close()
        
        await asyncio.sleep(15 * 60) # check every 15 mins

def start_reminders_loop():
    asyncio.create_task(check_reminders())
