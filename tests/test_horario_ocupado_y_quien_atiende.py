"""Simulación con IA real, 22/10: dos detalles que hacían perder al modelo.

- Una pareja pidió dos limpiezas seguidas; la de ella chocó con la de él, recién
  agendada, y la herramienta solo decía "ya hay un turno en ese horario".
- Un martes (solo atiende Murad) la disponibilidad anunciaba "con el Dr.
  Silvestro", el primero de la lista, y el turno después quedaba con Murad.
"""
import uuid
from datetime import time as dtime, timedelta

from backend.models.schedule import ProfessionalSchedule
from backend.services.appointment_service import create_appointment_logic, get_available_slots
from conftest import proximo_dia_habil


def _grilla(db, prof, dias):
    for wd in dias:
        db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=prof.id, weekday=wd,
                                    start_time=dtime(9, 0), end_time=dtime(12, 30), is_active=True))
    db.commit()


def test_horario_ocupado_sugiere_los_libres_del_dia(db, clinica, silvestro, paciente, otro_paciente):
    cuando = proximo_dia_habil()
    agendar = lambda p: create_appointment_logic(  # noqa: E731
        db, p.first_name, p.last_name, p.dni, "", "Extracción", "San Rafael",
        insurance_name="Particular", preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
        requester_phone=p.phone)
    assert agendar(paciente).get("status") == "ok"
    r = agendar(otro_paciente)
    assert "Libres ese día:" in r["error"]
    assert "10:30" in r["error"], r["error"]       # el siguiente, contiguo


def test_se_anuncia_a_quien_atiende_ese_dia(db, clinica, silvestro, murad):
    silvestro.specialties = ["Limpieza"]
    murad.specialties = ["Limpieza"]
    db.commit()
    _grilla(db, silvestro, [2, 3])      # miércoles y jueves
    _grilla(db, murad, [0, 1])          # lunes y martes
    martes = proximo_dia_habil(weekday=1)
    r = get_available_slots(db, martes.date().isoformat(), "San Rafael", "Limpieza", "Particular")
    assert r["date"] == str(martes.date())
    assert r["professional"] == murad.full_name
