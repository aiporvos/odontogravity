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


# ── Charla 21/09: el detector no detectó (plan E4) ──────────────────────────
from backend.routers.evolution_router import (  # noqa: E402
    CLAVE_RESCATE_HECHO, es_repeticion, resolver_loop,
)

A = ("El Dr. Silvestro no está disponible para tratamientos de conducto. "
     "La Dra. Elena Murad puede atenderte. ¿Te gustaría que busque disponibilidad "
     "para el jueves con ella?")
A_CON_MULETILLA = "No, e" + A[1:]  # "No, el Dr. Silvestro..."
B = "Te ofrezco un turno con la Dra. Elena Murad para el tratamiento de conducto. ¿Te gustaría que lo agende?"


def test_una_muletilla_adelante_no_lo_disfraza():
    """'No, el Dr. X…' vs 'El Dr. X…' es la misma respuesta."""
    assert es_repeticion(A, [A_CON_MULETILLA])
    assert es_repeticion(A_CON_MULETILLA, [A])


def test_reformulacion_minima_cuenta():
    casi = A.replace("¿Te gustaría que busque", "¿Querés que busque")
    assert es_repeticion(casi, [A])


def test_mira_las_ultimas_cuatro_no_dos():
    """Dijo A, B, A y va a decir A otra vez: A quedó a 2 respuestas de distancia."""
    assert es_repeticion(A, [A, B, A][-4:])
    assert es_repeticion(B, [A, B, A][-4:])


def test_distinto_de_verdad_no_es_repeticion():
    assert not es_repeticion("Listo, tu turno quedó para el jueves 24 a las 10:00.", [A, B])


def test_primera_vez_rescata_con_lo_que_falta():
    """Sin motivo ni cobertura: pregunta la cobertura con botones, no deriva."""
    accion, texto, opciones = resolver_loop(A, [A], None, {})
    assert accion == "rescate"
    assert opciones and opciones["tipo"] == "botones"
    assert opciones["opciones"] == ["Tengo obra social", "Particular"]
    assert "obra social" in texto.lower()


def test_rescate_pregunta_el_motivo_si_falta_solo_eso():
    accion, texto, opciones = resolver_loop(A, [A], None, {"obra_social": "OSDE"})
    assert accion == "rescate"
    assert "consulta" in texto.lower() or "motivo" in texto.lower()


def test_rescate_de_conducto_va_con_los_dos_botones():
    estado = {"obra_social": "OSDE"}
    accion, texto, opciones = resolver_loop(
        A, [A], None, estado, dichos=["quiero un tratamiento de conducto", "sí"],
    )
    assert accion == "rescate"
    assert opciones["opciones"] == ["Consulta (30 min)", "Tratamiento (1 hora)"]


def test_segunda_vez_deriva():
    accion, _, _ = resolver_loop(A, [A], None, {CLAVE_RESCATE_HECHO: True})
    assert accion == "derivar"


def test_con_el_estado_completo_deriva_directo():
    """No hay nada que preguntar por código: es un problema de otro tipo."""
    completo = {"obra_social": "OSDE", "motivo": "Limpieza", "fecha_hora": "x", "paciente": "y"}
    accion, _, _ = resolver_loop(A, [A], None, completo)
    assert accion == "derivar"


def test_sin_repeticion_no_hace_nada():
    accion, texto, opciones = resolver_loop("Otra cosa completamente distinta y larga.", [A], None, {})
    assert accion is None
