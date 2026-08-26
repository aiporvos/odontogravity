"""Que no se le den dos turnos al mismo profesional a la misma hora.

Reportado desde producción: "me dio turno un día que ya estaba ocupado".

La causa es una asimetría entre cómo se valida y cómo se asigna:

    slot_conflict pregunta  → "¿están ocupados TODOS los que pueden atenderlo?"
    create_appointment hace → prof = candidatos[0]   (siempre el primero)

Con un motivo que atienden los dos (Control, Limpieza, Arreglos,
Odontopediatría) y más de un sillón: si Martin está ocupado a las 10:00 pero
Elena libre, la validación pasa —no están ocupados los dos— y después el turno
se le asigna igual a Martin, que es el primero de la lista.

El índice único de la base tampoco lo atrapa: solo cubre `start_time` idéntico.
Un turno de 10:00 a 10:30 contra otro que arranca 10:15 se solapa sin repetir el
horario de inicio.
"""
import pytest

from backend.models.appointment import Appointment, AppointmentStatus
from backend.models.config import AppConfig
from backend.services.appointment_service import create_appointment_logic
from conftest import proximo_dia_habil, turno


@pytest.fixture
def dos_sillones(db):
    """La clínica atiende a dos pacientes a la vez, uno por profesional."""
    db.add(AppConfig(key="CHAIRS_PER_LOCATION", value="2"))
    db.commit()


def _agendar(db, paciente, cuando, motivo="Limpieza"):
    return create_appointment_logic(
        db, paciente.first_name, paciente.last_name, paciente.dni, "",
        motivo, "San Rafael", insurance_name="Particular",
        preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
        requester_phone=paciente.phone,
    )


def test_no_se_le_encima_un_turno_al_profesional_ocupado(
    db, clinica, dos_sillones, silvestro, murad, paciente, otro_paciente
):
    """El caso reportado, exacto."""
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, duracion=15, reason="Limpieza")

    r = _agendar(db, otro_paciente, cuando)
    assert r.get("status") == "ok", f"Con dos sillones debería entrar: {r}"

    nuevo = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert nuevo.professional_id == murad.id, (
        "Se lo asignó al profesional que ya estaba ocupado en ese horario"
    )


def test_tampoco_con_solapamiento_parcial(
    db, clinica, dos_sillones, silvestro, murad, paciente, otro_paciente
):
    """El índice único no cubre esto: los horarios de inicio son distintos."""
    from datetime import timedelta

    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, duracion=60, reason="Conducto")

    r = _agendar(db, otro_paciente, cuando + timedelta(minutes=15))
    assert r.get("status") == "ok", r

    nuevo = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert nuevo.professional_id == murad.id, (
        "Se encimó sobre una endodoncia en curso del mismo profesional"
    )


def test_si_estan_los_dos_ocupados_no_se_agenda(
    db, clinica, dos_sillones, silvestro, murad, paciente, otro_paciente
):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, duracion=15, reason="Limpieza")
    turno(db, otro_paciente, murad, cuando, duracion=15, reason="Limpieza")

    r = _agendar(db, paciente, cuando)
    assert "error" in r, f"No quedaba nadie libre: {r}"


def test_con_un_solo_sillon_cualquier_solapamiento_bloquea(
    db, clinica, silvestro, murad, paciente, otro_paciente
):
    """Sin dos_sillones: el límite físico manda por encima de quién atiende."""
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, duracion=15, reason="Limpieza")

    r = _agendar(db, otro_paciente, cuando)
    assert "error" in r, f"Con un solo sillón no entran dos turnos a la vez: {r}"


def test_el_motivo_sigue_mandando_sobre_quien_atiende(
    db, clinica, dos_sillones, silvestro, murad, paciente
):
    """Repartir la carga no puede romper el ruteo por especialidad."""
    cuando = proximo_dia_habil()
    r = _agendar(db, paciente, cuando, motivo="Extracción")
    assert r.get("status") == "ok", r

    nuevo = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert nuevo.professional_id == silvestro.id, "Las extracciones son de Silvestro"


def test_reparte_la_carga_entre_los_libres(
    db, clinica, dos_sillones, silvestro, murad, paciente, otro_paciente
):
    """Con los dos libres, no siempre al mismo: el segundo turno va al otro."""
    from datetime import timedelta

    base = proximo_dia_habil()
    r1 = _agendar(db, paciente, base)
    r2 = _agendar(db, otro_paciente, base + timedelta(minutes=30))
    assert r1.get("status") == "ok" and r2.get("status") == "ok"

    ids = {
        db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first().professional_id
        for r in (r1, r2)
    }
    assert len(ids) == 2, "Los dos turnos cayeron en el mismo profesional"


