"""Duración y ruteo salen de la base, no del código.

Pedido del consultorio: "dependiendo de para qué es y sabiendo que el sistema
tiene definido que atiende cada uno de los profesionales, determinar si el turno
es para Martin o para Elena, y también dependiendo para qué es el turno qué
duración tiene".

La mitad ya estaba: las especialidades de cada profesional se cargan desde el
panel. La otra mitad no: la duración de cada tipo de turno y los sinónimos con
que los pacientes lo nombran estaban escritos a mano en appointment_service.py.
"""
import pytest

from backend.models.professional import Professional
from backend.models.tipo_consulta import TipoConsulta
from backend.services.appointment_service import (
    duracion_para_motivo, find_professionals_for_reason,
)

TIPOS = [
    ("Control", 15, "Consulta", ["control", "revision", "chequeo", "duele"]),
    ("Limpieza", 15, "Limpieza", ["limpiar", "sarro", "profilaxis"]),
    ("Extracción", 30, "Extracción", ["sacar", "muela", "cordal"]),
    ("Ortodoncia", 30, "Ortodoncia", ["brackets", "aparato"]),
    ("Conducto", 60, "Endodoncia", ["conducto", "nervio"]),
]


@pytest.fixture
def tipos(db):
    db.add_all([
        TipoConsulta(nombre=n, duracion_minutos=d, especialidad=e, sinonimos=s)
        for n, d, e, s in TIPOS
    ])
    db.commit()


@pytest.fixture
def equipo(db):
    martin = Professional(full_name="Dr. Martin Silvestro", license_number="MP-1",
                          specialties=["Extracción", "Prótesis"], locations=["San Rafael"])
    elena = Professional(full_name="Dra. Elena Murad", license_number="MP-2",
                         specialties=["Ortodoncia", "Endodoncia"], locations=["San Rafael"])
    db.add_all([martin, elena])
    db.commit()
    db.refresh(martin)
    db.refresh(elena)
    return martin, elena


# ── Duración ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("motivo,esperado", [
    ("control", 15),
    ("limpieza", 15),
    ("sacar una muela", 30),
    ("brackets", 30),
    ("conducto", 60),
])
def test_la_duracion_sale_de_la_tabla(db, tipos, motivo, esperado):
    assert duracion_para_motivo(motivo, db) == esperado


def test_la_clinica_puede_cambiar_una_duracion(db, tipos):
    """Sin tocar código: es el punto del cambio."""
    limpieza = db.query(TipoConsulta).filter(TipoConsulta.nombre == "Limpieza").first()
    limpieza.duracion_minutos = 45
    db.commit()
    assert duracion_para_motivo("limpieza", db) == 45


def test_la_clinica_puede_agregar_un_sinonimo(db, tipos):
    """'se me rompió un diente' no matcheaba con nada; ahora se arregla desde el panel."""
    assert duracion_para_motivo("se me rompio un diente", db) == 15  # cae en genérico

    db.add(TipoConsulta(nombre="Arreglos", duracion_minutos=30, especialidad="Arreglos",
                        sinonimos=["rompio", "roto", "caries", "empaste"]))
    db.commit()
    assert duracion_para_motivo("se me rompio un diente", db) == 30


def test_un_tipo_desactivado_no_se_usa(db, tipos):
    conducto = db.query(TipoConsulta).filter(TipoConsulta.nombre == "Conducto").first()
    conducto.is_active = False
    db.commit()
    assert duracion_para_motivo("conducto", db) != 60


def test_sin_tabla_usa_los_valores_de_siempre():
    """Una base todavía sin migrar no puede quedarse sin duraciones."""
    assert duracion_para_motivo("extracción") == 30
    assert duracion_para_motivo("conducto") == 60
    assert duracion_para_motivo("control") == 15


# ── Ruteo al profesional correcto ───────────────────────────────────────────

def test_una_extraccion_va_a_martin(db, tipos, equipo):
    martin, _ = equipo
    assert [p.id for p in find_professionals_for_reason("sacar una muela", db)] == [martin.id]


def test_un_conducto_va_a_elena(db, tipos, equipo):
    _, elena = equipo
    assert [p.id for p in find_professionals_for_reason("conducto", db)] == [elena.id]


def test_los_brackets_van_a_elena(db, tipos, equipo):
    _, elena = equipo
    assert [p.id for p in find_professionals_for_reason("brackets", db)] == [elena.id]


def test_un_motivo_que_atienden_los_dos_los_ofrece_a_los_dos(db, tipos, equipo):
    """Un control genérico no debe quedar atado a uno solo."""
    assert len(find_professionals_for_reason("control", db)) == 2


def test_cambiar_la_especialidad_cambia_a_quien_va(db, tipos, equipo):
    """Si Elena empieza a hacer extracciones, el ruteo tiene que seguirla."""
    martin, elena = equipo
    elena.specialties = ["Ortodoncia", "Endodoncia", "Extracción"]
    db.commit()

    quienes = {p.id for p in find_professionals_for_reason("sacar una muela", db)}
    assert quienes == {martin.id, elena.id}
