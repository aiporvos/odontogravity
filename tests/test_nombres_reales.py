"""El bot nombra a los profesionales con su nombre real, no con el typo.

Charla 21/09: el paciente escribió "Silvestre" y el bot repitió "el Dr.
Silvestre" tres veces, como si fuera el apellido. El typo se resolvió bien
para buscar (fuzzy), pero el texto que sale tiene que decir Silvestro.

Y si el paciente pide a alguien que no existe ("Sosa"), el bot no puede
suavizarlo a "no está disponible": no existe, y atienden estos otros.
"""
import pytest

from bot import ai_agent


@pytest.fixture
def apellidos(monkeypatch):
    monkeypatch.setattr(ai_agent, "_apellidos_reales",
                        lambda: {"silvestro": "Silvestro", "murad": "Murad"})


@pytest.mark.parametrize("texto,esperado", [
    ("No, el Dr. Silvestre no hace conductos.", "No, el Dr. Silvestro no hace conductos."),
    ("Con el doctor silvestre no hay turno.", "Con el doctor Silvestro no hay turno."),
    ("La Dra. Murat te puede atender.", "La Dra. Murad te puede atender."),
    ("El Dr. Silvestro atiende jueves.", "El Dr. Silvestro atiende jueves."),
    ("Tenés turno el jueves a las 10:00.", "Tenés turno el jueves a las 10:00."),
])
def test_corrige_el_apellido_al_real(apellidos, texto, esperado):
    assert ai_agent.corregir_apellidos(texto) == esperado


def test_no_toca_palabras_comunes(apellidos):
    """'silvestre' es también una palabra: solo se corrige cuando va con Dr./doctor."""
    assert ai_agent.corregir_apellidos("un lugar silvestre") == "un lugar silvestre"


@pytest.mark.parametrize("texto,esperado", [
    ("Un turno con el doctor Sosa", "Sosa"),
    ("con la Dra. Gonzalez para el jueves", "Gonzalez"),
    ("Con el drama Silvestre no hay?", None),
    ("el doctor Silvestro", None),
    ("la doctora murad", None),
    ("quiero un turno para el jueves", None),
    ("el doctor para mañana", None),
])
def test_detecta_a_quien_no_existe_antes_de_llamar_al_modelo(apellidos, texto, esperado):
    assert ai_agent.profesional_inexistente_en(texto) == esperado


def test_si_la_tool_dijo_que_no_existe_no_se_suaviza():
    """'No hay ningún profesional llamado Sosa' no puede salir como 'no está disponible'."""
    tool = ("No hay ningún profesional llamado 'Sosa'. "
            "Atienden: Dr. Martín Silvestro y Dra. Elena Murad.")
    modelo = "El Dr. Sosa no está disponible. ¿Querés con la Dra. Murad?"
    assert ai_agent.suaviza_inexistente(modelo, [tool]) is True
    assert ai_agent.suaviza_inexistente(
        "No tenemos ningún Dr. Sosa. Atienden el Dr. Silvestro y la Dra. Murad, ¿con quién querés?",
        [tool],
    ) is False
    assert ai_agent.suaviza_inexistente(modelo, ["Tengo turno el jueves"]) is False
