"""Que no se parta el historial clinico de una persona en dos fichas.

En produccion aparecieron dos fichas de "Claudio Luna" con el mismo telefono y
DNIs distintos, y el historial quedo repartido entre las dos. Existe
scripts/unificar_pacientes_duplicados.py justamente para limpiar eso a mano.
El alta buscaba al paciente SOLO por DNI, asi que un digito distinto creaba una
persona nueva.

El limite del arreglo es el caso real de la familia: madre e hijo comparten el
numero de WhatsApp, y ahi si son dos personas distintas.
"""
from backend.models.patient import Patient
from backend.services.appointment_service import create_appointment_logic
from conftest import proximo_dia_habil


def _agendar(db, nombre, apellido, dni, telefono, motivo="Extracción"):
    return create_appointment_logic(
        db, nombre, apellido, dni, "", motivo, "San Rafael",
        insurance_name="Particular",
        preferred_date=proximo_dia_habil().strftime("%Y-%m-%d %H:%M"),
        requester_phone=telefono,
    )


def test_mismo_telefono_y_nombre_reutiliza_la_ficha(db, clinica, silvestro, paciente):
    """Claudio Luna con el DNI mal tipeado no debe crear una segunda ficha."""
    antes = db.query(Patient).count()

    r = _agendar(db, "Claudio", "Luna", "24785466", paciente.phone)  # un digito distinto
    assert r.get("status") == "ok", r
    assert db.query(Patient).count() == antes, "Se creo una ficha duplicada"


def test_el_turno_queda_colgado_de_la_ficha_original(db, clinica, silvestro, paciente):
    from backend.models.appointment import Appointment

    r = _agendar(db, "claudio", "LUNA", "99999999", paciente.phone)
    assert r.get("status") == "ok", r
    a = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert a.patient_id == paciente.id, "El historial quedo partido en otra ficha"


def test_el_orden_del_nombre_no_importa(db, clinica, silvestro, paciente):
    """"Luna Claudio" y "Claudio Luna" son la misma persona."""
    antes = db.query(Patient).count()
    r = _agendar(db, "Luna", "Claudio", "11112222", paciente.phone)
    assert r.get("status") == "ok", r
    assert db.query(Patient).count() == antes


def test_la_familia_sigue_siendo_gente_distinta(db, clinica, silvestro, paciente):
    """Mismo telefono pero otro nombre: es la madre, no un duplicado."""
    antes = db.query(Patient).count()

    r = _agendar(db, "Estela", "Pardo", "10203040", paciente.phone)
    assert r.get("status") == "ok", r
    assert db.query(Patient).count() == antes + 1, "Se fusiono a dos personas distintas"


def test_mismo_nombre_pero_otro_telefono_es_otra_persona(db, clinica, silvestro, paciente):
    """Dos homonimos que no comparten numero no se pueden unificar."""
    antes = db.query(Patient).count()
    r = _agendar(db, "Claudio", "Luna", "30303030", "+5492604999888")
    assert r.get("status") == "ok", r
    assert db.query(Patient).count() == antes + 1


def test_el_dni_correcto_sigue_mandando(db, clinica, silvestro, paciente):
    """Si el DNI coincide con una ficha, se usa esa sin mirar nada mas."""
    from backend.models.appointment import Appointment

    r = _agendar(db, "Otro", "Nombre", paciente.dni, "+5492604777666")
    assert r.get("status") == "ok", r
    a = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert a.patient_id == paciente.id
