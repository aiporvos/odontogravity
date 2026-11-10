"""Conducto: siempre aclarar consulta 30' vs tratamiento 60'.

Pedido del consultorio (21/09/2026):

    "siempre si le piden para tratamiento de conducto debe preguntar si viene
     derivado y es para consulta (30 minutos) si es para realizarse ya el
     tratamiento de conducto 1h"

"tratamiento de conducto" a secas es ambiguo: casi todos lo dicen así.
"""
import pytest
from fastapi.testclient import TestClient

from backend.models.tipo_consulta import TipoConsulta
from backend.services.appointment_service import (
    PREGUNTA_CONDUCTO,
    duracion_para_motivo,
    resolver_ambiguiedad_conducto,
)

TIPOS = [
    ("Control", 15, None, ["control", "revision", "chequeo", "duele"]),
    ("Limpieza", 15, "Limpieza", ["limpiar", "sarro", "profilaxis"]),
    ("Extracción", 30, "Extracción", ["sacar", "sacarme", "muela", "cordal"]),
    ("Consulta por conducto", 30, "Endodoncia",
     ["consulta por conducto", "consulta conducto", "derivado conducto"]),
    ("Conducto", 60, "Endodoncia", ["conducto", "nervio", "endodoncia"]),
]


@pytest.fixture
def cliente(db):
    db.add_all([
        TipoConsulta(nombre=n, duracion_minutos=d, especialidad=e, sinonimos=s)
        for n, d, e, s in TIPOS
    ])
    db.commit()

    from backend.main import app
    with TestClient(app) as c:
        yield c


