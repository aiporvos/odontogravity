"""El prompt y las herramientas tienen que viajar IDENTICOS en cada llamada.

Entre el SYSTEM_PROMPT (~6.450 tokens) y las 11 herramientas (~3.500) son unos
10.000 tokens de entrada que se reenvian hasta MAX_TOOL_ROUNDS veces por cada
mensaje del paciente. Una reserva de turno completa ronda las 20 llamadas: el
costo de este bot es casi todo entrada repetida.

OpenAI cachea eso a mitad de precio, pero el caché funciona por PREFIJO EXACTO:
se corta en el primer byte que cambia y desde ahi se paga todo entero, las
herramientas incluidas.

Lo que habia antes era esto, al final del system prompt:

    system_content += f"### ESTADO DE ESTA CONVERSACION:\\n{resumen_estado(...)}"

O sea un bloque que cambia cada vez que el paciente da un dato, metido justo
delante de las herramientas. El estado ahora viaja en el bloque [SISTEMA] del
ultimo mensaje, que es donde ya viajaban la fecha, el saludo y si la clinica
esta abierta.

Estos tests estan para que el proximo `+=` sobre system_content no pase sin que
nadie se entere.
"""
import pytest

from bot import ai_agent
from tests.test_no_confirmar_lo_que_no_se_hizo import _Cliente, _Mensaje


def _system_y_ultimo(monkeypatch, estado, history=None):
    """Corre un turno y devuelve (system message, ultimo mensaje) enviados."""
    cliente = _Cliente([_Mensaje("Listo.")])
    monkeypatch.setattr(ai_agent, "_build_client", lambda p: (cliente, "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: "ok")
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "get_estado_conversacion", lambda: estado)
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)

    ai_agent.chat("hola", history or [], "5492604590071", estado=estado)

    enviados = cliente.chat.completions.pedidos[0]["messages"]
    return enviados[0]["content"], enviados[-1]["content"]


# ── El prefijo no se mueve ──────────────────────────────────────────────────

def test_el_system_prompt_no_cambia_aunque_cambie_el_estado(monkeypatch):
    """El caso que rompia el caché: mas datos del paciente, otro prefijo."""
    vacio, _ = _system_y_ultimo(monkeypatch, {})
    cargado, _ = _system_y_ultimo(monkeypatch, {
        "paciente": "Claudio Luna",
        "motivo": "Limpieza",
        "obra_social": "OSDE",
    })

    assert vacio == cargado, (
        "El system prompt cambia segun el estado de la conversacion. Eso le "
        "rompe el caché al prefijo y hace que las 11 herramientas se paguen "
        "enteras en cada una de las ~20 llamadas del turno."
    )


def test_el_system_prompt_no_cambia_entre_el_primer_mensaje_y_el_resto(monkeypatch):
    """La marca de conversacion nueva y el saludo van en el ultimo mensaje."""
    primero, _ = _system_y_ultimo(monkeypatch, {}, history=[])
    despues, _ = _system_y_ultimo(monkeypatch, {}, history=[
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "Buenas tardes, ¿en que te ayudo?"},
    ])

    assert primero == despues, (
        "El system prompt cambia entre el primer mensaje y los siguientes."
    )


def test_el_system_prompt_no_lleva_el_estado(monkeypatch):
    """Concreto y directo: que nadie lo vuelva a pegar ahi.

    El prompt igual EXPLICA que existe un bloque de estado, y trae un ejemplo
    de como se ve ("YA SABES: obra_social=OSDE..."): eso es texto fijo y se
    cachea sin problema. Lo que no puede estar aca son los datos REALES del
    paciente, que cambian mensaje a mensaje.
    """
    system, _ = _system_y_ultimo(monkeypatch, {"paciente": "Claudio Luna"})

    assert "Claudio Luna" not in system, (
        "Un dato del paciente aparece en el system prompt: cambia por "
        "conversacion y por mensaje, que es justo lo que no puede cambiar."
    )
    assert "### 📌 ESTADO DE ESTA CONVERSACIÓN:" not in system, (
        "Volvio el `system_content +=` que le rompia el caché al prefijo."
    )


# ── Pero el estado tiene que seguir llegando ────────────────────────────────

def test_el_estado_sigue_llegando_en_el_ultimo_mensaje(monkeypatch):
    """Mover no es perder: el modelo tiene que seguir viendo lo que ya sabe."""
    _, ultimo = _system_y_ultimo(monkeypatch, {
        "paciente": "Claudio Luna",
        "motivo": "Limpieza",
    })

    assert "ESTADO DE ESTA CONVERSACIÓN" in ultimo
    assert "Claudio Luna" in ultimo
    assert "Limpieza" in ultimo


def test_sin_datos_tambien_avisa_que_no_sabe_nada(monkeypatch):
    _, ultimo = _system_y_ultimo(monkeypatch, {})
    assert "Todavía no tenés ningún dato" in ultimo


# ── El instrumento que mide todo esto ───────────────────────────────────────
# Sin esto no sabriamos si el caché pega: el log es la unica forma de verlo.


class _Detalle:
    def __init__(self, cached):
        self.cached_tokens = cached


class _Uso:
    def __init__(self, prompt, cached, out):
        self.prompt_tokens = prompt
        self.completion_tokens = out
        self.prompt_tokens_details = _Detalle(cached)


def _correr_con_uso(monkeypatch, usos):
    """Corre un turno donde el proveedor devuelve `usage` en cada llamada."""
    cliente = _Cliente([_Mensaje("Listo.")])
    completions = cliente.chat.completions
    create_original = completions.create

    pendientes = list(usos)

    def create(**kwargs):
        r = create_original(**kwargs)
        r.usage = pendientes.pop(0)
        return r

    completions.create = create
    monkeypatch.setattr(ai_agent, "_build_client", lambda p: (cliente, "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: "ok")
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "get_estado_conversacion", lambda: {})
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)
    ai_agent.chat("hola", [], "5492604590071", estado={})


def test_registra_los_tokens_y_cuanto_salio_del_cache(monkeypatch, caplog):
    with caplog.at_level("INFO", logger=ai_agent.logger.name):
        _correr_con_uso(monkeypatch, [_Uso(prompt=12000, cached=10000, out=150)])

    linea = [r.getMessage() for r in caplog.records if "AI_AGENT_USO" in r.getMessage()]
    assert linea, "No se registro el consumo de la llamada"
    assert "in=12000" in linea[0]
    assert "cache 10000 = 83%" in linea[0], (
        f"No informa que porcentaje salio del caché: {linea[0]}"
    )
    assert "out=150" in linea[0]


def test_un_proveedor_que_no_devuelve_usage_no_rompe(monkeypatch):
    """La cascada tiene OpenRouter y Groq: no todos informan lo mismo."""
    cliente = _Cliente([_Mensaje("Listo.")])
    monkeypatch.setattr(ai_agent, "_build_client", lambda p: (cliente, "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: "ok")
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "get_estado_conversacion", lambda: {})
    monkeypatch.setattr(ai_agent, "reiniciar_disponibilidad", lambda: None)

    texto, _, _ = ai_agent.chat("hola", [], "5492604590071", estado={})
    assert texto == "Listo."
