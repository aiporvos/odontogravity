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
from backend.schemas.schemas import (
    UserCreate, UserRead, UserUpdate,
    ProfessionalCreate, ProfessionalRead, ProfessionalUpdate,
)

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


# ── Users ───────────────────────────────────────────────
@router.get("/users", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db)):
    return db.query(User).filter(User.is_deleted == False).all()


@router.post("/users", response_model=UserRead, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email ya registrado")
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
    return {"detail": "Usuario eliminado (soft-delete)"}


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
    return {"detail": "Profesional eliminado (soft-delete)"}


# ── Clinic Locations ────────────────────────────────────
@router.get("/locations")
def list_locations(db: Session = Depends(get_db)):
    return db.query(ClinicLocation).filter(ClinicLocation.is_deleted == False).all()


@router.post("/locations", status_code=201)
def create_location(name: str, address: str = "", phone: str = "", db: Session = Depends(get_db)):
    loc = ClinicLocation(name=name, address=address, phone=phone)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


# ── Insurances ──────────────────────────────────────────
@router.get("/insurances")
def list_insurances(db: Session = Depends(get_db)):
    return db.query(Insurance).filter(Insurance.is_deleted == False).all()


@router.post("/insurances", status_code=201)
def create_insurance(name: str, code: str = "", db: Session = Depends(get_db)):
    ins = Insurance(name=name, code=code)
    db.add(ins)
    db.commit()
    db.refresh(ins)
    return ins
