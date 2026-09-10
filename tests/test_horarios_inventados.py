"""Que el bot no pueda ofrecer horarios ni fechas que nadie le dio.

Conversación real del 10/09/2026, con el bot ya "corregido":

    paciente: lunes
    bot:      No hay disponibilidad para el lunes 12 de septiembre. Pero tengo
              turnos para el *miércoles 16* a las *10:30*, *11:30* o *12:00*.
    paciente: y para la doctora murad?
    bot:      Para la Dra. Murad, tengo disponibilidad el *miércoles 16* a las
              *10:30*, *11:30* o *12:00*.

Tres inventos en dos mensajes:

1. El 12 de septiembre de 2026 era SÁBADO. El lunes era el 14.
2. La segunda respuesta no consultó nada: el log tiene UNA sola llamada a
   /availability en toda la conversación. Repitió los horarios de Silvestro.
3. Murad no atiende los miércoles (lunes, martes y viernes).

La causa directa del punto 2 estaba en el propio resultado de la herramienta,
que terminaba con "NO llames a esta herramienta de nuevo". El modelo obedeció.

Agregar el parámetro `profesional` no alcanzó: era un pedido, no una garantía.
Esto compara lo que sale con lo que el sistema realmente devolvió.
"""
import pytest

from bot import ai_agent
from bot.tools import appointment_tools as tools
from tests.test_no_confirmar_lo_que_no_se_hizo import (
    _Cliente, _LlamadaAHerramienta, _Mensaje,
)


def _correr(monkeypatch, texto, disponibilidad=None):
    """Corre un turno con lo que la herramienta devolvió de verdad."""
    tools.reiniciar_disponibilidad()
    for d in (disponibilidad or []):
        tools.registrar_disponibilidad(
            d.get("profesional"), d.get("fecha"), d.get("fecha_texto"), d.get("slots"))

    guion = [_Mensaje(texto)]
    monkeypatch.setattr(ai_agent, "_build_client", lambda p: (_Cliente(guion), "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: "ok")
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "get_estado_conversacion", lambda: {})
    # reiniciar_disponibilidad corre dentro de chat(): se preserva lo cargado.
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)
    return ai_agent.chat("hola", [], "5492604590071")[0]


REAL = [{
    "profesional": "Dr. Martin Silvestro",
    "fecha": "2026-09-16",
    "fecha_texto": "miércoles 16 de septiembre de 2026",
    "slots": ["10:30", "11:30", "12:00"],
}]


# ── El caso reportado ───────────────────────────────────────────────────────

def test_no_deja_pasar_horarios_de_otro_profesional(monkeypatch):
    """Se consultó por Silvestro y el mensaje los atribuye a Murad… pero eso
    solo se puede afirmar si se consultó por ella."""
    texto = ("Para la Dra. Murad, tengo disponibilidad el miércoles 16 de "
             "septiembre a las 14:00 o 15:00.")
    salida = _correr(monkeypatch, texto, REAL)
    assert "14:00" not in salida, f"Dejó pasar horarios inventados: {salida}"
    assert "15:00" not in salida


def test_rearma_el_mensaje_con_los_horarios_de_verdad(monkeypatch):
    salida = _correr(monkeypatch, "Tengo turnos a las 09:00 o 16:45.", REAL)
    assert "10:30" in salida and "11:30" in salida and "12:00" in salida
    assert "miércoles 16 de septiembre de 2026" in salida
    assert "09:00" not in salida and "16:45" not in salida


def test_sin_ninguna_consulta_no_ofrece_nada(monkeypatch):
    """Ni una sola llamada a la herramienta: no hay con qué rearmar."""
    salida = _correr(monkeypatch, "Tengo turnos el lunes a las 10:00 u 11:00.", [])
    assert "10:00" not in salida
    assert "verifique" in salida.lower()


# ── Lo que tiene que pasar intacto ─────────────────────────────────────────

