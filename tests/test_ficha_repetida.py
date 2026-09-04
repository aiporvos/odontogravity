"""Que no se pueda cargar dos veces al mismo paciente sin enterarse.

Produccion tiene 61 nombres repetidos —algunos con 3 y 4 fichas— que salieron de
cargar sin mirar si ya estaban. Cada ficha repetida parte la historia clinica en
dos y despues hay que unificarla a mano.

Unificar es la mitad de atras del problema; esta es la de adelante: al crear se
avisa que ya hay alguien con ese nombre, y quien carga decide si es la misma
persona o un homonimo.

El bot no pasa por aca: identifica por telefono + nombre
(_misma_persona_ya_cargada), que es mas fuerte que el nombre solo y no necesita
preguntarle nada al paciente.
"""
import pytest
from fastapi import HTTPException

from backend.models.patient import Patient
from backend.routers.clinic.clinic_routes import create_patient
from backend.schemas.schemas import PatientCreate
from conftest import proximo_dia_habil, turno


def _alta(db, nombre, apellido, **extra):
    return create_patient(
        PatientCreate(first_name=nombre, last_name=apellido, **extra), db=db)


# ── Avisa ───────────────────────────────────────────────────────────────────

def test_avisa_cuando_ya_hay_alguien_con_ese_nombre(db):
    _alta(db, "Juli", "Lopez")
    with pytest.raises(HTTPException) as e:
        _alta(db, "Juli", "Lopez")
    assert e.value.status_code == 409
    assert e.value.detail["puede_duplicar"] is True


@pytest.mark.parametrize("nombre,apellido", [
    ("juan", "rodriguez"),      # minusculas
    ("JUAN", "RODRIGUEZ"),      # mayusculas
    ("Juan", "Rodriguez"),      # sin acento
    ("Rodriguez", "Juan"),      # al reves: la agenda de papel usa las dos formas
])
def test_ignora_mayusculas_acentos_y_orden(db, nombre, apellido):
    _alta(db, "Juan", "Rodríguez")
    with pytest.raises(HTTPException) as e:
        _alta(db, nombre, apellido)
    assert e.value.status_code == 409


def test_el_aviso_trae_los_datos_para_poder_decidir(db, clinica, silvestro):
    """Con el nombre solo no se puede saber si es la misma persona."""
    ya = _alta(db, "Maria", "Lopez", dni="18488445", phone="2604641220")
    turno(db, ya, silvestro, proximo_dia_habil())

    with pytest.raises(HTTPException) as e:
        _alta(db, "maria", "lopez")

    ficha = e.value.detail["ya_existen"][0]
    assert ficha["id"] == str(ya.id)
    assert ficha["dni"] == "18488445"
    assert ficha["phone"] == "2604641220"
    assert ficha["turnos"] == 1


def test_lista_todas_las_fichas_repetidas(db):
    _alta(db, "Leonel", "Pugno")
    _alta(db, "leonel", "pugno", force=True)
    with pytest.raises(HTTPException) as e:
        _alta(db, "LEONEL", "PUGNO")
    assert len(e.value.detail["ya_existen"]) == 2


# ── Pero no bloquea ─────────────────────────────────────────────────────────

def test_con_force_se_crea_igual(db):
    """Dos personas distintas se pueden llamar igual."""
    _alta(db, "Juan", "Perez")
    otro = _alta(db, "Juan", "Perez", force=True)
    assert otro.id is not None
    assert db.query(Patient).filter(
        Patient.is_deleted == False, Patient.last_name.ilike("perez")).count() == 2


def test_un_nombre_nuevo_no_molesta(db):
    _alta(db, "Juli", "Lopez")
    assert _alta(db, "Juli", "Gomez") is not None
    assert _alta(db, "Ana", "Lopez") is not None


def test_una_ficha_dada_de_baja_no_cuenta(db):
    """Si se unifico y quedo retirada, el nombre vuelve a estar libre."""
    vieja = _alta(db, "Diego", "Amaya")
    vieja.is_deleted = True
    db.commit()
    assert _alta(db, "Diego", "Amaya") is not None


# ── El DNI repetido se sigue rechazando aparte ──────────────────────────────

def test_el_dni_repetido_no_se_puede_forzar(db):
    """force es para el nombre; el DNI es unico de verdad."""
    _alta(db, "Ana", "Gomez", dni="30111222")
    with pytest.raises(HTTPException) as e:
        _alta(db, "Otro", "Distinto", dni="30111222", force=True)
    assert e.value.status_code == 400
