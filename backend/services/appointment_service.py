
from datetime import datetime, timedelta, time as py_time
from sqlalchemy.orm import Session
from sqlalchemy import and_
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
from backend.models.professional import Professional
from backend.models.schedule import ClinicSchedule, ProfessionalTimeOff

# Maps reason keywords to professional LAST NAMES as stored in DB
# DB has: 'Dr. Silvestro' and 'Dra. Murad'
ROUTING_MAP = {
    "extracciones": "Silvestro",
    "extracción": "Silvestro",
    "extraccion": "Silvestro",
    "implantes": "Silvestro",
    "implante": "Silvestro",
    "prótesis": "Silvestro",
    "protesis": "Silvestro",
    "cirugía": "Silvestro",
    "cirugia": "Silvestro",
    "ortodoncia": "Murad",
    "conductos": "Murad",
    "conducto": "Murad",
    "endodoncia": "Murad",
    "limpieza": "Murad",
    "consulta": "Murad",
    "revisión": "Murad",
    "revision": "Murad",
}

import httpx

CLINIC_TZ_OFFSET = -3 # UTC-3 for Argentina
_time_cache = {"time": None, "fetched_at": None}

def get_clinic_now():
    """Returns the current time in the clinic's timezone, guaranteed by external API."""
    global _time_cache
    now_sys = datetime.utcnow()
    
    if _time_cache["time"] and _time_cache["fetched_at"] and (now_sys - _time_cache["fetched_at"]).total_seconds() < 600:
        return _time_cache["time"] + (now_sys - _time_cache["fetched_at"])
        
    try:
        r = httpx.get("http://worldtimeapi.org/api/timezone/America/Argentina/Buenos_Aires", timeout=3.0)
        if r.status_code == 200:
            dt_str = r.json()["datetime"]
            real_time = datetime.fromisoformat(dt_str).replace(tzinfo=None)
            _time_cache["time"] = real_time
            _time_cache["fetched_at"] = now_sys
            return real_time
    except Exception:
        pass
        
    # Fallback
    return datetime.utcnow() + timedelta(hours=CLINIC_TZ_OFFSET)

