import logging
import os
import secrets
from datetime import datetime, timedelta, date as py_date
from sqlalchemy.orm import Session
from backend.models.user import User, UserRole
from backend.models.professional import Professional
from backend.models.clinic_location import ClinicLocation
from backend.models.insurance import Insurance
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus
from backend.models.odontogram import OdontogramEntry, ToothFace, EntryCategory, ToothSymbol
from backend.security import hash_password

logger = logging.getLogger(__name__)


def _password_inicial(variable: str) -> tuple[str, bool]:
    """La password del usuario semilla: la configurada, o uno al azar.

    Antes esto sembraba "admin123" y "recepcion123", ademas publicadas en el
    README. Detras de ese login hay historia clinica y odontogramas, o sea
    datos de salud: alcanzaba con leer el repositorio para entrar.

    Ahora sale de una variable de entorno y, si no esta, se genera una al azar
    que se muestra UNA sola vez en el log del arranque. Nunca queda una
    password conocida de antemano.
    """
    definida = (os.getenv(variable) or "").strip()
    if definida:
        return definida, False
    return secrets.token_urlsafe(12), True


def run_seed(db: Session):
    """Seed initial data if tables are empty."""

    # ── Admin users ─────────────────────────────────────
    if db.query(User).count() < 2:
        semillas = [
            ("admin@dentalstudio.com", "ADMIN_PASSWORD",
             "Dr. Sergio Silvestro (Admin)", UserRole.admin),
            ("recepcion@dentalstudio.com", "RECEPCION_PASSWORD",
             "Carla Reception", UserRole.receptionist),
        ]
        for email, variable, nombre, rol in semillas:
            if db.query(User).filter(User.email == email).first():
                continue
            password, generada = _password_inicial(variable)
            db.add(User(
                email=email,
                hashed_password=hash_password(password),
                full_name=nombre,
                role=rol,
            ))
            if generada:
                logger.warning(
                    "🔑 Usuario %s creado con password generada: %s — anotala y "
                    "cambiala desde el panel. No vuelve a aparecer. Para fijarla "
                    "vos, definí %s en las variables de entorno.",
                    email, password, variable,
                )
        db.commit()

    # ── Professionals ───────────────────────────────────
    if db.query(Professional).count() == 0:
        db.add_all([
            Professional(
                full_name="Dr. Sergio Silvestro",
                license_number="MP-10520",
                specialties=["Cirugía", "Implantes", "Prótesis"],
                locations=["San Rafael", "Alvear"],
            ),
            Professional(
                full_name="Dra. Lucía Murad",
                license_number="MP-12480",
                specialties=["Ortodoncia", "Odontopediatría"],
                locations=["San Rafael"],
            )
        ])
        db.commit()

    # ── Locations & Insurances ─────────────────────────
    if db.query(ClinicLocation).count() == 0:
        db.add_all([
            ClinicLocation(name="San Rafael", address="Av. Mitre 450, San Rafael"),
            ClinicLocation(name="Alvear", address="Paso de los Andes 120, Gral. Alvear"),
        ])
        db.commit()

    if db.query(Insurance).count() == 0:
        db.add_all([
            Insurance(name="OSEP", code="001"),
            Insurance(name="OSPELSYM", code="005"),
            Insurance(name="OSDE", code="010"),
            Insurance(name="Swiss Medical", code="015"),
            Insurance(name="Particular", code="999"),
        ])
        db.commit()

    # ── Patients ───────────────────────────────────────
    if db.query(Patient).count() == 0:
        p1 = Patient(
            first_name="Carlos", last_name="Luna", dni="25123456",
            phone="2604111222", email="c.luna@test.com",
            insurance_name="OSPELSYM", insurance_number="XP-9988",
            date_of_birth=py_date(1976, 3, 15)
        )
        p2 = Patient(
            first_name="Ana", last_name="Martínez", dni="32987654",
            phone="2604333444", email="ana.m@test.com",
            insurance_name="OSEP", insurance_number="44556677",
            date_of_birth=py_date(1987, 8, 22)
        )
        p3 = Patient(
            first_name="Roberto", last_name="Sosa", dni="18333444",
            phone="2604555666", email="rober.sosa@test.com",
            insurance_name="Particular",
            date_of_birth=py_date(1965, 11, 2)
        )
        db.add_all([p1, p2, p3])
        db.commit()
        
        # Clinical Records for Carlos Luna (p1)
        db.refresh(p1)
        prof1 = db.query(Professional).first()
        
        # Appointments
        now = datetime.utcnow()
        db.add_all([
            Appointment(
                patient_id=p1.id, professional_id=prof1.id,
                start_time=now + timedelta(days=2, hours=10),
                duration_minutes=30, reason="Consulta Inicial",
                status=AppointmentStatus.confirmed, location="San Rafael"
            ),
            Appointment(
                patient_id=p2.id, professional_id=prof1.id,
                start_time=now + timedelta(days=1, hours=15),
                duration_minutes=60, reason="Limpieza y Caries",
                status=AppointmentStatus.confirmed, location="San Rafael"
            )
        ])

        # Odontogram - Clinical History OSPELSYM
        db.add_all([
            # Existing conditions (Rojo)
            OdontogramEntry(
                patient_id=p1.id, tooth_number=18, face=ToothFace.full,
                symbol=ToothSymbol.missing, category=EntryCategory.preexisting
            ),
            OdontogramEntry(
                patient_id=p1.id, tooth_number=11, face=ToothFace.vestibular,
                symbol=ToothSymbol.cavity, category=EntryCategory.preexisting
            ),
            OdontogramEntry(
                patient_id=p1.id, tooth_number=21, face=ToothFace.full,
                symbol=ToothSymbol.fracture, category=EntryCategory.preexisting
            ),
            # Treatments performed or planned (Azul)
            OdontogramEntry(
                patient_id=p1.id, tooth_number=16, face=ToothFace.full,
                symbol=ToothSymbol.crown, category=EntryCategory.treatment
            ),
            OdontogramEntry(
                patient_id=p1.id, tooth_number=24, face=ToothFace.full,
                symbol=ToothSymbol.extraction, category=EntryCategory.treatment
            ),
            OdontogramEntry(
                patient_id=p1.id, tooth_number=36, face=ToothFace.full,
                symbol=ToothSymbol.root_canal, category=EntryCategory.treatment
            ),
            OdontogramEntry(
                patient_id=p1.id, tooth_number=45, face=ToothFace.full,
                symbol=ToothSymbol.sff, category=EntryCategory.treatment
            ),
            OdontogramEntry(
                patient_id=p1.id, tooth_number=48, face=ToothFace.full,
                symbol=ToothSymbol.bridge, category=EntryCategory.treatment
            )
        ])
        db.commit()
