"""Que el paciente elija tocando, en vez de escribir.

Reclamo real: "tiene que existir una forma de que me muestre un listado o pueda
seleccionar cuales atiende, es muy facil confundirse". Y era cierto: escribiendo
a mano, "ospeysin" quedaba como no cubierta y el paciente terminaba agendado
como particular sin enterarse.

Los horarios y las obras sociales se comportan distinto a proposito:
- horarios: la lista va SOLO si el texto los menciona, porque el modelo puede
  consultar disponibilidad y despues decir otra cosa.
- obras sociales: la lista va SIEMPRE, porque la gracia es que el paciente no
  tenga que leerlas ni escribirlas.
"""
import asyncio

import pytest

from backend.routers import evolution_router as er
from bot.tools.appointment_tools import (
    set_opciones_ofrecidas, tomar_opciones_ofrecidas,
)


@pytest.fixture
def enviados(monkeypatch):
    """Intercepta los envios a WhatsApp para poder mirarlos."""
    registro = {"listas": [], "textos": []}

    async def _lista(jid, cuerpo, opciones, boton=None, titulo=None):
        registro["listas"].append({"cuerpo": cuerpo, "opciones": list(opciones),
                                   "boton": boton, "titulo": titulo})
        return True

    async def _texto(jid, cuerpo):
        registro["textos"].append(cuerpo)
        return True

    monkeypatch.setattr(er, "send_whatsapp_list", _lista)
    monkeypatch.setattr(er, "send_whatsapp_message", _texto)
    return registro


def _responder(texto, publicadas):
    asyncio.run(er._responder("549260@s.whatsapp.net", texto, publicadas))


# ── Obras sociales: la lista va siempre ──────────────────────────────────────

def test_las_obras_sociales_van_como_lista_aunque_el_texto_no_las_nombre(enviados):
    set_opciones_ofrecidas(["OSDE", "PAMI", "Particular"], siempre=True,
                           titulo="Obras sociales", boton="Elegir cobertura")
    _responder("¿Cuál es tu obra social?", tomar_opciones_ofrecidas())

    assert len(enviados["listas"]) == 1, "Tendría que haber mandado la lista tocable"
    assert enviados["listas"][0]["opciones"] == ["OSDE", "PAMI", "Particular"]
    assert enviados["listas"][0]["titulo"] == "Obras sociales"
    assert not enviados["textos"]


# ── Horarios: solo si el texto los menciona ──────────────────────────────────

def test_los_horarios_van_como_lista_si_el_texto_los_ofrece(enviados):
    set_opciones_ofrecidas(["09:00", "09:30", "10:00"])
    _responder("Tengo 09:00, 09:30 y 10:00. ¿Cuál te sirve?", tomar_opciones_ofrecidas())

    assert len(enviados["listas"]) == 1
    assert enviados["listas"][0]["opciones"] == ["09:00", "09:30", "10:00"]


def test_no_manda_horarios_que_el_texto_no_esta_ofreciendo(enviados):
    """El modelo consulto disponibilidad pero terminó pidiendo otro dato."""
    set_opciones_ofrecidas(["09:00", "09:30"])
    _responder("Antes de seguir, ¿me confirmás tu DNI?", tomar_opciones_ofrecidas())

    assert not enviados["listas"], "Mandó una lista que no se corresponde con el texto"
    assert len(enviados["textos"]) == 1


def test_con_una_sola_opcion_va_texto_plano(enviados):
    """Una lista de un solo item es mas incomoda que la frase."""
    set_opciones_ofrecidas(["09:00"])
    _responder("Me queda solo 09:00. ¿Te sirve?", tomar_opciones_ofrecidas())

    assert not enviados["listas"]
    assert len(enviados["textos"]) == 1


def test_sin_opciones_va_texto_plano(enviados):
    _responder("Listo, tu turno quedó agendado.", None)
    assert not enviados["listas"]
    assert len(enviados["textos"]) == 1


# ── Las opciones se consumen una sola vez ────────────────────────────────────

def test_las_opciones_no_se_arrastran_al_mensaje_siguiente():
    set_opciones_ofrecidas(["OSDE", "PAMI"], siempre=True)
    assert tomar_opciones_ofrecidas()["opciones"] == ["OSDE", "PAMI"]
    assert tomar_opciones_ofrecidas() is None, "Se estarían reofreciendo opciones viejas"
