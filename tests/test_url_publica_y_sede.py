"""El link de cancelación tiene que funcionar, y el bot saber dónde queda.

Los dos salen del mismo recordatorio real, del 25/08/2026:

    Hola Axel, te recordamos tu turno en Silprodent el 26/08/2026 a las 10:00...
    Si no podés asistir, cancelálo en el siguiente link:
    http://localhost:8000/api/public/cancel/2c8433df-...

Nadie puede cancelar desde localhost. Y el paciente que no puede cancelar falta
sin avisar, que es exactamente lo que el recordatorio existe para evitar.

Cinco minutos después, otra paciente preguntó "¿en dónde queda Silprodent?" y el
bot contestó "está ubicada en San Rafael" — la ciudad entera. La dirección
estaba cargada en la base y no se le pasaba al modelo.
"""
import os

import pytest

from backend.models.clinic_location import ClinicLocation
from backend.models.config import AppConfig
from backend.services.urls import link_de_cancelacion, url_publica


@pytest.fixture(autouse=True)
def sin_variables(monkeypatch):
    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)


# ── La URL pública ──────────────────────────────────────────────────────────

def test_usa_la_configurada_en_el_panel(db):
    db.add(AppConfig(key="PUBLIC_APP_URL", value="https://odobot.aiporvos.com"))
    db.commit()
    assert url_publica(db) == "https://odobot.aiporvos.com"


def test_usa_la_variable_de_entorno(db, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://odobot.aiporvos.com")
    assert url_publica(db) == "https://odobot.aiporvos.com"


def test_el_panel_le_gana_a_la_variable(db, monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://vieja.example.com")
    db.add(AppConfig(key="PUBLIC_APP_URL", value="https://odobot.aiporvos.com"))
    db.commit()
    assert url_publica(db) == "https://odobot.aiporvos.com"


def test_cae_en_allowed_origins_si_no_hay_nada_mas(db, monkeypatch):
    """En producción esa variable ya tiene el dominio bueno."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://odobot.aiporvos.com")
    assert url_publica(db) == "https://odobot.aiporvos.com"


def test_ignora_los_origenes_locales(db, monkeypatch):
    """El .env local lista localhost primero; no puede ganarle al dominio real."""
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8000,http://localhost:3000,https://odobot.aiporvos.com",
    )
    assert url_publica(db) == "https://odobot.aiporvos.com"


def test_saca_la_barra_final(db):
    db.add(AppConfig(key="PUBLIC_APP_URL", value="https://odobot.aiporvos.com/"))
    db.commit()
    assert url_publica(db) == "https://odobot.aiporvos.com"


def test_avisa_fuerte_si_queda_en_localhost(db, caplog):
    """Es el caso que salió a un paciente real: tiene que gritar en el log."""
    import logging
    with caplog.at_level(logging.ERROR):
        assert "localhost" in url_publica(db)
    assert any("no van a funcionar" in r.message.lower() or "PUBLIC_APP_URL" in r.message
               for r in caplog.records), "El fallback a localhost pasó en silencio"


def test_el_link_de_cancelacion_se_arma_completo(db):
    db.add(AppConfig(key="PUBLIC_APP_URL", value="https://odobot.aiporvos.com"))
    db.commit()
    link = link_de_cancelacion(db, "2c8433df-e092-4094-aba0-8a8c3a591cf4")
    assert link == (
        "https://odobot.aiporvos.com/api/public/cancel/2c8433df-e092-4094-aba0-8a8c3a591cf4"
    )


# ── La dirección de la clínica ──────────────────────────────────────────────

def test_el_bot_recibe_la_direccion_completa(db):
    from bot.ai_agent import get_sedes_texto

    db.query(ClinicLocation).delete()
    db.add(ClinicLocation(name="San Rafael", address="Moreno 374", phone="2604-123456"))
    db.commit()

    texto = get_sedes_texto()
    assert "Moreno 374" in texto, "Sigue sin poder decir la calle"
    assert "maps.google.com" in texto, "Sin link al mapa el paciente igual no sabe llegar"
    assert "2604-123456" in texto


def test_varias_sedes_van_todas(db):
    from bot.ai_agent import get_sedes_texto

    db.query(ClinicLocation).delete()
    db.add(ClinicLocation(name="San Rafael", address="Moreno 374"))
    db.add(ClinicLocation(name="Alvear", address="San Martín 100"))
    db.commit()

    texto = get_sedes_texto()
    assert "Moreno 374" in texto and "San Martín 100" in texto


def test_una_sede_sin_direccion_no_rompe(db):
    from bot.ai_agent import get_sedes_texto

    db.query(ClinicLocation).delete()
    db.add(ClinicLocation(name="San Rafael"))
    db.commit()
    assert "San Rafael" in get_sedes_texto()


def test_sin_sedes_cargadas_no_rompe(db):
    from bot.ai_agent import get_sedes_texto

    db.query(ClinicLocation).delete()
    db.commit()
    assert get_sedes_texto()
