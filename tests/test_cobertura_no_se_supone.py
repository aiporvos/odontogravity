"""Que el modelo no pueda registrar una cobertura que el paciente no dijo.

Simulación con IA real, 22/10: la paciente nunca dijo su obra social (tenía
Medifé) y el bot respondió "ya tengo que sos particular": registró Particular
por su cuenta y el turno quedó sin su cobertura.
"""
import pytest

from bot.tools import appointment_tools as t


def _con_dichos(*dichos):
    t._dichos_por_el_paciente.set(list(dichos))
    t._ultimo_mensaje.set(dichos[-1] if dichos else "")


def test_no_registra_particular_si_no_lo_dijo():
    _con_dichos("Necesito un turno para un conducto", "Soy derivada")
    r = t.recordar_dato("obra_social", "Particular")
    assert r.startswith("❌") and "preguntar_cobertura" in r
    assert not t._cobertura_registrada()


@pytest.mark.parametrize("dicho", ["Particular", "no tengo obra social", "voy como particular",
                                   "sin obra social, pago yo"])
def test_particular_dicho_se_registra(dicho):
    _con_dichos("hola, quiero un turno", dicho)
    assert t.recordar_dato("obra_social", "Particular").startswith("✅")


@pytest.mark.parametrize("dicho, registrada", [
    ("tengo Medifé", "Medifé"), ("OSEP", "OSEP"), ("jerarq", "Jerárquicos Salud"),
    ("es swiss", "Swiss Medical"), ("Galeno", "Galeno"),
])
def test_la_que_dijo_se_registra(dicho, registrada):
    _con_dichos("hola", dicho)
    assert t.recordar_dato("obra_social", registrada).startswith("✅")


def test_no_registra_otra_obra_social():
    _con_dichos("hola", "tengo Medifé")
    assert t.recordar_dato("obra_social", "OSEP").startswith("❌")
