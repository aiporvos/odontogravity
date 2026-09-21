"""El turno se agenda en el horario que ELIGIÓ el paciente, o no se agenda.

Arnés 21/09 (charla 6): el bot ofreció lunes 10:00 u 11:00, el paciente
contestó "El jueves con Silvestre" y el modelo llamó agendar_turno con
"2026-09-22 10:00" (que ni siquiera era jueves) y con Murad. Le agendó un
turno que nunca eligió, un día que no pidió, con otra profesional.
"""
import pytest

from bot.tools import appointment_tools as tools


@pytest.fixture(autouse=True)
def limpio():
    tools.set_dichos_por_el_paciente([])
    tools.set_ultimo_mensaje("")
    tools.set_estado_conversacion({"motivo": "Conducto", "obra_social": "Avalian"})
    yield


def _capturar(monkeypatch):
    enviados = []

    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"message": "ok", "datetime": "2026-09-24 10:00", "appointment_id": "x",
                    "cancel_url": "https://x"}

    def _post(url, json=None, **kw):
        enviados.append(json)
        return _R()
    monkeypatch.setattr(tools.httpx, "post", _post)
    monkeypatch.setattr(tools, "_profesional_en",
                        lambda t: "Dr. Sergio Silvestro" if "silvest" in (t or "").lower() else "")
    return enviados


def _agendar(fecha="2026-09-22 10:00", **kw):
    return tools.agendar_turno(reason="Conducto", preferred_date=fecha,
                               patient_name="Claudio", patient_last_name="Luna", **kw)


# ── El caso del arnés ────────────────────────────────────────────────────────

def test_sin_horario_elegido_no_se_agenda(monkeypatch):
    enviados = _capturar(monkeypatch)
    tools.set_dichos_por_el_paciente(["Tratamiento (1 hora)", "El jueves con Silvestre"])
    tools.set_ultimo_mensaje("El jueves con Silvestre")

    r = _agendar("2026-09-22 10:00")

    assert r.startswith("❌"), r
    assert not enviados, "Agendó sin que el paciente eligiera horario"
    assert "consultar_disponibilidad" in r


def test_el_dia_que_dijo_le_gana_al_del_modelo(monkeypatch):
    """Dijo jueves con hora; el modelo mandó martes."""
    enviados = _capturar(monkeypatch)
    monkeypatch.setattr(tools, "_fecha_en",
                        lambda t: "2026-09-24" if "jueves" in (t or "").lower() else "")
    tools.set_ultimo_mensaje("el jueves a las 10")

    r = _agendar("2026-09-22 10:00")

    assert r.startswith("❌"), r
    assert not enviados


def test_la_hora_que_dijo_le_gana_a_la_del_modelo(monkeypatch):
    enviados = _capturar(monkeypatch)
    tools.set_ultimo_mensaje("11:00")

    r = _agendar("2026-09-22 10:00")

    assert r.startswith("❌"), r
    assert "11:00" in r
    assert not enviados


def test_el_profesional_que_nombra_viaja_al_backend(monkeypatch):
    """Si nombró a Silvestro, el backend tiene que saberlo (y rechazarlo si no hace conducto)."""
    enviados = _capturar(monkeypatch)
    tools.set_ultimo_mensaje("a las 10:00 con Silvestre")

    _agendar("2026-09-22 10:00")

    assert enviados and enviados[0]["profesional_pedido"] == "Dr. Sergio Silvestro"


# ── Lo que sí tiene que pasar ────────────────────────────────────────────────

@pytest.mark.parametrize("ultimo", ["10:00", "a las 10", "10", "10hs", "las 10:00 está bien",
                                    "el de las 10"])
def test_con_la_hora_dicha_se_agenda(monkeypatch, ultimo):
    enviados = _capturar(monkeypatch)
    tools.set_ultimo_mensaje(ultimo)

    r = _agendar("2026-09-22 10:00")

    assert r.startswith("✅"), r
    assert enviados


@pytest.mark.parametrize("ultimo", ["el primero", "el primero que tengas", "cualquiera",
                                    "el que sea", "lo antes posible"])
def test_el_primero_que_tengas_tambien_vale(monkeypatch, ultimo):
    enviados = _capturar(monkeypatch)
    tools.set_ultimo_mensaje(ultimo)
    tools.registrar_disponibilidad("Dra. Lucía Murad", "2026-09-22",
                                   "martes 22 de septiembre de 2026", ["10:00", "11:00"])

    r = _agendar("2026-09-22 10:00")

    assert r.startswith("✅"), r


def test_un_si_a_una_unica_opcion_ofrecida_vale(monkeypatch):
    """Ofreció un solo horario; el paciente dijo 'dale'."""
    _capturar(monkeypatch)
    tools.set_ultimo_mensaje("dale")
    tools.registrar_disponibilidad("Dra. Lucía Murad", "2026-09-22",
                                   "martes 22 de septiembre de 2026", ["10:00"])

    r = _agendar("2026-09-22 10:00")

    assert r.startswith("✅"), r


def test_un_si_con_varias_opciones_no_alcanza(monkeypatch):
    enviados = _capturar(monkeypatch)
    tools.set_ultimo_mensaje("sí")
    tools.registrar_disponibilidad("Dra. Lucía Murad", "2026-09-22",
                                   "martes 22 de septiembre de 2026", ["10:00", "11:00"])

    r = _agendar("2026-09-22 10:00")

    assert r.startswith("❌"), r
    assert not enviados
