"""Que la suite se niegue a correr contra una base que no sea de pruebas.

Los tests borran el esquema. Antes, conftest resolvía la URL con
os.environ.setdefault("DATABASE_URL", ...): en una terminal donde alguien
hubiera exportado DATABASE_URL —a producción, por ejemplo— el setdefault no la
pisaba y el fixture `esquema` corría drop_all() sobre esa base.

Comprobado sobre una base descartable con una tabla `patients`: al terminar,
la tabla no existía y pytest había informado "11 passed". Verde mientras borra
pacientes.

Esto fija la defensa para que nadie la afloje sin darse cuenta.
"""
import pytest

from conftest import _exigir_base_de_pruebas


def _dentibot(nombre="dentibot_test", host="localhost"):
    return f"postgresql://usuario:clave@{host}:5432/{nombre}"


# ── Lo que sí puede correr ──────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    _dentibot("dentibot_test"),
    _dentibot("dentibot_test", "127.0.0.1"),
    _dentibot("pruebas_odonto"),
    _dentibot("test", "postgres"),          # el host del compose
    "postgresql://u:c@db:5432/algo_test",   # el host del compose
])
def test_acepta_una_base_de_pruebas(url):
    _exigir_base_de_pruebas(url)


# ── Lo que tiene que frenar ─────────────────────────────────────────────────

def test_rechaza_una_base_que_no_dice_ser_de_pruebas():
    with pytest.raises(RuntimeError) as e:
        _exigir_base_de_pruebas(_dentibot("dentibot"))
    assert "no parece de pruebas" in str(e.value)
    assert "dentibot" in str(e.value)


def test_rechaza_un_host_remoto():
    """El caso peligroso de verdad: la base del VPS."""
    with pytest.raises(RuntimeError) as e:
        _exigir_base_de_pruebas("postgresql://u:c@72.60.0.249:5432/dentibot_test")
    assert "host" in str(e.value)


def test_el_mensaje_dice_como_arreglarlo(monkeypatch):
    with pytest.raises(RuntimeError) as e:
        _exigir_base_de_pruebas(_dentibot("produccion"))
    assert "TEST_DATABASE_URL" in str(e.value)


def test_se_puede_ampliar_la_lista_para_un_runner_de_ci(monkeypatch):
    with pytest.raises(RuntimeError):
        _exigir_base_de_pruebas(_dentibot("dentibot_test", "postgres-ci"))
    monkeypatch.setenv("TEST_DB_ALLOWED_HOSTS", "postgres-ci, otro-runner")
    _exigir_base_de_pruebas(_dentibot("dentibot_test", "postgres-ci"))


def test_no_alcanza_con_el_host_si_el_nombre_no_lo_dice():
    """Las dos condiciones tienen que cumplirse."""
    with pytest.raises(RuntimeError):
        _exigir_base_de_pruebas(_dentibot("dentibot", "localhost"))
