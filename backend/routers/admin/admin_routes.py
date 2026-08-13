"""Admin-only routes: user management, clinic settings."""
from uuid import UUID
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.security import require_admin, hash_password
from backend.models.user import User
from backend.models.professional import Professional
from backend.models.clinic_location import ClinicLocation
from backend.models.insurance import Insurance
from backend.models.config import AppConfig
from backend.schemas.schemas import (
# ... existing imports continue ...
    UserCreate, UserRead, UserUpdate,
    ProfessionalCreate, ProfessionalRead, ProfessionalUpdate,
    LocationCreate, LocationRead, InsuranceCreate, InsuranceRead, InsuranceUpdate,
    ConfigCreate, ConfigRead
)

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


# ── Users ───────────────────────────────────────────────
@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).filter(User.is_deleted == False).order_by(User.full_name).all()

@router.post("/users", response_model=UserRead, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    # El email se guarda normalizado: si no, "Juan@X.com" y "juan@x.com" entran
    # como dos usuarios distintos y despues no se puede iniciar sesion.
    email = data.email.strip().lower()

    # Buscamos incluyendo los borrados. Al eliminar un usuario hacemos soft
    # delete (is_deleted=True): desaparece de la lista pero el email sigue
    # ocupado, asi que sin esto era imposible volver a dar de alta a alguien
    # que se habia eliminado ("Email ya registrado" para un usuario invisible).
    existing = db.query(User).filter(func.lower(User.email) == email).first()
    if existing and not existing.is_deleted:
        raise HTTPException(400, "Email ya registrado")

    try:
        if existing:
            # Reutilizamos el registro borrado en vez de rechazar el alta.
            existing.hashed_password = hash_password(data.password)
            existing.full_name = data.full_name
            existing.role = data.role
            existing.is_deleted = False
            existing.is_active = True
            user = existing
        else:
            user = User(
                email=email,
                hashed_password=hash_password(data.password),
                full_name=data.full_name,
                role=data.role,
            )
            db.add(user)
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Email ya registrado")
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error interno: {str(e)}")

@router.put("/users/{user_id}", response_model=UserRead)
def update_user(user_id: UUID, data: UserUpdate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id, User.is_deleted == False).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(user, key, val)
    db.commit()
    db.refresh(user)
    return user

@router.delete("/users/{user_id}")
def soft_delete_user(user_id: UUID, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    user.is_deleted = True
    user.is_active = False
    db.commit()
    return {"detail": "Usuario eliminado"}

# ── Professionals ───────────────────────────────────────
@router.get("/professionals", response_model=list[ProfessionalRead])
def list_professionals(db: Session = Depends(get_db)):
    return db.query(Professional).filter(Professional.is_deleted == False).all()

@router.post("/professionals", response_model=ProfessionalRead, status_code=201)
def create_professional(data: ProfessionalCreate, db: Session = Depends(get_db)):
    prof = Professional(**data.model_dump())
    db.add(prof)
    db.commit()
    db.refresh(prof)
    return prof

@router.put("/professionals/{prof_id}", response_model=ProfessionalRead)
def update_professional(prof_id: UUID, data: ProfessionalUpdate, db: Session = Depends(get_db)):
    prof = db.query(Professional).filter(Professional.id == prof_id, Professional.is_deleted == False).first()
    if not prof:
        raise HTTPException(404, "Profesional no encontrado")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(prof, key, val)
    db.commit()
    db.refresh(prof)
    return prof

@router.delete("/professionals/{prof_id}")
def soft_delete_professional(prof_id: UUID, db: Session = Depends(get_db)):
    prof = db.query(Professional).filter(Professional.id == prof_id).first()
    if not prof:
        raise HTTPException(404, "Profesional no encontrado")
    prof.is_deleted = True
    prof.is_active = False
    db.commit()
    return {"detail": "Profesional eliminado"}

# ── Clinic Locations ────────────────────────────────────
@router.get("/locations", response_model=list[LocationRead])
def list_locations(db: Session = Depends(get_db)):
    return db.query(ClinicLocation).filter(ClinicLocation.is_deleted == False).all()

@router.post("/locations", response_model=LocationRead, status_code=201)
def create_location(data: LocationCreate, db: Session = Depends(get_db)):
    loc = ClinicLocation(**data.model_dump())
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc

@router.delete("/locations/{loc_id}")
def delete_location(loc_id: UUID, db: Session = Depends(get_db)):
    loc = db.query(ClinicLocation).filter(ClinicLocation.id == loc_id).first()
    if loc:
        loc.is_deleted = True
        db.commit()
    return {"detail": "Sede eliminada"}

# ── Insurances ──────────────────────────────────────────
@router.get("/insurances", response_model=list[InsuranceRead])
def list_insurances(db: Session = Depends(get_db)):
    return db.query(Insurance).filter(Insurance.is_deleted == False).all()

@router.post("/insurances", response_model=InsuranceRead, status_code=201)
def create_insurance(data: InsuranceCreate, db: Session = Depends(get_db)):
    # Check if exists (including deleted)
    existing = db.query(Insurance).filter(Insurance.name.ilike(data.name)).first()
    if existing:
        if existing.is_deleted:
            # Restore
            existing.is_deleted = False
            existing.is_active = True
            existing.code = data.code
            db.commit()
            db.refresh(existing)
            return existing
        else:
            raise HTTPException(status_code=400, detail="Ya existe una obra social con ese nombre")
            
    ins = Insurance(**data.model_dump())
    db.add(ins)
    db.commit()
    db.refresh(ins)
    return ins

@router.put("/insurances/{ins_id}", response_model=InsuranceRead)
def update_insurance(ins_id: UUID, data: InsuranceUpdate, db: Session = Depends(get_db)):
    ins = db.query(Insurance).filter(Insurance.id == ins_id, Insurance.is_deleted == False).first()
    if not ins:
        raise HTTPException(status_code=404, detail="Obra social no encontrada")
    
    if data.name is not None and data.name.lower() != ins.name.lower():
        existing = db.query(Insurance).filter(Insurance.name.ilike(data.name)).first()
        if existing and not existing.is_deleted:
            raise HTTPException(status_code=400, detail="Ya existe una obra social con ese nombre")
    
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(ins, key, value)
        
    db.commit()
    db.refresh(ins)
    return ins

@router.delete("/insurances/{ins_id}")
def delete_insurance(ins_id: UUID, db: Session = Depends(get_db)):
    ins = db.query(Insurance).filter(Insurance.id == ins_id).first()
    if ins:
        ins.is_deleted = True
        db.commit()
    return {"detail": "Obra social eliminada"}

# ── System Config ───────────────────────────────────────
@router.get("/configs", response_model=list[ConfigRead])
def list_configs(db: Session = Depends(get_db)):
    return db.query(AppConfig).all()

@router.post("/configs", response_model=ConfigRead, status_code=201)
def set_config(data: ConfigCreate, db: Session = Depends(get_db)):
    config = db.query(AppConfig).filter(AppConfig.key == data.key).first()
    if config:
        config.value = data.value
        if data.description:
            config.description = data.description
    else:
        config = AppConfig(**data.model_dump())
        db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.post("/configs/bulk", response_model=list[ConfigRead])
def set_configs_bulk(data: dict[str, str] = Body(...), db: Session = Depends(get_db)):
    """Guarda todas las claves de una, en una sola transaccion.

    El panel mandaba un POST por campo con Promise.all: 16 requests en paralelo
    contra un pool de 15 conexiones. El request 16 esperaba los 30s de
    pool_timeout y moria con un 500, asi que "Guardar Todo" tardaba media
    minuto y despues avisaba error habiendo guardado casi todo. Peor: quedaba
    a medias, sin forma de saber que se guardo.
    """
    if not data:
        raise HTTPException(400, "No se recibió ninguna configuración")

    existentes = {c.key: c for c in db.query(AppConfig).filter(AppConfig.key.in_(data.keys())).all()}
    resultado = []
    for key, value in data.items():
        key = key.strip()
        if not key:
            continue
        # Los valores se guardan sin espacios de sobra: una API Key pegada con
        # un salto de linea al final falla con un 401 imposible de diagnosticar.
        if isinstance(value, str):
            value = value.strip()
        config = existentes.get(key)
        if config:
            config.value = value
        else:
            config = AppConfig(key=key, value=value)
            db.add(config)
        resultado.append(config)

    db.commit()
    for c in resultado:
        db.refresh(c)
    return resultado


# ── Test: Disparar recordatorios manualmente ────────────
@router.post("/test-reminders")
async def trigger_reminders_now(hours_override: float = 24, db: Session = Depends(get_db)):
    """
    Dispara el chequeo de recordatorios ahora mismo, sin esperar el loop de 15 minutos.

    - **hours_override**: ventana de horas a revisar (default 24 = turno de maniana).
      Para probar un turno especifico, usa el valor 'hours_override_sugerido' de 'proximos_turnos'.
    """
    from backend.services.reminders_loop import send_whatsapp_message, get_config as get_cfg
    from backend.models.appointment import Appointment, AppointmentStatus
    from backend.models.patient import Patient
    from backend.services.appointment_service import get_clinic_now
    from datetime import timedelta

    public_url = get_cfg(db, "PUBLIC_APP_URL", "http://localhost:8000")
    now = get_clinic_now()
    target_time = now + timedelta(hours=hours_override)
    start_window = target_time
    end_window = target_time + timedelta(minutes=60)  # ventana amplia para test

    appointments = db.query(Appointment).join(Patient).filter(
        Appointment.status == AppointmentStatus.confirmed,
        Appointment.is_deleted == False,
        Appointment.start_time >= start_window,
        Appointment.start_time < end_window,
    ).all()

    sent = []
    for appt in appointments:
        patient = appt.patient
        time_str = appt.start_time.strftime("%d/%m/%Y a las %H:%M")
        cancel_link = f"{public_url}/api/public/cancel/{appt.id}"
        msg = (
            f"[TEST RECORDATORIO] Hola {patient.first_name}, te recordamos tu turno "
            f"en Silprodent el {time_str} en nuestra sede de {appt.location}.\n\n"
            f"Si no podés asistir, por favor cancelálo en:\n{cancel_link}"
        )
        await send_whatsapp_message(patient.phone, msg)
        sent.append({
            "patient": f"{patient.first_name} {patient.last_name}",
            "phone": patient.phone,
            "appointment": time_str,
        })

    # Show next upcoming confirmed appointments to help calibrate hours_override
    upcoming = db.query(Appointment).join(Patient).filter(
        Appointment.status == AppointmentStatus.confirmed,
        Appointment.is_deleted == False,
        Appointment.start_time > now,
    ).order_by(Appointment.start_time).limit(10).all()

    proximos = []
    for appt in upcoming:
        diff_hours = (appt.start_time - now).total_seconds() / 3600
        proximos.append({
            "patient": f"{appt.patient.first_name} {appt.patient.last_name}",
            "phone": appt.patient.phone,
            "appointment": appt.start_time.strftime("%d/%m/%Y %H:%M"),
            "hours_override_sugerido": round(diff_hours, 1),
        })

    return {
        "now_argentina": now.strftime("%Y-%m-%d %H:%M"),
        "window_buscada": f"{start_window.strftime('%H:%M')} - {end_window.strftime('%H:%M')} del {start_window.strftime('%Y-%m-%d')}",
        "reminders_sent": len(sent),
        "detail": sent,
        "proximos_turnos_confirmados": proximos,
    }

