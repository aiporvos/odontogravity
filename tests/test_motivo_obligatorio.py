"""No ofrecer horarios sin saber para qué es la consulta.

Pedido textual del consultorio, después del primer día con pacientes reales:

    "los turnos no darlos sin preguntar para que son porque tienen una duracion
     diferente dependiendo para que es"

Y pasó de verdad: una paciente escribió su obra social y el bot le ofreció
horarios enseguida, sin preguntar nada. De ahí sale la duración —control 15',
extracción 30', endodoncia 60'— así que un turno reservado sin motivo le ocupa
el tiempo equivocado a la agenda.

El prompt ya lo pedía. Esta es la garantía por código.
"""
from bot.tools.appointment_tools import (
    consultar_disponibilidad, recordar_dato, set_estado_conversacion,
)


def test_sin_motivo_no_devuelve_horarios():
    set_estado_conversacion({})
    r = consultar_disponibilidad("control")
    assert r.startswith("❌")
    assert "motivo" in r.lower()


def test_no_alcanza_con_que_el_modelo_lo_invente():
    """El parámetro lo llena el modelo; el estado solo se llena si el paciente habló."""
    set_estado_conversacion({"obra_social": "OSDE"})
    r = consultar_disponibilidad("extracción de muela")
    assert r.startswith("❌"), "Se dejó pasar un motivo que el paciente nunca dijo"


def test_con_el_motivo_registrado_sigue_de_largo():
    set_estado_conversacion({})
    recordar_dato("motivo", "limpieza")
    r = consultar_disponibilidad("limpieza")
    # Sin backend levantado falla la llamada HTTP, pero lo importante es que ya
    # no corta por falta de motivo: llegó a intentar la consulta.
    assert not r.startswith("❌ Todavía no sabés para qué es")


def test_el_mensaje_le_dice_al_modelo_como_seguir():
    set_estado_conversacion({})
    r = consultar_disponibilidad("control")
    assert "recordar_dato" in r
    assert "PROHIBIDO" in r


def test_recordar_dato_guarda_el_motivo():
    set_estado_conversacion({})
    recordar_dato("motivo", "conducto")
    from bot.tools.appointment_tools import get_estado_conversacion
    assert get_estado_conversacion()["motivo"] == "conducto"
