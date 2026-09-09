"""Que "gracias" y "ok" cierren la conversación en vez de reabrirla.

N01, N02, N03 y N08 del plan de QA. Casos reales del 08/09/2026:

    bot:      Hola Marta, te recordamos tu turno el 09/09 a las 12:00...
    paciente: Ok
    bot:      ¿En qué puedo ayudarte hoy?

    paciente: Gracias!! Que tengas un lindo día!!! ☺️
    bot:      ¡De nada! 😊 Si necesitás algo más, no dudes en decírmelo...

Un acuse no es un pedido nuevo. Pero "gracias, ¿me pasás el alias?" sí lo es.
"""
import pytest

from backend.routers.evolution_router import es_solo_un_cierre


@pytest.mark.parametrize("mensaje", [
    "Gracias!!",
    "gracias",
    "Muchas gracias",
    "Ok",
    "ok",
    "okey",
    "Listo",
    "Perfecto",
    "Bárbaro",
    "Dale gracias",
    "👍",
    "🙏",
    "Gracias 😊",
    "graciasss",
    "Buenísimo!",
])
def test_reconoce_un_cierre(mensaje):
    assert es_solo_un_cierre(mensaje) is True, f"No lo tomó como cierre: {mensaje!r}"


@pytest.mark.parametrize("mensaje", [
    "Gracias, ¿me pasás el alias?",
    "Ok, y para el jueves tenés?",
    "gracias necesito otro turno",
    "listo, quiero cancelar el de mañana",
    "perfecto, cuanto sale?",
    "ok dale pero cambiame el horario",
])
def test_un_cierre_con_pedido_no_es_un_cierre(mensaje):
    assert es_solo_un_cierre(mensaje) is False, (
        f"Lo tomó como cierre y se iba a perder el pedido: {mensaje!r}"
    )


@pytest.mark.parametrize("mensaje", [
    "",
    "   ",
    "Hola",
    "Necesito un turno",
    "11:00",
    "Sí",
    # Un texto largo no es un acuse aunque empiece con "gracias".
    "Gracias por atenderme la vez pasada, la verdad que muy bien todo, "
    "quería contarte que sigo con la molestia en la muela de arriba",
])
def test_no_confunde_otras_cosas_con_un_cierre(mensaje):
    assert es_solo_un_cierre(mensaje) is False