def test_los_horarios_reales_salen_tal_cual(monkeypatch):
    texto = ("Tengo turnos para el miércoles 16 de septiembre a las 10:30, "
             "11:30 o 12:00. ¿Cuál te sirve?")
    assert _correr(monkeypatch, texto, REAL) == texto


def test_un_subconjunto_tambien_es_valido(monkeypatch):
    """Ofrecer dos de los tres horarios reales no es inventar."""
    texto = "Te puedo dar el miércoles 16 a las 10:30 o 12:00."
    assert _correr(monkeypatch, texto, REAL) == texto


@pytest.mark.parametrize("normal", [
    "¿Para qué es la consulta?",
    "El Dr. Silvestro atiende miércoles, jueves y viernes.",
    "Tu turno quedó cancelado.",
    "¡Hola! ¿En qué te puedo ayudar?",
    "Perfecto, ¿tenés obra social?",
])
def test_los_mensajes_sin_horarios_no_se_tocan(monkeypatch, normal):
    assert _correr(monkeypatch, normal, REAL) == normal


def test_un_numero_que_no_es_hora_no_dispara_nada(monkeypatch):
    """El DNI o un teléfono no son horarios."""
    texto = "Perfecto, quedó registrado el DNI 24785465. ¿Algo más?"
    assert _correr(monkeypatch, texto, REAL) == texto


# ── El resultado de la herramienta ya no le dice que no vuelva a llamar ────

def test_la_herramienta_pide_consultar_de_nuevo_si_cambia_el_profesional():
    import inspect
    fuente = inspect.getsource(tools.consultar_disponibilidad)
    assert "PROHIBIDO reusar estos horarios" in fuente
    assert "NO llames a esta herramienta de nuevo." not in fuente, (
        "Esa instrucción es la que hizo que reusara los horarios de otro profesional"
    )


# ── El caso EXACTO: horarios reales, profesional inventado ─────────────────
# El invento no estaba en los horarios —eran los de Silvestro, verdaderos— sino
# en a quién se los atribuía. Verificar solo los horarios no lo atrapa.

def test_no_le_atribuye_a_murad_los_horarios_de_silvestro(
    monkeypatch, db, clinica, silvestro, murad
):
    texto = ("Para la Dra. Murad, tengo disponibilidad el miércoles 16 de "
             "septiembre de 2026 a las 10:30, 11:30 o 12:00.")
    salida = _correr(monkeypatch, texto, REAL)

    assert "Murad" not in salida, f"Dejó pasar la atribución falsa: {salida}"
    assert "cada uno atiende días distintos" in salida


def test_si_se_consulto_por_ese_profesional_pasa(monkeypatch, db, clinica, silvestro, murad):
    consultado = [{
        "profesional": "Dra. Lucía Murad",
        "fecha": "2026-09-14",
        "fecha_texto": "lunes 14 de septiembre de 2026",
        "slots": ["09:00", "10:00"],
    }]
    texto = "Para la Dra. Murad tengo el lunes 14 a las 09:00 o 10:00."
    assert _correr(monkeypatch, texto, consultado) == texto


def test_sin_nombrar_a_nadie_no_molesta(monkeypatch, db, clinica, silvestro, murad):
    texto = "Tengo turnos el miércoles 16 a las 10:30 o 12:00. ¿Cuál te sirve?"
    assert _correr(monkeypatch, texto, REAL) == texto


def test_nombrar_al_profesional_correcto_pasa(monkeypatch, db, clinica, silvestro, murad):
    texto = ("Con el Dr. Silvestro tengo el miércoles 16 de septiembre a las "
             "10:30, 11:30 o 12:00.")
    assert _correr(monkeypatch, texto, REAL) == texto


def test_hablar_de_los_dias_de_un_profesional_no_es_ofrecer_horarios(
    monkeypatch, db, clinica, silvestro, murad
):
    """Sin horarios en el mensaje, no hay nada que verificar."""
    texto = "La Dra. Murad atiende lunes, martes y viernes."
    assert _correr(monkeypatch, texto, REAL) == texto
