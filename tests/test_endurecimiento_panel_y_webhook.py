"""Claves solo en el entorno, webhook cerrado sin secreto y /docs apagado."""
import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException

from backend.models.config import AppConfig
from backend.routers import whatsapp_router as er
from backend.routers.admin import admin_routes as ar
from backend.schemas.schemas import ConfigCreate


# ── Claves: solo en el entorno ──────────────────────────

def test_el_codigo_nunca_lee_claves_de_la_base(db, monkeypatch):
    from backend.services.config import get_config
    db.add(AppConfig(key="OPENAI_API_KEY", value="vieja-de-la-base"))
    db.add(AppConfig(key="OPENAI_MODEL", value="gpt-4.1-mini"))
    db.commit()
    monkeypatch.setenv("OPENAI_API_KEY", "  la-del-entorno\n")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    assert get_config("OPENAI_API_KEY", db=db) == "la-del-entorno"
    # Lo operativo sigue mandando desde el panel.
    assert get_config("OPENAI_MODEL", db=db) == "gpt-4.1-mini"


def test_el_panel_no_lista_claves(db):
    db.add(AppConfig(key="YCLOUD_API_KEY", value="no-deberia-estar"))
    db.add(AppConfig(key="OPENAI_MODEL", value="gpt-4o-mini"))
    db.commit()

    keys = {c.key for c in ar.list_configs(db)}

    assert "YCLOUD_API_KEY" not in keys
    assert "OPENAI_MODEL" in keys


def test_el_panel_no_acepta_claves(db):
    with pytest.raises(HTTPException) as e:
        ar.set_configs_bulk({"OPENAI_MODEL": "x", "OPENAI_API_KEY": "sk-nueva"}, db)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException):
        ar.set_config(ConfigCreate(key="YCLOUD_WEBHOOK_SECRET", value="x"), db)
    assert db.query(AppConfig).filter_by(key="OPENAI_API_KEY").count() == 0


def test_estado_de_claves_sin_valores(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secreta")
    monkeypatch.delenv("YCLOUD_API_KEY", raising=False)

    estado = ar.estado_claves()

    assert estado["OPENAI_API_KEY"] is True
    assert estado["YCLOUD_API_KEY"] is False
    assert "sk-secreta" not in str(estado)


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
