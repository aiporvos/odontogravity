
from datetime import datetime, timedelta, time as py_time
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
from backend.models.professional import Professional
from backend.models.schedule import ClinicSchedule, ProfessionalTimeOff, ClinicHoliday
from backend.models.config import AppConfig

# El ruteo por motivo sale de las especialidades que cada profesional tiene
# cargadas en su ficha (Profesionales -> Especialidades), no de un mapa fijo en
# el codigo. Asi la clinica lo cambia sola sin tocar el backend.
_STOPWORDS = {"de", "del", "la", "el", "y", "e", "los", "las", "un", "una",
              "en", "para", "por", "con", "al", "a"}


def _sin_acentos(texto: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def _palabras(texto: str) -> list[str]:
    limpio = "".join(c if c.isalnum() else " " for c in _sin_acentos(texto))
    return [p for p in limpio.split() if p not in _STOPWORDS and len(p) >= 3]


def _misma_palabra(a: str, b: str) -> bool:
    """Compara tolerando singular/plural: extraccion == extracciones."""
    n = min(len(a), len(b))
    return n >= 4 and a[:n] == b[:n]


def _especialidad_coincide(especialidad: str, palabras_motivo: list[str]) -> bool:
    """True si todas las palabras significativas de la especialidad estan en el motivo.

    Se exigen todas para evitar falsos positivos: "tratamiento de conducto" no
    matchea con "tratamiento de caries" porque falta "conducto".
    """
    requeridas = _palabras(especialidad)
    if not requeridas:
        return False
    return all(
        any(_misma_palabra(req, pal) for pal in palabras_motivo)
        for req in requeridas
    )


def match_insurance(nombre: str, db: Session):
    """Busca la obra social entre las activas. Devuelve el registro o None.

    La comparacion la hacia el modelo contra una lista dentro del prompt, y se
    le escapaban casos: aceptaba obras sociales que la clinica no atiende. Aca
    es deterministico. Tolera mayusculas, acentos y variantes como "OSDE 210",
    pero no confunde nombres parecidos: "osep" y "osde" no matchean entre si.
    """
    from backend.models.insurance import Insurance

    buscado = " ".join(_sin_acentos(nombre or "").split())
    if not buscado:
        return None

    # Se compara por palabras completas, no por substring: "OSPE" es una obra
    # social distinta de "OSPELSYM" y no debe darse por cubierta. Ante la duda
    # conviene devolver None: el bot avisa que no esta cubierta y el paciente
    # corrige, que es mejor que agendar con una cobertura que no se atiende.
    palabras_buscado = {p for p in buscado.split() if len(p) >= 3}

    activas = db.query(Insurance).filter(Insurance.is_active == True).all()
    for ins in activas:
        candidato = " ".join(_sin_acentos(ins.name).split())
        if not candidato:
            continue
        if buscado == candidato:
            return ins
        if ins.code and _sin_acentos(ins.code).strip() == buscado:
            return ins

        palabras_candidato = {p for p in candidato.split() if len(p) >= 3}
        if not palabras_buscado or not palabras_candidato:
            continue
        # "OSDE 210" contiene a "OSDE"; "Swiss" es parte de "Swiss Medical".
        if palabras_candidato <= palabras_buscado or palabras_buscado <= palabras_candidato:
            return ins
    return None


def find_professionals_for_reason(reason: str, db: Session) -> list[Professional]:
    """Profesionales que atienden ese motivo, segun sus especialidades cargadas.

    Si ninguno matchea (motivo vacio, generico o especialidad no cargada) se
    devuelven todos los activos: es preferible ofrecer turno con cualquiera
    antes que dejar al paciente sin respuesta.
    """
    activos = db.query(Professional).filter(
        Professional.is_deleted == False,
        Professional.is_active == True,
    ).order_by(Professional.full_name).all()

    palabras = _palabras(reason or "")
    if not palabras:
        return activos

    coinciden = [
        p for p in activos
        if any(_especialidad_coincide(e, palabras) for e in (p.specialties or []))
    ]
    return coinciden or activos


def route_professional(reason: str, db: Session) -> Professional | None:
    """El profesional asignado a un motivo. Si lo atienden varios, el primero."""
    candidatos = find_professionals_for_reason(reason, db)
    return candidatos[0] if candidatos else None


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

def get_chairs_per_location(db: Session) -> int:
    """Cuantos turnos pueden solaparse en una misma sede (sillones disponibles).

    Configurable desde el panel con la clave CHAIRS_PER_LOCATION. El default es 1
    (un solo sillon: cualquier solapamiento ocupa el horario), pero una clinica
    con varios sillones puede subirlo sin tocar codigo.
    """
    cfg = db.query(AppConfig).filter(AppConfig.key == "CHAIRS_PER_LOCATION").first()
    try:
        return max(1, int((cfg.value if cfg and cfg.value else "1").strip()))
    except (TypeError, ValueError):
        return 1


def get_day_appointments(db: Session, day, location: str | None):
    """Turnos activos de una sede en un dia, para calcular ocupacion.

    Incluye los que tienen la sede en NULL: son los que se cargaron desde el
    panel antes de que el formulario pidiera sede, y en SQL `location = 'X'`
    nunca matchea NULL, asi que quedaban invisibles y se ofrecian horarios ya
    tomados. Contarlos como ocupados es lo conservador.
    """
    start_of_day = datetime.combine(day, py_time(0, 0))
    end_of_day = datetime.combine(day, py_time(23, 59, 59))
    return db.query(Appointment).filter(
        or_(Appointment.location == location, Appointment.location.is_(None)),
        Appointment.is_deleted == False,
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
        Appointment.start_time >= start_of_day,
        Appointment.start_time <= end_of_day,
    ).all()


def overlapping_appointments(appointments, start: datetime, duration_minutes: int, exclude_id=None):
    """De una lista ya cargada, los que se pisan con el rango dado."""
    end = start + timedelta(minutes=duration_minutes)
    return [
        a for a in appointments
        if a.id != exclude_id
        and start < a.start_time + timedelta(minutes=a.duration_minutes or 30)
        and a.start_time < end
    ]


def slot_conflict(appointments, start: datetime, duration_minutes: int, chairs: int,
                  professional_ids=None, exclude_id=None) -> str | None:
    """Motivo por el que el horario no esta libre, o None si se puede agendar.

    professional_ids son los profesionales que podrian tomar ese turno. Si el
    motivo lo atienden varios (por ejemplo Limpieza, que hacen los dos), el
    horario recien se considera ocupado cuando estan todos ocupados.
    """
    solapan = overlapping_appointments(appointments, start, duration_minutes, exclude_id)

    # El limite de sillones manda: es fisico, no depende de quien atienda.
    if len(solapan) >= chairs:
        if chairs == 1:
            return "Ya hay un turno agendado en ese horario."
        return f"No hay sillones libres en ese horario (hay {chairs})."

    if professional_ids:
        ocupados = {a.professional_id for a in solapan}
        if all(pid in ocupados for pid in professional_ids):
            return "El profesional ya tiene otro turno en ese horario."
    return None


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
    # Garantia dura: si la obra social no esta entre las activas, el turno se
    # agenda como Particular. El prompt le pide al modelo que lo verifique con
    # verificar_obra_social, pero un prompt no es una garantia: sin esto podia
    # quedar agendado con una cobertura que la clinica no atiende.
    if insurance_name:
        encontrada = match_insurance(insurance_name, db)
        insurance_name = encontrada.name if encontrada else "Particular"

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

    # ── Feriado: si el día es feriado, saltar directamente al siguiente ──
    is_holiday = db.query(ClinicHoliday).filter(ClinicHoliday.date == day).first()
    if is_holiday:
        if recursive_depth < 14:
            return get_available_slots(db, (day + timedelta(days=1)).isoformat(), location, reason, obra_social, recursive_depth + 1)
        return {"date": str(day), "location": location, "available_slots": [], "message": "No hay turnos disponibles (feriados)."}

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

    # Turnos del dia en esa sede. Antes esta consulta filtraba tambien por
    # profesional, asi que un horario ocupado por el otro profesional se ofrecia
    # como libre aunque hubiera un solo sillon. Ahora se traen todos y la
    # decision la toma slot_conflict segun los sillones configurados.
    existing = get_day_appointments(db, day, location)
    chairs = get_chairs_per_location(db)
    # Si el motivo lo atienden varios, el horario esta libre mientras quede al
    # menos uno de ellos disponible.
    prof_ids = [p.id for p in find_professionals_for_reason(reason, db)]
    
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
            conflicto = slot_conflict(existing, current, duration_minutes, chairs, prof_ids)

            if not conflicto and current > clinic_now:
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
