"""Clinic-level routes: appointments, patients, odontogram, search."""
from uuid import UUID
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database import get_db
from backend.security import require_admin, require_clinic
from backend.models.patient import Patient
from backend.models.appointment import Appointment
from backend.models.odontogram import OdontogramEntry
from backend.models.professional import Professional
from backend.models.config import AppConfig
from backend.models.clinic_location import ClinicLocation
from backend.models.schedule import ClinicSchedule, ProfessionalTimeOff, ClinicHoliday
from backend.models.appointment import AppointmentStatus
from backend.models.insurance import Insurance
from backend.schemas.schemas import (
    PatientCreate, PatientRead, PatientUpdate,
    AppointmentCreate, AppointmentRead, AppointmentUpdate,
    OdontogramEntryCreate, OdontogramEntryRead, OdontogramEntryUpdate,
    ProfessionalRead, SearchResult,
    ScheduleBlock, ScheduleBlockRead, TimeOffCreate, TimeOffRead,
    InsuranceCreate, InsuranceUpdate, InsuranceRead,
    HolidayCreate, HolidayRead, LocationRead,
)

router = APIRouter(prefix="/api/clinic", tags=["Clínica"], dependencies=[Depends(require_clinic)])


# ═══════════════════════════════════════════════════════
# PATIENTS
# ═══════════════════════════════════════════════════════
@router.get("/patients", response_model=list[PatientRead])
def list_patients(
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(Patient).filter(Patient.is_deleted == False)
    if q:
        query = query.filter(
            or_(
                Patient.first_name.ilike(f"%{q}%"),
                Patient.last_name.ilike(f"%{q}%"),
                Patient.dni.ilike(f"%{q}%"),
            )
        )
    return query.offset(skip).limit(limit).all()


@router.get("/patients/{patient_id}", response_model=PatientRead)
def get_patient(patient_id: UUID, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id, Patient.is_deleted == False).first()
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    return p


@router.post("/patients", response_model=PatientRead, status_code=201)
def create_patient(data: PatientCreate, db: Session = Depends(get_db)):
    if db.query(Patient).filter(Patient.dni == data.dni, Patient.is_deleted == False).first():
        raise HTTPException(400, "DNI ya registrado")
    patient = Patient(**data.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient


@router.put("/patients/{patient_id}", response_model=PatientRead)
def update_patient(patient_id: UUID, data: PatientUpdate, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id, Patient.is_deleted == False).first()
    if not p:
        raise HTTPException(404, "Paciente no encontrado")

    payload = data.model_dump(exclude_unset=True)

    # El DNI es único: si viene y cambia, verificar que no lo tenga otro paciente
    new_dni = payload.get("dni")
    if new_dni is not None:
        new_dni = new_dni.strip()
        if not new_dni:
            payload.pop("dni")  # no permitir dejar el DNI vacío
        elif new_dni != p.dni:
            existe = db.query(Patient).filter(
                Patient.dni == new_dni,
                Patient.id != patient_id,
                Patient.is_deleted == False,
            ).first()
            if existe:
                raise HTTPException(400, f"Ya existe otro paciente con el DNI {new_dni}")
            payload["dni"] = new_dni

    for key, val in payload.items():
        setattr(p, key, val)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/patients/{patient_id}")
def soft_delete_patient(patient_id: UUID, db: Session = Depends(get_db)):
    p = db.query(Patient).filter(Patient.id == patient_id).first()
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    p.is_deleted = True
    db.commit()
    return {"detail": "Paciente eliminado (soft-delete)"}


# ═══════════════════════════════════════════════════════
# APPOINTMENTS (AGENDA)
# ═══════════════════════════════════════════════════════
@router.get("/appointments", response_model=list[AppointmentRead])
def list_appointments(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    professional_id: Optional[UUID] = None,
    status: Optional[str] = None,
    location: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(Appointment).filter(Appointment.is_deleted == False)
    if date_from:
        query = query.filter(Appointment.start_time >= date_from)
    if date_to:
        query = query.filter(Appointment.start_time <= date_to)
    if professional_id:
        query = query.filter(Appointment.professional_id == professional_id)
    if status:
        query = query.filter(Appointment.status == status)
    if location:
        query = query.filter(Appointment.location == location)
    return query.order_by(Appointment.start_time).offset(skip).limit(limit).all()


@router.get("/appointments/{appt_id}", response_model=AppointmentRead)
def get_appointment(appt_id: UUID, db: Session = Depends(get_db)):
    a = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.is_deleted == False).first()
    if not a:
        raise HTTPException(404, "Turno no encontrado")
    return a


def _assert_not_holiday(db: Session, when: datetime) -> None:
    """Corta el alta/reprogramacion si la fecha es feriado.

    El chequeo de feriados vivia solo en get_available_slots (el flujo del bot),
    asi que desde el panel se podian cargar turnos igual. Va aca, en el endpoint,
    para que valga para cualquier origen: agenda, dashboard o bot.
    """
    holiday = db.query(ClinicHoliday).filter(ClinicHoliday.date == when.date()).first()
    if holiday:
        detalle = f" ({holiday.description})" if holiday.description else ""
        raise HTTPException(
            400,
            f"El {when.strftime('%d/%m/%Y')} es feriado{detalle}. "
            "La clínica está cerrada, no se pueden agendar turnos.",
        )


def _assert_slot_free(db: Session, start: datetime, duration_minutes: int,
                      location: str | None, professional_id, exclude_id=None) -> None:
    """Corta el alta/reprogramacion si el horario ya esta ocupado.

    Misma regla que usa el bot para ofrecer horarios, para que el panel y el bot
    no se contradigan: la cantidad de turnos simultaneos permitidos sale de
    CHAIRS_PER_LOCATION (default 1) y ademas nunca se duplica un profesional.
    """
    from backend.services.appointment_service import (
        get_day_appointments, get_chairs_per_location, slot_conflict,
    )
    del_dia = get_day_appointments(db, start.date(), location)
    motivo = slot_conflict(
        del_dia, start, duration_minutes or 30, get_chairs_per_location(db),
        [professional_id] if professional_id else None, exclude_id,
    )
    if motivo:
        raise HTTPException(409, f"{start.strftime('%d/%m/%Y %H:%M')}: {motivo}")


@router.post("/appointments", response_model=AppointmentRead, status_code=201)
def create_appointment(data: AppointmentCreate, db: Session = Depends(get_db)):
    # Validate patient and professional exist
    if not db.query(Patient).filter(Patient.id == data.patient_id, Patient.is_deleted == False).first():
        raise HTTPException(404, "Paciente no encontrado")
    if not db.query(Professional).filter(Professional.id == data.professional_id, Professional.is_deleted == False).first():
        raise HTTPException(404, "Profesional no encontrado")

    _assert_not_holiday(db, data.start_time)
    if not data.force:
        _assert_slot_free(db, data.start_time, data.duration_minutes,
                          data.location, data.professional_id)

    campos = data.model_dump()
    campos.pop("force", None)  # no es una columna del modelo, solo una bandera del request
    appt = Appointment(**campos)
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


@router.put("/appointments/{appt_id}", response_model=AppointmentRead)
async def update_appointment(appt_id: UUID, data: AppointmentUpdate, db: Session = Depends(get_db)):
    a = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.is_deleted == False).first()
    if not a:
        raise HTTPException(404, "Turno no encontrado")
    
    was_cancelled = False
    if getattr(data, "status", None) == "cancelled" and a.status != "cancelled":
        was_cancelled = True

    # Reprogramar hacia un feriado tampoco se permite (salvo que se cancele).
    campos = data.model_dump(exclude_unset=True)
    campos.pop("force", None)  # no es una columna del modelo, solo una bandera del request
    if campos.get("start_time") and not was_cancelled:
        _assert_not_holiday(db, campos["start_time"])
        if not data.force:
            _assert_slot_free(
                db,
                campos["start_time"],
                campos.get("duration_minutes", a.duration_minutes),
                campos.get("location", a.location),
                campos.get("professional_id", a.professional_id),
                exclude_id=a.id,   # el propio turno no se cuenta como conflicto
            )

    for key, val in campos.items():
        setattr(a, key, val)
    db.commit()
    db.refresh(a)

    if was_cancelled and a.patient and a.patient.phone:
        try:
            from backend.services.whatsapp import send_whatsapp_message
            msg_text = f"Hola {a.patient.first_name}, te informamos que tu turno del {a.start_time.strftime('%Y-%m-%d %H:%M')} en la sede {a.location} ha sido cancelado desde la clínica. Por favor, contactate con nosotros si deseas reprogramarlo."
            await send_whatsapp_message(a.patient.phone, msg_text)
        except Exception as e:
            print(f"Error notifying patient of cancellation: {e}")

    return a


@router.delete("/appointments/{appt_id}")
async def soft_delete_appointment(appt_id: UUID, db: Session = Depends(get_db)):
    a = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not a:
        raise HTTPException(404, "Turno no encontrado")
    a.is_deleted = True
    a.status = "cancelled"
    db.commit()

    if a.patient and a.patient.phone:
        try:
            from backend.services.whatsapp import send_whatsapp_message
            msg_text = f"Hola {a.patient.first_name}, te informamos que tu turno del {a.start_time.strftime('%Y-%m-%d %H:%M')} en la sede {a.location} ha sido cancelado desde la clínica. Por favor, contactate con nosotros si deseas reprogramarlo."
            await send_whatsapp_message(a.patient.phone, msg_text)
        except Exception as e:
            print(f"Error notifying patient of cancellation: {e}")

    return {"detail": "Turno eliminado (soft-delete)"}


@router.delete("/appointments/{appt_id}/permanente", dependencies=[Depends(require_admin)])
def hard_delete_appointment(appt_id: UUID, db: Session = Depends(get_db)):
    """Borra el turno de la base para siempre. No es lo mismo que cancelar.

    Cancelar (o el soft-delete de arriba) deja el registro: sirve para
    historial y para no perder el rastro de por qué el paciente no vino. Esto
    es para lo que no debería haber quedado ahí ni como cancelado: turnos de
    prueba, duplicados por un doble clic, datos cargados mal. No hay vuelta
    atrás, así que queda restringido a admin.
    """
    a = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not a:
        raise HTTPException(404, "Turno no encontrado")
    db.delete(a)
    db.commit()
    return {"detail": "Turno borrado definitivamente"}


# ═══════════════════════════════════════════════════════
# ODONTOGRAM
# ═══════════════════════════════════════════════════════
@router.get("/odontogram/{patient_id}", response_model=list[OdontogramEntryRead])
def get_odontogram(patient_id: UUID, db: Session = Depends(get_db)):
    return db.query(OdontogramEntry).filter(
        OdontogramEntry.patient_id == patient_id,
        OdontogramEntry.is_deleted == False,
    ).order_by(OdontogramEntry.created_at).all()


@router.post("/odontogram", response_model=OdontogramEntryRead, status_code=201)
def create_odontogram_entry(data: OdontogramEntryCreate, db: Session = Depends(get_db)):
    entry = OdontogramEntry(**data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/odontogram/bulk", response_model=list[OdontogramEntryRead], status_code=201)
def create_odontogram_entries_bulk(data: list[OdontogramEntryCreate], db: Session = Depends(get_db)):
    entries = []
    for item in data:
        entry = OdontogramEntry(**item.model_dump())
        db.add(entry)
        entries.append(entry)
    db.commit()
    for entry in entries:
        db.refresh(entry)
    return entries


@router.put("/odontogram/{entry_id}", response_model=OdontogramEntryRead)
def update_odontogram_entry(entry_id: UUID, data: OdontogramEntryUpdate, db: Session = Depends(get_db)):
    e = db.query(OdontogramEntry).filter(OdontogramEntry.id == entry_id, OdontogramEntry.is_deleted == False).first()
    if not e:
        raise HTTPException(404, "Entrada no encontrada")
    
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(e, key, val)
        
    db.commit()
    db.refresh(e)
    return e


@router.delete("/odontogram/{entry_id}")
def soft_delete_odontogram_entry(entry_id: UUID, db: Session = Depends(get_db)):
    e = db.query(OdontogramEntry).filter(OdontogramEntry.id == entry_id).first()
    if not e:
        raise HTTPException(404, "Entrada no encontrada")
    e.is_deleted = True
    db.commit()
    return {"detail": "Entrada eliminada (soft-delete)"}


# ═══════════════════════════════════════════════════════
# PROFESSIONALS (READ for clinic staff)
# ═══════════════════════════════════════════════════════
@router.get("/professionals", response_model=list[ProfessionalRead])
def list_professionals_clinic(db: Session = Depends(get_db)):
    return db.query(Professional).filter(Professional.is_deleted == False, Professional.is_active == True).all()


# ═══════════════════════════════════════════════════════
# BOT SETTINGS (subconjunto de configs editable por el personal de clínica)
# Solo estas claves NO sensibles. Las API keys y demás quedan en /admin.
# ═══════════════════════════════════════════════════════
CLINIC_EDITABLE_CONFIGS = ["BOT_IS_ACTIVE", "ADMIN_NOTIFY_NUMBERS", "REMINDER_HOURS_BEFORE"]


@router.get("/bot-settings")
def get_bot_settings(db: Session = Depends(get_db)):
    rows = db.query(AppConfig).filter(AppConfig.key.in_(CLINIC_EDITABLE_CONFIGS)).all()
    values = {r.key: r.value for r in rows}
    return {k: values.get(k, "") for k in CLINIC_EDITABLE_CONFIGS}


@router.post("/bot-settings")
def set_bot_settings(data: dict = Body(...), db: Session = Depends(get_db)):
    # Solo se aceptan las claves de la lista blanca; el resto se ignora.
    for key in CLINIC_EDITABLE_CONFIGS:
        if key not in data:
            continue
        val = str(data[key])
        conf = db.query(AppConfig).filter(AppConfig.key == key).first()
        if conf:
            conf.value = val
        else:
            db.add(AppConfig(key=key, value=val))
    db.commit()
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════
# HORARIOS (schedule) Y AUSENCIAS (time-off)
# ═══════════════════════════════════════════════════════
@router.get("/schedule", response_model=list[ScheduleBlockRead])
def get_schedule(db: Session = Depends(get_db)):
    return db.query(ClinicSchedule).filter(ClinicSchedule.is_active == True).order_by(
        ClinicSchedule.weekday, ClinicSchedule.start_time
    ).all()


@router.put("/schedule", response_model=list[ScheduleBlockRead])
def replace_schedule(blocks: list[ScheduleBlock], db: Session = Depends(get_db)):
    """Reemplaza toda la grilla horaria por la lista recibida."""
    for b in blocks:
        if b.end_time <= b.start_time:
            raise HTTPException(400, f"El horario de fin debe ser mayor al de inicio (día {b.weekday}).")
    db.query(ClinicSchedule).delete()
    for b in blocks:
        db.add(ClinicSchedule(weekday=b.weekday, start_time=b.start_time, end_time=b.end_time))
    db.commit()
    return db.query(ClinicSchedule).order_by(ClinicSchedule.weekday, ClinicSchedule.start_time).all()


@router.get("/time-off", response_model=list[TimeOffRead])
def list_time_off(db: Session = Depends(get_db)):
    from datetime import date as _date
    return db.query(ProfessionalTimeOff).filter(
        ProfessionalTimeOff.date >= _date.today()
    ).order_by(ProfessionalTimeOff.date).all()


@router.post("/time-off", response_model=TimeOffRead, status_code=201)
def create_time_off(data: TimeOffCreate, db: Session = Depends(get_db)):
    existing = db.query(ProfessionalTimeOff).filter(
        ProfessionalTimeOff.professional_id == data.professional_id,
        ProfessionalTimeOff.date == data.date,
    ).first()
    if existing:
        return existing
    off = ProfessionalTimeOff(professional_id=data.professional_id, date=data.date, reason=data.reason)
    db.add(off)
    db.commit()
    db.refresh(off)
    return off


@router.delete("/time-off/{off_id}")
def delete_time_off(off_id: UUID, db: Session = Depends(get_db)):
    off = db.query(ProfessionalTimeOff).filter(ProfessionalTimeOff.id == off_id).first()
    if not off:
        raise HTTPException(404, "Ausencia no encontrada")
    db.delete(off)
    db.commit()
    return {"detail": "Ausencia eliminada"}


@router.get("/agenda-config")
def get_agenda_config(db: Session = Depends(get_db)):
    """Parametros de agenda que el frontend necesita para pintar conflictos.

    CHAIRS_PER_LOCATION vive en AppConfig, que es admin-only (/api/admin/configs).
    La agenda la usa cualquier rol de la clinica para saber si dos turnos
    superpuestos son un problema real (mas turnos que sillones) o algo que la
    sede puede absorber, asi que necesita un endpoint no restringido a admin.
    """
    from backend.services.appointment_service import get_chairs_per_location
    return {"chairs_per_location": get_chairs_per_location(db)}


# ═══════════════════════════════════════════════════════
# FERIADOS (días feriados de la clínica, aplica a TODOS los profesionales)
# ═══════════════════════════════════════════════════════
@router.get("/locations", response_model=list[LocationRead])
def list_clinic_locations(db: Session = Depends(get_db)):
    """Sedes activas. El endpoint de /admin/locations es admin-only y la agenda
    la usa tambien recepcion, que necesita elegir sede al cargar un turno."""
    return db.query(ClinicLocation).filter(
        ClinicLocation.is_active == True,
        ClinicLocation.is_deleted == False,
    ).order_by(ClinicLocation.name).all()


@router.get("/holidays", response_model=list[HolidayRead])
def list_holidays(db: Session = Depends(get_db)):
    from datetime import date as _date
    return db.query(ClinicHoliday).filter(
        ClinicHoliday.date >= _date.today()
    ).order_by(ClinicHoliday.date).all()


@router.post("/holidays", response_model=HolidayRead, status_code=201)
def create_holiday(data: HolidayCreate, db: Session = Depends(get_db)):
    existing = db.query(ClinicHoliday).filter(ClinicHoliday.date == data.date).first()
    if existing:
        return existing
    holiday = ClinicHoliday(date=data.date, description=data.description)
    db.add(holiday)
    db.commit()
    db.refresh(holiday)
    return holiday


@router.delete("/holidays/{holiday_id}")
def delete_holiday(holiday_id: UUID, db: Session = Depends(get_db)):
    holiday = db.query(ClinicHoliday).filter(ClinicHoliday.id == holiday_id).first()
    if not holiday:
        raise HTTPException(404, "Feriado no encontrado")
    db.delete(holiday)
    db.commit()
    return {"detail": "Feriado eliminado"}


@router.get("/reschedule-list", response_model=list[AppointmentRead])
def reschedule_list(db: Session = Depends(get_db)):
    """Turnos afectados por ausencias: mismo profesional y fecha, aún activos."""
    from datetime import date as _date, datetime as _dt, time as _time
    offs = db.query(ProfessionalTimeOff).filter(ProfessionalTimeOff.date >= _date.today()).all()
    result = []
    for off in offs:
        day_start = _dt.combine(off.date, _time(0, 0))
        day_end = _dt.combine(off.date, _time(23, 59, 59))
        appts = db.query(Appointment).filter(
            Appointment.professional_id == off.professional_id,
            Appointment.is_deleted == False,
            Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
            Appointment.start_time >= day_start,
            Appointment.start_time <= day_end,
        ).all()
        result.extend(appts)
    result.sort(key=lambda a: a.start_time)
    return result


# ═══════════════════════════════════════════════════════
# OBRAS SOCIALES / MUTUALES (gestionables por el personal de clínica)
# ═══════════════════════════════════════════════════════
@router.get("/insurances", response_model=list[InsuranceRead])
def clinic_list_insurances(db: Session = Depends(get_db)):
    return db.query(Insurance).filter(Insurance.is_deleted == False).all()


@router.post("/insurances", response_model=InsuranceRead, status_code=201)
def clinic_create_insurance(data: InsuranceCreate, db: Session = Depends(get_db)):
    existing = db.query(Insurance).filter(Insurance.name.ilike(data.name)).first()
    if existing:
        if existing.is_deleted:
            existing.is_deleted = False
            existing.is_active = True
            existing.code = data.code
            db.commit()
            db.refresh(existing)
            return existing
        raise HTTPException(400, "Ya existe una obra social con ese nombre")
    ins = Insurance(**data.model_dump())
    db.add(ins)
    db.commit()
    db.refresh(ins)
    return ins


@router.put("/insurances/{ins_id}", response_model=InsuranceRead)
def clinic_update_insurance(ins_id: UUID, data: InsuranceUpdate, db: Session = Depends(get_db)):
    ins = db.query(Insurance).filter(Insurance.id == ins_id, Insurance.is_deleted == False).first()
    if not ins:
        raise HTTPException(404, "Obra social no encontrada")
    if data.name is not None and data.name.lower() != ins.name.lower():
        dup = db.query(Insurance).filter(Insurance.name.ilike(data.name)).first()
        if dup and not dup.is_deleted:
            raise HTTPException(400, "Ya existe una obra social con ese nombre")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(ins, key, value)
    db.commit()
    db.refresh(ins)
    return ins


@router.delete("/insurances/{ins_id}")
def clinic_delete_insurance(ins_id: UUID, db: Session = Depends(get_db)):
    ins = db.query(Insurance).filter(Insurance.id == ins_id).first()
    if ins:
        ins.is_deleted = True
        db.commit()
    return {"detail": "Obra social eliminada"}


# ═══════════════════════════════════════════════════════
# OMNIBOX SEARCH
# ═══════════════════════════════════════════════════════
@router.get("/search", response_model=list[SearchResult])
def omnibox_search(q: str = Query(min_length=2), db: Session = Depends(get_db)):
    results: list[SearchResult] = []
    pattern = f"%{q}%"

    # Search patients
    patients = db.query(Patient).filter(
        Patient.is_deleted == False,
        or_(
            Patient.first_name.ilike(pattern),
            Patient.last_name.ilike(pattern),
            Patient.dni.ilike(pattern),
        )
    ).limit(10).all()
    for p in patients:
        results.append(SearchResult(
            type="patient", id=p.id,
            label=f"{p.last_name}, {p.first_name}",
            detail=f"DNI: {p.dni}"
        ))

    # Search professionals
    profs = db.query(Professional).filter(
        Professional.is_deleted == False,
        Professional.full_name.ilike(pattern),
    ).limit(5).all()
    for pr in profs:
        results.append(SearchResult(
            type="professional", id=pr.id,
            label=pr.full_name,
            detail=", ".join(pr.specialties),
        ))

    return results
