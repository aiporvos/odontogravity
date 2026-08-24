"""Que buscar la obra social funcione aunque el modelo no colabore.

Caso real del 23/08/2026, con la lista ya andando:

    bot:      elegí tu obra social o escribime las primeras letras  [lista]
    paciente: sw
    bot:      elegí tu obra social o escribime las primeras letras  [MISMA lista]
    paciente: swi
    bot:      no trabajamos con la obra social 'swi'...

Dos fallas del modelo, no del código: primero llamó a listar_obras_sociales sin
pasar el "sw", y después llamó a verificar_obra_social —la herramienta
equivocada— con "swi". El prompt le pedía las dos cosas bien.

Un prompt es un pedido, no una garantía. Estas son las garantías.
"""
import pytest

from backend.models.insurance import Insurance
from backend.services.appointment_service import buscar_obras_sociales
from bot.tools.appointment_tools import _texto_parece_busqueda

NOMBRES = ["OSDE", "OSEP", "OSPELSYM", "Swiss Medical", "Sancor Salud",
           "Medifé", "Galeno", "Omint", "PAMI", "Avalian"]


@pytest.fixture
def muchas(db):
    db.query(Insurance).delete()
    db.add_all([Insurance(name=n, is_active=True) for n in NOMBRES])
    db.commit()


# ── Reconocer que lo que escribió es una búsqueda ────────────────────────────

@pytest.mark.parametrize("texto", ["sw", "swi", "ospe", "swiss medical", "OSDE", "medife"])
def test_reconoce_un_fragmento_de_obra_social(texto):
    assert _texto_parece_busqueda(texto) == texto.strip().lower()


@pytest.mark.parametrize("texto", [
    "si", "no", "hola", "dale", "gracias", "particular", "",
    "quiero sacar un turno para una limpieza la semana que viene",
    "123",
])
def test_no_confunde_una_respuesta_normal_con_una_busqueda(texto):
    assert _texto_parece_busqueda(texto) == ""


# ── Que "sw" y "swi" encuentren Swiss Medical ────────────────────────────────

def test_sw_encuentra_swiss_medical(db, muchas):
    assert "Swiss Medical" in buscar_obras_sociales(db, "sw")


def test_swi_encuentra_swiss_medical(db, muchas):
    """El que el bot rechazó diciendo 'no trabajamos con swi'."""
    assert "Swiss Medical" in buscar_obras_sociales(db, "swi")


def test_dos_letras_no_traen_media_lista(db, muchas):
    """Un fragmento corto tiene que acotar, no devolver todo."""
    assert len(buscar_obras_sociales(db, "sw")) <= 3


# ── El endpoint devuelve las parecidas ───────────────────────────────────────

def test_verificar_devuelve_candidatas_en_vez_de_rechazar(db, muchas):
    """Si el modelo usa la herramienta equivocada, el paciente no lo paga."""
    from backend.services.appointment_service import match_insurance

    assert match_insurance("swi", db) is None, "No es una obra social exacta"
    assert "Swiss Medical" in buscar_obras_sociales(db, "swi"), (
        "Pero sí hay una candidata que ofrecerle en vez de mandarlo a Particular"
    )


def test_lo_que_no_existe_sigue_sin_existir(db, muchas):
    """La tolerancia no puede volverse invención."""
    assert buscar_obras_sociales(db, "banelco") == []
    assert buscar_obras_sociales(db, "zzz") == []
