"""Admin-only routes: user management, clinic settings."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
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
    LocationCreate, LocationRead, InsuranceCreate, InsuranceRead,
    ConfigCreate, ConfigRead
)

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


# ── Users ───────────────────────────────────────────────
@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).filter(User.is_deleted == False).order_by(User.full_name).all()

# create_user is already mostly handled in the previous replace_file_content call, I'll keep the logic.
@router.post("/users", response_model=UserRead, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email ya registrado")
    try:
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
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
    ins = Insurance(**data.model_dump())
    db.add(ins)
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
