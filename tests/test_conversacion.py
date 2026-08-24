"""Lo que el bot hace mal en una charla real, atado con tests.

Los casos salen de una conversacion de produccion del 23/08/2026: el bot ofrecio
cancelar un turno del 18/08 (cinco dias pasado) y volvio a saludar
("¡Buenas noches, Claudio! 😊") en el cuarto mensaje de la misma charla.
"""
from datetime import timedelta

from backend.models.appointment import AppointmentStatus
from backend.routers.evolution_router import quitar_presentacion, es_repeticion
from backend.routers.bot_routes import _turnos_cancelables
from backend.services.appointment_service import get_clinic_now
from conftest import proximo_dia_habil, turno


# ── No ofrecer turnos que ya pasaron ─────────────────────────────────────────

def test_un_turno_pasado_no_es_cancelable(db, clinica, silvestro, paciente):
    """El caso real: el 23/08 ofrecio cancelar uno del 18/08."""
    hace_cinco_dias = get_clinic_now() - timedelta(days=5)
    turno(db, paciente, silvestro, hace_cinco_dias, reason="Limpieza")

    assert _turnos_cancelables(db, [paciente.id]).count() == 0, (
        "Sigue ofreciendo cancelar un turno que ya pasó"
    )


def test_un_turno_futuro_si_es_cancelable(db, clinica, silvestro, paciente):
    turno(db, paciente, silvestro, proximo_dia_habil())
    assert _turnos_cancelables(db, [paciente.id]).count() == 1


def test_convive_pasado_y_futuro(db, clinica, silvestro, paciente, otro_paciente):
    """Con historial viejo encima, solo debe aparecer el que viene."""
    turno(db, paciente, silvestro, get_clinic_now() - timedelta(days=30))
    turno(db, paciente, silvestro, get_clinic_now() - timedelta(days=5))
    futuro = turno(db, paciente, silvestro, proximo_dia_habil())

    quedan = _turnos_cancelables(db, [paciente.id]).all()
    assert [t.id for t in quedan] == [futuro.id]


def test_los_cancelados_tampoco_aparecen(db, clinica, silvestro, paciente):
    turno(db, paciente, silvestro, proximo_dia_habil(),
          status=AppointmentStatus.cancelled)
    assert _turnos_cancelables(db, [paciente.id]).count() == 0


# ── No volver a saludar a mitad de la charla ─────────────────────────────────

def test_no_repite_el_saludo_con_el_nombre():
    """Textual de la conversacion real."""
    dicho = ("¡Buenas noches, Claudio! 😊 Si necesitás agendar un nuevo turno, "
             "puedo ayudarte con eso. ¿Para qué sería la consulta?")
    limpio = quitar_presentacion(dicho)
    assert not limpio.lower().startswith("¡buenas noches")
    assert "agendar un nuevo turno" in limpio


def test_saca_tambien_la_presentacion_completa():
    dicho = ("¡Hola! Soy DentiBot 🦷, el asistente de Silprodent. "
             "¿Querés que busquemos un turno para la semana que viene?")
    limpio = quitar_presentacion(dicho)
    assert "DentiBot" not in limpio
    assert "semana que viene" in limpio


def test_variantes_de_saludo():
    for dicho in [
        "Hola Claudio, te confirmo que el turno quedó agendado para el martes.",
        "¡Buen día! Ya te busqué los horarios disponibles para la limpieza.",
        "Buenas tardes, Estela. El turno de tu hijo quedó para el jueves 10:00.",
    ]:
        limpio = quitar_presentacion(dicho)
        assert limpio != dicho, f"No limpió el saludo de: {dicho}"
        assert len(limpio) > 15


def test_no_rompe_un_mensaje_que_no_saluda():
    """Sin saludo adelante, el texto tiene que quedar intacto."""
    dicho = "Tenés turno el martes 25 a las 10:00 con el Dr. Silvestro."
    assert quitar_presentacion(dicho) == dicho


def test_no_deja_el_mensaje_vacio():
    """Si sacar el saludo no deja nada util, se prefiere el original."""
    dicho = "¡Buenas noches, Claudio!"
    assert quitar_presentacion(dicho) == dicho


# ── El anti-loop que ya existia, para que no se rompa ────────────────────────

def test_detecta_que_se_esta_repitiendo():
    previa = "¿Para qué sería la consulta? (ej: limpieza, extracción, control)"
    assert es_repeticion(previa, [previa])


def test_no_confunde_mensajes_distintos():
    assert not es_repeticion(
        "¿Para qué sería la consulta?",
        ["Tenés turno el martes 25 a las 10:00 con el Dr. Silvestro."],
    )
