"""El motivo lo dice el paciente, no lo deduce el bot.

Regla del consultorio, textual:

    "de eso nunca suponer sino averiguar siempre primero que se va a tratar y
     luego le da el turno"

De ahí salen la duración del turno y a qué profesional va: un control son 15
minutos con cualquiera, un conducto son 60 con Elena. Suponer mal le desarma la
agenda a la clínica y le hace perder el turno al paciente.

Había dos agujeros. El primero —ofrecer horarios sin motivo— se cerró exigiendo
que estuviera registrado. Quedaba el segundo: el propio modelo podía
registrarlo por su cuenta, sin que el paciente hubiera dicho nada.

La verificación no puede ser una búsqueda literal: el paciente dice "sacarme una
muela" y el modelo lo registra como "Extracción", que es exactamente lo
correcto. Se compara contra los tipos de consulta y sus sinónimos, que la
clínica edita desde el panel.
"""
import pytest
from fastapi.testclient import TestClient

from backend.models.tipo_consulta import TipoConsulta

TIPOS = [
    ("Control", 15, None, ["control", "revision", "chequeo", "duele"]),
    ("Limpieza", 15, "Limpieza", ["limpiar", "sarro", "profilaxis"]),
    ("Extracción", 30, "Extracción", ["sacar", "sacarme", "muela", "cordal"]),
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


# ── El modelo no puede inventar el motivo ───────────────────────────────────

def test_rechaza_un_motivo_que_el_paciente_nunca_dijo(cliente):
    d = _resolver(cliente, "control", ["hola", "quiero un turno", "OSDE"])
    assert d["ok"] is False


def test_acepta_el_motivo_que_el_paciente_dijo(cliente):
    d = _resolver(cliente, "limpieza", ["hola", "necesito una limpieza"])
    assert d["ok"] is True
    assert d["motivo"] == "Limpieza"


def test_entiende_que_sacarse_una_muela_es_una_extraccion(cliente):
    """El caso que importa: el modelo normaliza y no por eso está inventando."""
    d = _resolver(cliente, "Extracción", ["necesito sacarme una muela", "OSDE"])
    assert d["ok"] is True
    assert d["motivo"] == "Extracción"
    assert d["duracion"] == 30


def test_devuelve_el_nombre_canonico(cliente):
    """Así el turno queda guardado siempre con el mismo texto."""
    d = _resolver(cliente, "me tienen que matar el nervio", ["me tienen que matar el nervio"])
    assert d["ok"] is True
    assert d["motivo"] == "Conducto"
    assert d["duracion"] == 60


def test_no_confunde_dos_tipos_distintos(cliente):
    """Dijo que quería una limpieza; el modelo no puede registrarle un conducto."""
    d = _resolver(cliente, "conducto", ["quiero una limpieza"])
    assert d["ok"] is False


def test_lo_reconoce_aunque_lo_haya_dicho_hace_varios_mensajes(cliente):
    d = _resolver(cliente, "Extracción",
                  ["necesito sacarme una muela", "OSDE", "sí", "a la tarde"])
    assert d["ok"] is True


def test_tolera_tildes(cliente):
    d = _resolver(cliente, "extraccion", ["tengo que hacerme una extracción"])
    assert d["ok"] is True


def test_sin_nada_dicho_no_bloquea(cliente):
    """Telegram no siempre tiene los mensajes previos: ante la duda se deja pasar."""
    d = _resolver(cliente, "limpieza", [])
    assert d["ok"] is True


def test_un_motivo_vacio_se_rechaza(cliente):
    assert _resolver(cliente, "", ["quiero un turno"])["ok"] is False


def test_requiere_la_key_del_bot(cliente):
    r = cliente.post("/api/bot/resolver-motivo",
                     json={"motivo": "limpieza", "dichos": []},
                     headers={"x-bot-key": "clave-que-no-es"})
    assert r.status_code == 403
