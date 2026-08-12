"""Bot-facing API routes - used by DentiBot tools to manage appointments."""
from uuid import UUID
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
import os

from backend.database import get_db
from backend.services.appointment_service import create_appointment_logic, get_available_slots, route_professional
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
from backend.models.professional import Professional
from backend.schemas.schemas import (
    BotAppointmentRequest, BotCancelRequest, BotRescheduleRequest, BotQueryRequest,
    BotAvailabilityRequest, AppointmentRead, PatientRead,
)

router = APIRouter(prefix="/api/bot", tags=["Bot"])

# BOT_API_KEY protege los endpoints que el bot usa para operar turnos.
# Sin un valor propio, cualquiera con la key de ejemplo podría agendar,
# cancelar o consultar datos de pacientes, así que la app no debe arrancar
# con el default inseguro.
_INSECURE_BOT_KEY_DEFAULT = "dev-bot-key-change-in-prod"
BOT_API_KEY = os.getenv("BOT_API_KEY")
if not BOT_API_KEY or BOT_API_KEY == _INSECURE_BOT_KEY_DEFAULT:
    raise RuntimeError(
        "BOT_API_KEY no está configurada (o usa el valor de ejemplo). "
        "Definí una BOT_API_KEY propia en las variables de entorno "
        "(debe coincidir en el servicio backend y en el bot)."
    )


def verify_bot_key(x_bot_key: str = Header(...)):
    if x_bot_key != BOT_API_KEY:
        raise HTTPException(403, "Bot API key inválida")


def _phones_match(stored: str | None, requester: str | None) -> bool:
    """Compara dos teléfonos tolerando distintos formatos argentinos.

    Devuelve True si coinciden por E.164 normalizado o por los últimos 8
    dígitos (cubre variantes como 549341..., 0341..., 341..., +54...).
    """
    from backend.services.whatsapp import normalize_to_e164

    if not stored or not requester:
        return False
    if normalize_to_e164(stored) == normalize_to_e164(requester):
        return True
    d_stored = "".join(filter(str.isdigit, stored))
    d_req = "".join(filter(str.isdigit, requester))
    return bool(d_stored) and bool(d_req) and d_stored[-8:] == d_req[-8:]


# Mensaje uniforme cuando el DNI consultado no pertenece a quien escribe.
# No revela si el DNI existe o no, para no filtrar datos.
_OWNERSHIP_ERROR = (
    "Por tu seguridad no puedo gestionar turnos de ese DNI desde este número. "
    "Si es un error, comunicate con la clínica."
)


def _ensure_owns_dni(patient, requester_phone: str | None):
    """Si hay una identidad de canal (WhatsApp), exige que el DNI le pertenezca.

    Si no hay requester_phone (ej. Telegram, que no tiene teléfono), no se
    aplica verificación y se mantiene el comportamiento anterior.
    """
    if requester_phone and not _phones_match(getattr(patient, "phone", None), requester_phone):
        raise HTTPException(403, _OWNERSHIP_ERROR)



