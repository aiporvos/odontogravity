"""No agendar sin cobertura, ni empujar Particular provisorio.

Caso real 21/09/2026 (Claudio):

    bot: ¿tenés obra social o particular?
    paciente: si obra social
    bot: ¿tenés obra social o particular?   ← de nuevo
    paciente: Tengo obra social
    bot: agendó el turno sin obra social (cayó en Particular por default)

Y en otra charla del mismo día:

    bot: registrado como particular
    ...
    paciente: Tengo obra social
    bot: ¿para qué tipo de consulta?   ← saltó el listado
    paciente: Tratamiento de conducto
    bot: No trabajamos con esa obra social  ← tomó el motivo como OS

La barrera vieja de `preguntar_cobertura`, cuando ya se había preguntado,
mandaba al modelo a usar Particular "de forma provisoria". Esa instrucción
era peor que el loop: dejaba el turno mal cargado.
"""
from bot.tools.appointment_tools import (
    agendar_turno,
    consultar_disponibilidad,
    get_estado_conversacion,
    preguntar_cobertura,
    set_estado_conversacion,
    set_ultimo_mensaje,
    _paciente_eligio_tiene_obra_social,
    _paciente_eligio_particular,
)


def test_segunda_pregunta_no_empuja_particular_provisorio():
    set_estado_conversacion({})
    set_ultimo_mensaje("quiero un turno")
    preguntar_cobertura()  # marca cobertura_preguntada
    r = preguntar_cobertura()
    assert "provisoria" not in r.lower()
    assert "Particular" not in r or "PROHIBIDO inventar Particular" in r
    assert "listar_obras_sociales" in r


def test_si_dijo_tengo_obra_social_manda_a_listar():
    set_estado_conversacion({"cobertura_preguntada": True})
    set_ultimo_mensaje("Tengo obra social")
    r = preguntar_cobertura()
    assert "listar_obras_sociales" in r
    assert "PROHIBIDO" in r
    assert "provisoria" not in r.lower()


def test_tengo_obra_social_pisa_particular_de_la_ficha():
    """Si la ficha decía Particular y ahora pide OS, hay que listar."""
    set_estado_conversacion({"obra_social": "Particular"})
    set_ultimo_mensaje("Tengo obra social")
    r = preguntar_cobertura()
    assert "listar_obras_sociales" in r
    assert get_estado_conversacion().get("obra_social") in (None, "")


def test_si_obra_social_tambien_cuenta():
    assert _paciente_eligio_tiene_obra_social("si obra social")
    assert _paciente_eligio_tiene_obra_social("Tengo obra social")
    assert not _paciente_eligio_tiene_obra_social("no tengo obra social")
    assert _paciente_eligio_particular("Particular")
    assert _paciente_eligio_particular("voy particular")


def test_no_consulta_horarios_sin_cobertura():
    set_estado_conversacion({"motivo": "Conducto", "cobertura_preguntada": True})
    set_ultimo_mensaje("Tengo obra social")
    r = consultar_disponibilidad("Conducto")
    assert r.startswith("❌")
    assert "listar_obras_sociales" in r


def test_no_agenda_sin_cobertura():
    set_estado_conversacion({"motivo": "Conducto"})
    set_ultimo_mensaje("10:00")
    r = agendar_turno(
        reason="Conducto",
        preferred_date="2026-10-05 10:00",
        patient_name="Claudio",
        patient_last_name="Luna",
    )
    assert r.startswith("❌")
    assert "cobertura" in r.lower() or "obra social" in r.lower()


def test_con_cobertura_registrada_agendar_no_corta_por_eso():
    """Sin backend falla el HTTP; lo importante es que no sea el bloqueo de cobertura."""
    set_estado_conversacion({"motivo": "Conducto", "obra_social": "OSDE"})
    set_ultimo_mensaje("10:00")
    r = agendar_turno(
        reason="Conducto",
        preferred_date="2026-10-05 10:00",
        patient_name="Claudio",
        patient_last_name="Luna",
    )
    assert not r.startswith("❌ Todavía no sabés la cobertura")
    assert "listar_obras_sociales" not in r
