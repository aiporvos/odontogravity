"""Que un nombre de sede escrito distinto no parta la agenda en dos.

Encontrado en producción el 08/09/2026, y NO está en el plan de QA.

La misma sede está cargada con tres nombres: "San Rafael" (382 turnos),
"Silprodent" (194) y "Silproden" (16, con la 't' faltante). get_day_appointments
comparaba `location = 'X'` a secas, así que cada nombre era una agenda separada.
El bot agenda siempre en "San Rafael" y por lo tanto no veía el 87% de los
turnos futuros.

No es teórico: el 01/09 a las 11:00 el bot agendó un tratamiento de conducto de
60 minutos encima de uno de 10:30 a 11:30 cargado como "Silprodent", con la
misma profesional y un solo sillón.
"""
from datetime import timedelta

import pytest

from backend.services.appointment_service import (
    get_available_slots, get_day_appointments, misma_sede,
)
from conftest import proximo_dia_habil, turno


# ── La comparación ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("Silprodent", "silprodent"),      # mayúsculas
    ("Silprodent", " Silprodent "),    # espacios
    ("San  Rafael", "San Rafael"),     # espacio doble
    ("Alvear", "álvear"),              # acentos
    ("Silprodent", None),              # sede sin cargar: cuenta como cualquiera
    (None, "San Rafael"),
])
def test_reconoce_la_misma_sede(a, b):
    assert misma_sede(a, b) is True


@pytest.mark.parametrize("a,b", [
    ("San Rafael", "Alvear"),
    ("Silprodent", "Silproden"),   # el typo NO se adivina: es otro nombre
])
def test_no_junta_sedes_distintas(a, b):
    assert misma_sede(a, b) is False


# ── El efecto sobre la ocupación ────────────────────────────────────────────

def test_ve_los_turnos_de_la_sede_escrita_distinto(db, clinica, silvestro, paciente):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, location="silprodent")

    vistos = get_day_appointments(db, cuando.date(), "Silprodent")
    assert len(vistos) == 1, "Una diferencia de mayúsculas escondió el turno"


def test_no_ofrece_un_horario_ocupado_en_la_sede_escrita_distinto(
    db, clinica, silvestro, murad, paciente
):
    """Una diferencia de grafía no puede liberar un horario ocupado."""
    cuando = proximo_dia_habil().replace(hour=10, minute=0)
    turno(db, paciente, silvestro, cuando, duracion=60, location="  SILPRODENT ")

    r = get_available_slots(db, cuando.date().isoformat(), "Silprodent", "Extracción")
    ocupados = {"10:00", "10:30"}
    assert not (ocupados & set(r["available_slots"])), (
        f"Ofreció horarios ya tomados en la otra grafía de la sede: "
        f"{r['available_slots']}"
    )


def test_dos_nombres_distintos_siguen_siendo_dos_agendas(
    db, clinica, silvestro, paciente
):
    """Lo que el código NO puede arreglar solo, y hay que decirlo.

    En producción la misma sede física está cargada como "San Rafael" y como
    "Silprodent". No son variantes de escritura: son dos cadenas distintas, y
    ningún normalizador puede adivinar que son el mismo lugar sin que alguien
    lo decida. Mientras la base siga así, el bot que agenda en "San Rafael" no
    ve los turnos de "Silprodent".

    Este test fija ese límite para que no se confunda con un arreglo hecho.
    """
    cuando = proximo_dia_habil().replace(hour=10, minute=0)
    turno(db, paciente, silvestro, cuando, duracion=60, location="Silprodent")

    assert get_day_appointments(db, cuando.date(), "San Rafael") == [], (
        "Si esto empieza a fallar es porque se unificaron los nombres: "
        "actualizá el test y sacá la advertencia de la documentación"
    )


def test_una_sede_de_verdad_distinta_sigue_siendo_independiente(
    db, clinica, silvestro, paciente
):
    """Alvear es otro lugar: su ocupación no bloquea San Rafael."""
    cuando = proximo_dia_habil().replace(hour=10, minute=0)
    turno(db, paciente, silvestro, cuando, duracion=60, location="Alvear")

    assert get_day_appointments(db, cuando.date(), "San Rafael") == []


# ── Con una sola sede, el backend la resuelve y el bot no puede errarle ─────

def test_con_una_sola_sede_activa_esa_gana(db, clinica):
    from backend.services.appointment_service import sede_efectiva, sede_por_defecto
    assert sede_por_defecto(db) == "San Rafael"
    # Mande lo que mande el bot, la única sede activa es la que vale.
    assert sede_efectiva(db, "San Rafael") == "San Rafael"
    assert sede_efectiva(db, "Silprodent") == "San Rafael"
    assert sede_efectiva(db, None) == "San Rafael"
    assert sede_efectiva(db, "") == "San Rafael"


def test_con_dos_sedes_activas_vuelve_a_mandar_el_parametro(db, clinica):
    from backend.models.clinic_location import ClinicLocation
    from backend.services.appointment_service import sede_efectiva, sede_por_defecto

    db.add(ClinicLocation(name="Alvear"))
    db.commit()

    assert sede_por_defecto(db) is None
    assert sede_efectiva(db, "Alvear") == "Alvear"


def test_sin_ninguna_sede_activa_no_inventa(db):
    from backend.services.appointment_service import sede_efectiva, sede_por_defecto
    assert sede_por_defecto(db) is None
    assert sede_efectiva(db, "lo que sea") == "lo que sea"


def test_el_turno_del_bot_queda_en_la_sede_del_sistema(db, clinica, silvestro, paciente):
    """Aunque el bot mande otro nombre, el turno no puede caer en otra agenda."""
    from backend.models.appointment import Appointment
    from backend.routers.bot_routes import bot_create_appointment
    from backend.schemas.schemas import BotAppointmentRequest

    r = bot_create_appointment(BotAppointmentRequest(
        patient_name=paciente.first_name, patient_last_name=paciente.last_name,
        dni=paciente.dni, reason="Extracción", location="Sede Inventada",
        preferred_date=proximo_dia_habil().strftime("%Y-%m-%d %H:%M"),
        requester_phone=paciente.phone,
    ), db=db)

    guardado = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert guardado.location == "San Rafael"
