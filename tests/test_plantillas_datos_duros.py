"""Horarios y confirmación salen de plantilla, no del modelo.

Capa 3 de la estrategia: el modelo decide; el código arma el texto con datos.
"""
import pytest

from bot import ai_agent
from bot.tools import appointment_tools as tools
from tests.test_no_confirmar_lo_que_no_se_hizo import (
    _Cliente, _Mensaje, _LlamadaAHerramienta,
)


def _correr(monkeypatch, guion, resultado_tool="ok"):
    tools.reiniciar_disponibilidad()
    tools.reiniciar_confirmacion_turno()
    tools.registrar_disponibilidad(
        "Dra. Lucía Murad", "2026-09-24", "jueves 24 de septiembre de 2026",
        ["09:00", "10:00", "11:00"])
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)
    monkeypatch.setattr(ai_agent, "reiniciar_confirmacion_turno", lambda: None)
    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda p: (_Cliente(guion), "modelo-de-prueba"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: resultado_tool)
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "corregir_apellidos", lambda t: t)
    monkeypatch.setattr(ai_agent, "get_estado_conversacion", lambda: {})
    return ai_agent.chat("hola", [], "5492604046245")


def test_horarios_salen_de_plantilla_aunque_el_modelo_redacte_distinto(monkeypatch):
    """El modelo inventó redacción; el paciente ve los slots reales."""
    texto, _, _ = _correr(monkeypatch, [
        _Mensaje("Tengo turno mañana a las 09:00, 10:00 o 11:00, ¿cuál querés?")
    ])
    assert "jueves 24 de septiembre de 2026" in texto
    assert "09:00" in texto and "11:00" in texto
    assert "¿Cuál te sirve?" in texto


def test_confirmacion_sale_de_plantilla(monkeypatch):
    tools.reiniciar_disponibilidad()
    tools.reiniciar_confirmacion_turno()
    tools.registrar_confirmacion_turno(
        "Listo 😊 Turno agendado con Dra. Lucía Murad. Fecha: 2026-09-24 09:00. "
        "Si necesitás cancelar, escribime 'quiero cancelar mi turno'."
    )
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)
    monkeypatch.setattr(ai_agent, "reiniciar_confirmacion_turno", lambda: None)
    monkeypatch.setattr(ai_agent, "confirmacion_turno_agendada",
                        lambda: tools.confirmacion_turno_agendada())
    guion = [
        _Mensaje("", tool_calls=[_LlamadaAHerramienta("agendar_turno")]),
        _Mensaje("Te agendé para el lunes a las 99:99 con el Dr. Inventado."),
    ]

    def _tool(n, a):
        if n == "agendar_turno":
            return "✅ ok"
        return "ok"
    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda p: (_Cliente(guion), "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", _tool)
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "corregir_apellidos", lambda t: t)
    monkeypatch.setattr(ai_agent, "get_estado_conversacion", lambda: {})

    # Marcar agendo: execute_tool returns ✅ so agendo_de_verdad=True
    texto, _, _ = ai_agent.chat("09:00", [], "5492604046245")
    assert "99:99" not in texto
    assert "Inventado" not in texto
    assert "Listo" in texto and "Murad" in texto


def test_horarios_y_duraciones_salen_de_la_base(db, clinica):
    from backend.models.tipo_consulta import TipoConsulta
    db.add(TipoConsulta(nombre="Limpieza", duracion_minutos=15, is_active=True))
    db.add(TipoConsulta(nombre="Conducto", duracion_minutos=60, is_active=True))
    db.commit()
    h = ai_agent.get_horarios_texto()
    assert "Lunes" in h and "09:00" in h
    d = ai_agent.get_duraciones_texto()
    assert "Limpieza" in d and "15" in d
    assert "Conducto" in d and "60" in d
