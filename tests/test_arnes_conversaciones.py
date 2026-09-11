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
from tests.test_no_confirmar_lo_que_no_se_hizo import _Cliente, _Mensaje, _Respuesta


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


# ── Lo que encontró el arnés la primera vez que corrió ──────────────────────

def test_el_primer_mensaje_no_pide_despedirse(monkeypatch, db, clinica,
                                              silvestro, paciente):
    """El bot se despedía en el mismo mensaje en que saludaba.

    Corrida real del 11/09 con el arnés:

        paciente: hola
        bot:      Buen día, ¿en qué te puedo ayudar? Que tengas un buen día.

    No era capricho del modelo: la instrucción que inyectaba el código decía
    "Saludá diciendo X y despedite con Y", una sola orden con dos verbos, y el
    modelo la cumplió entera. La rama para conversaciones ya empezadas lo decía
    bien desde antes ("Si te despedís, usá Y"); la del primer mensaje no.
    """
    capturado = {}

    class _Espia:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    capturado.update(kwargs)
                    return _Respuesta(_Mensaje("Buen día 😊 ¿En qué te ayudo?"))

    monkeypatch.setattr(ai_agent, "_build_client", lambda p: (_Espia, "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: "ok")
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)

    ai_agent.chat("hola", [], "+5492604590071", estado={})

    instruccion = capturado["messages"][-1]["content"]
    assert "NO te despidas" in instruccion, (
        "El primer mensaje no aclara que no hay que despedirse."
    )
    assert "y despedite con" not in instruccion, (
        "Volvió la orden de dos verbos: el modelo saluda y se despide junto."
    )
