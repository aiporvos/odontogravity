"""Las reglas duras del negocio, que antes solo se validaban al ofrecer horarios.

El bot es el canal que genera casi todos los turnos y su camino de escritura
(create_appointment_logic) insertaba directo, sin chequear solapamiento,
sillones, feriado ni la regla de PAMI. El caso 4 de QA/casos_de_prueba.md
("Prevención de Doble Reserva") daba eso por resuelto y no lo estaba.
"""
from datetime import timedelta

import pytest

from backend.models.appointment import AppointmentStatus
from backend.models.schedule import ClinicHoliday
from backend.services.appointment_service import (
    create_appointment_logic, duracion_para_motivo, motivo_no_agendable,
    motivo_regla_obra_social, slot_conflict,
)
from conftest import proximo_dia_habil, turno


# ── Duracion segun el motivo ─────────────────────────────────────────────────

@pytest.mark.parametrize("motivo,esperado", [
    ("Limpieza", 15),
    ("Control", 15),
    ("Extracción", 30),
    ("extraccion de muela", 30),
    ("Ortodoncia", 30),
    ("Implante", 30),
    ("Conducto", 60),
    ("Endodoncia", 60),
])
def test_duracion_sale_del_motivo(motivo, esperado):
    assert duracion_para_motivo(motivo) == esperado


def test_la_duracion_la_decide_el_servidor_no_el_bot(db, clinica, silvestro, paciente):
    """Aunque el modelo mande 15 minutos, una endodoncia ocupa 60."""
    cuando = proximo_dia_habil()
    r = create_appointment_logic(
        db, "Claudio", "Luna", paciente.dni, "", "Endodoncia", "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
        duration_minutes=15,   # lo que "eligio" el modelo
    )
    assert r.get("status") == "ok", r
    from backend.models.appointment import Appointment
    a = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert a.duration_minutes == 60


# ── Doble reserva ────────────────────────────────────────────────────────────

def test_no_se_puede_agendar_sobre_un_turno_existente(db, clinica, silvestro,
                                                      paciente, otro_paciente):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, duracion=30)

    r = create_appointment_logic(
        db, "Estela", "Pardo", otro_paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
    )
    assert "error" in r, f"Se agendo encima de otro turno: {r}"


def test_tampoco_si_solo_se_superpone_parcialmente(db, clinica, silvestro,
                                                   paciente, otro_paciente):
    """Una endodoncia de 60' a las 10:00 bloquea las 10:30."""
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, duracion=60, reason="Endodoncia")

    encima = cuando + timedelta(minutes=30)
    r = create_appointment_logic(
        db, "Estela", "Pardo", otro_paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=encima.strftime("%Y-%m-%d %H:%M"),
    )
    assert "error" in r, f"Se agendo pisando una endodoncia en curso: {r}"


def test_un_turno_cancelado_libera_el_horario(db, clinica, silvestro,
                                              paciente, otro_paciente):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, status=AppointmentStatus.cancelled)

    r = create_appointment_logic(
        db, "Estela", "Pardo", otro_paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
    )
    assert r.get("status") == "ok", f"Un turno cancelado no deberia ocupar el horario: {r}"


