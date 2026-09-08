"""Que "quiero al Dr. Silvestro" se respete, y que no se confirme lo que no se hizo.

Reportado desde producción el 08/09/2026. Conversación real:

    paciente: Para el doctor silvestro necesito también
    bot:      Para el Dr. Silvestro, tengo disponibilidad el lunes 14 de
              septiembre a las 11:00, 12:15, 17:00 o 20:15. ¿Cuál te gustaría?
    paciente: A las 11
    bot:      Te agendé para el lunes 14 a las 11:00 con el Dr. Martin Silvestro.

Dos cosas mal, y la segunda es peor:

1. Silvestro NO atiende los lunes (miércoles, jueves y viernes). Ninguna
   herramienta tenía dónde pasar "quiero a este profesional", así que la
   consulta devolvía los horarios de cualquiera y el modelo los presentaba
   como si fueran de él.
2. Ese turno NUNCA se creó. El log de la conversación no tiene ni una llamada a
   /availability ni a /appointments después del primer turno, y el link de
   cancelación era el del turno anterior, copiado. El paciente se fue creyendo
   que tenía un turno que no existe.
"""
import uuid
from datetime import datetime, time as py_time, timedelta

import pytest

from backend.models.appointment import Appointment
from backend.models.schedule import ProfessionalSchedule
from backend.services.appointment_service import (
    buscar_profesional, create_appointment_logic, dias_que_atiende,
    get_available_slots,
)


@pytest.fixture
def grillas(db, silvestro, murad):
    """Los días reales: Murad lunes/martes/viernes, Silvestro miércoles a viernes."""
    def franjas(prof, dias, con_tarde=True):
        for d in dias:
            db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=prof.id,
                                        weekday=d, start_time=py_time(9, 0),
                                        end_time=py_time(12, 30), is_active=True))
            if con_tarde and d != 2:
                db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=prof.id,
                                            weekday=d, start_time=py_time(17, 0),
                                            end_time=py_time(20, 30), is_active=True))
    franjas(murad, [0, 1, 4])
    franjas(silvestro, [2, 3, 4])
    db.commit()


def _proximo(weekday: int, hora=10) -> datetime:
    base = datetime.now().replace(hour=hora, minute=0, second=0, microsecond=0) + timedelta(days=1)
    while base.weekday() != weekday:
        base += timedelta(days=1)
    return base


# ── Reconocer al profesional que nombra el paciente ─────────────────────────

@pytest.mark.parametrize("como_lo_dijo", [
    "Silvestro", "silvestro", "el doctor silvestro", "Dr. Silvestro",
    "dr silvestro", "SILVESTRO",
])
def test_lo_reconoce_como_sea_que_lo_escriban(db, silvestro, murad, como_lo_dijo):
    assert buscar_profesional(db, como_lo_dijo).id == silvestro.id


def test_no_confunde_a_uno_con_el_otro(db, silvestro, murad):
    assert buscar_profesional(db, "la Dra. Murad").id == murad.id


def test_un_nombre_que_no_existe_devuelve_nada(db, silvestro, murad):
    assert buscar_profesional(db, "Dr. Perez") is None
    assert buscar_profesional(db, "") is None
    assert buscar_profesional(db, "doctor") is None, (
        "'doctor' solo es un tratamiento, no el nombre de nadie"
    )


def test_sabe_que_dias_atiende_cada_uno(db, grillas, silvestro, murad):
    assert dias_que_atiende(db, silvestro) == ["miércoles", "jueves", "viernes"]
    assert dias_que_atiende(db, murad) == ["lunes", "martes", "viernes"]


# ── El caso reportado ───────────────────────────────────────────────────────

def test_no_ofrece_un_lunes_con_quien_no_atiende_los_lunes(db, clinica, grillas, silvestro):
    """Lo que se le contestó al paciente: horarios del lunes con Silvestro."""
    lunes = _proximo(0)
    r = get_available_slots(db, lunes.date().isoformat(), "San Rafael", "Extracción",
                            profesional_pedido="Silvestro")

    assert r["date"] != str(lunes.date()), (
        f"Ofreció el lunes con Silvestro, que los lunes no atiende: {r['available_slots']}"
    )
    # Y el día al que se movió tiene que ser uno en el que sí atienda.
    assert datetime.fromisoformat(r["date"]).weekday() in (2, 3, 4)


def test_al_moverlo_explica_que_dias_atiende(db, clinica, grillas, silvestro):
    """Para que el paciente sepa por qué le ofrecen otro día."""
    r = get_available_slots(db, _proximo(0).date().isoformat(), "San Rafael",
                            "Extracción", profesional_pedido="Silvestro")
    motivo = (r.get("motivo_salto") or "").lower()
    assert "silvestro" in motivo
    assert "miércoles" in motivo


def test_un_dia_que_si_atiende_devuelve_horarios(db, clinica, grillas, silvestro):
    r = get_available_slots(db, _proximo(3).date().isoformat(), "San Rafael",
                            "Extracción", profesional_pedido="Silvestro")
    assert r["available_slots"], "El jueves sí atiende"
    assert "Silvestro" in r["professional"]


def test_pedir_a_uno_no_devuelve_los_horarios_del_otro(db, clinica, grillas, silvestro, murad):
    """El martes atiende Murad y no Silvestro: pedir a Silvestro no puede
    devolver el martes como si fuera de él."""
    martes = _proximo(1)
    r = get_available_slots(db, martes.date().isoformat(), "San Rafael", "Extracción",
                            profesional_pedido="Silvestro")
    assert r["date"] != str(martes.date())


# ── El alta también lo respeta ──────────────────────────────────────────────

def _agendar(db, paciente, cuando, quien=None, motivo="Extracción"):
    return create_appointment_logic(
        db, paciente.first_name, paciente.last_name, paciente.dni, "",
        motivo, "San Rafael", insurance_name="Particular",
        preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
        requester_phone=paciente.phone, profesional_pedido=quien,
    )


def test_no_agenda_con_quien_no_atiende_ese_dia(db, clinica, grillas, silvestro, paciente):
    r = _agendar(db, paciente, _proximo(0), quien="Silvestro")
    assert "error" in r, "Agendó un lunes con Silvestro"
    assert "miércoles" in r["error"], "No le dice al paciente qué días sí atiende"


def test_agenda_con_el_pedido_cuando_si_atiende(db, clinica, grillas, silvestro, paciente):
    r = _agendar(db, paciente, _proximo(3), quien="Silvestro")
    assert r.get("status") == "ok", r
    guardado = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert guardado.professional_id == silvestro.id


def test_sin_pedir_a_nadie_sigue_funcionando_como_antes(db, clinica, grillas, silvestro, paciente):
    r = _agendar(db, paciente, _proximo(3))
    assert r.get("status") == "ok", r


def test_pedir_a_alguien_que_no_existe_no_agenda_con_otro(db, clinica, grillas, silvestro, paciente):
    r = _agendar(db, paciente, _proximo(3), quien="Dr. Gonzalez")
    assert "error" in r
    assert db.query(Appointment).count() == 0
