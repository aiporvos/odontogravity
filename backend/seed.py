"""Initial seed data for Dental Studio Pro."""
from sqlalchemy.orm import Session
from backend.models.user import User, UserRole
from backend.models.professional import Professional
from backend.models.clinic_location import ClinicLocation
from backend.models.insurance import Insurance
from backend.security import hash_password


def run_seed(db: Session):
    """Seed initial data if tables are empty."""

    # ── Admin user ──────────────────────────────────────
    if not db.query(User).first():
        admin = User(
            email="admin@dentalstudio.com",
            hashed_password=hash_password("admin123"),
            full_name="Administrador",
            role=UserRole.admin,
        )
        receptionist = User(
            email="recepcion@dentalstudio.com",
            hashed_password=hash_password("recepcion123"),
            full_name="Recepcionista",
            role=UserRole.receptionist,
        )
        db.add_all([admin, receptionist])
        db.commit()

    # ── Professionals ───────────────────────────────────
    if not db.query(Professional).first():
        dr_silvestro = Professional(
            full_name="Dr. Silvestro",
            license_number="MP-001",
            specialties=["Extracciones", "Implantes", "Prótesis"],
            locations=["San Rafael", "Alvear"],
        )
        dra_murad = Professional(
            full_name="Dra. Murad",
            license_number="MP-002",
            specialties=["Ortodoncia", "Endodoncia", "Conductos"],
            locations=["San Rafael", "Alvear"],
        )
        db.add_all([dr_silvestro, dra_murad])
        db.commit()

    # ── Locations ───────────────────────────────────────
    if not db.query(ClinicLocation).first():
        db.add_all([
            ClinicLocation(name="San Rafael", address="Sede San Rafael"),
            ClinicLocation(name="Alvear", address="Sede Alvear"),
        ])
        db.commit()

    # ── Insurances ──────────────────────────────────────
    if not db.query(Insurance).first():
        db.add_all([
            Insurance(name="OSEP", code="OSEP"),
            Insurance(name="OSPELSYM", code="OSPELSYM"),
            Insurance(name="OSDE", code="OSDE"),
            Insurance(name="Swiss Medical", code="SM"),
            Insurance(name="Particular", code="PART"),
        ])
        db.commit()
