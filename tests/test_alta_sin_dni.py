"""Un paciente nuevo saca turno dando solo su nombre.

Conversación real del 25/08/2026:

    bot:      Para agendar el turno, necesito tu nombre, apellido y DNI.
    paciente: Maria Prueba
    bot:      Parece que es la primera vez que sacás turno con nosotros.
              Necesito tu DNI para crear tu ficha. ¿Me lo podés pasar?
    paciente: 101010
    bot:      El DNI que me diste parece tener 6 dígitos, pero un DNI argentino
              tiene 7 u 8. ¿Podrías verificarlo?

Tres mensajes más por un dato que el sistema no necesita para reservar: al
paciente lo identifica su número de WhatsApp, que además es más confiable que un
DNI (Meta verifica el número; un DNI lo sabe cualquiera).

El DNI sigue haciendo falta para facturarle a la obra social, pero eso lo
completa recepción cuando el paciente llega con el documento.
"""
from backend.models.patient import Patient
from backend.services.appointment_service import create_appointment_logic
from conftest import proximo_dia_habil


def _agendar(db, nombre, apellido, telefono, dni="", hora=10):
    # Cada alta en un horario distinto: si no, la segunda choca contra la
    # proteccion de doble reserva y el test mide otra cosa.
    return create_appointment_logic(
        db, nombre, apellido, dni, "", "Limpieza", "San Rafael",
        insurance_name="Particular",
        preferred_date=proximo_dia_habil().replace(hour=hora).strftime("%Y-%m-%d %H:%M"),
        requester_phone=telefono,
    )


def test_se_agenda_sin_dni(db, clinica, silvestro):
    r = _agendar(db, "Maria", "Prueba", "+5492604999111")
    assert r.get("status") == "ok", r


def test_la_ficha_queda_creada_y_marcada_como_incompleta(db, clinica, silvestro):
    _agendar(db, "Maria", "Prueba", "+5492604999111")

    p = db.query(Patient).filter(Patient.first_name == "Maria").first()
    assert p is not None, "No se creó la ficha"
    assert p.dni is None, "Recepción tiene que ver que falta el DNI"
    assert p.phone == "+5492604999111"


def test_dos_pacientes_sin_dni_no_chocan_entre_si(db, clinica, silvestro):
    """En PostgreSQL un UNIQUE admite varios NULL; conviene comprobarlo."""
    assert _agendar(db, "Maria", "Prueba", "+5492604999111", hora=10).get("status") == "ok"
    assert _agendar(db, "Jose", "Gomez", "+5492604999222", hora=11).get("status") == "ok"
    assert db.query(Patient).filter(Patient.dni.is_(None)).count() == 2


def test_el_mismo_paciente_sin_dni_no_se_duplica(db, clinica, silvestro):
    """Vuelve a escribir otro día: es la misma persona, no una ficha nueva."""
    _agendar(db, "Maria", "Prueba", "+5492604999111")
    antes = db.query(Patient).count()

    r = create_appointment_logic(
        db, "Maria", "Prueba", "", "", "Control", "San Rafael",
        insurance_name="Particular",
        preferred_date=proximo_dia_habil().replace(hour=12).strftime("%Y-%m-%d %H:%M"),
        requester_phone="+5492604999111",
    )
    assert r.get("status") == "ok", r
    assert db.query(Patient).count() == antes, "Se duplicó la ficha"


def test_recepcion_puede_completar_el_dni_despues(db, clinica, silvestro):
    _agendar(db, "Maria", "Prueba", "+5492604999111")
    p = db.query(Patient).filter(Patient.first_name == "Maria").first()

    p.dni = "40111222"
    db.commit()
    db.refresh(p)
    assert p.dni == "40111222"


def test_el_dni_sigue_funcionando_cuando_lo_dan(db, clinica, silvestro):
    """Quien lo escribe igual, o los que ya estaban cargados, no cambian."""
    r = _agendar(db, "Jose", "Gomez", "+5492604999333", dni="30111222")
    assert r.get("status") == "ok", r
    assert db.query(Patient).filter(Patient.dni == "30111222").first() is not None


def test_un_paciente_ya_cargado_con_dni_se_reconoce(db, clinica, silvestro, paciente):
    from backend.models.appointment import Appointment

    r = _agendar(db, "Claudio", "Luna", paciente.phone, dni=paciente.dni)
    assert r.get("status") == "ok", r
    a = db.query(Appointment).filter(Appointment.id == r["appointment_id"]).first()
    assert a.patient_id == paciente.id
