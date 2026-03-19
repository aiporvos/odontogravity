
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
from backend.models.professional import Professional

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
    return db.query(Professional).filter(Professional.is_deleted == False, Professional.is_active == True).first()

def create_appointment_logic(
    db: Session,
    patient_name: str,
    patient_last_name: str,
    dni: str,
    phone: str,
    reason: str,
    location: str,
    insurance_name: str = None,
    preferred_date: str = None,
    channel: AppointmentChannel = AppointmentChannel.bot_whatsapp
):
    # Find or create patient
    patient = db.query(Patient).filter(Patient.dni == dni, Patient.is_deleted == False).first()
    if not patient:
        patient = Patient(
            first_name=patient_name,
            last_name=patient_last_name,
            dni=dni,
            phone=phone,
            insurance_name=insurance_name,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)

    # Route professional
    prof = route_professional(reason, db)
    if not prof:
        return {"error": "No hay profesionales disponibles"}

    # Parse date
    try:
        start = datetime.fromisoformat(preferred_date) if preferred_date else datetime.utcnow()
    except Exception:
        start = datetime.utcnow()

    appt = Appointment(
        patient_id=patient.id,
        professional_id=prof.id,
        start_time=start,
        reason=reason,
        location=location,
        channel=channel,
        status=AppointmentStatus.pending,
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)

    return {
        "status": "ok",
        "message": f"Turno agendado con {prof.full_name} en {location}",
        "appointment_id": str(appt.id),
        "professional": prof.full_name,
        "datetime": str(appt.start_time),
    }
