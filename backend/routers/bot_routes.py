"""Bot-facing API routes - used by DentiBot tools to manage appointments."""
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
import os

from backend.database import get_db
from backend.services.appointment_service import create_appointment_logic, get_available_slots
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
from backend.models.professional import Professional
from backend.schemas.schemas import (
    BotAppointmentRequest, BotCancelRequest, BotRescheduleRequest, BotQueryRequest,
    AppointmentRead, PatientRead,
)

router = APIRouter(prefix="/api/bot", tags=["Bot"])

BOT_API_KEY = os.getenv("BOT_API_KEY", "dev-bot-key-change-in-prod")


def verify_bot_key(x_bot_key: str = Header(...)):
    if x_bot_key != BOT_API_KEY:
        raise HTTPException(403, "Bot API key inválida")


# ── Routing Logic ──────────────────────────────────────
ROUTING_MAP = {
    "extracciones": "Dr. Silvestro",
    "extracción": "Dr. Silvestro",
    "implantes": "Dr. Silvestro",
    "implante": "Dr. Silvestro",
    "prótesis": "Dr. Silvestro",
    "protesis": "Dr. Silvestro",
    "ortodoncia": "Dra. Murad",
    "conductos": "Dra. Murad",
    "conducto": "Dra. Murad",
    "endodoncia": "Dra. Murad",
}


def route_professional(reason: str, db: Session) -> Professional | None:
    reason_lower = reason.lower()
    for keyword, prof_name in ROUTING_MAP.items():
        if keyword in reason_lower:
            prof = db.query(Professional).filter(
                Professional.full_name.ilike(f"%{prof_name.split('.')[-1].strip()}%"),
                Professional.is_deleted == False,
            ).first()
            if prof:
                return prof
    # Default: return first available professional
    return db.query(Professional).filter(Professional.is_deleted == False, Professional.is_active == True).first()


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
        channel=AppointmentChannel.bot_whatsapp
    )
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ── Cancelar Turno ─────────────────────────────────────
@router.post("/cancel", dependencies=[Depends(verify_bot_key)])
def bot_cancel_appointment(data: BotCancelRequest, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.dni == data.dni, Patient.is_deleted == False).first()
    if not patient:
        raise HTTPException(404, "Paciente no encontrado")

    query = db.query(Appointment).filter(
        Appointment.patient_id == patient.id,
        Appointment.is_deleted == False,
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
    )
    if data.appointment_id:
        query = query.filter(Appointment.id == data.appointment_id)

    appt = query.order_by(Appointment.start_time).first()
    if not appt:
        raise HTTPException(404, "No se encontró turno para cancelar")

    appt.status = AppointmentStatus.cancelled
    db.commit()
    return {"status": "ok", "message": "Turno cancelado exitosamente", "appointment_id": str(appt.id)}


# ── Reprogramar Turno ──────────────────────────────────
@router.post("/reschedule", dependencies=[Depends(verify_bot_key)])
def bot_reschedule_appointment(data: BotRescheduleRequest, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.dni == data.dni, Patient.is_deleted == False).first()
    if not patient:
        raise HTTPException(404, "Paciente no encontrado")

    appt = db.query(Appointment).filter(
        Appointment.id == data.appointment_id,
        Appointment.patient_id == patient.id,
        Appointment.is_deleted == False,
    ).first()
    if not appt:
        raise HTTPException(404, "Turno no encontrado")

    appt.start_time = data.new_start_time
    appt.status = AppointmentStatus.pending
    db.commit()
    return {"status": "ok", "message": f"Turno reprogramado para {data.new_start_time}", "appointment_id": str(appt.id)}


# ── Consultar Turnos ───────────────────────────────────
@router.post("/my-appointments", dependencies=[Depends(verify_bot_key)])
def bot_query_appointments(data: BotQueryRequest, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.dni == data.dni, Patient.is_deleted == False).first()
    if not patient:
        raise HTTPException(404, "Paciente no encontrado con ese DNI")

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
def bot_get_availability(data: BotQueryRequest, db: Session = Depends(get_db)):
    # Reusing BotQueryRequest because it has 'dni', but technically we only need date/location.
    # Actually, I'll allow an optional location and date.
    # For now, let's keep it simple.
    # We'll use a new schema if needed, but for now BotQueryRequest is fine (or we can just use raw dict).
    return get_available_slots(db, datetime.utcnow().isoformat(), "San Rafael")
