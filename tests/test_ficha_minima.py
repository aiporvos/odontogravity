"""Que para dar de alta una ficha alcancen el nombre y el apellido.

Recepcion carga fichas desde la agenda de papel, donde la mayoria de los turnos
solo tiene un nombre anotado. Con el DNI y el telefono obligatorios, la unica
forma de guardar esa ficha era inventarlos. El DNI inventado salia como
"TMP-dfsgtfk603" y se leia en la lista como si fuera un documento; un telefono
inventado es peor, porque el recordatorio le llega a un tercero.
"""
import pytest
from fastapi import HTTPException

from backend.models.patient import Patient
from backend.routers.clinic.clinic_routes import (
    create_patient, list_patients, update_patient,
)
from backend.schemas.schemas import PatientCreate, PatientUpdate


# ── Alta ─────────────────────────────────────────────────────────────────────

def test_alcanza_con_nombre_y_apellido(db):
    p = create_patient(PatientCreate(first_name="Morena", last_name="Funez"), db=db)
    assert p.dni is None
    assert p.phone is None


def test_dos_fichas_sin_dni_conviven(db):
    """El chequeo de duplicado se traducia a "dni IS NULL": la primera ficha
    sin DNI hacia rebotar a todas las siguientes con "DNI ya registrado"."""
    create_patient(PatientCreate(first_name="Morena", last_name="Funez"), db=db)
    create_patient(PatientCreate(first_name="Elias", last_name="Carrazan"), db=db)
    assert db.query(Patient).filter(Patient.dni.is_(None)).count() == 2


def test_los_vacios_se_guardan_como_null_no_como_string_vacio(db):
    """Dos DNI en '' chocarian contra el indice UNIQUE; dos NULL no."""
    a = create_patient(
        PatientCreate(first_name="Ana", last_name="Perez", dni="", phone="  "), db=db)
    b = create_patient(
        PatientCreate(first_name="Beto", last_name="Gomez", dni="   ", phone=""), db=db)
    assert (a.dni, a.phone) == (None, None)
    assert (b.dni, b.phone) == (None, None)


def test_el_dni_repetido_se_sigue_rechazando(db, paciente):
    with pytest.raises(HTTPException) as e:
        create_patient(
            PatientCreate(first_name="Otro", last_name="Distinto", dni=paciente.dni), db=db)
    assert e.value.status_code == 400


# ── Edicion ──────────────────────────────────────────────────────────────────

def test_se_puede_vaciar_un_dni_provisorio(db):
    """Los 'TMP-xxxx' los invento el panel: hay que poder sacarlos."""
    p = create_patient(
        PatientCreate(first_name="Morena", last_name="Funez", dni="TMP-dfsgtfk603"), db=db)
    actualizado = update_patient(p.id, PatientUpdate(dni=""), db=db)
    assert actualizado.dni is None


def test_vaciar_el_telefono_no_deja_un_string_vacio(db, paciente):
    assert update_patient(paciente.id, PatientUpdate(phone=""), db=db).phone is None


def test_editar_el_nombre_no_toca_el_dni(db, paciente):
    """PatientUpdate usa exclude_unset: lo que no se manda, no se pisa."""
    actualizado = update_patient(paciente.id, PatientUpdate(first_name="Claudia"), db=db)
    assert actualizado.dni == paciente.dni
    assert actualizado.phone == paciente.phone


# ── Sigue siendo buscable ────────────────────────────────────────────────────

def test_una_ficha_sin_dni_ni_telefono_aparece_en_el_buscador(db):
    create_patient(PatientCreate(first_name="Morena", last_name="Funez"), db=db)
    assert [p.last_name for p in list_patients(q="funez", db=db)] == ["Funez"]


# ── Sin telefono no hay recordatorio, y se avisa ─────────────────────────────

@pytest.mark.asyncio
async def test_sin_telefono_el_recordatorio_no_se_intenta(
    db, monkeypatch, clinica, silvestro
):
    """Antes fallaba tres veces contra la API por una ficha sin telefono."""
    from backend.services import reminders_loop as rl
    from conftest import proximo_dia_habil, turno

    intentos = []

    async def _registrar(*a, **k):
        intentos.append(a)
        return False

    monkeypatch.setattr(rl, "send_whatsapp_message", _registrar)
    monkeypatch.setattr(rl, "send_whatsapp_template", _registrar)

    sin_tel = create_patient(PatientCreate(first_name="Morena", last_name="Funez"), db=db)
    a = turno(db, sin_tel, silvestro, proximo_dia_habil())

    ok = await rl.enviar_recordatorio(db, a, sin_tel, "26/08 10:00", "http://x", "msg")
    assert ok is False
    assert intentos == [], "Intento mandar el recordatorio a un telefono que no existe"
