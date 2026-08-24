"""Encontrar la obra social entre 45, sin escribirla completa.

La clinica tiene ~45 cargadas y una lista de WhatsApp admite 10 filas, asi que
no entran. Y el error real no es de una letra: alguien escribe "ospeysin"
buscando OSPELSYM, que son tres sustituciones. Corregir tipeos ahi no alcanza;
lo que funciona es buscar por como empieza.
"""
import pytest

from backend.models.insurance import Insurance
from backend.services.appointment_service import (
    buscar_obras_sociales, match_insurance, obras_sociales_frecuentes,
)
from conftest import proximo_dia_habil, turno

NOMBRES = [
    "OSDE", "OSDE 210", "OSEP", "OSPELSYM", "OSPE", "OSPRERA", "OSPACA",
    "Swiss Medical", "Medifé", "Galeno", "Sancor Salud", "Omint", "PAMI",
    "Jerárquicos Salud", "Avalian", "Unión Personal", "Medicus", "MetLife",
]


@pytest.fixture
def muchas(db):
    db.query(Insurance).delete()
    db.add_all([Insurance(name=n, is_active=True) for n in NOMBRES])
    db.commit()


def test_encuentra_la_que_el_paciente_escribio_mal(db, muchas):
    """El caso real: escribió 'ospeysin' buscando OSPELSYM."""
    assert "OSPELSYM" in buscar_obras_sociales(db, "ospeysin")


def test_busca_por_las_primeras_letras(db, muchas):
    r = buscar_obras_sociales(db, "ospe")
    assert "OSPE" in r and "OSPELSYM" in r


def test_ignora_acentos(db, muchas):
    assert "Medifé" in buscar_obras_sociales(db, "medife")
    assert "Jerárquicos Salud" in buscar_obras_sociales(db, "jerarquicos")


def test_encuentra_por_una_palabra_del_nombre(db, muchas):
    assert "Swiss Medical" in buscar_obras_sociales(db, "swiss")
    assert "Sancor Salud" in buscar_obras_sociales(db, "sancor")


def test_lo_mas_parecido_va_primero(db, muchas):
    assert buscar_obras_sociales(db, "osde")[0] == "OSDE"


def test_no_inventa_coincidencias(db, muchas):
    assert buscar_obras_sociales(db, "banelco") == []
    assert buscar_obras_sociales(db, "") == []


def test_nunca_devuelve_mas_de_diez(db, muchas):
    """El tope de una lista de WhatsApp."""
    assert len(buscar_obras_sociales(db, "os")) <= 10


def test_particular_no_aparece_como_obra_social(db, muchas):
    db.add(Insurance(name="Particular", is_active=True))
    db.commit()
    assert "Particular" not in buscar_obras_sociales(db, "particular")


def test_no_ofrece_las_inactivas(db, muchas):
    baja = db.query(Insurance).filter(Insurance.name == "Galeno").first()
    baja.is_active = False
    db.commit()
    assert "Galeno" not in buscar_obras_sociales(db, "galeno")


# ── Las frecuentes, para la primera lista ────────────────────────────────────

def test_las_mas_usadas_van_primero(db, clinica, muchas, silvestro, paciente):
    """Con 45 cargadas, la primera lista tiene que mostrar las que de verdad se usan."""
    for i in range(3):
        turno(db, paciente, silvestro,
              proximo_dia_habil() .replace(hour=9 + i), insurance="OSEP")
    turno(db, paciente, silvestro, proximo_dia_habil().replace(hour=17), insurance="Omint")

    frecuentes = obras_sociales_frecuentes(db)
    assert frecuentes[0] == "OSEP"
    assert "Omint" in frecuentes[:3]


def test_las_frecuentes_entran_en_una_lista(db, muchas):
    assert len(obras_sociales_frecuentes(db)) <= 9, "No entrarían junto a 'Particular'"


def test_sin_historial_igual_devuelve_opciones(db, muchas):
    """Una clínica recién instalada no tiene turnos de donde sacar frecuencia."""
    assert len(obras_sociales_frecuentes(db)) > 0


# ── El matching estricto del alta no se afloja ───────────────────────────────

def test_agendar_sigue_exigiendo_el_nombre_correcto(db, muchas):
    """Buscar es tolerante; agendar no. 'ospeysin' no puede dar por cubierta a
    OSPELSYM sin que el paciente la haya elegido."""
    assert match_insurance("ospeysin", db) is None
    assert match_insurance("OSPELSYM", db) is not None
