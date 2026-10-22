"""Que el bot no le agende a un paciente el mismo turno dos veces.

Simulación con IA real, 21/10: una paciente terminó con tres limpiezas el mismo
viernes (9:45, 10:00 y 10:15). Cada vez que pedía otro horario, el bot daba de
alta un turno nuevo en lugar de mover el que ya tenía.
"""
from datetime import timedelta

from backend.models.appointment import Appointment, AppointmentChannel, AppointmentStatus
from backend.services.appointment_service import create_appointment_logic
from conftest import proximo_dia_habil, turno


def _agendar(db, paciente, cuando, motivo, canal=AppointmentChannel.bot_whatsapp,
             nombre=None, apellido=None):
    return create_appointment_logic(
        db, nombre or paciente.first_name, apellido or paciente.last_name,
        paciente.dni if nombre is None else "", "", motivo, "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
        channel=canal, requester_phone=paciente.phone,
    )


def _activos(db, paciente):
    return db.query(Appointment).filter(
        Appointment.patient_id == paciente.id,
        Appointment.status != AppointmentStatus.cancelled,
    ).count()


def test_un_segundo_turno_igual_no_se_crea(db, clinica, silvestro, paciente):
    cuando = proximo_dia_habil()
    assert _agendar(db, paciente, cuando, "Extracción").get("status") == "ok"

    r = _agendar(db, paciente, cuando + timedelta(hours=1), "Extracción")
    assert "error" in r and "reprogramar_turno" in r["error"]
    assert r.get("turno_existente")
    assert _activos(db, paciente) == 1


def test_el_mismo_motivo_dicho_distinto_tambien_cuenta(db, clinica, silvestro, paciente):
    from backend.models.tipo_consulta import TipoConsulta
    db.add(TipoConsulta(nombre="Extracción", duracion_minutos=30, especialidad="Extracción",
                        sinonimos=["extraccion", "sacar", "muela"]))
    db.commit()
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, reason="Extracción")
    r = _agendar(db, paciente, cuando + timedelta(hours=1), "extraccion de muela")
    assert "error" in r


def test_otro_motivo_si_se_agenda(db, clinica, silvestro, murad, paciente):
    cuando = proximo_dia_habil()
    turno(db, paciente, murad, cuando, duracion=30, reason="Ortodoncia")
    r = _agendar(db, paciente, cuando + timedelta(hours=1), "Extracción")
    assert r.get("status") == "ok", r


def test_un_turno_pasado_o_cancelado_no_bloquea(db, clinica, silvestro, paciente):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, reason="Extracción",
          status=AppointmentStatus.cancelled)
    r = _agendar(db, paciente, cuando + timedelta(hours=1), "Extracción")
    assert r.get("status") == "ok", r


def test_el_familiar_con_el_mismo_telefono_tiene_su_propio_turno(db, clinica, silvestro, paciente):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, reason="Extracción")
    r = _agendar(db, paciente, cuando + timedelta(hours=1), "Extracción",
                 nombre="Tomás", apellido="Luna")
    assert r.get("status") == "ok", r


def test_desde_el_panel_se_puede_cargar_otro(db, clinica, silvestro, paciente):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, reason="Extracción")
    r = _agendar(db, paciente, cuando + timedelta(hours=1), "Extracción",
                 canal=AppointmentChannel.phone)
    assert r.get("status") == "ok", r
