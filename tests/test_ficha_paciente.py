"""Que el bot sepa de qué vino el paciente la última vez.

Reclamo real de Claudio probando el bot: "tampoco sabe porque me atendio el
doctor". El motivo estaba guardado en cada turno y no se le pasaba al modelo:
la ficha decia QUIEN lo atendio y CUANDO, pero no DE QUE, que es justamente lo
que uno espera que recuerden de uno.
"""
from datetime import timedelta

from backend.models.appointment import AppointmentStatus
from backend.routers.bot_routes import ficha_para_el_bot
from backend.services.appointment_service import get_clinic_now
from conftest import proximo_dia_habil, turno


def test_la_ficha_trae_el_motivo_de_la_ultima_visita(db, clinica, silvestro, paciente):
    turno(db, paciente, silvestro, get_clinic_now() - timedelta(days=5),
          reason="Limpieza", status=AppointmentStatus.completed)

    ficha = ficha_para_el_bot(db, paciente)
    assert ficha["ultimo_motivo"] == "Limpieza"
    assert ficha["ultimo_profesional"] == silvestro.full_name
    assert ficha["es_paciente_nuevo"] is False


def test_trae_las_consultas_anteriores(db, clinica, silvestro, paciente):
    turno(db, paciente, silvestro, get_clinic_now() - timedelta(days=90),
          reason="Conducto", status=AppointmentStatus.completed)
    turno(db, paciente, silvestro, get_clinic_now() - timedelta(days=5),
          reason="Limpieza", status=AppointmentStatus.completed)

    motivos = [c["motivo"] for c in ficha_para_el_bot(db, paciente)["consultas_previas"]]
    assert motivos == ["Limpieza", "Conducto"], "Deben venir de la más reciente a la más vieja"


def test_un_turno_futuro_no_es_una_visita_pasada(db, clinica, silvestro, paciente):
    """Sin filtro de fecha, un turno que todavia no ocurrio figuraba como
    'la ultima vez que vino'."""
    turno(db, paciente, silvestro, proximo_dia_habil(), reason="Extracción")

    ficha = ficha_para_el_bot(db, paciente)
    assert ficha["ultima_visita"] is None, "Un turno futuro no es una visita pasada"
    assert ficha["ultimo_motivo"] is None
    assert ficha["es_paciente_nuevo"] is True
    assert ficha["proximo_turno"] is not None, "Pero sí tiene que figurar como turno próximo"


def test_paciente_sin_historia(db, clinica, silvestro, paciente):
    ficha = ficha_para_el_bot(db, paciente)
    assert ficha["es_paciente_nuevo"] is True
    assert ficha["consultas_previas"] == []
    assert ficha["nombre"] == "Claudio"
    assert ficha["obra_social"] == "Particular"


def test_un_turno_cancelado_no_cuenta_como_visita(db, clinica, silvestro, paciente):
    turno(db, paciente, silvestro, get_clinic_now() - timedelta(days=5),
          reason="Limpieza", status=AppointmentStatus.cancelled)
    assert ficha_para_el_bot(db, paciente)["ultimo_motivo"] is None


def test_la_franja_preferida_sale_de_sus_turnos(db, clinica, silvestro, paciente):
    """Tres visitas a la mañana: no hace falta preguntarle cuándo prefiere."""
    for dias in (10, 40, 70):
        cuando = (get_clinic_now() - timedelta(days=dias)).replace(hour=9, minute=30)
        turno(db, paciente, silvestro, cuando, reason="Control",
              status=AppointmentStatus.completed)

    assert ficha_para_el_bot(db, paciente)["franja_preferida"] == "mañana"
