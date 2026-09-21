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


def _resolver(cliente, motivo, dichos):
    import os
    r = cliente.post(
        "/api/bot/resolver-motivo",
        json={"motivo": motivo, "dichos": dichos},
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


def test_api_acepta_realizar_conducto(cliente):
    d = _resolver(
        cliente,
        "Conducto",
        ["tratamiento de conducto", "para realizármelo ya"],
    )
    assert d["ok"] is True
    assert d["motivo"] == "Conducto"
    assert d["duracion"] == 60


def test_pregunta_incluye_los_dos_tiempos():
    assert "30 minutos" in PREGUNTA_CONDUCTO
    assert "1 hora" in PREGUNTA_CONDUCTO
