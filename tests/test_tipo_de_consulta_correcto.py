"""El tipo de consulta correcto, con los tipos y sinónimos reales de producción (21/10).

Simulación con IA real, 22/10:
- "una consulta para que lo revisen" (chico de 8 años) quedó como Consulta por
  conducto: el sinónimo "consulta por conducto" se comparaba entero por prefijo y
  cualquier "consulta" le sumaba.
- "Control de ortodoncia" empataba Control con Ortodoncia y ganaba Control por
  orden alfabético: el turno quedó con un profesional que no hace ortodoncia.
"""
import pytest

from backend.models.tipo_consulta import TipoConsulta
from backend.services.appointment_service import _tipo_para_motivo

TIPOS = [('Arreglos', 30, 'Arreglos', ['arreglo', 'arreglar', 'caries', 'tapar', 'empaste', 'roto', 'rotura']), ('Cirugía', 60, 'Cirugía', ['cirugia', 'operacion', 'operar', 'operarme', 'quirurgico']), ('Conducto', 60, 'Endodoncia', ['conducto', 'endodoncia', 'nervio', 'matar el nervio']), ('Consulta por conducto', 30, 'Endodoncia', ['consulta por conducto', 'consulta conducto', 'evaluacion conducto', 'evaluación conducto', 'conducto derivado', 'derivado conducto']), ('Control', 15, None, ['control', 'revision', 'chequeo', 'consulta', 'ver', 'duele', 'dolor', 'puntos']), ('Extracción', 30, 'Extracción', ['sacar', 'sacarme', 'muela', 'cordal', 'extraer', 'extraigan', 'quitar', 'extraccion']), ('Limpieza', 15, 'Limpieza', ['limpiar', 'limpieza', 'sarro', 'profilaxis', 'higiene', 'blanquear']), ('Odontopediatría', 30, None, ['niño', 'nino', 'nena', 'nene', 'chico', 'chica', 'hijo', 'hija', 'pediatria', 'odontopediatria', 'criatura', 'bebe', 'menor']), ('Ortodoncia', 30, 'Ortodoncia', ['ortodoncia', 'brackets', 'aparato', 'alinear', 'invisalign']), ('Prótesis', 30, 'Prótesis', ['protesis', 'placa', 'dentadura', 'puente', 'implante'])]


@pytest.fixture
def tipos(db):
    for n, d, e, s in TIPOS:
        db.add(TipoConsulta(nombre=n, duracion_minutos=d, especialidad=e, sinonimos=s))
    db.commit()


@pytest.mark.parametrize("dicho, esperado", [
    ("Consulta", "Control"),
    ("es una consulta para revisarlo", "Control"),
    ("Control de ortodoncia", "Ortodoncia"),
    ("consulta por conducto", "Consulta por conducto"),
    ("vengo derivado, consulta conducto", "Consulta por conducto"),
    ("tratamiento de conducto", "Conducto"),
    ("extraccion de muela", "Extracción"),
    ("Revisión general", "Control"),
    ("limpieza", "Limpieza"),
])
def test_tipo_correcto(db, tipos, dicho, esperado):
    assert _tipo_para_motivo(db, dicho).nombre == esperado
