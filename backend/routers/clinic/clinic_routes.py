"""Clinic-level routes: appointments, patients, odontogram, search."""
from uuid import UUID
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from backend.database import get_db
from backend.security import require_clinic
from backend.models.patient import Patient
from backend.models.appointment import Appointment
from backend.models.odontogram import OdontogramEntry
from backend.models.professional import Professional
from backend.schemas.schemas import (
    PatientCreate, PatientRead, PatientUpdate,
    AppointmentCreate, AppointmentRead, AppointmentUpdate,
    OdontogramEntryCreate, OdontogramEntryRead,
    ProfessionalRead, SearchResult,
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
    for key, val in data.model_dump(exclude_unset=True).items():
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


@router.post("/appointments", response_model=AppointmentRead, status_code=201)
def create_appointment(data: AppointmentCreate, db: Session = Depends(get_db)):
    # Validate patient and professional exist
    if not db.query(Patient).filter(Patient.id == data.patient_id, Patient.is_deleted == False).first():
        raise HTTPException(404, "Paciente no encontrado")
    if not db.query(Professional).filter(Professional.id == data.professional_id, Professional.is_deleted == False).first():
        raise HTTPException(404, "Profesional no encontrado")

    appt = Appointment(**data.model_dump())
    db.add(appt)
    db.commit()
    db.refresh(appt)
    return appt


@router.put("/appointments/{appt_id}", response_model=AppointmentRead)
def update_appointment(appt_id: UUID, data: AppointmentUpdate, db: Session = Depends(get_db)):
    a = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.is_deleted == False).first()
    if not a:
        raise HTTPException(404, "Turno no encontrado")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(a, key, val)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/appointments/{appt_id}")
def soft_delete_appointment(appt_id: UUID, db: Session = Depends(get_db)):
    a = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if not a:
        raise HTTPException(404, "Turno no encontrado")
    a.is_deleted = True
    db.commit()
    return {"detail": "Turno eliminado (soft-delete)"}


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
