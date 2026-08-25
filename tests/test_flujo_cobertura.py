"""Elegir la cobertura en dos escalones, sin escribir nombres largos.

Diseño pedido por el consultorio: primero preguntar si es obra social o
particular, y solo si es obra social mostrar un listado; si la suya no está,
que escriba las primeras letras y se muestre un listado nuevo.

El detalle que obliga al escalonado es del mercado argentino: casi todas las
obras sociales empiezan con "OS". En esta clínica hay **12** con ese prefijo, y
una lista de WhatsApp admite **10 filas**. Con dos letras fijas, el caso más
común es justamente el que desborda, y el paciente ve una lista que no lo
contiene sin saber qué hacer.

Por eso la respuesta depende de cuántas coincidencias haya, y nunca deja al
paciente sin salida.
"""
import pytest
from fastapi.testclient import TestClient

from backend.models.insurance import Insurance
from backend.services.appointment_service import buscar_obras_sociales

# Las 12 con prefijo "os" que tiene la clínica, más otras.
NOMBRES = [
    "OSDE", "OSEP", "OSPE", "OSPELSYM", "OSPRERA", "OSPACA", "OSPIM",
    "OSPIA", "OSMATA", "OSECAC", "OSPAT", "OSPICA",
    "Swiss Medical", "Medifé", "Galeno", "Omint", "PAMI", "Particular",
]


@pytest.fixture
def muchas(db):
    db.query(Insurance).delete()
    db.add_all([Insurance(name=n, is_active=True) for n in NOMBRES])
    db.commit()


@pytest.fixture
def cliente(db, muchas):
    from backend.main import app
    with TestClient(app) as c:
        yield c


def _listar(cliente, q=None):
    import os
    r = cliente.get("/api/bot/obras-sociales", params={"q": q} if q else None,
                    headers={"x-bot-key": os.environ["BOT_API_KEY"]})
    assert r.status_code == 200, r.text
    return r.json()


# ── Paso 1: obra social o particular ────────────────────────────────────────

def test_los_botones_son_dos_y_uno_es_particular():
    from bot.tools.appointment_tools import preguntar_cobertura, tomar_opciones_ofrecidas

    preguntar_cobertura()
    pub = tomar_opciones_ofrecidas()
    assert pub["tipo"] == "botones", "Para una elección binaria, botones y no lista"
    assert pub["opciones"] == ["Tengo obra social", "Particular"]
    assert pub["siempre"] is True


def test_particular_deja_de_ser_una_suposicion():
    """Antes se asignaba en silencio por el default del parámetro."""
    from bot.tools.appointment_tools import preguntar_cobertura
    r = preguntar_cobertura()
    assert "Particular" in r
    assert "NO enumeres obras sociales todavía" in r


# ── Paso 2: el primer listado ───────────────────────────────────────────────

def test_el_primer_listado_entra_en_una_lista_de_whatsapp(cliente):
    d = _listar(cliente)
    assert len(d["activas"]) <= 6
    assert d["hay_mas"] is True, "Con 17 cargadas, tiene que avisar que hay más"


def test_particular_ya_no_va_mezclado_en_el_listado(cliente):
    """Se elige antes, con botones: acá sobra."""
    assert "Particular" not in _listar(cliente)["activas"]


# ── Paso 3: la búsqueda por letras ──────────────────────────────────────────

def test_el_caso_os_desborda_y_se_avisa(cliente):
    """12 coincidencias contra un tope de 10: es el caso más común."""
    d = _listar(cliente, "os")
    assert len(d["activas"]) == 10, "Nunca más de lo que entra en una lista"
    assert d["hay_mas"] is True, "Sin esto el paciente queda sin salida"


def test_con_una_letra_mas_se_acota(cliente):
    d = _listar(cliente, "ospel")
    assert d["activas"] == ["OSPELSYM"]
    assert d["hay_mas"] is False


def test_cada_letra_acota_la_busqueda(db, muchas):
    """Lo que el paciente espera: más letras, menos opciones."""
    assert len(buscar_obras_sociales(db, "os")) >= 10
    assert len(buscar_obras_sociales(db, "ospe")) < len(buscar_obras_sociales(db, "os"))
    assert buscar_obras_sociales(db, "ospel") == ["OSPELSYM"]


def test_osde_210_sigue_encontrando_osde(db):
    """La tolerancia suelta se mantiene cuando ninguna empieza igual."""
    from backend.models.insurance import Insurance
    db.query(Insurance).delete()
    db.add(Insurance(name="OSDE", is_active=True))
    db.commit()
    assert "OSDE" in buscar_obras_sociales(db, "osde 210")


def test_lo_que_no_existe_no_se_inventa(cliente):
    assert _listar(cliente, "banelco")["activas"] == []


def test_swiss_medical_se_encuentra_con_dos_letras(cliente):
    """Fuera del grupo "os", dos letras alcanzan de sobra."""
    d = _listar(cliente, "sw")
    assert d["activas"] == ["Swiss Medical"]
    assert d["hay_mas"] is False


def test_medife_con_acento(cliente):
    assert "Medifé" in _listar(cliente, "medife")["activas"]
