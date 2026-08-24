"""Infraestructura de tests.

Corren contra una base PostgreSQL de verdad, no SQLite: el esquema usa tipos
propios de Postgres (UUID, ENUM) y el indice unico parcial que evita la doble
reserva tampoco existe en SQLite. Probar sobre otro motor daria una falsa
sensacion de cobertura justo en lo que mas importa.

La base se llama dentibot_test y se recrea entera en cada corrida.

    createdb dentibot_test   # o docker exec ... psql -c "CREATE DATABASE dentibot_test"
    pytest
"""
import os
import uuid
from datetime import datetime, timedelta, time as py_time

import pytest
from sqlalchemy import text as sa_text

# Tiene que quedar seteado ANTES de importar nada del backend: database.py lee
# DATABASE_URL al importarse, y security.py/bot_routes.py abortan si no hay
# SECRET_KEY y BOT_API_KEY propias.
os.environ.setdefault(
    "DATABASE_URL",
    os.getenv("TEST_DATABASE_URL",
              "postgresql://dentibot:dentibot_secure_2024@localhost:5432/dentibot_test"),
)
os.environ.setdefault("SECRET_KEY", "clave-solo-para-tests-no-usar-en-serio")
os.environ.setdefault("BOT_API_KEY", "bot-key-solo-para-tests")

from backend.database import Base, engine, SessionLocal  # noqa: E402
from backend.models import *  # noqa: E402,F401,F403  (registra todo en Base.metadata)
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel  # noqa: E402
from backend.models.clinic_location import ClinicLocation  # noqa: E402
from backend.models.config import AppConfig  # noqa: E402
from backend.models.insurance import Insurance  # noqa: E402
from backend.models.patient import Patient  # noqa: E402
from backend.models.professional import Professional  # noqa: E402
from backend.models.schedule import ClinicSchedule, ClinicHoliday  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def esquema():
    """Crea el esquema una vez y aplica las migraciones, igual que el arranque real."""
    Base.metadata.drop_all(bind=engine)
    # alembic_version no pertenece a Base.metadata, asi que drop_all no la toca.
    # Si queda de una corrida anterior, Alembic se cree al dia y saltea TODAS las
    # migraciones sobre el esquema recien creado: el indice unico nunca se crea y
    # los tests pasan a verde por el motivo equivocado.
    with engine.begin() as conn:
        conn.execute(sa_text("DROP TABLE IF EXISTS alembic_version"))

    Base.metadata.create_all(bind=engine)

    from alembic.config import Config
    from alembic import command
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(raiz, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(raiz, "database/migrations"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")

    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db(esquema):
    """Sesion limpia: cada test arranca sin datos de los anteriores."""
    sesion = SessionLocal()
    for tabla in reversed(Base.metadata.sorted_tables):
        sesion.execute(tabla.delete())
    sesion.commit()
    try:
        yield sesion
    finally:
        sesion.rollback()
        sesion.close()


# ── Datos base ───────────────────────────────────────────────────────────────

@pytest.fixture
def clinica(db):
    """Horario real del consultorio: L-V 09:00-12:30 y 17:00-20:30, miércoles sin tarde."""
    for wd in range(0, 5):
        db.add(ClinicSchedule(id=uuid.uuid4(), weekday=wd,
                              start_time=py_time(9, 0), end_time=py_time(12, 30),
                              is_active=True))
        if wd != 2:
            db.add(ClinicSchedule(id=uuid.uuid4(), weekday=wd,
                                  start_time=py_time(17, 0), end_time=py_time(20, 30),
                                  is_active=True))
    db.add(ClinicLocation(name="San Rafael"))
    db.add(Insurance(name="PAMI", is_active=True))
    db.add(Insurance(name="OSDE", is_active=True))
    db.commit()


@pytest.fixture
def silvestro(db):
    p = Professional(full_name="Dr. Sergio Silvestro", license_number="MP-10520",
                     specialties=["Extracción", "Implantes"], locations=["San Rafael"])
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def murad(db):
    p = Professional(full_name="Dra. Lucía Murad", license_number="MP-12480",
                     specialties=["Ortodoncia"], locations=["San Rafael"])
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def paciente(db):
    p = Patient(first_name="Claudio", last_name="Luna", dni="24785465",
                phone="+5492604590071", insurance_name="Particular")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture
def otro_paciente(db):
    p = Patient(first_name="Estela", last_name="Pardo", dni="10203040",
                phone="+5492604111222", insurance_name="Particular")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ── Utilidades de fecha ──────────────────────────────────────────────────────

def proximo_dia_habil(desde: datetime = None, weekday: int = None) -> datetime:
    """Un martes (o el weekday pedido) futuro a las 10:00.

    Los tests no pueden depender del dia en que se corren: la clinica cierra
    los miercoles a la tarde y los viernes son solo PAMI.
    """
    base = (desde or datetime.now()) + timedelta(days=1)
    objetivo = 1 if weekday is None else weekday  # 1 = martes
    while base.weekday() != objetivo:
        base += timedelta(days=1)
    return base.replace(hour=10, minute=0, second=0, microsecond=0)


def turno(db, paciente, profesional, cuando, duracion=30, location="San Rafael",
          status=AppointmentStatus.confirmed, insurance="Particular", reason="Extracción"):
    a = Appointment(
        patient_id=paciente.id, professional_id=profesional.id, start_time=cuando,
        duration_minutes=duracion, reason=reason, location=location,
        insurance_name=insurance, status=status, channel=AppointmentChannel.bot_whatsapp,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a
