"""Respetar la franja que pidió el paciente.

Pedido textual del consultorio:

    "si piden para la tarde buscar el dia que tenga libre a la tarde"

La mitad ya estaba: interpretar_preferencia traduce "a la tarde" o "después de
las 18:45" a un rango, y get_available_slots filtra por él y salta al día
siguiente que sí tenga algo en esa franja.

Lo que faltaba es que el modelo pasara el parámetro. El prompt se lo pedía, y ya
sabemos cómo termina eso: pasó lo mismo con la obra social ("sw") y con el
motivo. Ahora, si no lo reenvía, la franja se saca del mensaje del paciente.
"""
import pytest

from backend.services.appointment_service import interpretar_preferencia
from bot.tools.appointment_tools import _franja_en_el_texto


# ── Reconocer que pidió una franja ──────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "a la tarde",
    "si puede ser a la mañana",
    "prefiero temprano",
    "después de las 18",
    "después de las 18:45",
    "antes de las 12",
    "a partir de las 9",
    "que sea a la tarde por favor",
    "después del trabajo",
    "al mediodía",
])
def test_reconoce_el_pedido_de_franja(texto):
    assert _franja_en_el_texto(texto) == texto.strip(), f"No detectó la franja en '{texto}'"


@pytest.mark.parametrize("texto", [
    "hola", "quiero un turno", "OSDE", "Maria Prueba",
    "una limpieza", "sí", "dale", "",
])
def test_no_inventa_una_franja_donde_no_la_hay(texto):
    assert _franja_en_el_texto(texto) == ""


# ── Traducir la franja a un rango ───────────────────────────────────────────

def test_la_tarde_es_de_las_12_30_en_adelante():
    desde, hasta = interpretar_preferencia("a la tarde")
    assert desde == 12 * 60 + 30 and hasta == 24 * 60


def test_la_manana_es_hasta_las_12_30():
    desde, hasta = interpretar_preferencia("a la mañana")
    assert desde == 0 and hasta == 12 * 60 + 30


def test_temprano_cuenta_como_manana():
    assert interpretar_preferencia("temprano") == interpretar_preferencia("a la mañana")


def test_despues_de_una_hora_puntual():
    desde, hasta = interpretar_preferencia("después de las 18:45")
    assert desde == 18 * 60 + 45


def test_antes_de_una_hora_puntual():
    desde, hasta = interpretar_preferencia("antes de las 12")
    assert desde == 0 and hasta == 12 * 60


def test_sin_preferencia_no_filtra_nada():
    assert interpretar_preferencia("") is None
    assert interpretar_preferencia(None) is None


# ── El circuito completo ────────────────────────────────────────────────────

def test_lo_que_el_paciente_escribe_llega_al_filtro():
    """De la frase del paciente al rango, sin que el modelo participe."""
    franja = _franja_en_el_texto("necesito un turno después de las 17")
    assert franja
    desde, _ = interpretar_preferencia(franja)
    assert desde == 17 * 60


def test_la_tarde_del_paciente_no_devuelve_horarios_de_la_manana(
    db, clinica, silvestro, paciente
):
    from backend.services.appointment_service import get_available_slots, _a_minutos

    r = get_available_slots(db, "", "San Rafael", "Limpieza",
                            obra_social="Particular", preferencia_horaria="a la tarde")
    assert r["available_slots"], "No ofreció ningún horario"
    for h in r["available_slots"]:
        assert _a_minutos(h) >= 12 * 60 + 30, f"Ofreció {h}, que es de mañana"


def test_si_ese_dia_no_hay_tarde_salta_al_siguiente(db, clinica, silvestro, paciente):
    """El miércoles la clínica cierra a la tarde: tiene que ofrecer otro día."""
    from datetime import timedelta
    from backend.services.appointment_service import get_available_slots, get_clinic_now

    hoy = get_clinic_now()
    miercoles = hoy + timedelta(days=(2 - hoy.weekday()) % 7 or 7)

    r = get_available_slots(db, miercoles.date().isoformat(), "San Rafael", "Limpieza",
                            obra_social="Particular", preferencia_horaria="a la tarde")
    assert r["available_slots"], "Se quedó sin ofrecer nada"
    assert r["date"] != miercoles.date().isoformat(), (
        "Ofreció el miércoles a la tarde, que está cerrado"
    )
