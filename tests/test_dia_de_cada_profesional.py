"""Que el bot sepa qué días atiende cada uno, y lo diga.

Conversación real del 10/09/2026, y el reclamo textual:

    "debe tener en cuenta qué día atiende cada uno y si piden para otro día que
     no atiende decirlo y ofrecerle el próximo turno libre que tiene. No debe
     dar turnos para los días que no corresponden a cada uno de ellos."

Lo que pasó:

    paciente: quiero un turno con Murad para el jueves
    paciente: extraccion
    bot:      no hay disponibilidad para extracción el martes 15... pero tengo
              turnos para el miércoles 16 a las 10:30, 11:30 o 12:00
    paciente: y para silvestro el lunes??
    bot:      Dejame que lo verifique bien y te confirmo en un momento.
              [y nunca llegó nada]

Tres cosas: el martes 15 no era el día pedido ni ninguno relacionado, el
miércoles no es día de Murad, y la última respuesta fue una promesa que no se
cumplía nunca. El log muestra que para el último mensaje no hubo NINGUNA
consulta: el modelo inventó 10:00 y 11:00 y la barrera lo frenó, dejando al
paciente esperando.
"""
from datetime import date, datetime, timedelta

import pytest

from backend.services.appointment_service import fecha_dicha_por_el_paciente


JUEVES = datetime(2026, 9, 10, 8, 30)   # jueves 10/09/2026


# ── La fecha sale del texto del paciente, no de la aritmética del modelo ──

@pytest.mark.parametrize("dicho,esperada", [
    ("quiero un turno con Murad para el jueves", date(2026, 9, 17)),
    ("y para silvestro el lunes??", date(2026, 9, 14)),
    ("el viernes", date(2026, 9, 11)),
    ("hoy", date(2026, 9, 10)),
    ("mañana", date(2026, 9, 11)),
    ("pasado mañana", date(2026, 9, 12)),
    ("el 16", date(2026, 9, 16)),
    ("16/09", date(2026, 9, 16)),
    ("16 de septiembre", date(2026, 9, 16)),
])
def test_reconoce_el_dia_que_pidio(dicho, esperada):
    assert fecha_dicha_por_el_paciente(dicho, JUEVES) == esperada


@pytest.mark.parametrize("dicho", [
    "a la mañana",          # es una franja, no el día de mañana
    "por la mañana",
    "quiero un turno",
    "extraccion",
    "",
])
def test_no_inventa_una_fecha(dicho):
    assert fecha_dicha_por_el_paciente(dicho, JUEVES) is None


def test_el_mismo_dia_de_la_semana_es_el_de_la_proxima(JUEVES=JUEVES):
    """Hoy es jueves: "el jueves" es el que viene, no hoy."""
    assert fecha_dicha_por_el_paciente("el jueves", JUEVES) == date(2026, 9, 17)


# ── El día que no es del profesional se salta, y se explica ───────────────

@pytest.fixture
def grillas(db, silvestro, murad):
    """Murad lunes/martes/viernes, Silvestro miércoles/jueves/viernes."""
    import uuid
    from datetime import time as py_time
    from backend.models.schedule import ProfessionalSchedule

    def franjas(prof, dias):
        for d in dias:
            db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=prof.id,
                                        weekday=d, start_time=py_time(9, 0),
                                        end_time=py_time(12, 30), is_active=True))
            if d != 2:
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


def test_no_ofrece_a_murad_un_miercoles(db, clinica, grillas, murad):
    """El caso reportado: Murad no atiende miércoles."""
    from backend.services.appointment_service import get_available_slots

    r = get_available_slots(db, _proximo(2).date().isoformat(), "San Rafael",
                            "Extracción", profesional_pedido="Murad")
    if r["available_slots"]:
        elegido = datetime.fromisoformat(r["date"]).weekday()
        assert elegido in (0, 1, 4), (
            f"Ofreció a Murad el {r['fecha_texto']}, que no es día suyo"
        )


def test_al_saltar_el_dia_dice_cuales_atiende(db, clinica, grillas, silvestro):
    """Lo que el paciente necesita saber para elegir otro día."""
    from backend.services.appointment_service import get_available_slots

    r = get_available_slots(db, _proximo(0).date().isoformat(), "San Rafael",
                            "Extracción", profesional_pedido="Silvestro")
    motivo = (r.get("motivo_salto") or "").lower()
    assert "silvestro" in motivo
    assert "no atiende" in motivo
    assert "miércoles" in motivo, f"No dice qué días atiende: {motivo!r}"


# ── Si ese profesional no hace ese tratamiento, decir quién sí ────────────
# "quiero un turno con Murad" + "extracción": ella no hace extracciones, las
# hace Silvestro. Decir solo "no atiende Extracción" deja al paciente sin saber
# qué hacer, y el modelo terminaba inventando una respuesta.

def test_dice_quien_hace_ese_tratamiento(db, clinica, grillas, silvestro, murad):
    from backend.services.appointment_service import get_available_slots

    r = get_available_slots(db, _proximo(3).date().isoformat(), "San Rafael",
                            "Extracción", profesional_pedido="Murad")
    mensaje = r.get("message") or ""
    assert "no hace Extracción" in mensaje
    assert "Silvestro" in mensaje, f"No dice quién sí lo hace: {mensaje!r}"
    assert r["available_slots"] == [], "No puede ofrecer horarios sin que lo acepte"


def test_no_cambia_de_profesional_por_su_cuenta(db, clinica, grillas, silvestro, murad):
    """Cambiar de profesional es una decisión del paciente, no del sistema."""
    from backend.services.appointment_service import get_available_slots

    r = get_available_slots(db, _proximo(3).date().isoformat(), "San Rafael",
                            "Extracción", profesional_pedido="Murad")
    assert "PROHIBIDO ofrecerle horarios sin que lo acepte" in (r.get("message") or "")


def test_lo_que_si_hace_se_busca_normal(db, clinica, grillas, silvestro, murad):
    from backend.services.appointment_service import get_available_slots

    r = get_available_slots(db, _proximo(0).date().isoformat(), "San Rafael",
                            "Ortodoncia", profesional_pedido="Murad")
    assert "Murad" in (r.get("professional") or ""), r
