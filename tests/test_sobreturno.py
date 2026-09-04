"""Que recepcion pueda doblar un horario a proposito, y que quede marcado.

El consultorio encaja pacientes encima de horarios ya tomados: es parte de como
trabajan. Pero la restriccion EXCLUDE de la base —la barrera contra la doble
reserva accidental, la que el bot nunca puede saltear— tampoco dejaba pasar el
caso legitimo.

La diferencia entre los dos casos no es tecnica, es de intencion, asi que ahora
se escribe. `is_overbooking` marca el turno cargado a proposito por encima de
otro, y esas filas quedan fuera del indice de la restriccion. Todo lo demas
sigue igual de bloqueado.

Marcarlo importa tanto como permitirlo: antes el panel deducia cual era el
sobreturno mirando cual se habia creado despues, y esa marca se mudaba sola si
el original se cancelaba.
"""
import pytest
from fastapi import HTTPException

from backend.models.appointment import Appointment, AppointmentStatus
from backend.routers.clinic.clinic_routes import (
    create_appointment, update_appointment,
)
from backend.schemas.schemas import AppointmentCreate, AppointmentUpdate
from conftest import proximo_dia_habil, turno


def _alta(db, paciente, profesional, cuando, force=False, duracion=30):
    return create_appointment(AppointmentCreate(
        patient_id=paciente.id,
        professional_id=profesional.id,
        start_time=cuando,
        duration_minutes=duracion,
        location="San Rafael",
        force=force,
    ), db=db)


# ── La barrera de la base tiene que estar puesta de verdad ──────────────────
# Sin esto, todo lo de abajo pasaria igual con la restriccion caida: el codigo
# valida y la base no diria nada. Ya paso una vez en este proyecto que una
# corrida quedo en verde por el motivo equivocado.

def test_la_restriccion_exclude_existe(db):
    from sqlalchemy import text
    definicion = db.execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'no_solapar_turnos_por_profesional'"
    )).scalar()
    assert definicion, "La restriccion contra la doble reserva no esta creada"
    assert "is_overbooking = false" in definicion, (
        f"La restriccion no exceptua los sobreturnos: {definicion}"
    )


def test_la_base_rechaza_un_solapamiento_no_marcado(db, clinica, silvestro, paciente):
    """La ultima barrera: aunque el codigo se equivoque, la base no deja pasar."""
    from sqlalchemy.exc import IntegrityError
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando)

    db.add(Appointment(
        patient_id=paciente.id, professional_id=silvestro.id,
        start_time=cuando, duration_minutes=30, location="San Rafael",
        status=AppointmentStatus.confirmed,   # sin marcar como sobreturno
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── Sin insistir, el horario ocupado se sigue rechazando ────────────────────

def test_el_horario_ocupado_se_rechaza_por_default(
    db, clinica, silvestro, paciente, otro_paciente
):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando)

    with pytest.raises(HTTPException) as e:
        _alta(db, otro_paciente, silvestro, cuando)
    assert e.value.status_code == 409


def test_el_rechazo_avisa_que_se_puede_cargar_como_sobreturno(
    db, clinica, silvestro, paciente, otro_paciente
):
    """Es lo que le permite al panel ofrecer la salida en vez de dejar sin nada."""
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando)

    with pytest.raises(HTTPException) as e:
        _alta(db, otro_paciente, silvestro, cuando)
    assert e.value.detail["puede_sobreturno"] is True
    assert e.value.detail["message"]


# ── Insistiendo, entra y queda marcado ──────────────────────────────────────

def test_con_force_entra_y_queda_marcado(
    db, clinica, silvestro, paciente, otro_paciente
):
    cuando = proximo_dia_habil()
    primero = turno(db, paciente, silvestro, cuando)

    segundo = _alta(db, otro_paciente, silvestro, cuando, force=True)

    assert segundo.is_overbooking is True
    assert db.query(Appointment).filter(Appointment.id == primero.id).first().is_overbooking is False, (
        "El turno original no es el sobreturno: el sobreturno es el que se cargo encima"
    )


def test_tambien_con_solapamiento_parcial(
    db, clinica, silvestro, paciente, otro_paciente
):
    """No hace falta que empiecen a la misma hora para pisarse."""
    from datetime import timedelta
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, duracion=30)

    segundo = _alta(db, otro_paciente, silvestro, cuando + timedelta(minutes=15), force=True)
    assert segundo.is_overbooking is True


def test_forzar_un_horario_libre_no_crea_ningun_sobreturno(
    db, clinica, silvestro, paciente
):
    """La marca sale de que HAYA habido conflicto, no de que se mande force."""
    a = _alta(db, paciente, silvestro, proximo_dia_habil(), force=True)
    assert a.is_overbooking is False


def test_se_pueden_apilar_varios(db, clinica, silvestro, paciente, otro_paciente):
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando)
    _alta(db, otro_paciente, silvestro, cuando, force=True)
    tercero = _alta(db, paciente, silvestro, cuando, force=True)
    assert tercero.is_overbooking is True

    vivos = db.query(Appointment).filter(
        Appointment.start_time == cuando, Appointment.is_deleted == False).all()
    assert len(vivos) == 3


# ── Un sobreturno no le abre la puerta a la doble reserva accidental ────────

def test_el_sobreturno_no_habilita_al_siguiente_sin_insistir(
    db, clinica, silvestro, paciente, otro_paciente
):
    """Cargar uno a proposito no deja el horario libre para cualquiera."""
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando)
    _alta(db, otro_paciente, silvestro, cuando, force=True)

    with pytest.raises(HTTPException) as e:
        _alta(db, paciente, silvestro, cuando)
    assert e.value.status_code == 409


def test_el_bot_no_puede_hacer_sobreturnos(
    db, clinica, silvestro, paciente, otro_paciente
):
    """El flujo del bot no expone force: sigue sin poder pisar un horario."""
    from backend.services.appointment_service import create_appointment_logic
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, reason="Limpieza")

    r = create_appointment_logic(
        db, otro_paciente.first_name, otro_paciente.last_name, otro_paciente.dni, "",
        "Limpieza", "San Rafael", insurance_name="Particular",
        preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
        requester_phone=otro_paciente.phone,
    )
    assert r.get("status") != "ok", f"El bot piso un horario ocupado: {r}"


# ── La marca se recalcula al mover el turno ─────────────────────────────────

@pytest.mark.asyncio
async def test_mover_un_sobreturno_a_un_horario_libre_lo_deja_de_ser(
    db, clinica, silvestro, paciente, otro_paciente
):
    from datetime import timedelta
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando)
    sobre = _alta(db, otro_paciente, silvestro, cuando, force=True)

    movido = await update_appointment(
        sobre.id, AppointmentUpdate(start_time=cuando + timedelta(hours=2)), db=db)
    assert movido.is_overbooking is False, (
        "Se corrio a un horario libre: ya no esta encima de nadie"
    )


@pytest.mark.asyncio
async def test_mover_un_turno_normal_encima_de_otro_pide_insistir(
    db, clinica, silvestro, paciente, otro_paciente
):
    from datetime import timedelta
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando)
    suelto = turno(db, otro_paciente, silvestro, cuando + timedelta(hours=2))

    with pytest.raises(HTTPException) as e:
        await update_appointment(suelto.id, AppointmentUpdate(start_time=cuando), db=db)
    assert e.value.status_code == 409

    movido = await update_appointment(
        suelto.id, AppointmentUpdate(start_time=cuando, force=True), db=db)
    assert movido.is_overbooking is True
