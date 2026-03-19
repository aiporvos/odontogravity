
from datetime import datetime, timedelta, time as py_time
from sqlalchemy.orm import Session
from sqlalchemy import and_
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
from backend.models.professional import Professional

ROUTING_MAP = {
    "extracciones": "Martin Silvestro",
    "extracción": "Martin Silvestro",
    "implantes": "Martin Silvestro",
    "implante": "Martin Silvestro",
    "prótesis": "Martin Silvestro",
    "protesis": "Martin Silvestro",
    "ortodoncia": "Helena Murad",
    "conductos": "Helena Murad",
    "conducto": "Helena Murad",
    "endodoncia": "Helena Murad",
}

CLINIC_TZ_OFFSET = -3 # UTC-3 for Argentina

def get_clinic_now():
    """Returns the current time in the clinic's timezone."""
    return datetime.utcnow() + timedelta(hours=CLINIC_TZ_OFFSET)

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
    channel: AppointmentChannel = AppointmentChannel.bot_whatsapp,
    duration_minutes: int = 30
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
        start = datetime.fromisoformat(preferred_date) if preferred_date else get_clinic_now()
    except Exception:
        start = get_clinic_now()

    appt = Appointment(
        patient_id=patient.id,
        professional_id=prof.id,
        start_time=start,
        duration_minutes=duration_minutes if duration_minutes else 30,
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

def get_available_slots(db: Session, target_date: str, location: str, recursive_depth=0):
    """Calculate free slots for a given date and location based on clinic schedule."""
    clinic_now = get_clinic_now()
    try:
        # If target_date is a full ISO string, we take the date part
        day_dt = datetime.fromisoformat(target_date)
        day = day_dt.date()
    except Exception:
        day = clinic_now.date()
        
    weekday = day.weekday() # 0=Mon, 2=Wed
        
    # Clinic schedule:
    # Mon-Fri: 09:00 - 12:30
    # Mon-Fri (except Wed): 17:00 - 20:30
    
    shifts = []
    if weekday < 5: # Mon-Fri
        shifts.append((py_time(9, 0), py_time(12, 30)))
        if weekday != 2: # Not Wednesday
            shifts.append((py_time(17, 0), py_time(20, 30)))
    
    if not shifts:
        # If it's a weekend, try next Monday if we are auto-searching
        if recursive_depth < 7: # Search up to a week
            return get_available_slots(db, (day + timedelta(days=1)).isoformat(), location, recursive_depth + 1)
        return {"date": str(day), "location": location, "available_slots": [], "message": "Cerrado los fines de semana."}

    # Existing appointments for that day and location
    start_of_day = datetime.combine(day, py_time(0, 0))
    end_of_day = datetime.combine(day, py_time(23, 59))
    
    existing = db.query(Appointment).filter(
        Appointment.location == location,
        Appointment.is_deleted == False,
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
        Appointment.start_time >= start_of_day,
        Appointment.start_time <= end_of_day
    ).all()
    
    occupied_ranges = []
    for a in existing:
        occupied_ranges.append((a.start_time, a.start_time + timedelta(minutes=a.duration_minutes)))
    
    available_slots = []
    for shift_start_time, shift_end_time in shifts:
        current = datetime.combine(day, shift_start_time)
        shift_end = datetime.combine(day, shift_end_time)
        
        while current + timedelta(minutes=15) <= shift_end:
            slot_end = current + timedelta(minutes=15)
            is_occupied = False
            for occ_start, occ_end in occupied_ranges:
                if current < occ_end and occ_start < slot_end:
                    is_occupied = True
                    break
            
            if not is_occupied and current > clinic_now:
                available_slots.append(current.strftime("%H:%M"))
            
            current += timedelta(minutes=15)
    
    # If no slots found for today, auto-search next available day
    if not available_slots and recursive_depth < 7:
        return get_available_slots(db, (day + timedelta(days=1)).isoformat(), location, recursive_depth + 1)
        
    return {
        "date": str(day),
        "location": location,
        "available_slots": available_slots[:15]
    }
