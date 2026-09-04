"""Que unificar fichas duplicadas no pierda datos ni mezcle a dos personas.

El script existia y movia turnos, odontograma y conversaciones a la ficha que
sobrevive. Pero elige la sobreviviente por cantidad de turnos, no por tener el
documento cargado, y el DNI no estaba en la lista de datos que se conservan: si
la que ganaba no tenia DNI, el DNI de la otra se iba con la ficha dada de baja.

Y le faltaba una defensa: dos fichas del mismo nombre con DNI o telefono
DISTINTOS no son un duplicado, son dos personas que se llaman igual. Fusionarlas
mezcla dos historias clinicas, que es peor que dejar el duplicado.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from backend.models.appointment import Appointment
from backend.models.patient import Patient
from conftest import proximo_dia_habil, turno

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / "scripts" / "unificar_pacientes_duplicados.py"


def _correr(*args):
    import os
    entorno = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    r = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True, cwd=RAIZ, env=entorno)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _ficha(db, nombre, apellido, dni=None, phone=None, insurance=None):
    p = Patient(first_name=nombre, last_name=apellido, dni=dni, phone=phone,
                insurance_name=insurance)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ── El DNI no se pierde ─────────────────────────────────────────────────────

def test_el_dni_pasa_a_la_ficha_que_sobrevive(db, clinica, silvestro):
    """El caso real: la que tiene mas turnos no es la que tiene el documento."""
    con_turnos = _ficha(db, "Maria", "Lopez")
    turno(db, con_turnos, silvestro, proximo_dia_habil())
    con_dni = _ficha(db, "maria", "lopez", dni="18488445", phone="2604641220")

    _correr()
    db.expire_all()

    sobrevive = db.query(Patient).filter(Patient.id == con_turnos.id).first()
    retirada = db.query(Patient).filter(Patient.id == con_dni.id).first()
    assert sobrevive.is_deleted is False
    assert sobrevive.dni == "18488445", "Se perdio el DNI al unificar"
    assert sobrevive.phone == "2604641220"
    assert retirada.is_deleted is True
    assert retirada.dni is None, (
        "El DNI tiene que SALIR de la ficha retirada: la columna es UNIQUE y el "
        "indice tambien cuenta las dadas de baja"
    )


def test_no_le_pisa_el_dni_a_la_que_ya_tenia_uno(db, clinica, silvestro):
    buena = _ficha(db, "Jose", "Marich", dni="45360806", phone="2604224628")
    turno(db, buena, silvestro, proximo_dia_habil())
    _ficha(db, "jose", "marich", dni=None)

    _correr()
    db.expire_all()
    assert db.query(Patient).filter(Patient.id == buena.id).first().dni == "45360806"


# ── Los turnos quedan en una sola ficha ─────────────────────────────────────

def test_los_turnos_quedan_todos_en_la_que_sobrevive(db, clinica, silvestro):
    from datetime import timedelta
    cuando = proximo_dia_habil()
    a = _ficha(db, "Juli", "Lopez")
    b = _ficha(db, "juli", "lopez")
    c = _ficha(db, "JULI", "LOPEZ")
    turno(db, a, silvestro, cuando)
    turno(db, a, silvestro, cuando + timedelta(hours=1))
    turno(db, b, silvestro, cuando + timedelta(hours=2))
    turno(db, c, silvestro, cuando + timedelta(hours=3))

    _correr()
    db.expire_all()

    assert db.query(Appointment).filter(Appointment.patient_id == a.id).count() == 4
    assert db.query(Patient).filter(
        Patient.is_deleted == False, Patient.last_name.ilike("lopez")).count() == 1


# ── Dos personas que se llaman igual NO se fusionan ─────────────────────────

def test_no_fusiona_dos_dni_distintos(db, clinica, silvestro):
    uno = _ficha(db, "Juan", "Perez", dni="20111222")
    otro = _ficha(db, "juan", "perez", dni="30333444")
    turno(db, uno, silvestro, proximo_dia_habil())

    salida = _correr()
    db.expire_all()

    assert db.query(Patient).filter(Patient.id == otro.id).first().is_deleted is False, (
        "Fusiono a dos personas distintas: mezclo dos historias clinicas"
    )
    assert "saltearon" in salida.lower()


def test_no_fusiona_dos_telefonos_distintos(db, clinica, silvestro):
    uno = _ficha(db, "Ana", "Gomez", phone="2604111111")
    otro = _ficha(db, "ana", "gomez", phone="2604999999")

    _correr()
    db.expire_all()
    assert db.query(Patient).filter(Patient.id == otro.id).first().is_deleted is False


def test_el_mismo_telefono_en_otro_formato_no_frena_la_union(db, clinica, silvestro):
    """+5492604590071 y 2604590071 son el mismo numero."""
    uno = _ficha(db, "Elsa", "Suarez", phone="+5492604590071")
    otro = _ficha(db, "elsa", "suarez", phone="2604590071")
    turno(db, uno, silvestro, proximo_dia_habil())

    _correr()
    db.expire_all()
    assert db.query(Patient).filter(Patient.id == otro.id).first().is_deleted is True


# ── El dry-run no escribe ───────────────────────────────────────────────────

def test_dry_run_no_toca_nada(db, clinica, silvestro):
    a = _ficha(db, "Diego", "Amaya")
    b = _ficha(db, "diego", "amaya")
    turno(db, a, silvestro, proximo_dia_habil())

    salida = _correr("--dry-run")
    db.expire_all()

    assert db.query(Patient).filter(Patient.id == b.id).first().is_deleted is False
    assert "no se escribió nada" in salida


def test_sin_duplicados_no_hace_nada(db, clinica, paciente):
    assert "No hay fichas duplicadas" in _correr("--dry-run")