def _resolver(cliente, motivo, dichos, telefono=None):
    import os
    r = cliente.post(
        "/api/bot/resolver-motivo",
        json={"motivo": motivo, "dichos": dichos, "telefono": telefono},
        headers={"x-bot-key": os.environ["BOT_API_KEY"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ── Unidad: sin backend ─────────────────────────────────────────────────────

def test_conducto_a_secas_queda_bloqueado():
    r = resolver_ambiguiedad_conducto("tratamiento de conducto", ["quiero un conducto"])
    assert r["ok"] is False
    assert "30" in r["razon"] and "1 hora" in r["razon"]


def test_consulta_derivado_son_30_minutos():
    r = resolver_ambiguiedad_conducto(
        "Consulta por conducto",
        ["tratamiento de conducto", "sí, vengo derivado para consulta"],
    )
    assert r["ok"] is True
    assert r["motivo"] == "Consulta por conducto"
    assert r["duracion"] == 30


def test_realizar_el_tratamiento_son_60_minutos():
    r = resolver_ambiguiedad_conducto(
        "Conducto",
        ["necesito un conducto", "ya para hacerme el tratamiento"],
    )
    assert r["ok"] is True
    assert r["motivo"] == "Conducto"
    assert r["duracion"] == 60


def test_derivado_pero_para_realizarlo_gana_60():
    r = resolver_ambiguiedad_conducto(
        "Conducto",
        ["me derivaron para hacerme el conducto"],
    )
    assert r["ok"] is True
    assert r["motivo"] == "Conducto"
    assert r["duracion"] == 60


def test_limpieza_no_dispara_la_regla():
    assert resolver_ambiguiedad_conducto("Limpieza", ["quiero una limpieza"]) is None


def test_duracion_hardcodeada_distingue():
    assert duracion_para_motivo("Consulta por conducto") == 30
    assert duracion_para_motivo("Conducto") == 60


# ── API: resolver-motivo ────────────────────────────────────────────────────

def test_api_rechaza_conducto_ambiguo(cliente):
    d = _resolver(cliente, "Conducto", ["quiero un tratamiento de conducto"])
    assert d["ok"] is False
    assert "derivado" in d["razon"].lower() or "consulta" in d["razon"].lower()


def test_api_acepta_consulta_por_conducto(cliente):
    d = _resolver(
        cliente,
        "Consulta por conducto",
        ["turno para conducto", "es para consulta, me derivaron"],
    )
    assert d["ok"] is True
    assert d["motivo"] == "Consulta por conducto"
    assert d["duracion"] == 30


# Pedido del consultorio, 10/11/2026: el tratamiento (60') solo despues de la
# consulta por conducto (30'), venga derivado o no.
TEL = "5492604111222"


def _con_consulta_previa(db, dias=-7, estado=None, motivo="Consulta por conducto"):
    from datetime import datetime, timedelta
    from backend.models.appointment import Appointment, AppointmentStatus
    from backend.models.patient import Patient
    from backend.models.professional import Professional
    pac = Patient(first_name="Ana", last_name="Paz", phone=TEL)
    pro = Professional(full_name="Dra. Prueba", license_number="MP-TEST-1", specialties=["Endodoncia"], locations=[])
    db.add_all([pac, pro]); db.flush()
    db.add(Appointment(patient_id=pac.id, professional_id=pro.id, reason=motivo,
                       start_time=datetime.now() + timedelta(days=dias),
                       status=estado or AppointmentStatus.completed))
    db.commit()


def test_api_sin_consulta_previa_no_da_el_tratamiento(cliente):
    from backend.services.appointment_service import RAZON_SIN_CONSULTA_PREVIA
    d = _resolver(cliente, "Conducto", ["tratamiento de conducto", "para realizármelo ya"], TEL)
    assert d["ok"] is False
    assert d["razon"] == RAZON_SIN_CONSULTA_PREVIA


def test_api_derivado_para_hacerse_el_conducto_igual_va_a_consulta(cliente):
    d = _resolver(cliente, "Conducto", ["me derivaron para hacerme el conducto"], TEL)
    assert d["ok"] is False, "Venga derivado o no, primero la consulta de 30'"


def test_api_con_consulta_previa_da_el_tratamiento(cliente, db):
    _con_consulta_previa(db)
    d = _resolver(cliente, "Conducto", ["tratamiento de conducto", "Ya hice la consulta"], TEL)
    assert d["ok"] is True
    assert d["motivo"] == "Conducto"
    assert d["duracion"] == 60


@pytest.mark.parametrize("dias,estado,motivo", [
    (+3, None, "Consulta por conducto"),        # todavia no paso
    (-7, "cancelled", "Consulta por conducto"),  # se cancelo
    (-7, None, "Limpieza"),                      # otra cosa
])
def test_api_lo_que_no_cuenta_como_consulta_previa(cliente, db, dias, estado, motivo):
    from backend.models.appointment import AppointmentStatus
    _con_consulta_previa(db, dias, AppointmentStatus(estado) if estado else None, motivo)
    d = _resolver(cliente, "Conducto", ["conducto", "Ya hice la consulta"], TEL)
    assert d["ok"] is False


def test_api_sin_telefono_no_da_el_tratamiento(cliente, db):
    _con_consulta_previa(db)
    d = _resolver(cliente, "Conducto", ["conducto", "Ya hice la consulta"], None)
    assert d["ok"] is False


def test_pregunta_incluye_los_dos_tiempos():
    assert "30 minutos" in PREGUNTA_CONDUCTO
    assert "1 hora" in PREGUNTA_CONDUCTO


# ── Respuestas cortas a la pregunta resuelven (plan E2) ─────────────────────
# El bot pregunta "¿consulta (30 min) o tratamiento (1 hora)?". Una respuesta
# de una o dos palabras tiene que alcanzar; si no, se repregunta y es un loop.

@pytest.mark.parametrize("respuesta,motivo,minutos", [
    ("Ya hice la consulta", "Conducto", 60),
    ("sí", "Conducto", 60),
    ("si, ya la hice", "Conducto", 60),
    ("ya", "Conducto", 60),
    ("tratamiento", "Conducto", 60),
    ("el tratamiento", "Conducto", 60),
    ("una hora", "Conducto", 60),
    ("1 hora", "Conducto", 60),
    ("60", "Conducto", 60),
    ("ya para hacérmelo", "Conducto", 60),
    ("Necesito la consulta", "Consulta por conducto", 30),
    ("no", "Consulta por conducto", 30),
    ("todavía no", "Consulta por conducto", 30),
    ("consulta", "Consulta por conducto", 30),
    ("vengo derivado", "Consulta por conducto", 30),
    ("30", "Consulta por conducto", 30),
    ("media hora", "Consulta por conducto", 30),
    ("evaluación", "Consulta por conducto", 30),
])
def test_respuesta_corta_resuelve(respuesta, motivo, minutos):
    r = resolver_ambiguiedad_conducto(
        "Conducto",
        ["quiero un turno para tratamiento de conducto", respuesta],
    )
    assert r["ok"] is True, r
    assert r["motivo"] == motivo
    assert r["duracion"] == minutos


def test_una_respuesta_corta_que_no_aclara_sigue_preguntando():
    r = resolver_ambiguiedad_conducto(
        "Conducto", ["tratamiento de conducto", "el jueves"],
    )
    assert r["ok"] is False


def test_tratamiento_en_la_frase_larga_inicial_no_alcanza():
    """'quiero un tratamiento de conducto' es la frase ambigua de siempre."""
    r = resolver_ambiguiedad_conducto(
        "Conducto", ["quiero un tratamiento de conducto para el jueves"],
    )
    assert r["ok"] is False


def test_los_botones_se_reconocen_sin_pasar_por_el_modelo():
    from bot.tools.appointment_tools import motivo_por_boton_conducto
    assert motivo_por_boton_conducto("Ya hice la consulta") == "Conducto"
    assert motivo_por_boton_conducto("Necesito la consulta") == "Consulta por conducto"
    assert motivo_por_boton_conducto("si") is None
    assert motivo_por_boton_conducto("consulta") is None, "Texto libre va por el modelo"


# ── Simulación con IA real, 22/10: el modelo pregunta por su cuenta, mal ──────

@pytest.mark.parametrize("parafraseo", [
    "¡Buen día! 😊 Para el tratamiento de conducto, ¿venís derivado o es para una consulta de evaluación?",
    "¿Vení derivado? ¿Es para una consulta de evaluación o ya para realizar el tratamiento de conducto?",
])
def test_la_pregunta_mal_armada_se_repone_con_tiempos_y_botones(monkeypatch, parafraseo):
    from bot import ai_agent
    from bot.tools import appointment_tools as tools
    from backend.services.appointment_service import (
        PREGUNTA_CONDUCTO_PACIENTE, BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO,
    )
    from tests.test_no_confirmar_lo_que_no_se_hizo import _Cliente, _Mensaje

    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda p: (_Cliente([_Mensaje(parafraseo)]), "modelo-de-prueba"))
    monkeypatch.setattr(ai_agent, "corregir_apellidos", lambda t: t)
    texto, opciones, _ = ai_agent.chat("Necesito un turno para un conducto", [], "5492604046245", {})
    assert texto == PREGUNTA_CONDUCTO_PACIENTE
    assert opciones and opciones.get("opciones") == [BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO]


def test_con_el_motivo_ya_resuelto_no_se_vuelve_a_preguntar(monkeypatch):
    from bot import ai_agent
    from tests.test_no_confirmar_lo_que_no_se_hizo import _Cliente, _Mensaje
    texto_modelo = "Perfecto, la consulta por conducto es de 30 minutos. ¿Qué día te viene bien?"
    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda p: (_Cliente([_Mensaje(texto_modelo)]), "modelo-de-prueba"))
    monkeypatch.setattr(ai_agent, "corregir_apellidos", lambda t: t)
    texto, _, _ = ai_agent.chat("vengo derivado para un conducto", [], "5492604046245",
                                {"motivo": "Consulta por conducto"})
    assert texto == texto_modelo
