"""Que un turno para un familiar no se cargue en la ficha del dueño del teléfono.

Caso 8 y I01 del plan de QA, verificado en el código (bot_routes.py:393-398).

Cuando el bot no manda DNI, el backend resolvía la ficha por el teléfono y se
quedaba con SU DNI, aunque el bot hubiera pasado otro nombre. Como el alta busca
primero por DNI, el turno del familiar terminaba en la ficha del titular: dos
personas con una sola historia clínica.

Un teléfono es un contacto, no un paciente. En una familia lo comparten.
"""
import pytest
from fastapi import HTTPException

from backend.models.appointment import Appointment
from backend.models.patient import Patient
from backend.routers.bot_routes import bot_create_appointment
from backend.schemas.schemas import BotAppointmentRequest
from conftest import proximo_dia_habil

TELEFONO = "+5492604590071"


def _pedir(db, nombre=None, apellido=None, cuando=None, dni=None):
    return bot_create_appointment(BotAppointmentRequest(
        patient_name=nombre, patient_last_name=apellido, dni=dni,
        reason="Extracción", location="San Rafael",
        preferred_date=(cuando or proximo_dia_habil()).strftime("%Y-%m-%d %H:%M"),
        requester_phone=TELEFONO,
    ), db=db)


@pytest.fixture
def titular(db):
    """Quien ya usa ese teléfono, con su ficha y su DNI."""
    p = Patient(first_name="Claudio", last_name="Luna", dni="24785465", phone=TELEFONO)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ── El caso que estaba mal ──────────────────────────────────────────────────

def test_el_familiar_no_hereda_el_dni_del_titular(db, clinica, silvestro, titular):
    _pedir(db, "Morena", "Funes")

    morena = db.query(Patient).filter(Patient.first_name == "Morena").first()
    assert morena is not None, "No creó la ficha del familiar"
    assert morena.id != titular.id
    assert morena.dni != titular.dni
    assert morena.dni is None, "Le puso el DNI de otra persona"


def test_el_turno_del_familiar_no_queda_en_la_ficha_del_titular(
    db, clinica, silvestro, titular
):
    r = _pedir(db, "Morena", "Funes")
    turno = db.query(Appointment).filter(
        Appointment.id == r["appointment_id"]).first()
    assert turno.patient_id != titular.id, (
        "El turno del familiar quedó en la historia clínica del titular"
    )


def test_no_le_toca_la_ficha_al_titular(db, clinica, silvestro, titular):
    _pedir(db, "Morena", "Funes")
    db.refresh(titular)
    assert titular.first_name == "Claudio"
    assert titular.dni == "24785465"
    assert titular.phone == TELEFONO


# ── Lo que tiene que seguir andando ─────────────────────────────────────────

def test_sin_nombre_el_turno_es_para_quien_usa_el_telefono(
    db, clinica, silvestro, titular
):
    """El caso normal: el paciente de siempre pide turno y no dice su nombre."""
    r = _pedir(db)
    turno = db.query(Appointment).filter(
        Appointment.id == r["appointment_id"]).first()
    assert turno.patient_id == titular.id


def test_con_su_propio_nombre_usa_su_ficha(db, clinica, silvestro, titular):
    r = _pedir(db, "Claudio", "Luna")
    turno = db.query(Appointment).filter(
        Appointment.id == r["appointment_id"]).first()
    assert turno.patient_id == titular.id
    assert db.query(Patient).filter(Patient.last_name == "Luna").count() == 1


def test_el_nombre_al_reves_sigue_siendo_la_misma_persona(
    db, clinica, silvestro, titular
):
    """La agenda de papel escribe "Luna Claudio"; es el mismo."""
    r = _pedir(db, "Luna", "Claudio")
    turno = db.query(Appointment).filter(
        Appointment.id == r["appointment_id"]).first()
    assert turno.patient_id == titular.id


def test_dos_familiares_tienen_dos_fichas(db, clinica, silvestro, titular):
    from datetime import timedelta
    cuando = proximo_dia_habil()
    _pedir(db, "Morena", "Funes", cuando)
    _pedir(db, "Elias", "Carrazan", cuando + timedelta(hours=1))

    assert db.query(Patient).filter(Patient.is_deleted == False).count() == 3
    ids = {a.patient_id for a in db.query(Appointment).all()}
    assert len(ids) == 2, "Los dos turnos quedaron en la misma ficha"


def test_con_varios_en_el_telefono_y_nombre_dado_no_pregunta(
    db, clinica, silvestro, titular
):
    """Si el bot ya dijo de quién es el turno, no hay nada que preguntar."""
    from datetime import timedelta
    cuando = proximo_dia_habil()
    _pedir(db, "Morena", "Funes", cuando)          # ahora son dos en el número

    r = _pedir(db, "Claudio", "Luna", cuando + timedelta(hours=1))
    turno = db.query(Appointment).filter(
        Appointment.id == r["appointment_id"]).first()
    assert turno.patient_id == titular.id


def test_con_varios_en_el_telefono_y_sin_nombre_si_pregunta(
    db, clinica, silvestro, titular
):
    """Ahí sí es ambiguo: hay que preguntar, no adivinar."""
    from datetime import timedelta
    cuando = proximo_dia_habil()
    _pedir(db, "Morena", "Funes", cuando)

    with pytest.raises(HTTPException) as e:
        _pedir(db, cuando=cuando + timedelta(hours=1))
    assert "¿Para quién es?" in e.value.detail
