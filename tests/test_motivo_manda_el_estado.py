"""La duración del turno sale del motivo registrado, no del que escribe el modelo.

Si el estado dice "Consulta por conducto" (30') y el modelo manda
reason="tratamiento de conducto", el backend calcularía 60'. El motivo que
viaja al backend tiene que ser el del estado, siempre.

También: cuando el modelo pide el motivo y el backend devuelve la pregunta de
conducto, el paciente tiene que ver dos botones, no una pregunta abierta.
"""
import pytest

from bot.tools import appointment_tools as tools


@pytest.fixture(autouse=True)
def limpio():
    tools.set_dichos_por_el_paciente([])
    tools.set_ultimo_mensaje("")
    yield


def _capturar(monkeypatch, respuesta):
    enviados = []

    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return respuesta

    def _post(url, json=None, **kw):
        enviados.append((url, json))
        return _R()

    monkeypatch.setattr(tools.httpx, "post", _post)
    monkeypatch.setattr(tools, "_profesional_en", lambda t: "")
    monkeypatch.setattr(tools, "_fecha_en", lambda t: "")
    return enviados


def test_consultar_disponibilidad_usa_el_motivo_del_estado(monkeypatch):
    enviados = _capturar(monkeypatch, {
        "available_slots": ["10:00"], "date": "2026-10-01",
        "fecha_texto": "jueves 1 de octubre de 2026", "professional": "Dra. Elena Murad",
    })
    tools.set_estado_conversacion({"motivo": "Consulta por conducto", "obra_social": "OSDE"})

    tools.consultar_disponibilidad("tratamiento de conducto")

    assert enviados[0][1]["reason"] == "Consulta por conducto"


def test_agendar_usa_el_motivo_del_estado(monkeypatch):
    enviados = _capturar(monkeypatch, {
        "message": "ok", "datetime": "2026-10-01 10:00", "appointment_id": "x",
        "cancel_url": "https://x",
    })
    tools.set_estado_conversacion({"motivo": "Consulta por conducto", "obra_social": "OSDE"})
    tools.set_ultimo_mensaje("10:00")

    tools.agendar_turno(reason="conducto", preferred_date="2026-10-01 10:00",
                        patient_name="Ana", patient_last_name="Paz", duration_minutes=60)

    assert enviados[0][1]["reason"] == "Consulta por conducto"


def test_la_pregunta_de_conducto_va_con_botones(monkeypatch):
    from backend.services.appointment_service import PREGUNTA_CONDUCTO
    _capturar(monkeypatch, {"ok": False, "motivo": None, "razon": PREGUNTA_CONDUCTO})
    tools.set_estado_conversacion({})
    tools.set_dichos_por_el_paciente(["quiero un tratamiento de conducto"])

    r = tools.recordar_dato("motivo", "Conducto")

    assert r.startswith("❌")
    pub = tools.tomar_opciones_ofrecidas()
    assert pub and pub["tipo"] == "botones"
    assert pub["opciones"] == ["Consulta (30 min)", "Tratamiento (1 hora)"]
