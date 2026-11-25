"""El guion de sacar turno, de punta a punta contra el backend real.

Lo único simulado es lo que la IA entiende de cada mensaje (`extraer`): el
validador de motivos, la identificación, la agenda y el alta son los de
verdad, sobre la base de pruebas. La IA real se prueba con el simulador.

Cada conversación sale de algo que pasó en las pruebas de Claudio del 15/11.
"""
import os
import uuid
from datetime import time as py_time

import pytest
from fastapi.testclient import TestClient

from backend.models.appointment import Appointment
from backend.models.patient import Patient
from backend.models.schedule import ProfessionalSchedule
from backend.models.tipo_consulta import TipoConsulta
from backend.services.appointment_service import (
    PREGUNTA_CONDUCTO_PACIENTE, TEXTO_SIN_CONSULTA_PREVIA,
    BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO,
)
from bot import ai_agent, flujo_turno

TEL_CLAUDIO = "+5492604590071"     # el del fixture `paciente`
TEL_NUEVO = "+5492605550199"

TIPOS = [
    ("Control", 15, None, ["control", "revision"]),
    ("Extracción", 30, "Extracción", ["sacar", "sacarme", "muela"]),
    ("Arreglos", 30, "Extracción", ["arreglo", "caries"]),
    ("Consulta por conducto", 30, "Endodoncia", ["consulta por conducto"]),
    ("Conducto", 60, "Endodoncia", ["conducto", "nervio", "endodoncia"]),
]

CAMPOS = ["intencion", "motivo", "para_quien", "nombre", "apellido", "cobertura",
          "obra_social", "dia", "preferencia_horaria", "hora", "profesional",
          "pregunta", "respuesta_si_no"]


@pytest.fixture
def consultorio(db, clinica, silvestro, murad, monkeypatch):
    db.add_all([TipoConsulta(nombre=n, duracion_minutos=d, especialidad=e, sinonimos=s)
                for n, d, e, s in TIPOS])
    murad.specialties = ["Ortodoncia", "Endodoncia"]
    for prof, dias in ((murad, [0, 1, 4]), (silvestro, [2, 3, 4])):
        for d in dias:
            for ini, fin in ((py_time(9, 0), py_time(12, 30)), (py_time(17, 0), py_time(20, 30))):
                db.add(ProfessionalSchedule(id=uuid.uuid4(), professional_id=prof.id,
                                            weekday=d, start_time=ini, end_time=fin,
                                            is_active=True))
    db.commit()

    from backend.main import app
    with TestClient(app) as c:
        clave = {"x-bot-key": os.environ["BOT_API_KEY"]}

        def post(ruta, payload, timeout=30):
            r = c.post(ruta, json=payload, headers=clave)
            return r.status_code, r.json()

        def get(ruta, params):
            r = c.get(ruta, params=params, headers=clave)
            r.raise_for_status()
            return r.json()

        monkeypatch.setattr(flujo_turno, "_post", post)
        monkeypatch.setattr(flujo_turno, "_get", get)
        monkeypatch.setattr(flujo_turno, "ACTIVO", True)
        monkeypatch.setattr(flujo_turno, "responder_pregunta",
                            lambda p: "Estamos en Av. San Martín 123, San Rafael.")
        yield db


class Charla:
    """Una conversación: cada mensaje con lo que la IA entendería de él."""

    def __init__(self, monkeypatch, telefono):
        self.telefono, self.history, self.estado, self.ia = telefono, [], {}, {}
        self.respuestas = []
        monkeypatch.setattr(flujo_turno, "extraer", self._extraer)
        monkeypatch.setattr(ai_agent, "_build_client", lambda: (None, None))

    def _extraer(self, mensaje, ultima):
        datos = {k: None for k in CAMPOS}
        datos["intencion"] = "dar_datos"
        datos.update(self.ia.get(mensaje, {}))
        return datos

    def dice(self, mensaje, **entiende):
        self.ia[mensaje] = entiende
        texto, opciones, self.estado = ai_agent.chat(mensaje, self.history, self.telefono, self.estado)
        self.history += [{"role": "user", "content": mensaje}, {"role": "assistant", "content": texto}]
        self.respuestas.append(texto)
        self.opciones = (opciones or {}).get("opciones") or []
        return texto


