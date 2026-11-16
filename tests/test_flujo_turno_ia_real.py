"""Lo que entiende la IA de verdad, mensaje por mensaje.

Corre contra OpenAI (gasta centavos): solo con OPENAI_API_KEY y `-m conversacion`.
Los mensajes son los de las pruebas reales de Claudio del 15/11, tal cual.

    OPENAI_API_KEY=... OPENAI_MODEL=gpt-4.1-mini \\
        .venv/bin/python -m pytest tests/test_flujo_turno_ia_real.py -m conversacion
"""
import os

import pytest

from backend.models.tipo_consulta import TipoConsulta
from backend.services.appointment_service import PREGUNTA_CONDUCTO_PACIENTE
from bot import flujo_turno

pytestmark = [
    pytest.mark.conversacion,
    pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="Sin OPENAI_API_KEY"),
]

TIPOS = ["Control", "Limpieza", "Extracción", "Arreglos", "Ortodoncia", "Implantes",
         "Consulta", "Consulta por conducto", "Conducto", "Odontopediatría"]

CASOS = [
    # (mensaje, última pregunta del bot, lo que tiene que entender)
    ("quiero un turnopara una extraccion", "", {"intencion": "sacar_turno", "motivo": "Extracción"}),
    ("me das un turno pra un tratamiento de conducto??", "", {"intencion": "sacar_turno", "motivo": "Conducto"}),
    ("un lunes", "¿Qué día te vendría bien?", {"dia": "lunes"}),
    ("mio", "¿A nombre de quién agendo el turno? Necesito nombre y apellido.", {"para_quien": "yo", "obra_social": None}),
    ("si", PREGUNTA_CONDUCTO_PACIENTE, {"respuesta_si_no": "si"}),
    ("es para mi hijo Tomás", "¿El turno es para vos, Claudio, o para otra persona?",
     {"para_quien": "otra_persona", "nombre": "Tomás"}),
    ("swi", "Elegí tu obra social de la lista. Si no la ves, escribime las primeras letras.",
     {"obra_social": "swi"}),
    ("a las 5 de la tarde", "¿Qué horario te queda mejor?", {"hora": "17:00"}),
    ("¿dónde quedan?", "¿El turno es para vos, Claudio, o para otra persona?", {"intencion": "pregunta"}),
    ("quiero cancelar mi turno", "", {"intencion": "cancelar_turno"}),
    ("hola", "", {"intencion": "saludo_o_cierre"}),
    ("quiero sacarme una muela el viernes a la tarde, es para mi mamá Ana Pérez, tiene PAMI", "",
     {"intencion": "sacar_turno", "motivo": "Extracción", "para_quien": "otra_persona",
      "nombre": "Ana", "apellido": "Pérez", "obra_social": "PAMI", "preferencia_horaria": "tarde"}),
    ("me duele una muela", "", {"intencion": "sacar_turno"}),
    ("mejor que me arreglen una caries", "¿Qué horario te queda mejor?", {"motivo": "Arreglos"}),
    ("Florencia Ramos", "¿A nombre de quién agendo el turno? Necesito nombre y apellido.",
     {"nombre": "Florencia", "apellido": "Ramos", "obra_social": None}),
    ("particular", "¿La atención sería con obra social o particular?", {"cobertura": "particular"}),
    ("no puedo el 20, necesito antes. hay otro dia?", "¿Qué horario te queda mejor?", {"quiere_otro_dia": True}),
    ("No puedo el miércoles, busco extracción el viernes a la mañana.", "¿Qué horario te queda mejor?",
     {"quiere_otro_dia": True, "dia": "viernes"}),
    ("Está bien, confirmo el martes 24 de noviembre a las 10:30.", "¿Qué horario te queda mejor?",
     {"hora": "10:30", "dia": "24"}),
    ("OSEP.", "¿Es alguna de estas?", {"obra_social": "OSEP"}),
    ("sí", "¿Seguís atendiéndote como *particular*?", {"respuesta_si_no": "si", "obra_social": None}),
    ("no, ahora tengo OSDE", "¿Seguís atendiéndote como *particular*?",
     {"respuesta_si_no": "no", "obra_social": "OSDE"}),
]


@pytest.fixture
def tipos(db):
    db.add_all([TipoConsulta(nombre=n, duracion_minutos=30) for n in TIPOS])
    db.commit()


def _parecido(obtenido, esperado):
    if isinstance(esperado, bool):
        return obtenido is esperado
    if esperado is None:
        return obtenido is None
    return esperado.lower() in (obtenido or "").lower()


@pytest.mark.parametrize("mensaje,pregunta,esperado", CASOS, ids=[c[0][:30] for c in CASOS])
def test_entiende(tipos, mensaje, pregunta, esperado):
    datos = flujo_turno.extraer(mensaje, pregunta)
    for campo, valor in esperado.items():
        assert _parecido(datos.get(campo), valor), (
            f"«{mensaje}» → {campo}={datos.get(campo)!r}, se esperaba {valor!r}. Todo: {datos}")
