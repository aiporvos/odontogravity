"""Que el nombre de un profesional no se registre como motivo de consulta.

Conversación real del 10/09/2026:

    paciente: si quiero un turno
    paciente: para silverte
    bot:      Claro, ¿para qué motivo necesitás el turno y qué día te vendría bien?
    bot:      Perfecto, ya tengo el motivo. ¿Qué día te gustaría venir?

El paciente nunca dijo para qué era la consulta: dijo con QUIÉN quería
atenderse. El bot registró "silverte" como motivo y siguió adelante.

De eso depende cuánto dura el turno, así que el error no es cosmético: reserva
el tiempo equivocado.
"""
import pytest

from backend.routers.bot_routes import bot_resolver_motivo


def _resolver(db, motivo, dichos=None):
    return bot_resolver_motivo({"motivo": motivo, "dichos": dichos or []}, db=db)


# ── El caso reportado ───────────────────────────────────────────────────────

@pytest.mark.parametrize("como_lo_dijo", [
    "silvestro",
    "Silvestro",
    "para silvestro",
    "el doctor silvestro",
    "Dr. Silvestro",
    "murad",
    "la Dra. Murad",
])
def test_un_profesional_no_es_un_motivo(db, silvestro, murad, como_lo_dijo):
    r = _resolver(db, como_lo_dijo, ["si quiero un turno", como_lo_dijo])
    assert r["ok"] is False, f"Aceptó '{como_lo_dijo}' como motivo"
    assert r["motivo"] is None


def test_el_rechazo_explica_que_hacer(db, silvestro, murad):
    r = _resolver(db, "silvestro", ["para silvestro"])
    assert "no el motivo" in r["razon"]
    assert "profesional" in r["razon"]
    assert "PARA QUÉ" in r["razon"]


# ── Los motivos de verdad siguen andando ───────────────────────────────────

@pytest.mark.parametrize("motivo,dicho", [
    ("Limpieza", "quiero una limpieza"),
    ("Extracción", "necesito una extracción"),
    ("Control", "vengo para un control"),
])
# "sacarme una muela" → Extracción depende de los sinónimos que la clínica
# cargue en el panel, no del código: no se prueba acá.
def test_un_motivo_real_pasa(db, clinica, silvestro, murad, motivo, dicho):
    r = _resolver(db, motivo, [dicho])
    assert r["ok"] is True, r


def test_sin_motivo_sigue_rechazando(db, silvestro, murad):
    assert _resolver(db, "")["ok"] is False
