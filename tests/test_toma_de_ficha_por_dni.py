"""Que saber un DNI ajeno no alcance para quedarse con la ficha de otro.

Hasta el 07/10/2026, cualquiera escribía por WhatsApp "mi DNI es X, quiero un
turno" y el alta le pisaba el teléfono a la ficha de X con el suyo. Desde ahí el
bot lo reconocía como dueño: veía obra social, consultas y tratamientos, y podía
cancelar o reprogramar. El paciente real perdía el acceso.

El teléfono de WhatsApp es la única identidad verificada; el DNI no es secreto.
"""
import pytest
from fastapi import HTTPException

from backend.models.appointment import Appointment
from backend.models.patient import Patient
from backend.routers.bot_routes import bot_create_appointment, resolver_paciente
from backend.schemas.schemas import BotAppointmentRequest
from conftest import proximo_dia_habil

INTRUSO = "+5492604999888"


def _pedir(db, dni, requester_phone=INTRUSO, nombre="Juan", apellido="Pérez"):
    return bot_create_appointment(BotAppointmentRequest(
        patient_name=nombre, patient_last_name=apellido, dni=dni,
        reason="Extracción", location="San Rafael",
        preferred_date=proximo_dia_habil().strftime("%Y-%m-%d %H:%M"),
        requester_phone=requester_phone,
    ), db=db)


def test_un_dni_ajeno_no_agenda_ni_pisa_el_telefono(db, clinica, silvestro, paciente):
    telefono_real = paciente.phone
    with pytest.raises(HTTPException) as e:
        _pedir(db, paciente.dni)
    assert e.value.status_code == 403
    db.refresh(paciente)
    assert paciente.phone == telefono_real
    assert db.query(Appointment).count() == 0


def test_el_dueno_del_dni_sigue_agendando(db, clinica, silvestro, paciente):
    r = _pedir(db, paciente.dni, requester_phone=paciente.phone,
               nombre="Claudio", apellido="Luna")
    assert r.get("status") == "ok", r


def test_una_ficha_sin_telefono_no_se_adopta_al_agendar(db, clinica, silvestro):
    ficha = Patient(first_name="Ana", last_name="Gómez", dni="30111222", phone=None)
    db.add(ficha)
    db.commit()
    with pytest.raises(HTTPException) as e:
        _pedir(db, "30111222")
    assert e.value.status_code == 403
    db.refresh(ficha)
    assert not ficha.phone


def test_una_ficha_sin_telefono_no_se_adopta_al_consultar(db, clinica):
    ficha = Patient(first_name="Ana", last_name="Gómez", dni="30111222", phone="")
    db.add(ficha)
    db.commit()
    with pytest.raises(HTTPException) as e:
        resolver_paciente(db, "30111222", INTRUSO)
    assert e.value.status_code == 403
    db.refresh(ficha)
    assert not ficha.phone


def test_sin_telefono_verificado_un_dni_no_da_acceso(db, clinica, paciente):
    """Telegram no tiene número: con solo el DNI no se ven ni tocan turnos."""
    with pytest.raises(HTTPException) as e:
        resolver_paciente(db, paciente.dni, None)
    assert e.value.status_code == 403


@pytest.mark.parametrize("campo", ["patient_name", "patient_last_name", "reason"])
def test_el_bot_no_acepta_etiquetas_html(campo):
    """Lo que dicta el paciente se dibuja en el panel: no puede traer código."""
    from pydantic import ValidationError

    datos = {"reason": "Extracción", campo: '<img src=x onerror="alert(1)">'}
    with pytest.raises(ValidationError):
        BotAppointmentRequest(**datos)


def test_sin_telefono_verificado_no_agenda_en_una_ficha_ajena(db, clinica, silvestro, paciente):
    with pytest.raises(HTTPException) as e:
        bot_create_appointment(BotAppointmentRequest(
            patient_name="Claudio", patient_last_name="Luna", dni=paciente.dni,
            phone="2604999888", reason="Extracción", location="San Rafael",
            preferred_date=proximo_dia_habil().strftime("%Y-%m-%d %H:%M"),
        ), db=db)
    assert e.value.status_code == 403
