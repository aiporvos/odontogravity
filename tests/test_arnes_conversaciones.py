"""Que el arnés de conversaciones detecte lo que dice detectar.

`test_conversaciones_completas.py` corre charlas enteras contra el modelo real y
verifica invariantes después de cada respuesta. Pero un arnés en el que no se
puede confiar es peor que no tener arnés: da verde mientras deja pasar el error.

Estos tests le dan de comer respuestas que SABEMOS malas —las que pasaron en
producción— y comprueban que las atrapa. Corren con el modelo simulado, así que
no gastan tokens ni necesitan API key.
"""
import pytest
from bot import ai_agent
from tests.test_conversaciones_completas import Charla
from tests.test_no_confirmar_lo_que_no_se_hizo import _Cliente, _Mensaje


def _falso(monkeypatch, respuestas):
    cliente = _Cliente([_Mensaje(r) for r in respuestas])
    monkeypatch.setattr(ai_agent, "_build_client", lambda p: (cliente, "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: "ok")
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)


def test_la_charla_acumula_historial(monkeypatch, db, clinica, silvestro, paciente):
    _falso(monkeypatch, ["¡Hola! ¿En qué te ayudo?", "¿Para qué sería el turno?"])
    charla = Charla(db)
    charla.decir("hola")
    charla.decir("quiero turno")
    assert len(charla.history) == 4, "No acumuló el historial de ida y vuelta"
    assert len(charla.turnos) == 2


def test_atrapa_el_saludo_repetido(monkeypatch, db, clinica, silvestro, paciente):
    _falso(monkeypatch, ["¡Hola! ¿En qué te ayudo?", "Buenas noches Claudio, decime"])
    charla = Charla(db)
    charla.decir("hola")
    with pytest.raises(AssertionError, match="Volvió a saludar"):
        charla.decir("quiero turno")


def test_atrapa_el_turno_confirmado_que_no_existe(monkeypatch, db, clinica,
                                                  silvestro, paciente):
    _falso(monkeypatch, ["Te agendé para el lunes 14 a las 11:00."])
    charla = Charla(db)
    with pytest.raises(AssertionError, match="no hay ningún turno en la base"):
        charla.decir("dale el lunes")


def test_atrapa_la_pregunta_repetida(monkeypatch, db, clinica, silvestro, paciente):
    _falso(monkeypatch, ["¿Me pasás tu DNI?", "¿Me pasás tu DNI?"])
    charla = Charla(db)
    charla.decir("hola")
    with pytest.raises(AssertionError, match="misma pregunta dos veces"):
        charla.decir("35878761")