# ── Agendar Turno ──────────────────────────────────────
@router.post("/appointments", dependencies=[Depends(verify_bot_key)])
def bot_create_appointment(data: BotAppointmentRequest, db: Session = Depends(get_db)):
    result = create_appointment_logic(
        db=db,
        patient_name=data.patient_name,
        patient_last_name=data.patient_last_name,
        dni=data.dni,
        phone=data.phone,
        reason=data.reason,
        location=data.location,
        insurance_name=data.insurance_name,
        preferred_date=data.preferred_date,
        duration_minutes=data.duration_minutes,
        channel=AppointmentChannel.bot_whatsapp,
        requester_phone=data.requester_phone,
    )
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ── Cancelar Turno ─────────────────────────────────────
@router.post("/cancel", dependencies=[Depends(verify_bot_key)])
async def bot_cancel_appointment(data: BotCancelRequest, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.dni == data.dni, Patient.is_deleted == False).first()
    if not patient:
        raise HTTPException(404, "Paciente no encontrado")

    _ensure_owns_dni(patient, data.requester_phone)

    query = db.query(Appointment).filter(
        Appointment.patient_id == patient.id,
        Appointment.is_deleted == False,
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
    )
    
    if data.appointment_id:
        appt = query.filter(Appointment.id == data.appointment_id).first()
        if not appt:
            raise HTTPException(404, "No se encontró el turno especificado para cancelar")
    else:
        appts = query.order_by(Appointment.start_time).all()
        if not appts:
            raise HTTPException(404, "No se encontraron turnos activos para cancelar")
        if len(appts) > 1:
            appts_list = ", ".join([f"ID: {a.id} el {a.start_time.strftime('%Y-%m-%d %H:%M')}" for a in appts])
            raise HTTPException(400, f"Múltiples turnos encontrados. Por favor especifique cuál cancelar usando su ID: {appts_list}")
        appt = appts[0]

    appt.status = AppointmentStatus.cancelled
    db.commit()

    # Notificar a los admins (cada número por separado para que un fallo no bloquee al resto)
    from backend.models.config import AppConfig
    from backend.services.whatsapp import send_whatsapp_message
    import os

    def get_val(key):
        conf = db.query(AppConfig).filter(AppConfig.key == key).first()
        return conf.value if conf and conf.value else os.getenv(key, "")

    admin_numbers = get_val("ADMIN_NOTIFY_NUMBERS")
    if admin_numbers:
        numbers = [n.strip() for n in admin_numbers.split(",") if n.strip()]
        msg_text = (
            f"⚠️ Turno Cancelado por Bot:\n"
            f"Paciente: {patient.first_name} {patient.last_name} ({patient.dni})\n"
            f"Fecha original: {appt.start_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"Sede: {appt.location}"
        )
        for number in numbers:
            try:
                await send_whatsapp_message(number, msg_text)
                print(f"Admin notificado de cancelación: {number}")
            except Exception as e:
                print(f"Error notifying admin {number} of cancellation: {e}")

    return {"status": "ok", "message": "Turno cancelado exitosamente", "appointment_id": str(appt.id)}


# ── Reprogramar Turno ──────────────────────────────────
@router.post("/reschedule", dependencies=[Depends(verify_bot_key)])
def bot_reschedule_appointment(data: BotRescheduleRequest, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.dni == data.dni, Patient.is_deleted == False).first()
    if not patient:
        raise HTTPException(404, "Paciente no encontrado")

    _ensure_owns_dni(patient, data.requester_phone)

    appt = db.query(Appointment).filter(
        Appointment.id == data.appointment_id,
        Appointment.patient_id == patient.id,
        Appointment.is_deleted == False,
    ).first()
    if not appt:
        raise HTTPException(404, "Turno no encontrado")

    appt.start_time = data.new_start_time
    # Se mantiene confirmado: si volvia a "pending" el recordatorio dejaba de
    # dispararse, porque el loop solo notifica turnos confirmados.
    appt.status = AppointmentStatus.confirmed
    db.commit()
    return {"status": "ok", "message": f"Turno reprogramado para {data.new_start_time}", "appointment_id": str(appt.id)}


# ── Consultar Turnos ───────────────────────────────────
@router.post("/my-appointments", dependencies=[Depends(verify_bot_key)])
def bot_query_appointments(data: BotQueryRequest, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.dni == data.dni, Patient.is_deleted == False).first()
    if not patient:
        raise HTTPException(404, "Paciente no encontrado con ese DNI")

    _ensure_owns_dni(patient, data.requester_phone)

    appts = db.query(Appointment).filter(
        Appointment.patient_id == patient.id,
        Appointment.is_deleted == False,
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
    ).order_by(Appointment.start_time).limit(10).all()

    return {
        "patient": f"{patient.first_name} {patient.last_name}",
        "appointments": [
            {
                "id": str(a.id),
                "date": str(a.start_time),
                "status": a.status.value,
                "reason": a.reason,
                "location": a.location,
                "professional": a.professional.full_name if a.professional else "?",
            }
            for a in appts
        ],
    }


@router.post("/availability", dependencies=[Depends(verify_bot_key)])
def bot_get_availability(data: BotAvailabilityRequest, db: Session = Depends(get_db)):
    # Always use Argentina timezone (UTC-3) as the reference date, never UTC
    from backend.services.appointment_service import get_clinic_now
    argentina_now = get_clinic_now()
    target_date = data.date if data.date else argentina_now.date().isoformat()
    return get_available_slots(db, target_date, data.location, data.reason, data.obra_social)
