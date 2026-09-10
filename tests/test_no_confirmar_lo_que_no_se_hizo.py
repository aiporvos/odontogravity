"""Que el bot no pueda decir "te agendé" sin haber agendado.

El 08/09/2026, en producción:

    bot: Te agendé para el lunes 14 de septiembre de 2026 a las 11:00 con el
         Dr. Martin Silvestro.

Ese turno no existe. El log de la conversación no tiene ninguna llamada a
/appointments después del turno anterior, y el link de cancelación que le mandó
era el de ESE turno anterior, copiado. El paciente se fue con la certeza de
tener un turno que nadie iba a atender.

Es el modo de falla más caro del sistema: no es un horario mal ofrecido, es una
persona que viaja al consultorio para nada. El prompt ya pedía no inventar; un
prompt no es una garantía.
"""
import pytest

from bot import ai_agent


class _Mensaje:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, message):
        self.message = message


class _Respuesta:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _Completions:
    """Cliente falso: devuelve los mensajes que se le den, en orden."""
    def __init__(self, guion):
        self.guion = list(guion)
        self.pedidos = []

    def create(self, **kwargs):
        self.pedidos.append(kwargs)
        return _Respuesta(self.guion.pop(0))


class _Cliente:
    def __init__(self, guion):
        self.chat = type("C", (), {"completions": _Completions(guion)})()


class _LlamadaAHerramienta:
    def __init__(self, nombre, args="{}"):
        self.id = "tc_1"
        self.function = type("F", (), {"name": nombre, "arguments": args})()


def _correr(monkeypatch, guion, resultado_tool="✅ Turno agendado"):
    # Un mensaje que ofrece horarios tiene que estar respaldado por una
    # consulta real (ver test_horarios_inventados.py). Acá se registra la que
    # corresponde para que la barrera de horarios no se meta con estos casos,
    # que prueban otra cosa.
    from bot.tools import appointment_tools as _tools
    _tools.reiniciar_disponibilidad()
    _tools.registrar_disponibilidad(
        "Dr. Martin Silvestro", "2026-09-17", "jueves 17 de septiembre de 2026",
        ["09:00", "10:00", "11:00"])
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)

    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda p: (_Cliente(guion), "modelo-de-prueba"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: resultado_tool)
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "get_estado_conversacion", lambda: {})
    return ai_agent.chat("hola", [], "5492604046245")


PROMESA = ("Te agendé para el lunes 14 de septiembre de 2026 a las 11:00 con el "
           "Dr. Martin Silvestro.")


# ── Lo que pasó en producción ───────────────────────────────────────────────

def test_no_deja_pasar_un_te_agende_sin_turno(monkeypatch):
    texto, _, _ = _correr(monkeypatch, [_Mensaje(PROMESA)])
    assert "Te agendé" not in texto, f"Dejó pasar la confirmación falsa: {texto}"
    assert "no llegué a confirmar" in texto


@pytest.mark.parametrize("promesa", [
    "Te agendé para el jueves a las 11:00.",
    "Quedó agendado tu turno para mañana.",
    "Listo, te reservé el horario de las 18:00.",
    "Ya te anoté para el viernes.",
    "Turno confirmado para el lunes 14.",
    "Estás agendada para el martes a las 9.",
])
def test_reconoce_las_formas_de_prometer_un_turno(monkeypatch, promesa):
    texto, _, _ = _correr(monkeypatch, [_Mensaje(promesa)])
    assert "no llegué a confirmar" in texto, f"Se le escapó: {promesa}"


# ── Pero no molesta cuando el turno SÍ se creó ──────────────────────────────

def test_si_agendo_de_verdad_el_mensaje_sale_tal_cual(monkeypatch):
    guion = [
        _Mensaje("", tool_calls=[_LlamadaAHerramienta("agendar_turno")]),
        _Mensaje(PROMESA),
    ]
    texto, _, _ = _correr(monkeypatch, guion)
    assert texto == PROMESA


def test_si_la_herramienta_fallo_no_se_confirma(monkeypatch):
    """agendar_turno devolvió ❌: el turno no existe, aunque se haya llamado."""
    guion = [
        _Mensaje("", tool_calls=[_LlamadaAHerramienta("agendar_turno")]),
        _Mensaje(PROMESA),
    ]
    texto, _, _ = _correr(monkeypatch, guion,
                          resultado_tool="❌ No se pudo agendar: horario ocupado")
    assert "no llegué a confirmar" in texto


def test_otra_herramienta_no_habilita_la_confirmacion(monkeypatch):
    """Consultar disponibilidad no es agendar."""
    guion = [
        _Mensaje("", tool_calls=[_LlamadaAHerramienta("consultar_disponibilidad")]),
        _Mensaje(PROMESA),
    ]
    texto, _, _ = _correr(monkeypatch, guion, resultado_tool="✅ Horarios: 09:00, 11:00")
    assert "no llegué a confirmar" in texto


# ── Y no se mete con los mensajes normales ──────────────────────────────────

@pytest.mark.parametrize("normal", [
    "Tengo disponibilidad el jueves a las 09:00, 10:00 o 11:00. ¿Cuál te sirve?",
    "¿Para qué es la consulta?",
    "El Dr. Silvestro atiende miércoles, jueves y viernes.",
    "Tu turno del jueves quedó cancelado.",
    "¡Hola! ¿En qué te puedo ayudar?",
])
def test_los_mensajes_que_no_prometen_turno_pasan_intactos(monkeypatch, normal):
    texto, _, _ = _correr(monkeypatch, [_Mensaje(normal)])
    assert texto == normal