def test_el_indice_de_la_base_impide_el_duplicado(db, clinica, silvestro,
                                                  paciente, otro_paciente):
    """Ultima barrera: aunque la validacion no corriera, la base rechaza."""
    from sqlalchemy.exc import IntegrityError
    from backend.models.appointment import Appointment, AppointmentChannel

    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando)

    db.add(Appointment(
        patient_id=otro_paciente.id, professional_id=silvestro.id,
        start_time=cuando, duration_minutes=30, reason="Extracción",
        location="San Rafael", insurance_name="Particular",
        status=AppointmentStatus.confirmed, channel=AppointmentChannel.web,
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_sillones_configurables(db, clinica, silvestro, murad, paciente, otro_paciente):
    """Con 2 sillones, dos profesionales distintos pueden atender a la misma hora."""
    from backend.models.config import AppConfig
    db.add(AppConfig(key="CHAIRS_PER_LOCATION", value="2"))
    db.commit()

    cuando = proximo_dia_habil()
    turno(db, paciente, murad, cuando, reason="Ortodoncia")

    r = create_appointment_logic(
        db, "Estela", "Pardo", otro_paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
    )
    assert r.get("status") == "ok", f"Con 2 sillones deberia entrar: {r}"


# ── Feriados ─────────────────────────────────────────────────────────────────

def test_no_se_agenda_en_feriado(db, clinica, silvestro, paciente):
    cuando = proximo_dia_habil()
    db.add(ClinicHoliday(date=cuando.date(), description="Feriado de prueba"))
    db.commit()

    r = create_appointment_logic(
        db, "Claudio", "Luna", paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
    )
    assert "error" in r and "feriado" in r["error"].lower(), r


# ── Horario de atencion ──────────────────────────────────────────────────────

def test_no_se_agenda_fuera_del_horario(db, clinica, silvestro, paciente):
    """Las 23:00 no existen para el consultorio, aunque el modelo las proponga."""
    cuando = proximo_dia_habil().replace(hour=23, minute=0)
    r = create_appointment_logic(
        db, "Claudio", "Luna", paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
    )
    assert "error" in r, f"Agendo a las 23:00: {r}"


def test_no_se_agenda_el_miercoles_a_la_tarde(db, clinica, silvestro, paciente):
    """El miércoles a la tarde el consultorio está cerrado."""
    miercoles = proximo_dia_habil(weekday=2).replace(hour=18, minute=0)
    r = create_appointment_logic(
        db, "Claudio", "Luna", paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=miercoles.strftime("%Y-%m-%d %H:%M"),
    )
    assert "error" in r, f"Agendo un miercoles a la tarde: {r}"


def test_no_se_agenda_en_el_pasado(db, clinica, silvestro, paciente):
    from backend.services.appointment_service import get_clinic_now
    ayer = get_clinic_now() - timedelta(days=1)
    r = create_appointment_logic(
        db, "Claudio", "Luna", paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=ayer.strftime("%Y-%m-%d %H:%M"),
    )
    assert "error" in r, f"Agendo en el pasado: {r}"


# ── Regla interna de PAMI ────────────────────────────────────────────────────

def test_pami_solo_viernes():
    martes = proximo_dia_habil(weekday=1)
    viernes = proximo_dia_habil(weekday=4)
    assert motivo_regla_obra_social("PAMI", martes) is not None
    assert motivo_regla_obra_social("PAMI", viernes) is None


def test_viernes_solo_pami():
    viernes = proximo_dia_habil(weekday=4)
    assert motivo_regla_obra_social("Particular", viernes) is not None
    assert motivo_regla_obra_social("OSDE", viernes) is not None


def test_no_se_agenda_pami_un_martes(db, clinica, silvestro, paciente):
    martes = proximo_dia_habil(weekday=1)
    r = create_appointment_logic(
        db, "Claudio", "Luna", paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="PAMI", preferred_date=martes.strftime("%Y-%m-%d %H:%M"),
    )
    assert "error" in r, f"Agendo PAMI un martes: {r}"


def test_el_motivo_de_pami_no_se_le_explica_al_paciente(db, clinica, silvestro, paciente):
    """La regla es interna: el mensaje no puede nombrar PAMI ni decir por que."""
    martes = proximo_dia_habil(weekday=1)
    r = create_appointment_logic(
        db, "Claudio", "Luna", paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="PAMI", preferred_date=martes.strftime("%Y-%m-%d %H:%M"),
    )
    assert "PAMI" not in r["error"], r["error"]
    assert "viernes" not in r["error"].lower(), r["error"]


# ── Obra social ──────────────────────────────────────────────────────────────

def test_obra_social_no_cubierta_se_agenda_como_particular(db, clinica, silvestro, paciente):
    """Garantia por codigo: el modelo no puede inventar una cobertura."""
    cuando = proximo_dia_habil()
    r = create_appointment_logic(
        db, "Claudio", "Luna", paciente.dni, "", "Extracción", "San Rafael",
        insurance_name="Una Obra Social Que No Existe",
        preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
    )
    assert r.get("status") == "ok", r
    from backend.models.appointment import Appointment
    a = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert a.insurance_name == "Particular"


# ── Un intento fallido no debe ensuciar la base ──────────────────────────────

def test_un_alta_rechazada_no_crea_la_ficha_del_paciente(db, clinica, silvestro):
    """Antes se creaba el paciente antes de validar la fecha."""
    from backend.models.patient import Patient
    cuando = proximo_dia_habil().replace(hour=23, minute=0)  # fuera de horario
    antes = db.query(Patient).count()

    r = create_appointment_logic(
        db, "Fulano", "De Tal", "99887766", "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
    )
    assert "error" in r
    assert db.query(Patient).count() == antes, "Quedo una ficha de un turno que nunca se agendo"


# ── slot_conflict directo ────────────────────────────────────────────────────

def test_slot_conflict_ignora_el_propio_turno_al_reprogramar(db, clinica,
                                                             silvestro, paciente):
    cuando = proximo_dia_habil()
    a = turno(db, paciente, silvestro, cuando)
    del_dia = [a]
    assert slot_conflict(del_dia, cuando, 30, 1, [silvestro.id]) is not None
    assert slot_conflict(del_dia, cuando, 30, 1, [silvestro.id], exclude_id=a.id) is None
