"""Que «menos martes y jueves» se respete, al ofrecer y al agendar.

R01, R02, R03 y R06 del plan de QA. Caso real del 08/09/2026:

    paciente: Puede ser en la tarde, menos Martes y Jueves
    bot:      Tengo disponibilidad para limpieza el martes 8 de septiembre...
    → turno agendado el martes 08/09 a las 17:45

La franja ("tarde") sí se respetaba. La exclusión de días no tenía por dónde
entrar, así que se ignoraba entera. Es una restricción DURA: se mantiene hasta
que la persona la cambie.
"""
from datetime import datetime, timedelta

import pytest

from backend.models.appointment import Appointment
from backend.services.appointment_service import (
    create_appointment_logic, dias_excluidos, get_available_slots,
    interpretar_preferencia,
)


def _proximo(weekday: int, hora=17) -> datetime:
    base = datetime.now().replace(hour=hora, minute=0, second=0, microsecond=0) + timedelta(days=1)
    while base.weekday() != weekday:
        base += timedelta(days=1)
    return base


# ── Leer la exclusión ───────────────────────────────────────────────────────

def test_el_caso_reportado():
    assert dias_excluidos("Puede ser en la tarde, menos Martes y Jueves") == {1, 3}


@pytest.mark.parametrize("dicho,esperado", [
    ("menos martes", {1}),
    ("excepto los miércoles", {2}),
    ("salvo viernes", {4}),
    ("sin lunes ni martes", {0, 1}),
    ("que no sea jueves", {3}),
])
def test_reconoce_las_formas_de_excluir(dicho, esperado):
    assert dias_excluidos(dicho) == esperado


@pytest.mark.parametrize("dicho", [
    "martes o jueves",      # los quiere, no los descarta
    "el martes me viene bien",
    "a la tarde",
    "",
    None,
])
def test_no_inventa_exclusiones(dicho):
    assert dias_excluidos(dicho) == set()


# ── R02 y R03: ambigüedades que estaban mal ────────────────────────────────

def test_manana_a_la_tarde_es_la_tarde():
    """El día de mañana, franja tarde. Antes ganaba la palabra 'mañana'."""
    desde, hasta = interpretar_preferencia("mañana a la tarde")
    assert desde == 12 * 60 + 30, "Le ofrecía la mañana a quien pidió la tarde"


def test_despues_del_16_no_es_las_16():
    """«después del 16» es una fecha, no un horario."""
    assert interpretar_preferencia("después del 16") is None


def test_una_hora_de_verdad_si_se_entiende():
    assert interpretar_preferencia("después de las 18:45") == (18 * 60 + 45, 24 * 60)
    assert interpretar_preferencia("a las 18") == (18 * 60, 24 * 60)
    assert interpretar_preferencia("18hs") == (18 * 60, 24 * 60)
    assert interpretar_preferencia("antes de las 11") == (0, 11 * 60)


# ── Al ofrecer ──────────────────────────────────────────────────────────────

def test_no_ofrece_un_dia_excluido(db, clinica, silvestro, murad):
    martes = _proximo(1)
    r = get_available_slots(
        db, martes.date().isoformat(), "San Rafael", "Extracción",
        preferencia_horaria="a la tarde, menos martes y jueves")

    elegido = datetime.fromisoformat(r["date"])
    assert elegido.weekday() not in (1, 3), (
        f"Ofreció {r['date']}, que es un día que el paciente descartó"
    )


def test_al_saltear_explica_por_que(db, clinica, silvestro, murad):
    r = get_available_slots(
        db, _proximo(1).date().isoformat(), "San Rafael", "Extracción",
        preferencia_horaria="menos martes")
    assert "martes" in (r.get("motivo_salto") or "").lower()


# ── Al agendar: la segunda barrera ─────────────────────────────────────────

def test_no_agenda_en_un_dia_excluido(db, clinica, silvestro, paciente):
    """Aunque el modelo elija la fecha por su cuenta."""
    martes = _proximo(1)
    r = create_appointment_logic(
        db, paciente.first_name, paciente.last_name, paciente.dni, "",
        "Extracción", "San Rafael", insurance_name="Particular",
        preferred_date=martes.strftime("%Y-%m-%d %H:%M"),
        requester_phone=paciente.phone,
        preferencia_horaria="a la tarde, menos martes y jueves",
    )
    assert "error" in r, "Agendó el martes que la paciente había descartado"
    assert "martes" in r["error"].lower()
    assert db.query(Appointment).count() == 0


def test_un_dia_permitido_se_agenda(db, clinica, silvestro, paciente):
    # Lunes a la tarde: no está excluido y el consultorio atiende (el miércoles
    # no tiene turno tarde, así que no sirve para este caso).
    r = create_appointment_logic(
        db, paciente.first_name, paciente.last_name, paciente.dni, "",
        "Extracción", "San Rafael", insurance_name="Particular",
        preferred_date=_proximo(0).strftime("%Y-%m-%d %H:%M"),
        requester_phone=paciente.phone,
        preferencia_horaria="a la tarde, menos martes y jueves",
    )
    assert r.get("status") == "ok", r


def test_sin_restriccion_sigue_andando_igual(db, clinica, silvestro, paciente):
    r = create_appointment_logic(
        db, paciente.first_name, paciente.last_name, paciente.dni, "",
        "Extracción", "San Rafael", insurance_name="Particular",
        preferred_date=_proximo(1).strftime("%Y-%m-%d %H:%M"),
        requester_phone=paciente.phone,
    )
    assert r.get("status") == "ok", r
