"""Que el buscador de pacientes del panel encuentre a todos, no a los primeros 50.

Los dos buscadores del panel -- el del modal de Nuevo Turno y el del
odontograma -- filtraban en el navegador sobre lo que devolvia
/clinic/patients al abrir la pantalla. Ese endpoint pagina de a 50 y no tenia
ORDER BY, asi que "los primeros 50" era un recorte arbitrario. Con la agenda
de papel cargada, el paciente buscado casi nunca caia ahi: se tipeaba el
apellido y el desplegable quedaba vacio.

Estos tests cubren la parte del servidor. Lo que arregla el sintoma es que la
busqueda pase por aca en vez de resolverse en el navegador.
"""
import pytest

from backend.models.patient import Patient
from backend.routers.clinic.clinic_routes import (
    MAX_PACIENTES_POR_PAGINA, contar_patients, list_patients,
)


def _cargar(db, cuantos: int, apellido="Zzz"):
    for i in range(cuantos):
        db.add(Patient(first_name=f"Paciente{i:03d}", last_name=f"{apellido}{i:03d}",
                       dni=f"9{i:07d}", phone=f"+54926040{i:05d}"))
    db.commit()


def _nombres(filas):
    return [f"{p.last_name}, {p.first_name}" for p in filas]


# ── El caso que se rompio en produccion ──────────────────────────────────────

def test_encuentra_a_alguien_que_no_entra_en_la_primera_pagina(db):
    """El apellido buscado esta al final del alfabeto, detras de 60 fichas."""
    _cargar(db, 60, apellido="Aguilera")
    db.add(Patient(first_name="Morena", last_name="Funes", dni="45123456",
                   phone="+5492604777888"))
    db.commit()

    primera_pagina = list_patients(db=db)
    assert len(primera_pagina) == 50
    assert "Funes, Morena" not in _nombres(primera_pagina), (
        "El caso de prueba no sirve si la ficha ya entra en la primera pagina"
    )

    assert _nombres(list_patients(q="morena", db=db)) == ["Funes, Morena"]
    assert _nombres(list_patients(q="funes", db=db)) == ["Funes, Morena"]


# ── Formas de escribirlo ─────────────────────────────────────────────────────

def test_busca_por_nombre_apellido_y_dni(db, paciente):
    for termino in ("claudio", "LUNA", "2478"):
        assert paciente.id in [p.id for p in list_patients(q=termino, db=db)], termino


def test_apellido_y_nombre_de_corrido(db, paciente):
    """Es como lo tipea recepcion: 'luna claudio' o 'claudio luna'."""
    assert [p.id for p in list_patients(q="luna claudio", db=db)] == [paciente.id]
    assert [p.id for p in list_patients(q="claudio luna", db=db)] == [paciente.id]


def test_las_palabras_suman_condiciones_no_las_aflojan(db, paciente, otro_paciente):
    """'luna pardo' no es nadie: son dos pacientes distintos."""
    assert list_patients(q="luna pardo", db=db) == []


def test_no_devuelve_al_que_no_es(db, paciente, otro_paciente):
    assert [p.id for p in list_patients(q="pardo", db=db)] == [otro_paciente.id]


def test_sin_resultados_devuelve_lista_vacia(db, paciente):
    assert list_patients(q="apellidoquenoexiste", db=db) == []


# ── Orden y paginado ─────────────────────────────────────────────────────────

def test_la_primera_pagina_es_alfabetica_y_estable(db):
    """Sin ORDER BY, PostgreSQL elegia el orden y el recorte cambiaba solo."""
    _cargar(db, 60)
    apellidos = [p.last_name for p in list_patients(db=db)]
    assert apellidos == sorted(apellidos)
    assert apellidos == [p.last_name for p in list_patients(db=db)]


def test_el_limite_tiene_tope(db):
    """Pedir 10.000 fichas no puede volcar la base entera en una respuesta."""
    _cargar(db, 5)
    assert len(list_patients(limit=10_000, db=db)) <= MAX_PACIENTES_POR_PAGINA


def test_un_limite_absurdo_no_rompe(db, paciente):
    assert len(list_patients(limit=0, db=db)) == 1
    assert len(list_patients(limit=-3, db=db)) == 1
    assert len(list_patients(skip=-5, db=db)) == 1


def test_los_borrados_no_aparecen(db, paciente):
    paciente.is_deleted = True
    db.commit()
    assert list_patients(q="luna", db=db) == []


# ── El total no es el largo de la primera pagina ────────────────────────────
# El dashboard mostraba len(getPatients()) como "Pacientes Registrados": 50 fijo,
# con 475 fichas cargadas. El total lo tiene que contar el servidor.

def test_cuenta_todos_no_solo_la_primera_pagina(db):
    _cargar(db, 137)
    assert contar_patients(db=db) == {"total": 137}
    assert len(list_patients(db=db)) == 50


def test_la_cuenta_respeta_el_filtro(db, paciente, otro_paciente):
    assert contar_patients(q="luna", db=db)["total"] == 1
    assert contar_patients(q="noexiste", db=db)["total"] == 0


def test_los_borrados_no_se_cuentan(db, paciente):
    paciente.is_deleted = True
    db.commit()
    assert contar_patients(db=db) == {"total": 0}