def _turnos(db):
    """Los que agendó el bot (el arranque de la app crea dos de demostración)."""
    from backend.models.appointment import AppointmentChannel
    db.expire_all()
    return db.query(Appointment).filter(
        Appointment.is_deleted == False,  # noqa: E712
        Appointment.channel == AppointmentChannel.bot_whatsapp,
    ).all()


# ── Número conocido ──────────────────────────────────────────────────────────

def test_conocido_para_si_mismo(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    assert "para vos, Claudio" in t
    assert c.opciones == ["Para mí", "Para otra persona"]

    t = c.dice("Para mí")
    # La ficha dice Particular: se confirma, no se da por hecho.
    assert t == "¿Seguís atendiéndote como *particular*?"
    assert c.opciones == ["Sí", "Cambió"]
    t = c.dice("Sí")
    assert "Silvestro" in t and "horario" in t.lower()
    hora = c.opciones[0]
    t = c.dice(hora)
    assert t.startswith("¡Listo, Claudio!") and hora in t
    (turno,) = _turnos(consultorio)
    assert turno.patient_id == paciente.id and turno.reason == "Extracción"
    assert flujo_turno.CLAVE not in c.estado
    # Pedido cerrado: no deja el motivo para el próximo y avisa que agendó.
    assert "motivo" not in c.estado and c.estado.get("accion_hecha") is True


# ── Número nuevo: el "mío" que terminó buscado como obra social ─────────────

def test_numero_nuevo_dice_mio(consultorio, monkeypatch):
    """Orden del 24/11: obra social primero, después el motivo, y recién al
    final el nombre de quien se atiende (número sin ficha)."""
    c = Charla(monkeypatch, TEL_NUEVO)
    t = c.dice("quiero un turno para una extraccion", intencion="sacar_turno", motivo="Extracción")
    assert "obra social o particular" in t
    t = c.dice("Tengo obra social")
    assert "primeras letras" in t and "PAMI" in c.opciones
    t = c.dice("PAMI")
    assert "nombre y apellido" in t
    t = c.dice("mio", para_quien="yo")
    assert "obra social" not in t.lower()
    assert "tu nombre y apellido" in t and not t.startswith("Perdón")
    t = c.dice("Ana Pérez", nombre="Ana", apellido="Pérez")
    assert "horario" in t.lower()
    c.dice(c.opciones[0])
    (turno,) = _turnos(consultorio)
    p = consultorio.get(Patient, turno.patient_id)
    assert (p.first_name, p.last_name) == ("Ana", "Pérez")


def test_numero_nuevo_sin_apellido(consultorio, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("turno para extracción", intencion="sacar_turno", motivo="Extracción")
    c.dice("Particular")
    t = c.dice("Ana", nombre="Ana")
    assert "apellido de Ana" in t


# ── Todo junto en un mensaje ────────────────────────────────────────────────

def test_todo_en_un_mensaje(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("turno para sacarle una muela a mi mamá Estela Pardo, tiene PAMI, el viernes a la tarde",
               intencion="sacar_turno", motivo="Extracción", para_quien="otra_persona",
               nombre="Estela", apellido="Pardo", obra_social="PAMI", dia="el viernes",
               preferencia_horaria="tarde")
    assert "viernes" in t and "horario" in t.lower()
    assert all(h >= "17:00" for h in c.opciones if ":" in h)
    c.dice(c.opciones[0])
    (turno,) = _turnos(consultorio)
    p = consultorio.get(Patient, turno.patient_id)
    assert (p.first_name, p.last_name) == ("Estela", "Pardo")
    assert turno.patient_id != paciente.id


# ── Conducto ────────────────────────────────────────────────────────────────

def test_osde_un_viernes_se_ofrece_otro_dia_sin_explicar_la_regla(consultorio, paciente, monkeypatch):
    """Los viernes son solo PAMI: se ofrece otro día con naturalidad."""
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("sacarle una muela a mi mamá Estela Pardo, tiene OSDE, el viernes",
               intencion="sacar_turno", motivo="Extracción", para_quien="otra_persona",
               nombre="Estela", apellido="Pardo", obra_social="OSDE", dia="el viernes")
    assert "no tengo turnos para extracción" in t and "horario" in t.lower()
    assert "PAMI" not in t and "cerrad" not in t.lower()


def test_conducto_dice_que_si_y_no_figura(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("me das un turno para un tratamiento de conducto??", intencion="sacar_turno", motivo="Conducto")
    assert "para vos, Claudio" in t
    c.dice("Para mí")
    t = c.dice("Sí")
    assert t.endswith(PREGUNTA_CONDUCTO_PACIENTE)
    assert c.opciones == [BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO]
    t = c.dice("si", respuesta_si_no="si")
    assert t == TEXTO_SIN_CONSULTA_PREVIA
    assert c.opciones == [BOTON_CONSULTA_CONDUCTO]
    t = c.dice("Necesito la consulta")
    assert "horario" in t.lower()
    c.dice(c.opciones[0])
    (turno,) = _turnos(consultorio)
    assert turno.reason == "Consulta por conducto"


def test_conducto_boton_necesito_la_consulta(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("turno para conducto", intencion="sacar_turno", motivo="Conducto")
    c.dice("Para mí")
    c.dice("Sí")
    t = c.dice("no", respuesta_si_no="no")
    assert "horario" in t.lower()


# ── Obra social ─────────────────────────────────────────────────────────────

def test_obra_social_no_cubierta(consultorio, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("turno para extracción", intencion="sacar_turno", motivo="Extracción")
    c.dice("Tengo obra social")
    t = c.dice("Swiss Medical")
    assert "No trabajamos con" in t and "Particular" in c.opciones
    t = c.dice("Particular")
    assert "nombre y apellido" in t
    t = c.dice("Ana Pérez", nombre="Ana", apellido="Pérez")
    assert "horario" in t.lower()


# ── Elegir horario ──────────────────────────────────────────────────────────

def test_elegir_con_una_frase_agenda_sin_repetir_la_lista(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    c.dice("Sí")
    hora = c.opciones[1]
    t = c.dice(f"me viene bien a las {hora} gracias", hora=hora)
    assert t.startswith("¡Listo")
    assert len(_turnos(consultorio)) == 1


def test_otro_dia(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    c.dice("Sí")
    primera = c.estado["turno"]["oferta"]["fecha"]
    t = c.dice("Otro día")
    assert "otra fecha" in t and c.estado["turno"]["oferta"]["fecha"] > primera
    t = c.dice("el jueves", dia="el jueves", quiere_otro_dia=True)
    assert "jueves" in t


def test_cambia_de_motivo(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero un control", intencion="sacar_turno", motivo="Control")
    c.dice("Para mí")
    c.dice("Sí")
    c.dice("mejor que me saquen una muela", motivo="Extracción")
    c.dice(c.opciones[0])
    (turno,) = _turnos(consultorio)
    assert turno.reason == "Extracción"


# ── Fuera del guion ─────────────────────────────────────────────────────────

def test_pregunta_suelta_en_medio(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    t = c.dice("¿dónde quedan?", intencion="pregunta", pregunta="¿dónde quedan?")
    assert t.startswith("Estamos en Av. San Martín")
    assert "para vos, Claudio" in t


def test_cancelar_en_medio_lo_toma_el_guion(consultorio, paciente, monkeypatch):
    """24/11: cancelar pasó al guion (antes el agente general decía "no pude
    confirmar los horarios" antes de cancelar)."""
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    t = c.dice("quiero cancelar mi turno", intencion="cancelar_turno")
    assert flujo_turno.CLAVE not in c.estado
    assert "¿Qué día tenías el turno?" in t


def test_un_saludo_no_arranca_el_guion(consultorio, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.ia["hola"] = {"intencion": "saludo_o_cierre"}
    assert flujo_turno.responder("hola", [], {}, TEL_CLAUDIO, []) is None


# ── Lo que encontró la simulación con IA real del 16/11 ─────────────────────

def test_no_puedo_ese_dia_escrito_busca_otra_fecha(consultorio, paciente, monkeypatch):
    """04-pami-jubilada: "no puedo el 20, necesito antes" repetía la misma oferta."""
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    c.dice("Sí")
    primera = c.estado["turno"]["oferta"]["fecha"]
    t = c.dice("no puedo ese día", quiere_otro_dia=True)
    assert c.estado["turno"]["oferta"]["fecha"] > primera
    assert not t.startswith("Perdón")


def test_fecha_explicita_manda_sobre_el_dia_de_la_semana(consultorio, paciente, monkeypatch):
    """12-murad-miercoles: "martes 24 de noviembre" se leía como el próximo martes."""
    from bot.flujo_turno import _fecha_iso
    assert _fecha_iso("martes 24 de noviembre").endswith("-11-24")
    assert _fecha_iso("el 24/11").endswith("-11-24")


def test_obra_social_con_punto_de_la_lista(consultorio, monkeypatch):
    """16-rafaga: "OSEP." no coincidía con la lista y daba vueltas."""
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("turno para extracción", intencion="sacar_turno", motivo="Extracción")
    c.dice("Tengo obra social")
    t = c.dice("PAMI.", obra_social="PAMI.")
    assert "nombre y apellido" in t


def test_tres_veces_lo_mismo_manda_a_llamar(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero un turno", intencion="sacar_turno")
    t2 = c.dice("mmm")
    assert t2.startswith("Perdón, no te entendí bien")
    t3 = c.dice("eh")
    assert "llamá al consultorio" in t3
    assert flujo_turno.CLAVE not in c.estado


def test_pide_otro_dia_con_hora_y_esta_libre_agenda_directo(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    c.dice("Sí")
    primera = c.estado["turno"]["oferta"]["fecha"]
    # El jueves siguiente a la primera oferta, a las 10:00 (libre en la base vacía).
    from datetime import date, timedelta
    d = date.fromisoformat(primera) + timedelta(days=1)
    while d.weekday() != 3:
        d += timedelta(days=1)
    t = c.dice(f"mejor el {d.day}/{d.month} a las 10:00", dia=f"{d.day}/{d.month}", hora="10:00",
               quiere_otro_dia=True)
    assert t.startswith("¡Listo") and "10:00" in t
    (turno,) = _turnos(consultorio)
    assert turno.start_time.date() == d


def test_obra_social_de_la_ficha_cambio(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    t = c.dice("Cambió")
    assert "obra social o particular" in t
    c.dice("Tengo obra social")
    t = c.dice("PAMI")
    assert "horario" in t.lower()
    c.dice(c.opciones[0])
    (turno,) = _turnos(consultorio)
    assert turno.reason == "Extracción"


def test_obra_social_de_la_ficha_dice_la_nueva_directo(consultorio, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    t = c.dice("no, ahora tengo PAMI", respuesta_si_no="no", obra_social="PAMI")
    assert "horario" in t.lower()


def test_insiste_con_un_dia_sin_lugar(consultorio, paciente, monkeypatch):
    """01-extraccion-directa: pidió mañana, no había, insistió y el bot repetía."""
    c = Charla(monkeypatch, TEL_CLAUDIO)
    # El lunes: Silvestro no atiende, así que la oferta cae otro día.
    c.dice("quiero sacarme una muela el lunes", intencion="sacar_turno", motivo="Extracción", dia="el lunes")
    c.dice("Para mí")
    t = c.dice("Sí")
    assert "no tengo turnos para extracción" in t
    t = c.dice("no puedo, ¿me pueden atender el lunes?", dia="el lunes", quiere_otro_dia=True)
    assert t.startswith("Ya me fijé") and "lunes" in t
    assert not t.startswith("Perdón")


def test_pide_un_profesional_que_no_hace_esa_practica(consultorio, paciente, monkeypatch):
    """Prueba real 16/11 0:55: consulta por conducto "con Silvestro"."""
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("turno para conducto", intencion="sacar_turno", motivo="Conducto")
    c.dice("Para mí")
    c.dice("Sí")
    t = c.dice("Necesito la consulta", profesional="Silvestro")
    assert "no la hace" in t and "Murad" in t and "con ella" in t
    t = c.dice("dale", respuesta_si_no="si")
    assert "Murad" in t and "horario" in t.lower()


def test_el_nombre_se_pide_cada_vez_distinto(consultorio, monkeypatch):
    """Prueba en producción 16/11: "un lunes" y "mío" repetían la misma frase."""
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("quiero un turnopara una extraccion", intencion="sacar_turno", motivo="Extracción")
    t1 = c.dice("Particular")
    t2 = c.dice("un lunes", dia="un lunes", para_quien="yo")
    t3 = c.dice("mio", para_quien="yo")
    assert len({t1, t2, t3}) == 3
    assert not any(t.startswith("Perdón") for t in (t2, t3))
    t = c.dice("Ana Prueba", nombre="Ana", apellido="Prueba")
    assert "horario" in t.lower()
