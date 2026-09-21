"""Un "sí" a una oferta del bot se ejecuta; no se vuelve a preguntar.

Charla 21/09, mensajes 11–14:

    bot:      ¿Te gustaría que busque disponibilidad para el jueves con ella?
    paciente: Si
    bot:      ¿Te gustaría que busque disponibilidad para el jueves con ella?
    paciente: Si
    bot:      Te ofrezco un turno con la Dra. Murad. ¿Te gustaría que lo agende?
    paciente: Si
    bot:      Para poder buscar disponibilidad, necesito que confirmes el motivo...

Cuatro "sí" y ninguna llamada a consultar_disponibilidad. Y "¿querés que lo
agende?" sin haber mostrado un solo horario: no hay nada que agendar.
"""
import pytest

from bot import ai_agent
from bot.tools import appointment_tools as tools
from tests.test_no_confirmar_lo_que_no_se_hizo import _Cliente, _Mensaje

OFERTA = ("El Dr. Silvestro no hace conductos. La Dra. Elena Murad puede atenderte. "
          "¿Te gustaría que busque disponibilidad para el jueves con ella?")


# ── Reconocer la situación ──────────────────────────────────────────────────

@pytest.mark.parametrize("texto", ["sí", "Si", "dale", "ok", "bueno", "sí, por favor",
                                   "claro", "obvio", "perfecto", "buscá", "sí dale"])
def test_reconoce_una_afirmacion(texto):
    assert ai_agent.es_afirmacion(texto)


@pytest.mark.parametrize("texto", ["no", "el jueves", "Avalian", "sí pero con Silvestro",
                                   "quiero un turno", "10:30", ""])
def test_no_confunde_otra_cosa_con_afirmacion(texto):
    assert not ai_agent.es_afirmacion(texto)


@pytest.mark.parametrize("texto", [
    OFERTA,
    "¿Querés que busque horarios con la Dra. Murad?",
    "¿Te gustaría que lo agende?",
    "¿Buscamos disponibilidad para el jueves?",
    "¿Te gustaría agendar con la Dra. Lucía Murad?",
    "El Dr. Silvestro no hace conductos. ¿Querés agendar con la Dra. Murad?",
])
def test_reconoce_una_oferta_del_bot(texto):
    assert ai_agent.ultima_oferta([{"role": "assistant", "content": texto}])


def test_una_pregunta_de_dato_no_es_oferta():
    assert not ai_agent.ultima_oferta([{"role": "assistant", "content": "¿Para qué es la consulta?"}])
    assert not ai_agent.ultima_oferta([])


# ── Que se ejecute ──────────────────────────────────────────────────────────

def _correr(monkeypatch, guion, estado, ultimo="sí", consulta_devuelve=None):
    """El modelo contesta sin tools. Si el código no consulta, nadie lo hace."""
    tools.reiniciar_disponibilidad()
    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda p: (_Cliente(guion), "modelo-de-prueba"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: "")
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "corregir_apellidos", lambda t: t)

    llamadas = []

    def _consulta_falsa(**kw):
        llamadas.append(kw)
        if consulta_devuelve:
            tools.registrar_disponibilidad(
                "Dra. Elena Murad", "2026-09-24", "jueves 24 de septiembre de 2026",
                consulta_devuelve)
        return "ok"
    monkeypatch.setattr(tools, "consultar_disponibilidad", _consulta_falsa)

    history = [{"role": "user", "content": "quiero un conducto con silvestro"},
               {"role": "assistant", "content": OFERTA}]
    texto, _, _ = ai_agent.chat(ultimo, history, "5492604046245", estado)
    return texto, llamadas


COMPLETO = {"motivo": "Conducto", "obra_social": "Avalian"}


def test_si_con_estado_completo_trae_horarios_reales(monkeypatch):
    """El modelo repreguntó; el código consultó por su cuenta."""
    texto, llamadas = _correr(
        monkeypatch, [_Mensaje(OFERTA)], COMPLETO, consulta_devuelve=["10:00", "11:00"],
    )
    assert llamadas, "Nadie consultó disponibilidad"
    assert "10:00" in texto and "11:00" in texto
    assert "te gustaría que busque" not in texto.lower()


def test_el_sistema_le_ordena_consultar(monkeypatch):
    """Además del rescate, el bloque [SISTEMA] se lo exige al modelo."""
    cliente = _Cliente([_Mensaje(OFERTA)])
    tools.reiniciar_disponibilidad()
    monkeypatch.setattr(ai_agent, "_build_client", lambda p: (cliente, "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: "")
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(tools, "consultar_disponibilidad", lambda **kw: "ok")
    history = [{"role": "assistant", "content": OFERTA}]

    ai_agent.chat("sí", history, "5492604046245", COMPLETO)

    ultimo_user = [m for m in cliente.chat.completions.pedidos[0]["messages"]
                   if m["role"] == "user"][-1]["content"]
    assert "consultar_disponibilidad" in ultimo_user and "OBLIGATORIO" in ultimo_user


def test_ofrecer_agendar_sin_horario_se_reemplaza_por_horarios(monkeypatch):
    texto, llamadas = _correr(
        monkeypatch,
        [_Mensaje("Te ofrezco un turno con la Dra. Elena Murad. ¿Te gustaría que lo agende?")],
        COMPLETO, consulta_devuelve=["10:00"],
    )
    assert "agende" not in texto.lower()
    assert "10:00" in texto


def test_si_falta_el_motivo_pregunta_eso_una_vez(monkeypatch):
    """No hay qué consultar: se pregunta lo que falta, por código."""
    texto, llamadas = _correr(
        monkeypatch, [_Mensaje(OFERTA)], {"obra_social": "Avalian"},
    )
    assert not llamadas, "Sin motivo no se puede consultar"
    assert "conducto" in texto.lower()
    assert "30" in texto and "1 hora" in texto, "Dijo conducto: botones de duración"


def test_si_falta_la_cobertura_la_pregunta(monkeypatch):
    texto, _ = _correr(monkeypatch, [_Mensaje(OFERTA)], {"motivo": "Conducto"})
    assert "obra social" in texto.lower()


def test_una_respuesta_con_horarios_reales_pasa_intacta(monkeypatch):
    """Si el modelo sí consultó y ofrece lo real, no se toca."""
    def _guion_con_tool():
        from tests.test_no_confirmar_lo_que_no_se_hizo import _LlamadaAHerramienta
        return [
            _Mensaje("", tool_calls=[_LlamadaAHerramienta("consultar_disponibilidad")]),
            _Mensaje("Tengo turno con la Dra. Murad el jueves 24 a las 10:00 o 11:00. ¿Cuál te sirve?"),
        ]
    tools.reiniciar_disponibilidad()
    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda p: (_Cliente(_guion_con_tool()), "m"))

    def _tool(n, a):
        tools.registrar_disponibilidad("Dra. Elena Murad", "2026-09-24",
                                       "jueves 24 de septiembre de 2026", ["10:00", "11:00"])
        return "ok"
    monkeypatch.setattr(ai_agent, "execute_tool", _tool)
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "corregir_apellidos", lambda t: t)
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)
    history = [{"role": "assistant", "content": OFERTA}]
    texto, _, _ = ai_agent.chat("sí", history, "5492604046245", COMPLETO)
    assert "10:00" in texto and "11:00" in texto
    assert "Murad" in texto
    assert "¿Cuál te sirve?" in texto
