"""Lo que el paciente quiere hacer no es el nombre de su obra social.

Conversación real del 25/08/2026, tres mensajes seguidos:

    paciente: agendar
    bot:      No trabajamos con "agendar" como obra social, así que tu atención
              sería particular. ¿Te gustaría seguir adelante con eso?
    paciente: agendar turno
    bot:      No trabajamos con "agendar turno" como obra social...
    paciente: agendar un turno
    bot:      Para agendar un turno, primero necesito saber tu obra social.

Es lo primero que escribe cualquiera, y el sistema le contestaba un absurdo tres
veces. Lo introduje al hacer que las herramientas tomaran el último mensaje del
paciente como búsqueda de obra social: no filtré las palabras de intención.
"""
import pytest

from bot.tools.appointment_tools import (
    _parece_nombre_de_obra_social, _texto_parece_busqueda, verificar_obra_social,
)


# ── Lo que NO es una obra social ────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "agendar", "agendar turno", "agendar un turno", "quiero un turno",
    "necesito un turno", "sacar turno", "cancelar", "cancelar turno",
    "consultar mis turnos", "hola", "buenas tardes", "gracias",
    "¿donde quedan?", "cuanto sale?", "necesito informacion",
])
def test_no_confunde_una_intencion_con_una_cobertura(texto):
    assert not _parece_nombre_de_obra_social(texto), f"Tomó '{texto}' como obra social"


def test_el_caso_exacto_no_declara_no_cubierta():
    """Lo que el bot NO puede volver a contestar."""
    r = verificar_obra_social("agendar")
    assert "NO CUBIERTA" not in r
    assert "PROHIBIDO" in r and "no tiene ningún sentido" in r


def test_tampoco_se_usa_como_busqueda():
    """El fallback al último mensaje era el otro camino al mismo error."""
    assert _texto_parece_busqueda("agendar") == ""
    assert _texto_parece_busqueda("quiero un turno") == ""


# ── Lo que SÍ es una obra social ────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "OSDE", "OSEP", "OSPELSYM", "Swiss Medical", "PAMI", "Medifé",
    "sw", "ospe", "osde 210", "Jerárquicos Salud", "Unión Personal",
])
def test_reconoce_las_obras_sociales_de_verdad(texto):
    assert _parece_nombre_de_obra_social(texto), f"Rechazó '{texto}', que sí lo es"


def test_una_obra_social_con_una_palabra_comun_pasa_igual():
    """'Consulta Médica' tiene una palabra de relleno, pero no es solo relleno."""
    assert _parece_nombre_de_obra_social("Consulta Médica SA")


def test_ante_la_duda_deja_pasar():
    """Hay obras sociales con nombres rarísimos: peor es rechazar la verdadera."""
    assert _parece_nombre_de_obra_social("AMFFA")
    assert _parece_nombre_de_obra_social("Boreal")
    assert _parece_nombre_de_obra_social("DASUTEN")
