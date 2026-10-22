"""Pruebas de preservación: fijan cómo funciona HOY lo que no puede romperse.

Tanda 1 del relevamiento (21/10/2026). No cambian comportamiento: si alguna
falla después de un cambio, el cambio alteró una regla vigente y tiene que
discutirse antes, no ajustarse el test.

Las que documentan algo que se sabe mejorable llevan "documenta" en el nombre:
fijan el comportamiento actual para que cambiarlo sea una decisión visible.
"""
import os
from datetime import timedelta

import pytest

from backend.models.config import AppConfig
from backend.services.appointment_service import (
    create_appointment_logic,
    get_chairs_per_location,
    slot_conflict,
)
from conftest import proximo_dia_habil, turno

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _agendar(db, paciente, cuando, motivo):
    return create_appointment_logic(
        db, paciente.first_name, paciente.last_name, paciente.dni, "",
        motivo, "San Rafael", insurance_name="Particular",
        preferred_date=cuando.strftime("%Y-%m-%d %H:%M"),
        requester_phone=paciente.phone,
    )


# ── Un solo sillón compartido (regla confirmada por Claudio) ────────────────

def test_sillon_sin_configurar_vale_uno(db):
    assert get_chairs_per_location(db) == 1


@pytest.mark.parametrize("valor", ["", "abc", "0", "-3"])
def test_sillon_con_valor_invalido_vale_uno(db, valor):
    db.add(AppConfig(key="CHAIRS_PER_LOCATION", value=valor))
    db.commit()
    assert get_chairs_per_location(db) == 1


def test_otro_profesional_no_entra_si_se_pisa_el_intervalo(
    db, clinica, silvestro, murad, paciente, otro_paciente
):
    """Murad con conducto de 1 h a las 10:00: Silvestro no puede atender a las
    10:30 aunque esté libre. Distinto profesional y distinto horario de inicio."""
    cuando = proximo_dia_habil()
    turno(db, paciente, murad, cuando, duracion=60, reason="Conducto")

    r = _agendar(db, otro_paciente, cuando + timedelta(minutes=30), "Extracción")
    assert "error" in r, f"Un solo sillón: no entra un turno a las 10:30: {r}"


def test_tampoco_si_termina_adentro_del_otro(
    db, clinica, silvestro, murad, paciente, otro_paciente
):
    """Extracción de 30' a las 9:45 termina 10:15, encima del turno de 10:00."""
    cuando = proximo_dia_habil()
    turno(db, paciente, murad, cuando, duracion=60, reason="Conducto")

    r = _agendar(db, otro_paciente, cuando - timedelta(minutes=15), "Extracción")
    assert "error" in r, f"Se pisa el final con el inicio del otro: {r}"


def test_turnos_contiguos_si_entran(db, clinica, silvestro, paciente, otro_paciente):
    """No sobre-bloquear: 10:00-10:30 y 10:30 en adelante no se pisan."""
    cuando = proximo_dia_habil()
    turno(db, paciente, silvestro, cuando, duracion=30, reason="Extracción")

    r = _agendar(db, otro_paciente, cuando + timedelta(minutes=30), "Extracción")
    assert r.get("status") == "ok", f"Contiguo debería entrar: {r}"


def test_slot_conflict_mira_el_intervalo_completo(db, clinica, silvestro, paciente):
    cuando = proximo_dia_habil()
    existente = turno(db, paciente, silvestro, cuando, duracion=60, reason="Conducto")
    adentro = cuando + timedelta(minutes=45)
    assert slot_conflict([existente], adentro, 15, chairs=1) is not None
    assert slot_conflict([existente], cuando + timedelta(minutes=60), 15, chairs=1) is None


# ── Lo ya corregido en 6fe641d y f29baab ────────────────────────────────────

def _compose():
    with open(os.path.join(RAIZ, "docker-compose.yml"), encoding="utf-8") as f:
        return f.read()


def test_compose_no_publica_puertos():
    lineas = [l.strip() for l in _compose().splitlines() if not l.strip().startswith("#")]
    assert not any(l.startswith("ports:") for l in lineas)


def test_compose_exige_la_clave_de_postgres():
    c = _compose()
    assert "${POSTGRES_PASSWORD:?" in c
    assert "${DATABASE_URL:?" in c


def test_telegram_apagado_por_defecto():
    assert 'profiles: ["telegram"]' in _compose()


def test_dockerignore_deja_afuera_los_backups():
    with open(os.path.join(RAIZ, ".dockerignore"), encoding="utf-8") as f:
        entradas = {l.strip().strip("/") for l in f if l.strip()}
    assert {"backups", "imagenes-turnos"} <= entradas


def test_cors_por_defecto_no_tiene_el_dominio_vencido():
    with open(os.path.join(RAIZ, "backend", "main.py"), encoding="utf-8") as f:
        assert "aiporvos" not in f.read()


# ── Recordatorios apagados a propósito (05/10) ──────────────────────────────

def test_recordatorios_siguen_apagados():
    with open(os.path.join(RAIZ, "backend", "main.py"), encoding="utf-8") as f:
        activas = [l for l in f if "start_reminders_loop" in l and not l.lstrip().startswith("#")]
    assert activas == [], "Los recordatorios no se reactivan sin plantilla aprobada y OK de Claudio"


# ── Comportamiento vigente que se sabe mejorable (no cambiar sin aprobación) ─

@pytest.mark.parametrize("guardado, escribe", [
    ("+5492604590071", "2604590071"), ("+5492604590071", "02604590071"),
    ("2604590071", "5492604590071@s.whatsapp.net"), ("+54 9 260 459-0071", "+5492604590071"),
])
def test_telefono_variantes_del_mismo_numero(guardado, escribe):
    from backend.routers.bot_routes import _phones_match
    assert _phones_match(guardado, escribe)


@pytest.mark.parametrize("guardado, escribe", [
    ("+5511904590071", "+5492604590071"),     # otro país, mismos 8 finales
    ("+5492614590071", "+5492604590071"),     # otra área
    ("4590071", "+5492604590071"),            # sin característica: no alcanza
])
def test_telefono_distinto_no_coincide(guardado, escribe):
    """Antes bastaban los últimos 8 dígitos (tanda 2, 22/10: ahora 10)."""
    from backend.routers.bot_routes import _phones_match
    assert not _phones_match(guardado, escribe)


def test_sin_base_no_se_inventan_datos(monkeypatch):
    """Antes, con la base caída, el prompt recibía un horario viejo, OSDE como
    cubierta y "San Rafael" como dirección (corregido 22/10)."""
    from bot import ai_agent

    class Rota:
        def query(self, *a, **k):
            raise RuntimeError("base caida")

        def close(self):
            pass

    monkeypatch.setattr(ai_agent, "SessionLocal", lambda: Rota())
    assert ai_agent.get_horarios_texto() == ai_agent.SIN_DATO
    assert ai_agent.get_active_insurances() == []
    assert ai_agent.get_sedes_texto() == ai_agent.SIN_DATO
