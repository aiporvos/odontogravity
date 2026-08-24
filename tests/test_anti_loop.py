"""Cuándo el bot está trabado de verdad y cuándo solo lo parece.

Caso real del 23/08/2026: el paciente escribió "sw" para buscar Swiss Medical
entre las 45 obras sociales, y el bot respondió "Perdón, me parece que no nos
estamos entendiendo" y se derivó solo a una persona, pausándose 30 minutos.

El guard comparaba únicamente el texto. Pero el flujo de obras sociales manda
dos mensajes casi iguales a propósito —primero las frecuentes, después las
filtradas— con listas distintas. Repetir la frase mientras se ofrece algo nuevo
no es estar trabado: es avanzar.
"""
from backend.routers.evolution_router import (
    CLAVE_ULTIMAS_OPCIONES, debe_derivar_por_loop,
)

PIDE_OBRA_SOCIAL = ("Te muestro una lista de las obras sociales que atendemos. "
                    "Elegí la tuya o escribime las primeras letras si no la ves.")


def _ofrece(*opciones):
    return {"opciones": list(opciones), "siempre": True}


def test_el_caso_de_swiss_medical_no_es_un_loop():
    """Misma frase, pero ahora le muestra las que matchean 'sw'."""
    estado = {CLAVE_ULTIMAS_OPCIONES: "OSDE|OSEP|PAMI|Particular"}
    assert not debe_derivar_por_loop(
        PIDE_OBRA_SOCIAL, [PIDE_OBRA_SOCIAL],
        _ofrece("Swiss Medical", "Particular"), estado,
    )


def test_la_misma_lista_dos_veces_si_es_un_loop():
    """Si ni el texto ni las opciones cambian, no está avanzando."""
    estado = {CLAVE_ULTIMAS_OPCIONES: "OSDE|OSEP|Particular"}
    assert debe_derivar_por_loop(
        PIDE_OBRA_SOCIAL, [PIDE_OBRA_SOCIAL],
        _ofrece("OSDE", "OSEP", "Particular"), estado,
    )


def test_repetir_sin_ofrecer_nada_sigue_siendo_un_loop():
    """El comportamiento original: preguntar lo mismo una y otra vez."""
    pregunta = "¿Para qué sería la consulta? (ej: limpieza, extracción, control)"
    assert debe_derivar_por_loop(pregunta, [pregunta], None, {})


def test_una_respuesta_distinta_nunca_es_un_loop():
    assert not debe_derivar_por_loop(
        "Listo, tu turno quedó agendado para el martes 25 a las 10:00.",
        [PIDE_OBRA_SOCIAL], None, {},
    )


def test_primera_vez_que_ofrece_opciones_no_es_un_loop():
    """Sin opciones previas registradas, cualquier lista es nueva."""
    assert not debe_derivar_por_loop(
        PIDE_OBRA_SOCIAL, [PIDE_OBRA_SOCIAL],
        _ofrece("OSDE", "OSEP", "Particular"), {},
    )


def test_los_horarios_tambien_cuentan_como_progreso():
    """Ofrecer otro día no es repetirse, aunque la frase sea la misma."""
    frase = "Estos son los horarios disponibles. ¿Cuál te viene bien para el turno?"
    estado = {CLAVE_ULTIMAS_OPCIONES: "09:00|09:30|10:00"}
    assert not debe_derivar_por_loop(
        frase, [frase], _ofrece("17:00", "17:30", "18:00"), estado,
    )


def test_ofrecer_los_mismos_horarios_de_nuevo_si_es_un_loop():
    frase = "Estos son los horarios disponibles. ¿Cuál te viene bien para el turno?"
    estado = {CLAVE_ULTIMAS_OPCIONES: "09:00|09:30"}
    assert debe_derivar_por_loop(frase, [frase], _ofrece("09:00", "09:30"), estado)
