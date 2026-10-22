"""Claves enmascaradas en el panel, webhook cerrado sin secreto y /docs apagado."""
import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException

from backend.models.config import AppConfig
from backend.routers import evolution_router as er
from backend.routers.admin import admin_routes as ar
from backend.schemas.schemas import ConfigCreate


# ── Claves de API en el panel ───────────────────────────

def test_el_panel_no_devuelve_claves_completas(db):
    db.add(AppConfig(key="OPENAI_API_KEY", value="sk-secreta-1234"))
    db.add(AppConfig(key="OPENAI_MODEL", value="gpt-4o-mini"))
    db.commit()

    configs = {c["key"]: c["value"] for c in ar.list_configs(db)}

    assert configs["OPENAI_API_KEY"] == ar.MASCARA + "1234"
    assert "sk-secreta" not in configs["OPENAI_API_KEY"]
    assert configs["OPENAI_MODEL"] == "gpt-4o-mini"


def test_guardar_con_la_mascara_conserva_la_clave(db):
    db.add(AppConfig(key="YCLOUD_API_KEY", value="clave-real-abcd"))
    db.commit()

    ar.set_configs_bulk({"YCLOUD_API_KEY": ar.MASCARA + "abcd", "OPENAI_MODEL": "x"}, db)
    ar.set_config(ConfigCreate(key="YCLOUD_API_KEY", value=ar.MASCARA + "abcd"), db)

    assert db.query(AppConfig).filter_by(key="YCLOUD_API_KEY").one().value == "clave-real-abcd"


def test_una_clave_nueva_si_se_guarda(db):
    db.add(AppConfig(key="GROQ_API_KEY", value="vieja"))
    db.commit()

    ar.set_configs_bulk({"GROQ_API_KEY": "nueva-9999"}, db)

    assert db.query(AppConfig).filter_by(key="GROQ_API_KEY").one().value == "nueva-9999"


# ── Webhook de YCloud ───────────────────────────────────

def _firmar(raw: bytes, secreto: str) -> str:
    ts = str(int(time.time()))
    s = hmac.new(secreto.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return f"t={ts},s={s}"


def test_sin_secreto_el_webhook_rechaza(monkeypatch):
    monkeypatch.delenv("YCLOUD_WEBHOOK_SECRET", raising=False)
    with pytest.raises(HTTPException) as e:
        er._autenticar_webhook(b"{}", None)
    assert e.value.status_code == 503


def test_el_panel_no_puede_apagar_la_verificacion(monkeypatch):
    """ENFORCE y el secreto salen del entorno: lo que haya en app_configs no cuenta."""
    monkeypatch.setenv("YCLOUD_WEBHOOK_SECRET", "secreto-del-entorno")
    monkeypatch.setenv("YCLOUD_WEBHOOK_ENFORCE", "true")
    monkeypatch.setattr(er, "get_config", lambda key, default="": "false")
    with pytest.raises(HTTPException) as e:
        er._autenticar_webhook(b"{}", None)
    assert e.value.status_code == 401


def test_con_firma_valida_pasa(monkeypatch):
    monkeypatch.setenv("YCLOUD_WEBHOOK_SECRET", "secreto-del-entorno")
    raw = b'{"type":"whatsapp.inbound_message.received"}'
    er._autenticar_webhook(raw, _firmar(raw, "secreto-del-entorno"))


# ── Documentación de la API ─────────────────────────────

def test_docs_apagados_por_defecto():
    from backend.main import app
    assert app.docs_url is None
    assert app.openapi_url is None


def test_cabeceras_de_seguridad(db):
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        h = c.get("/api/health").headers
    assert "connect-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY"
    assert h["x-content-type-options"] == "nosniff"
    assert "max-age" in h["strict-transport-security"]
