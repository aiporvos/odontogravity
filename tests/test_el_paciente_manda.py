"""Que el día y el profesional los decida el paciente, no el modelo.

Conversación real del 10/09/2026:

    paciente: quiero un turno con Murad para el jueves
    paciente: extraccion
    bot:      Lamentablemente, no hay disponibilidad para extracción el
              *martes 15 de septiembre de 2026*. Pero tengo turnos para el
              *miércoles 16* a las *10:30*, *11:30* o *12:00*.

El paciente dijo JUEVES. El modelo mandó `date=2026-09-15`, que era martes, y
no mandó el profesional: la búsqueda salió genérica y devolvió los horarios del
otro profesional. Reproducido contra una copia de producción: con esos dos
parámetros el backend produce ese mensaje palabra por palabra.

Completar los parámetros cuando vienen vacíos no alcanzaba: una fecha
equivocada no está vacía.
"""
import pytest

from bot.tools import appointment_tools as tools


@pytest.fixture(autouse=True)
def sin_estado():
    tools.set_dichos_por_el_paciente([])
    tools.set_ultimo_mensaje("")
    yield


def _capturar(monkeypatch):
    """Intercepta el payload que sale hacia el backend."""
    enviados = []

    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"available_slots": ["10:00"], "date": "2026-09-17",
                    "fecha_texto": "jueves 17 de septiembre de 2026",
                    "professional": "Dra. Elena Murad"}

    def _post(url, json=None, **kw):
        enviados.append(json)
        return _R()

    monkeypatch.setattr(tools.httpx, "post", _post)
    monkeypatch.setattr(tools, "_estado_conversacion",
                        type("C", (), {"get": staticmethod(
                            lambda: {"motivo": "Limpieza", "obra_social": "Particular"})})())
    monkeypatch.setattr(tools, "set_opciones_ofrecidas", lambda *a, **k: None)
    monkeypatch.setattr(tools, "_profesional_en",
                        lambda t: "Dra. Elena Murad" if "murad" in (t or "").lower() else "")
    return enviados


# ── El caso reportado ───────────────────────────────────────────────────────

def test_la_fecha_del_paciente_le_gana_a_la_del_modelo(monkeypatch):
    """Dijo jueves; el modelo mandó martes 15."""
    enviados = _capturar(monkeypatch)
    monkeypatch.setattr(tools, "_fecha_en",
                        lambda t: "2026-09-17" if "jueves" in (t or "").lower() else "")
    tools.set_ultimo_mensaje("quiero un turno con Murad para el jueves")

    tools.consultar_disponibilidad("Limpieza", date="2026-09-15")

    assert enviados[0]["date"] == "2026-09-17", (
        f"Mandó la fecha inventada por el modelo: {enviados[0]['date']}"
    )


def test_un_si_toma_al_profesional_que_ofrecio_el_bot(monkeypatch):
    """Pidió Silvestro, el bot ofreció Murad, dijo 'sí': es Murad (arnés 21/09)."""
    enviados = _capturar(monkeypatch)
    monkeypatch.setattr(tools, "_fecha_en", lambda t: "")
    # El caso real: ambas fichas aparecen en el mensaje del bot. El mock de
    # _profesional_en devolvería la primera; acá se prueba el helper que elige
    # a la ofrecida (la última).
    monkeypatch.setattr(tools, "_profesional_ofrecido_en",
                        lambda t: "Dra. Elena Murad" if "murad" in (t or "").lower() else "")
    monkeypatch.setattr(tools, "_profesional_en", lambda t: (
        "Dr. Sergio Silvestro" if "silvest" in (t or "").lower()
        else "Dra. Elena Murad" if "murad" in (t or "").lower() else ""))
    tools.set_dichos_por_el_paciente(["un conducto con Silvestre", "sí"])
    tools.set_ultima_respuesta_bot(
        "El Dr. Sergio Silvestro no hace conductos. ¿Querés con la Dra. Murad?")
    tools.set_ultimo_mensaje("sí")

    tools.consultar_disponibilidad("Conducto")

    assert enviados[0]["profesional_pedido"] == "Dra. Elena Murad", enviados[0]


def test_profesional_ofrecido_elige_al_ultimo(db, silvestro, murad):
    """'Silvestro no… ¿con Murad?' → Murad, no Silvestro."""
    assert tools._profesional_ofrecido_en(
        "El Dr. Sergio Silvestro no hace conductos. ¿Querés con la Dra. Lucía Murad?"
    ) == murad.full_name


def test_el_profesional_del_paciente_viaja_aunque_el_modelo_lo_omita(monkeypatch):
    enviados = _capturar(monkeypatch)
    monkeypatch.setattr(tools, "_fecha_en", lambda t: "")
    tools.set_ultimo_mensaje("quiero un turno con Murad")

    tools.consultar_disponibilidad("Limpieza")

    assert enviados[0]["profesional_pedido"] == "Dra. Elena Murad", (
        "Salió una búsqueda genérica: devuelve horarios de otro profesional"
    )


def test_el_profesional_que_nombra_ahora_le_gana_al_del_modelo(monkeypatch):
    enviados = _capturar(monkeypatch)
    monkeypatch.setattr(tools, "_fecha_en", lambda t: "")
    tools.set_ultimo_mensaje("y para murad?")

    tools.consultar_disponibilidad("Limpieza", profesional="Dr. Martin Silvestro")

    assert enviados[0]["profesional_pedido"] == "Dra. Elena Murad"


# ── Pero lo viejo no pisa lo que el paciente acaba de aceptar ─────────────

def test_un_dia_de_hace_tres_mensajes_no_pisa_al_que_manda_el_modelo(monkeypatch):
    """Pidió jueves, se le ofreció el miércoles 16 y dijo "dale": el 16 vale."""
    enviados = _capturar(monkeypatch)
    monkeypatch.setattr(tools, "_fecha_en",
                        lambda t: "2026-09-17" if "jueves" in (t or "").lower() else "")
    tools.set_dichos_por_el_paciente(["quiero un turno para el jueves", "dale"])
    tools.set_ultimo_mensaje("dale")

    tools.consultar_disponibilidad("Limpieza", date="2026-09-16")

    assert enviados[0]["date"] == "2026-09-16", (
        "Un 'jueves' viejo pisó el día que el paciente acababa de aceptar"
    )


def test_lo_viejo_si_completa_cuando_el_modelo_no_manda_nada(monkeypatch):
    enviados = _capturar(monkeypatch)
    monkeypatch.setattr(tools, "_fecha_en",
                        lambda t: "2026-09-17" if "jueves" in (t or "").lower() else "")
    tools.set_dichos_por_el_paciente(["quiero un turno para el jueves", "extraccion"])
    tools.set_ultimo_mensaje("extraccion")

    tools.consultar_disponibilidad("Limpieza")

    assert enviados[0]["date"] == "2026-09-17", (
        "Se perdió el día que el paciente había pedido"
    )
