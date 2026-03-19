
from datetime import datetime, timedelta, time as py_time
from sqlalchemy.orm import Session
from sqlalchemy import and_
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

def get_available_slots(db: Session, target_date: str, location: str):
    """Calculate free slots for a given date and location."""
    try:
        day = datetime.fromisoformat(target_date).date()
    except Exception:
        day = datetime.utcnow().date()
        
    # Standard working hours: 09:00 to 18:00
    start_of_day = datetime.combine(day, py_time(9, 0))
    end_of_day = datetime.combine(day, py_time(18, 0))
    
    # Existing appointments for that day and location
    existing = db.query(Appointment).filter(
        Appointment.location == location,
        Appointment.is_deleted == False,
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
        Appointment.start_time >= start_of_day,
        Appointment.start_time <= end_of_day
    ).all()
    
    occupied_starts = [a.start_time for a in existing]
    
    slots = []
    current = start_of_day
    # 20 minute slots
    while current < end_of_day:
        # Check if the current slot is occupied
        # (Simplified: check if any appointment starts at this exact time)
        if not any(abs((current - t).total_seconds()) < 1200 for t in occupied_starts):
            # Also don't offer slots in the past
            if current > datetime.utcnow():
                slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=20)
        
    return {
        "date": str(day),
        "location": location,
        "available_slots": slots[:10] # Return top 10
    }