def route_professional(reason: str, db: Session) -> Professional | None:
    """Route to the correct professional based on the reason keyword. Uses last-name search."""
    reason_lower = reason.lower()
    for keyword, last_name in ROUTING_MAP.items():
        if keyword in reason_lower:
            prof = db.query(Professional).filter(
                Professional.full_name.ilike(f"%{last_name}%"),
                Professional.is_deleted == False,
            ).first()
            if prof:
                return prof
    # Fallback: return first active professional
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
    duration_minutes: int = 30,
    requester_phone: str = None,
):
    # Find or create patient
    patient = db.query(Patient).filter(Patient.dni == dni, Patient.is_deleted == False).first()
    if not patient:
        # Para pacientes nuevos preferimos el número real del canal (WhatsApp)
        # como teléfono: es la identidad verificada que luego usamos para
        # comprobar la propiedad de los turnos. Si no lo hay (ej. Telegram),
        # usamos el teléfono que declaró el paciente.
        patient = Patient(
            first_name=patient_name,
            last_name=patient_last_name,
            dni=dni,
            phone=requester_phone or phone,
            insurance_name=insurance_name,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
    else:
        # Paciente existente: refrescar con los datos obligatorios que tomó el
        # bot. Teléfono y obra social se actualizan siempre (el último dato es
        # el más vigente). Nombre/Apellido solo si están vacíos, para no pisar
        # correcciones hechas desde el panel por recepción.
        new_phone = requester_phone or phone
        if new_phone:
            patient.phone = new_phone
        if insurance_name:
            patient.insurance_name = insurance_name
        if patient_name and not (patient.first_name or "").strip():
            patient.first_name = patient_name
        if patient_last_name and not (patient.last_name or "").strip():
            patient.last_name = patient_last_name
        db.commit()
        db.refresh(patient)

    # Route professional
    prof = route_professional(reason, db)
    if not prof:
        return {"error": "No hay profesionales disponibles"}

    # Parse date - preferred_date is required, never default to now
    if not preferred_date or not preferred_date.strip():
        return {"error": "Se requiere la fecha y hora del turno (preferred_date). El bot debe pasar la fecha exacta que eligió el paciente."}
    try:
        start = datetime.fromisoformat(preferred_date.strip())
    except Exception:
        return {"error": f"Formato de fecha inválido: '{preferred_date}'. Usar formato YYYY-MM-DD HH:MM."}

    appt = Appointment(
        patient_id=patient.id,
        professional_id=prof.id,
        start_time=start,
        duration_minutes=duration_minutes if duration_minutes else 30,
        reason=reason,
        location=location,
        insurance_name=insurance_name,
        channel=channel,
        status=AppointmentStatus.confirmed,
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

def get_available_slots(db: Session, target_date: str, location: str, reason: str, obra_social: str = "Particular", recursive_depth=0):
    """Calculate free slots for a given date and location based on clinic schedule."""
    clinic_now = get_clinic_now()
    try:
        # If target_date is a full ISO string, we take the date part
        day_dt = datetime.fromisoformat(target_date)
        day = day_dt.date()
    except Exception:
        day = clinic_now.date()
        
    weekday = day.weekday() # 0=Mon, 2=Wed
        
    # Regla PAMI: solo viernes
    if obra_social and obra_social.upper() == "PAMI" and weekday != 4:
        if recursive_depth < 14:
            return get_available_slots(db, (day + timedelta(days=1)).isoformat(), location, reason, obra_social, recursive_depth + 1)
        return {"date": str(day), "location": location, "available_slots": [], "message": "No hay turnos disponibles para PAMI en las próximas semanas."}

    # Profesional asignado por el motivo (necesario para chequear ausencias)
    prof = route_professional(reason, db)
    prof_name = prof.full_name if prof else "Cualquier profesional disponible"

    # Horario de la clínica para ese día (configurable desde el panel)
    schedule_rows = db.query(ClinicSchedule).filter(
        ClinicSchedule.weekday == weekday,
        ClinicSchedule.is_active == True,
    ).order_by(ClinicSchedule.start_time).all()
    shifts = [(r.start_time, r.end_time) for r in schedule_rows]

    # Si el profesional está ausente ese día, no se ofrece
    if prof:
        absent = db.query(ProfessionalTimeOff).filter(
            ProfessionalTimeOff.professional_id == prof.id,
            ProfessionalTimeOff.date == day,
        ).first()
        if absent:
            shifts = []

    if not shifts:
        # Día cerrado o profesional ausente: buscar el próximo día con disponibilidad
        if recursive_depth < 14:
            return get_available_slots(db, (day + timedelta(days=1)).isoformat(), location, reason, obra_social, recursive_depth + 1)
        return {"date": str(day), "location": location, "available_slots": [], "message": "Sin disponibilidad en las próximas dos semanas."}

    # Existing appointments for that day and location
    start_of_day = datetime.combine(day, py_time(0, 0))
    end_of_day = datetime.combine(day, py_time(23, 59))
    
    query = db.query(Appointment).filter(
        Appointment.location == location,
        Appointment.is_deleted == False,
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
        Appointment.start_time >= start_of_day,
        Appointment.start_time <= end_of_day
    )
    if prof:
        query = query.filter(Appointment.professional_id == prof.id)
        
    existing = query.all()
    
    occupied_ranges = []
    for a in existing:
        occupied_ranges.append((a.start_time, a.start_time + timedelta(minutes=a.duration_minutes)))
    
    # Determine duration based on reason
    duration_minutes = 15
    reason_lower = reason.lower()
    if any(x in reason_lower for x in ["extracc", "ortodoncia", "implante", "prótesis", "protesis"]):
        duration_minutes = 30
    elif any(x in reason_lower for x in ["conducto", "endodoncia"]):
        duration_minutes = 60

    available_slots = []
    for shift_start_time, shift_end_time in shifts:
        current = datetime.combine(day, shift_start_time)
        shift_end = datetime.combine(day, shift_end_time)
        
        while current + timedelta(minutes=duration_minutes) <= shift_end:
            slot_end = current + timedelta(minutes=duration_minutes)
            is_occupied = False
            for occ_start, occ_end in occupied_ranges:
                if current < occ_end and occ_start < slot_end:
                    is_occupied = True
                    break
            
            if not is_occupied and current > clinic_now:
                available_slots.append(current.strftime("%H:%M"))
            
            current += timedelta(minutes=duration_minutes)
    
    # If no slots found for today, auto-search next available day
    if not available_slots and recursive_depth < 14:
        return get_available_slots(db, (day + timedelta(days=1)).isoformat(), location, reason, obra_social, recursive_depth + 1)
        
    return {
        "date": str(day),
        "location": location,
        "professional": prof_name,
        "available_slots": available_slots[:4]
    }
