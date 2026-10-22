"""Que los logs no guarden teléfonos ni DNI de pacientes.

Los logs del contenedor tenían el número completo del paciente en cada mensaje,
el texto que escribía y la transcripción de sus audios.
"""
import logging

import pytest

from backend.logs_privados import instalar, tapar_numeros


@pytest.mark.parametrize("texto, no_debe_quedar", [
    ("Enviando a +5492604590071", "5492604590071"),
    ("de 5492605550101@s.whatsapp.net", "5492605550101"),
    ("DNI 24785465 no coincide", "24785465"),
    ("llamá al 2604-590071", "590071"),
    ("tel 260 4590071", "4590071"),
])
def test_tapa_telefonos_y_dni(texto, no_debe_quedar):
    tapado = tapar_numeros(texto)
    assert no_debe_quedar not in tapado
    assert "…" in tapado


@pytest.mark.parametrize("texto", [
    "turno el 2026-10-22 a las 10:30",
    "duró 30 minutos, 15 llamadas",
    "appointment 9f2c1d4e-77ab-4c1e-9a00-1b2c3d4e5f60",
])
def test_no_toca_fechas_horas_ni_ids(texto):
    assert tapar_numeros(texto) == texto


def test_aplica_a_cualquier_logger(caplog):
    instalar()
    log = logging.getLogger("cualquiera.de.afuera")
    with caplog.at_level(logging.INFO):
        log.info("Mensaje de %s con DNI %s", "+5492604590071", "24785465")
    escrito = caplog.records[-1].getMessage()
    assert "5492604590071" not in escrito and "24785465" not in escrito
    assert "…071" in escrito and "…465" in escrito


def test_instalar_dos_veces_no_anida():
    instalar()
    fabrica = logging.getLogRecordFactory()
    instalar()
    assert logging.getLogRecordFactory() is fabrica