def test_un_turno_cancelado_no_ocupa_al_profesional(
    db, clinica, dos_sillones, silvestro, murad, paciente, otro_paciente
):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, reason="Limpieza",
          status=AppointmentStatus.cancelled)

    r = _agendar(db, otro_paciente, cuando)
    assert r.get("status") == "ok", r


# ── Reprogramar mantiene al profesional: no alcanza con que otro esté libre ──

def test_no_se_reprograma_encima_del_mismo_profesional(
    db, clinica, dos_sillones, silvestro, murad, paciente, otro_paciente
):
    """Mover un turno mantiene al profesional, así que tiene que estar libre ÉL."""
    from datetime import timedelta
    from backend.services.appointment_service import profesional_libre

    manana = proximo_dia_habil()
    ocupado = turno(db, paciente, silvestro, manana, duracion=60, reason="Conducto")
    mover = turno(db, otro_paciente, silvestro, manana + timedelta(hours=2),
                  duracion=15, reason="Limpieza")

    # Encima del primero: Murad está libre, pero el turno es de Silvestro.
    assert profesional_libre(
        db, [silvestro], manana + timedelta(minutes=15), 15, "San Rafael",
        exclude_id=mover.id,
    ) is None, "Se lo dejó mover encima de su propia endodoncia"

    # A un hueco libre de Silvestro sí se puede. A la tarde, no a las 13:00:
    # el consultorio cierra de 12:30 a 17:00 y ese corte también se respeta.
    assert profesional_libre(
        db, [silvestro], manana.replace(hour=17), 15, "San Rafael",
        exclude_id=mover.id,
    ) is not None


# ── Cada profesional tiene sus días: no atienden nunca juntos ────────────────

def test_no_se_le_asigna_un_turno_a_quien_no_trabaja_ese_dia(
    db, clinica, silvestro, murad, paciente
):
    """El caso real del consultorio: un solo sillón y días asignados.

    La validación mira la UNIÓN de los horarios de todos los candidatos, así que
    un día en el que solo atiende Murad figura como hábil. Sin verificar quién
    atiende, el turno se le asignaba igual a Silvestro, que ese día no está.
    """
    import uuid
    from datetime import time as t
    from backend.models.schedule import ProfessionalSchedule
    from backend.services.appointment_service import profesional_libre

    martes = proximo_dia_habil(weekday=1)     # solo Murad
    jueves = proximo_dia_habil(weekday=3)     # solo Silvestro

    db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=murad.id,
                                weekday=1, start_time=t(9, 0), end_time=t(12, 30),
                                is_active=True))
    db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=silvestro.id,
                                weekday=3, start_time=t(9, 0), end_time=t(12, 30),
                                is_active=True))
    db.commit()

    elegido = profesional_libre(db, [silvestro, murad], martes, 15, "San Rafael")
    assert elegido is not None, "Murad atiende los martes"
    assert elegido.id == murad.id, "Se lo asignó a Silvestro, que los martes no está"

    elegido = profesional_libre(db, [silvestro, murad], jueves, 15, "San Rafael")
    assert elegido.id == silvestro.id, "Los jueves atiende Silvestro"


def test_nadie_trabaja_ese_dia_no_se_agenda(db, clinica, silvestro, murad, paciente):
    import uuid
    from datetime import time as t
    from backend.models.schedule import ProfessionalSchedule
    from backend.services.appointment_service import profesional_libre

    db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=murad.id,
                                weekday=1, start_time=t(9, 0), end_time=t(12, 30),
                                is_active=True))
    db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=silvestro.id,
                                weekday=1, start_time=t(9, 0), end_time=t(12, 30),
                                is_active=True))
    db.commit()

    jueves = proximo_dia_habil(weekday=3)
    assert profesional_libre(db, [silvestro, murad], jueves, 15, "San Rafael") is None


def test_una_ausencia_puntual_tambien_lo_saca(db, clinica, silvestro, paciente):
    from backend.models.schedule import ProfessionalTimeOff
    from backend.services.appointment_service import profesional_libre

    cuando = proximo_dia_habil()
    assert profesional_libre(db, [silvestro], cuando, 15, "San Rafael") is not None

    db.add(ProfessionalTimeOff(professional_id=silvestro.id, date=cuando.date(),
                               reason="Congreso"))
    db.commit()
    assert profesional_libre(db, [silvestro], cuando, 15, "San Rafael") is None


def test_sin_grilla_cargada_sigue_disponible(db, clinica, silvestro, paciente):
    """Quien todavía no configuró sus días atiende en el horario general."""
    from backend.services.appointment_service import profesional_libre
    assert profesional_libre(
        db, [silvestro], proximo_dia_habil(), 15, "San Rafael"
    ) is not None
