"""Que "Jerárquicos Salud" no se guarde como "tv salud".

Simulación con IA real, 22/10: con cualquier modelo, la cobertura terminaba
cambiada. "tv salud" se reducía a la palabra "salud" ("tv" es corta) y esa
palabra está en muchas: SanCor Salud, Federada Salud, Jerárquicos Salud... La
primera de la tabla que coincidía se llevaba el turno.
"""
import pytest

from backend.models.insurance import Insurance
from backend.services.appointment_service import match_insurance

ACTIVAS = ["tv salud", "TV Salud (OSPTV)", "Jerárquicos Salud", "SanCor Salud",
           "Federada Salud", "Prevención Salud", "Swiss Medical", "Omint",
           "Omint C.S. Consulmed", "OSEP", "OSPELSYM", "Particular"]


@pytest.fixture
def obras(db):
    # "tv salud" primero a propósito: era la que se quedaba con todo.
    for nombre in ACTIVAS:
        db.add(Insurance(name=nombre, is_active=True))
    db.add(Insurance(name="OSDE", is_active=False))
    db.commit()


@pytest.mark.parametrize("nombre", ACTIVAS)
def test_cada_una_se_encuentra_a_si_misma(db, obras, nombre):
    assert match_insurance(nombre, db).name == nombre


@pytest.mark.parametrize("dicho, esperada", [
    ("jerarquicos", "Jerárquicos Salud"),
    ("JERÁRQUICOS SALUD", "Jerárquicos Salud"),
    ("sancor", "SanCor Salud"),
    ("swiss", "Swiss Medical"),
    ("osep", "OSEP"),
    ("omint consulmed", "Omint C.S. Consulmed"),
])
def test_variantes_del_paciente(db, obras, dicho, esperada):
    assert match_insurance(dicho, db).name == esperada


@pytest.mark.parametrize("dicho", ["salud", "obra social", "medical", "ospe", "osde"])
def test_lo_generico_o_inexistente_no_se_adivina(db, obras, dicho):
    assert match_insurance(dicho, db) is None
