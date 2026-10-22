"""Dos reservas al mismo tiempo no pueden pisarse en el único sillón.

Con profesionales distintos: el mismo profesional ya lo frena la base.

El índice único de la base solo frena dos turnos con el MISMO horario de
inicio. Dos pacientes que eligen 10:00 (60') y 10:30 al mismo tiempo pasaban
las dos validaciones antes de que cualquiera de los dos guardara.
"""
import threading
from datetime import timedelta

from backend.database import SessionLocal
from backend.models.appointment import Appointment, AppointmentStatus
from backend.services import appointment_service as svc
from conftest import proximo_dia_habil


def test_dos_reservas_que_se_pisan_al_mismo_tiempo(db, clinica, silvestro, murad, monkeypatch,
                                                  paciente, otro_paciente):
    cuando = proximo_dia_habil()
    # Datos copiados: los hilos no pueden tocar la sesión del test.
    datos = lambda p: (p.first_name, p.last_name, p.dni, p.phone)  # noqa: E731
    pedidos = [(datos(paciente), cuando, "Conducto"),
               (datos(otro_paciente), cuando + timedelta(minutes=30), "Extracción")]
    duraciones = {"Conducto": 60, "Extracción": 30}
    monkeypatch.setattr(svc, "duracion_para_motivo", lambda motivo, db=None: duraciones[motivo])
    # Profesionales DISTINTOS: el mismo profesional ya lo frena la base
    # (EXCLUDE por profesional). El sillón compartido no tenía barrera.
    murad.specialties = ["Endodoncia", "Conducto"]
    db.commit()

    # Los dos validan antes de que cualquiera guarde: así se fuerza la carrera.
    barrera = threading.Barrier(2)
    original = svc.profesional_libre

    def libre_y_esperar(*a, **k):
        r = original(*a, **k)
        try:
            barrera.wait(timeout=3)
        except threading.BrokenBarrierError:
            pass
        return r

    monkeypatch.setattr(svc, "profesional_libre", libre_y_esperar)
    resultados = []

    def reservar(pac, inicio, motivo):
        s = SessionLocal()
        try:
            nombre, apellido, dni, tel = pac
            resultados.append(svc.create_appointment_logic(
                s, nombre, apellido, dni, "", motivo, "San Rafael",
                insurance_name="Particular", preferred_date=inicio.strftime("%Y-%m-%d %H:%M"),
                requester_phone=tel,
            ))
        finally:
            s.close()

    hilos = [threading.Thread(target=reservar, args=p) for p in pedidos]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=20)

    ok = [r for r in resultados if r.get("status") == "ok"]
    assert len(resultados) == 2
    assert len(ok) == 1, f"Un solo sillón: entra una sola. Resultados: {resultados}"
    db.expire_all()
    activos = db.query(Appointment).filter(Appointment.status != AppointmentStatus.cancelled).count()
    assert activos == 1
