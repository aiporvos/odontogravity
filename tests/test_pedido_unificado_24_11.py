"""Pedido unificado del 24/11/2026: lo que mostraron los chats reales de Silprodent.

Cada test nombra el punto del pedido (1 a 22) y, si viene de un chat, cuál.
Como en test_flujo_turno.py, lo único simulado es lo que la IA entiende de cada
mensaje; el backend, la agenda y el alta son los reales sobre la base de pruebas.
"""
from datetime import date, datetime, timedelta

import pytest

from backend.models.appointment import Appointment
from backend.models.config import AppConfig
from backend.models.tipo_consulta import TipoConsulta
from bot import flujo_turno
from tests.test_flujo_turno import (  # noqa: F401  (fixtures)
    Charla, TEL_CLAUDIO, TEL_NUEVO, _turnos, consultorio,
)


@pytest.fixture
def clinica_completa(consultorio, silvestro, murad):
    """Prótesis (Silvestro, 30') y Ortodoncia (Murad) cargadas como en el panel."""
    db = consultorio
    db.add_all([
        TipoConsulta(nombre="Prótesis", duracion_minutos=30, especialidad="Prótesis",
                     sinonimos=["protesis", "placa", "dentadura"]),
        TipoConsulta(nombre="Ortodoncia", duracion_minutos=30, especialidad="Ortodoncia",
                     sinonimos=["ortodoncia", "aparatos", "brackets"]),
    ])
    silvestro.specialties = ["Extracción", "Implantes", "Prótesis"]
    db.commit()
    return db


# ── 1-2. Orden: obra social → motivo → especialista → turno ────────────────

def test_1_numero_nuevo_obra_social_antes_que_el_motivo(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    t = c.dice("hola, quiero un turno", intencion="sacar_turno")
    assert "obra social o particular" in t
    t = c.dice("Particular")
    assert "¿Para qué sería el turno?" in t and "prótesis" in t
    t = c.dice("una extracción", motivo="Extracción")
    assert "nombre y apellido" in t
    t = c.dice("Ana Pérez", nombre="Ana", apellido="Pérez")
    assert "Silvestro" in t and "horario" in t.lower()


def test_1_numero_conocido_para_quien_y_obra_social_antes_que_el_motivo(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("quiero un turno", intencion="sacar_turno")
    assert "para vos, Claudio" in t
    t = c.dice("Para mí")
    assert t == "¿Seguís atendiéndote como *particular*?"
    t = c.dice("Sí")
    assert "¿Para qué sería el turno?" in t


def test_2_obra_social_ya_confirmada_no_se_repregunta(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    c.dice("Sí")
    c.dice(c.opciones[0])
    assert len(_turnos(clinica_completa)) == 1
    # Mismo chat, otro pedido: ya dijo que es particular.
    t = c.dice("y otro turno para una limpieza", intencion="sacar_turno", motivo="Control",
               para_quien="yo")
    assert "Seguís" not in t and "obra social" not in t.lower()


# ── 4. Si esta semana no hay, la próxima con lugar, explicando el salto ────

def test_4_esta_semana_no_hay_se_explica_el_salto(monkeypatch):
    from backend.services import appointment_service
    lunes = date(2026, 11, 23)
    monkeypatch.setattr(appointment_service, "get_clinic_now",
                        lambda: datetime(2026, 11, 24, 10, 0))
    monkeypatch.setattr(flujo_turno, "_disponibilidad", lambda t, f, os=None: (200, {
        "date": (lunes + timedelta(days=8)).isoformat(), "fecha_texto": "martes 1 de diciembre",
        "available_slots": ["10:00"], "professional": "Dr. Sergio Silvestro"}))
    t = {"motivo": "Extracción", "obra_social": "Particular"}
    texto, _ = flujo_turno._ofrecer_horarios(t)
    assert texto.startswith("Esta semana ya no me quedan turnos para extracción")
    assert "semana que viene" in texto and "martes 1 de diciembre" in texto


# ── 6, 11, 12. Sin cupo: salidas con botones, particular, nunca el mismo texto

def _agenda_sin_lugar_con_obra_social(monkeypatch):
    def disp(t, fecha, os=None):
        if (os or t.get("obra_social")) == "Particular":
            return 200, {"date": "2026-12-03", "fecha_texto": "jueves 3 de diciembre",
                         "available_slots": ["18:00", "18:30"], "professional": "Dra. Lucía Murad"}
        return 200, {"available_slots": [], "message": "sin lugar"}
    monkeypatch.setattr(flujo_turno, "_disponibilidad", disp)


def test_6_12_sin_cupo_ofrece_otro_dia_particular_o_llamar(monkeypatch):
    """Chat real: OSEP sin lugar → "no hay en semanas" → loop → llamar."""
    _agenda_sin_lugar_con_obra_social(monkeypatch)
    t = {"motivo": "Ortodoncia", "obra_social": "OSEP"}
    texto, _ = flujo_turno._ofrecer_horarios(t)
    opciones = flujo_turno.tomar_opciones_ofrecidas()["opciones"]
    assert opciones == [flujo_turno.BOTON_OTRO_DIA, flujo_turno.BOTON_PARTICULAR, flujo_turno.BOTON_LLAMAR]
    assert "Como *particular* sí tengo lugar" in texto
    otra, _ = flujo_turno._ofrecer_horarios(t)
    assert otra != texto, "Repetir el mismo texto dispara el anti-loop"


def test_11_hacelo_sin_obra_social_pasa_a_particular_y_rebusca(monkeypatch):
    _agenda_sin_lugar_con_obra_social(monkeypatch)
    t = {"motivo": "Ortodoncia", "obra_social": "OSEP", "esperando": "sin_cupo",
         "identificado": True, "para_quien": "listo", "orto_vez": "-"}
    flujo_turno._incorporar(t, {}, "hacelo sin obra social", None)
    assert t["obra_social"] == "Particular"
    texto, _ = flujo_turno._siguiente_paso(t, TEL_NUEVO, [])
    assert "jueves 3 de diciembre" in texto


def test_12_boton_llamar_cierra_con_el_telefono(monkeypatch):
    t = {"motivo": "Ortodoncia", "obra_social": "OSEP", "esperando": "sin_cupo"}
    flujo_turno._incorporar(t, {}, "Llamar", None)
    texto, _ = flujo_turno._siguiente_paso(t, TEL_NUEVO, [])
    assert "llamá al consultorio" in texto and t["terminado"]


def test_11_frases_de_particular():
    for frase in ("hacelo sin obra social", "particular", "no tengo obra social", "lo pago yo"):
        assert flujo_turno.dice_particular(frase), frase
    assert not flujo_turno.dice_particular("tengo OSEP")


# ── 13. "Hola, quiero un turno" con el pedido trabado: se reinicia ─────────

def test_13_pedido_trabado_se_reinicia(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero un turno de ortodoncia", intencion="sacar_turno", motivo="Ortodoncia")
    c.dice("Para mí")
    c.dice("Sí")
    c.estado["turno"]["esperando"] = "sin_cupo"
    c.estado["turno"]["sin_cupo"] = 2
    t = c.dice("Hola, quiero un turno", intencion="sacar_turno")
    assert "llam" not in t.lower() and not t.startswith("Perdón")
    assert "¿Para qué sería el turno?" in t
    assert c.estado["turno"]["obra_social"] == "Particular"


# ── 14-15. Ortodoncia: "la doctora" es Murad; 1ª o 2ª consulta; el nombre ──

def test_14_15_ortodoncia_con_la_doctora(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero turno con la doctora por los aparatos", intencion="sacar_turno",
           motivo="Ortodoncia", profesional="la doctora")
    c.dice("Para mí")
    t = c.dice("Sí")
    assert "primera consulta de ortodoncia" in t
    assert c.opciones == [flujo_turno.BOTON_PRIMERA, flujo_turno.BOTON_SEGUNDA]
    t = c.dice(flujo_turno.BOTON_SEGUNDA)
    assert "Claudio, para ortodoncia" in t and "Murad" in t
    t = c.dice(c.opciones[0])
    assert t.startswith("¡Listo, Claudio!")
    (turno,) = _turnos(clinica_completa)
    assert turno.professional.full_name == "Dra. Lucía Murad"
    assert "2ª consulta" in (turno.notes or "")


# ── Prótesis SÍ es turno: Dr. Silvestro, 30 minutos (tipo del panel) ───────

def test_protesis_pide_turno_con_silvestro_de_media_hora(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("me quiero hacer una prótesis", intencion="sacar_turno", motivo="Prótesis")
    c.dice("Para mí")
    t = c.dice("Sí")
    assert "prótesis" in t and "Silvestro" in t
    c.dice(c.opciones[0])
    (turno,) = _turnos(clinica_completa)
    assert turno.reason == "Prótesis"
    assert turno.professional.full_name == "Dr. Sergio Silvestro"
    assert turno.duration_minutes == 30
    assert flujo_turno.es_tramite("me quiero hacer una prótesis") is None


# ── 16-18. Trámites: firmar HC, retirar prótesis → pasar por consultorio ───

def test_16_18_firmar_historia_clinica_no_es_turno(clinica_completa, monkeypatch):
    """Chat real: el bot buscaba "turno de prótesis" y decía que no había."""
    clinica_completa.add(AppConfig(key="EXCEPCIONES_TRAMITES", value="menos los miércoles a la tarde"))
    clinica_completa.commit()
    c = Charla(monkeypatch, TEL_NUEVO)
    t = c.dice("hola, es para ir a firmar la historia clínica de la prótesis", intencion="sacar_turno",
               motivo="Prótesis")
    assert "no hace falta sacar turno" in t and "firmar la historia clínica" in t
    assert "menos los miércoles a la tarde" in t
    assert "no hay turnos" not in t.lower() and "espera" not in t.lower()
    assert _turnos(clinica_completa) == []
    assert flujo_turno.CLAVE not in c.estado


def test_16_tramite_en_medio_de_un_pedido_lo_corta(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero un turno", intencion="sacar_turno")
    t = c.dice("ah no, es para retirar la placa", intencion="dar_datos")
    assert "retirar la prótesis" in t
    assert flujo_turno.CLAVE not in c.estado


def test_16_detector_de_tramites():
    assert flujo_turno.es_tramite("tengo que firmar la HC") == "firmar la historia clínica"
    assert flujo_turno.es_tramite("cuando paso a buscar la dentadura") == "retirar la prótesis"
    assert flujo_turno.es_tramite("le llevo la orden de PAMI") == "traer la orden o la autorización"
    assert flujo_turno.es_tramite("quiero un turno para limpieza") is None


# ── 7-10. "Ya tenía turno": preguntar el día, asociar o llamar ─────────────

def _turno_existente(db, monkeypatch) -> Appointment:
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    c.dice("Sí")
    c.dice(c.opciones[0])
    (turno,) = _turnos(db)
    return turno


def _dia(turno: Appointment) -> str:
    return f"{turno.start_time.day}/{turno.start_time.month}"


def test_7_10_ya_tenia_turno_pregunta_el_dia_y_lo_asocia(clinica_completa, paciente, monkeypatch):
    turno = _turno_existente(clinica_completa, monkeypatch)
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("Ya tenía turno", intencion="ya_tengo_turno")
    assert "¿Qué día tenías el turno?" in t and "para qué" not in t.lower()
    t = c.dice(f"el {_dia(turno)}", dia=_dia(turno))
    assert "encontré el turno" in t and turno.start_time.strftime("%H:%M") in t
    assert c.opciones == [flujo_turno.BOTON_CONFIRMO, flujo_turno.BOTON_CAMBIAR]
    t = c.dice("Lo confirmo")
    assert "Queda confirmado" in t
    assert len(_turnos(clinica_completa)) == 1


def test_9_ya_tenia_turno_y_lo_cambia(clinica_completa, paciente, monkeypatch):
    turno = _turno_existente(clinica_completa, monkeypatch)
    antes = turno.start_time
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice(f"tengo turno el {_dia(turno)} y no llego", intencion="ya_tengo_turno", dia=_dia(turno))
    t = c.dice("Quiero cambiarlo")
    assert "Para cambiarlo" in t or "cambiarlo" in t
    nueva = next(h for h in c.opciones if h != antes.strftime("%H:%M") and ":" in h)
    t = c.dice(nueva)
    assert "Te pasé el turno" in t
    (movido,) = _turnos(clinica_completa)
    assert movido.id == turno.id and movido.start_time != antes


def test_10_dia_que_no_coincide_manda_a_llamar_sin_duplicar(clinica_completa, paciente, monkeypatch):
    turno = _turno_existente(clinica_completa, monkeypatch)
    otro = turno.start_time.date() + timedelta(days=2)
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice(f"mi turno del {otro.day}/{otro.month}", intencion="ya_tengo_turno",
               dia=f"{otro.day}/{otro.month}")
    assert "El único que tenés" in t
    t = c.dice("No", respuesta_si_no="no")
    assert "llamá al consultorio" in t and "repetido" in t
    assert len(_turnos(clinica_completa)) == 1


def test_7_ya_tenia_turno_en_medio_del_pedido_no_pide_motivo(clinica_completa, paciente, monkeypatch):
    """Chat real: citaba "JUEVES 26 A LAS 17:30" y el bot pedía el motivo."""
    turno = _turno_existente(clinica_completa, monkeypatch)
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero un turno", intencion="sacar_turno")
    t = c.dice(f"ya tenía turno el {_dia(turno)}", intencion="dar_datos", dia=_dia(turno))
    assert "para qué" not in t.lower() and "encontré el turno" in t


def test_10_numero_sin_ficha_pregunta_el_dia_y_despues_llamar(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    t = c.dice("ya tenía turno", intencion="ya_tengo_turno")
    assert "¿Qué día tenías el turno?" in t
    t = c.dice("el jueves 26", dia="el jueves 26")
    assert "llamá al consultorio" in t and "repetido" in t


def test_prueba_real_turno_en_ficha_con_otro_formato_de_telefono(clinica_completa, paciente, monkeypatch):
    """24/11 22:06: el turno estaba en una ficha del mismo número escrito de otra
    forma; la búsqueda solo miraba la ficha exacta y decía que no había nada."""
    from datetime import datetime as dt
    from backend.models.patient import Patient
    db = clinica_completa
    otra = Patient(first_name="Claudio", last_name="Luna", phone="2604590071", insurance_name="Particular")
    db.add(otra)
    db.commit()
    from backend.models.professional import Professional
    turno = Appointment(patient_id=otra.id, professional_id=db.query(Professional).first().id,
                        start_time=dt.combine(date.today() + timedelta(days=1), dt.min.time()).replace(hour=9),
                        duration_minutes=30, reason="Extracción")
    db.add(turno)
    db.commit()
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("reset\nHola, ya tenía turno\nel jueves 26", intencion="ya_tengo_turno", dia="el jueves 26")
    assert "llamá" not in t.lower() and ("El único que tenés" in t or "encontré el turno" in t)
    if "El único que tenés" in t:
        t = c.dice("Sí", respuesta_si_no="si")
    assert "encontré el turno" in t and "09:00" in t


# ── 19-21. La secretaria gestiona: el bot no la pisa ────────────────────────

def test_20_21_gestion_humana_reciente_el_bot_no_pisa(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.estado = {"gestion_humana": True}
    t = c.dice("tenés primeros de diciembre? el 3?", intencion="dar_datos", dia="el 3 de diciembre")
    assert "secretaria" in t
    assert c.estado.get("pausar") is True and "gestion_humana" not in c.estado
    assert _turnos(clinica_completa) == []


def test_19_la_marca_de_la_secretaria_queda_y_no_entra_al_historial(db):
    import asyncio
    from backend.routers.whatsapp_router import (
        _pausar_por_intervencion_humana, gestion_humana_reciente, get_or_create_session,
        load_history,
    )
    jid = "5492604305278@s.whatsapp.net"
    asyncio.run(_pausar_por_intervencion_humana(jid, "SOY LA SECRETARIA, LA ESPERAMOS"))
    session = get_or_create_session(db, jid)
    assert gestion_humana_reciente(db, session.id)
    historial = load_history(db, session.id)
    assert all(m["role"] != "system" for m in historial)
    assert historial[-1]["content"] == "SOY LA SECRETARIA, LA ESPERAMOS"


# ── Lo que encontró el simulador con IA real (24/11) ────────────────────────

def test_sim_firma_sigue_hablando_del_tramite(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("necesito saber cuándo puedo pasar a firmar la historia clínica", intencion="pregunta")
    t = c.dice("¿Podría pasar mañana a la mañana?", intencion="pregunta", dia="mañana")
    assert "obra social" not in t.lower() and "para qué" not in t.lower()
    assert "No hace falta turno" in t or "no atiende" in t


def test_sim_ortodoncia_pasa_a_particular_no_repite_la_oferta(monkeypatch):
    monkeypatch.setattr(flujo_turno, "_disponibilidad", lambda t, f, os=None: (200, {
        "date": "2026-11-30", "fecha_texto": "lunes 30 de noviembre", "available_slots": ["17:30"],
        "professional": "Dra. Elena Murad"}))
    t = {"motivo": "Ortodoncia", "obra_social": "OSEP", "orto_vez": "-", "identificado": True,
         "para_quien": "listo", "esperando": "horario",
         "oferta": {"fecha": "2026-11-30", "fecha_texto": "lunes 30 de noviembre",
                    "profesional": "Dra. Elena Murad", "slots": ["17:30"]}}
    flujo_turno._incorporar(t, {}, "Hacelo sin obra social", None)
    texto, _ = flujo_turno._siguiente_paso(t, TEL_NUEVO, [])
    assert texto.startswith("Dale, lo busco como particular.")


def test_sim_gracias_despues_de_agendar_es_un_cierre(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    c.dice("Sí")
    c.dice(c.opciones[0])
    t = c.dice("Gracias, quedo a la espera. Nos vemos el jueves.", intencion="saludo_o_cierre",
               dia="el jueves")
    assert t.startswith("¡Gracias a vos!")


# ── Prueba real de Claudio (24/11, 22:05) ───────────────────────────────────

def _router(monkeypatch, chat_falso, rescate=None):
    from backend.routers import whatsapp_router as er
    enviados = []

    async def enviar(jid, texto, *a, **k):
        enviados.append(texto)
        return True

    monkeypatch.setattr(er, "chat", chat_falso)
    monkeypatch.setattr(er, "_responder", enviar)
    monkeypatch.setattr(er, "send_whatsapp_message", enviar)
    monkeypatch.setattr(er, "resolver_loop", rescate or (lambda *a: (None, None, None)))
    return er, enviados


def test_reset_pegado_a_otros_mensajes_resetea_y_sigue(db, monkeypatch):
    import asyncio
    import json
    visto = {}

    def chat_falso(text, history, phone, estado):
        visto.update(text=text, history=history, estado=estado)
        return "respuesta", None, estado

    er, enviados = _router(monkeypatch, chat_falso)
    jid = "5492605550997@s.whatsapp.net"
    session = er.get_or_create_session(db, jid)
    session.context_data = json.dumps({"tramite": "firmar la historia clínica"})
    db.commit()
    asyncio.run(er.handle_text_message(jid, "reset\nHola, ya tenía turno\nel jueves 26",
                                       partes=["reset", "Hola, ya tenía turno", "el jueves 26"]))
    assert visto["text"] == "Hola, ya tenía turno\nel jueves 26"
    assert visto["history"] == [] and visto["estado"] == {}
    assert enviados == ["respuesta"]


def test_el_rescate_viejo_no_pisa_al_guion(db, monkeypatch):
    import asyncio

    def chat_falso(text, history, phone, estado):
        return "Llamá al consultorio.", None, {"_guion": True}

    def rescate(*a):
        raise AssertionError("El rescate no debe correr sobre una respuesta del guion")

    er, enviados = _router(monkeypatch, chat_falso, rescate)
    asyncio.run(er.handle_text_message("5492605550996@s.whatsapp.net", "Hola, ya tenía turno"))
    assert enviados == ["Llamá al consultorio."]


def test_hola_quiero_turno_tras_mmm_no_pide_perdon(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero un turno", intencion="sacar_turno")
    c.dice("mmm")
    t = c.dice("Hola, quiero un turno", intencion="sacar_turno")
    assert not t.startswith("Perdón") and "llam" not in t.lower()


def test_profesional_ocupado_en_otra_sede_no_se_ofrece(clinica_completa, paciente, silvestro, monkeypatch):
    """24/11: la agenda ofrecía las 17:00 y la base las rechazaba porque el
    profesional tenía un turno cargado con la sede escrita distinto."""
    from datetime import datetime as dt
    from backend.services.appointment_service import get_available_slots
    db = clinica_completa
    dia = date.today() + timedelta(days=1)
    while dia.weekday() != 3:
        dia += timedelta(days=1)
    db.add(Appointment(patient_id=paciente.id, professional_id=silvestro.id,
                       start_time=dt.combine(dia, dt.min.time()).replace(hour=19),
                       duration_minutes=60, reason="Control", location="Silproden"))
    db.commit()
    r = get_available_slots(db, dia.isoformat(), "San Rafael", "Extracción", "Particular")
    if r.get("date") == dia.isoformat():
        assert "19:00" not in r["available_slots"] and "19:30" not in r["available_slots"]


def test_cancelar_por_el_guion(clinica_completa, paciente, monkeypatch):
    turno = _turno_existente(clinica_completa, monkeypatch)
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("quiero cancelar mi turno", intencion="cancelar_turno")
    assert "¿Confirmás que cancelo" in t and turno.start_time.strftime("%H:%M") in t
    t = c.dice(flujo_turno.BOTON_CANCELAR_SI)
    assert t.startswith("Listo, cancelé")
    clinica_completa.expire_all()
    assert clinica_completa.get(Appointment, turno.id).status.value == "cancelled"
    t = c.dice("Gracias, que tengas buena noche", intencion="saludo_o_cierre")
    assert "¿Para qué" not in t and ("gracias" in t.lower() or "de nada" in t.lower())


def test_turno_repetido_ofrece_el_que_ya_tiene(clinica_completa, paciente, monkeypatch):
    turno = _turno_existente(clinica_completa, monkeypatch)
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí")
    c.dice("Sí")
    t = c.dice(c.opciones[1] if c.opciones[0] == turno.start_time.strftime("%H:%M") else c.opciones[0])
    assert "Ya tenés un turno de extracción" in t and "problema del sistema" not in t
    assert c.opciones == [flujo_turno.BOTON_CONFIRMO, flujo_turno.BOTON_CAMBIAR]
    t = c.dice(flujo_turno.BOTON_CONFIRMO)
    assert "Queda confirmado" in t
    assert len(_turnos(clinica_completa)) == 1


def test_despues_de_mandar_a_llamar_no_pregunta_en_circulo(clinica_completa, paciente, monkeypatch):
    _turno_existente(clinica_completa, monkeypatch)
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("tenía turno el 15/12", intencion="ya_tengo_turno", dia="15/12")
    t = c.dice("No, era el 15/12", respuesta_si_no="no", dia="15/12")
    assert "llamá al consultorio" in t
    t = c.dice("pero no quiero llamar, ya tenía turno", intencion="ya_tengo_turno")
    assert "llamar" in t and "¿Qué día" not in t


def test_hijo_de_8_anios_es_odontopediatria(clinica_completa, paciente, monkeypatch):
    """Sim 24/11: "mi hijo ... le duele un diente" se rechazaba como Odontopediatría."""
    clinica_completa.add(TipoConsulta(nombre="Odontopediatría", duracion_minutos=30, especialidad=None,
                                      sinonimos=["niño", "nene", "hijo", "hija"]))
    clinica_completa.commit()
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("turno para mi hijo Tomás de 8 años, le duele un diente", intencion="sacar_turno",
           motivo="Odontopediatría", para_quien="otra_persona", nombre="Tomás")
    c.dice("Particular")
    t = c.dice("Benítez", apellido="Benítez")
    assert "odontopediatría" in t.lower(), t


# ── Simulación completa 24/11 23:17 ─────────────────────────────────────────

def test_sim_pregunta_sobre_el_turno_no_recibe_respuesta_generica(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    llamadas = []
    monkeypatch.setattr(flujo_turno, "responder_pregunta", lambda p: llamadas.append(p) or "LLAMÁ")
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    t = c.dice("¿puedo tener el turno igual?", intencion="pregunta", pregunta="¿puedo tener el turno igual?")
    assert "LLAMÁ" not in t and llamadas == []


def test_sim_rechaza_al_otro_profesional_y_se_cierra(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("control de ortodoncia con Silvestro", intencion="sacar_turno", motivo="Ortodoncia",
           profesional="Silvestro")
    c.dice("Para mí"); c.dice("Sí"); t = c.dice(flujo_turno.BOTON_SEGUNDA)
    assert "con ella" in t
    t = c.dice("No, gracias. Voy a buscar otro profesional", respuesta_si_no="no")
    assert t.startswith("Entendido") and _turnos(clinica_completa) == []
    assert flujo_turno.CLAVE not in c.estado


def test_sim_se_despide_en_medio_de_la_oferta(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí"); c.dice("Sí")
    t = c.dice("si no hay hoy busco en otro lado, gracias igual", intencion="saludo_o_cierre")
    assert t.startswith("Entendido") and not t.startswith("Perdón")


def test_sim_urgencia_avisa_sobreturno(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("tengo un dolor intenso y la cara hinchada, necesito turno", intencion="sacar_turno")
    assert "urgencia" in t and "sobreturno" in t


def test_sim_direccion_y_horarios_sin_pedido(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    t = c.dice("¿dónde queda el consultorio y en qué horario atienden?", intencion="pregunta",
               pregunta="¿dónde queda el consultorio y en qué horario atienden?")
    assert "Av. San Martín" in t


def test_sim_dia_equivocado_con_un_solo_turno_pregunta_si_es_ese(clinica_completa, paciente, monkeypatch):
    turno = _turno_existente(clinica_completa, monkeypatch)
    otro = turno.start_time.date() + timedelta(days=2)
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice(f"quiero mover mi turno del {otro.day}/{otro.month}", intencion="reprogramar_turno",
               dia=f"{otro.day}/{otro.month}")
    assert "El único que tenés" in t and turno.start_time.strftime("%H:%M") in t
    t = c.dice("Sí")
    assert "Para cambiarlo" in t


def test_sim_insiste_hoy_no_da_vueltas(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí"); c.dice("Sí")
    hoy = date.today()
    respuestas = [c.dice(f"necesito hoy {i}", dia="hoy", quiere_otro_dia=True) for i in range(4)]
    assert any("sobreturno" in r for r in respuestas)
    assert sum(r.startswith("Perdón, no te entendí") for r in respuestas) <= 1


# ── Prueba real 25/11 9:48 ──────────────────────────────────────────────────

def test_reset_en_la_misma_linea_de_un_mensaje(db, monkeypatch):
    import asyncio
    import json
    visto = {}

    def chat_falso(text, history, phone, estado):
        visto.update(text=text, estado=estado)
        return "respuesta", None, estado

    er, enviados = _router(monkeypatch, chat_falso)
    jid = "5492605550995@s.whatsapp.net"
    session = er.get_or_create_session(db, jid)
    session.context_data = json.dumps({"turno": {"activo": True, "obra_social": "Particular"}})
    db.commit()
    asyncio.run(er.handle_text_message(jid, "reset\ntengo un dolor muy fuerte",
                                       partes=["reset\ntengo un dolor muy fuerte"]))
    assert visto["text"] == "tengo un dolor muy fuerte" and visto["estado"] == {}


def test_hora_despues_de_agendar_mueve_ese_turno(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí"); c.dice("Sí")
    libres = [h for h in c.opciones if ":" in h]
    c.dice(libres[0])
    (turno,) = _turnos(clinica_completa)
    t = c.dice(libres[1], hora=libres[1])
    assert "Te pasé el turno" in t and libres[1] in t, t
    (movido,) = _turnos(clinica_completa)
    assert movido.id == turno.id and movido.start_time.strftime("%H:%M") == libres[1]


def test_fecha_con_barra_aunque_ya_haya_pasado():
    from bot.flujo_turno import _fecha_iso
    assert _fecha_iso("el 24/11").endswith("-11-24")
    assert _fecha_iso("el 3/12").endswith("-12-03")


# ── Prueba real 25/11 ~10:00 ────────────────────────────────────────────────

def test_para_quien_no_se_supone_si_no_lo_dijo(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("quiero un turno", intencion="sacar_turno", para_quien="yo")
    assert "para vos, Claudio, o para otra persona" in t


def test_para_mi_dicho_si_vale(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    t = c.dice("quiero un turno para mí", intencion="sacar_turno", para_quien="yo")
    assert "para otra persona" not in t


def test_otro_dia_de_la_lista_vieja_mueve_el_turno_recien_agendado(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí"); c.dice("Sí")
    t = c.dice(c.opciones[0])
    assert "Si querés otro horario, decímelo y lo cambio" in t
    (turno,) = _turnos(clinica_completa)
    antes = turno.start_time
    t = c.dice("Otro día", quiere_otro_dia=True)
    assert "Para cambiarlo" in t and "para otra persona" not in t, t
    t = c.dice(next(h for h in c.opciones if ":" in h))
    assert "Te pasé el turno" in t
    (movido,) = _turnos(clinica_completa)
    assert movido.id == turno.id and movido.start_time.date() > antes.date()


# ── Chat real de un paciente, 25/11 10:07 ───────────────────────────────────

def test_real_precio_se_contesta_y_sigue(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    monkeypatch.setattr(flujo_turno, "responder_pregunta", lambda p: "El precio lo consultás llamando.")
    c.dice("quiero un turno", intencion="sacar_turno")
    t = c.dice("Si me dirías que sale la consulta?", intencion="pregunta",
               pregunta="¿qué sale la consulta?")
    assert t.startswith("El precio lo consultás llamando.")
    t = c.dice("Que sale una consulta", intencion="pregunta", pregunta="Que sale una consulta")
    assert "precio" in t.lower()


def test_real_otro_dia_ignora_la_fecha_que_invente_la_ia(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("quiero un turno de control", intencion="sacar_turno", motivo="Control")
    c.dice("Particular")
    c.dice("Julián Pereyra", nombre="Julián", apellido="Pereyra")
    primera = c.estado["turno"]["oferta"]["fecha"]
    # La IA "lee" una fecha anterior en el mensaje del botón.
    from datetime import date as d_, timedelta as td
    antes = (d_.fromisoformat(primera) - td(days=1))
    c.dice("Otro día", dia=f"{antes.day}/{antes.month}")
    assert c.estado["turno"]["oferta"]["fecha"] > primera


def test_real_dato_util_no_pide_perdon(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("Hola, que sale una consulta", intencion="sacar_turno")
    t = c.dice("En la tarde viernes", dia="viernes", preferencia_horaria="tarde")
    assert t.startswith("Dale, lo anoto") and "obra social" in t


def test_oferta_explica_como_elegir(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("quiero un turno de control", intencion="sacar_turno", motivo="Control")
    c.dice("Particular")
    t = c.dice("Julián Pereyra", nombre="Julián", apellido="Pereyra")
    slots = c.estado["turno"]["oferta"]["slots"]
    assert "Horarios libres:" in t and f"1️⃣ {slots[0]}" in t and "Respondé con el *número*" in t
    # Botones: los dos más cercanos + "Otro día".
    assert c.opciones == slots[:2] + [flujo_turno.BOTON_OTRO_DIA]



# ── Chat real 25/11 tarde: botones visibles, conducto "bueno", presencial ───

def test_elige_por_numero_de_la_lista(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    c.dice("quiero un turno de control", intencion="sacar_turno", motivo="Control")
    c.dice("Particular")
    c.dice("Julián Pereyra", nombre="Julián", apellido="Pereyra")
    slots = c.estado["turno"]["oferta"]["slots"]
    t = c.dice("3")
    assert t.startswith("¡Listo") and slots[2] in t


def test_numero_de_la_lista_variantes():
    slots = ["09:00", "10:30", "17:00"]
    assert flujo_turno._numero_elegido("el 2", slots) == "10:30"
    assert flujo_turno._numero_elegido("2️⃣", slots) == "10:30"
    assert flujo_turno._numero_elegido("opción 3", slots) == "17:00"
    assert flujo_turno._numero_elegido("10", slots) is None        # es una hora, no un número de la lista
    assert flujo_turno._numero_elegido("17:00", slots) is None


def test_conducto_bueno_agenda_la_consulta(clinica_completa, paciente, monkeypatch):
    from backend.services.appointment_service import TEXTO_SIN_CONSULTA_PREVIA
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero terminar un conducto", intencion="sacar_turno", motivo="Conducto")
    c.dice("Para mí"); c.dice("Sí")
    t = c.dice("Ya hice la consulta", respuesta_si_no="si")
    assert t == TEXTO_SIN_CONSULTA_PREVIA
    t = c.dice("bueno")
    assert "¿Para qué sería el turno?" not in t and "consulta por conducto" in t.lower(), t


def test_me_acerco_presencial_cierra(clinica_completa, paciente, monkeypatch):
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero un turno", intencion="sacar_turno")
    c.dice("Para mí"); c.dice("Sí")
    t = c.dice("me acerco mañana presencial", dia="mañana")
    assert t.startswith("Entendido") and flujo_turno.CLAVE not in c.estado


# ── Prueba de Claudio 25/11 noche: PAMI sin lugar, un solo horario ──────────

def test_pami_sin_lugar_no_ofrece_particular(monkeypatch):
    monkeypatch.setattr(flujo_turno, "_disponibilidad",
                        lambda t, f, os=None: (200, {"available_slots": [], "message": "sin lugar"}))
    t = {"motivo": "Extracción", "obra_social": "PAMI"}
    texto, _ = flujo_turno._ofrecer_horarios(t)
    ops = flujo_turno.tomar_opciones_ofrecidas()["opciones"]
    assert flujo_turno.BOTON_PARTICULAR not in ops and "particular" not in texto.lower()


def test_un_solo_horario_se_dice_cual(monkeypatch):
    t = {"motivo": "Extracción", "obra_social": "Particular", "identificado": True, "para_quien": "listo",
         "orto_vez": "-", "esperando": "horario",
         "oferta": {"fecha": "2026-12-02", "fecha_texto": "miércoles 2 de diciembre de 2026",
                    "profesional": "Dr. Sergio Silvestro", "slots": ["09:00"]}}
    texto, _ = flujo_turno._siguiente_paso(t, TEL_NUEVO, [])
    assert "solo me queda *09:00*" in texto and "Otro día" in texto



def test_confirmacion_sin_botones_cuando_escribe_la_hora(clinica_completa, paciente, monkeypatch):
    """Captura de Claudio 26/11: "¡Listo!" seguía mostrando 10:00 / 11:00 / Otro día."""
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero sacarme una muela", intencion="sacar_turno", motivo="Extracción")
    c.dice("Para mí"); c.dice("Sí")
    oferta = c.estado["turno"]["oferta"]
    from datetime import date as d_, timedelta as td
    otro = d_.fromisoformat(oferta["fecha"]) + td(days=1)
    while otro.weekday() not in (2, 3):
        otro += td(days=1)
    t = c.dice(f"mejor el {otro.day}/{otro.month} a las 10:00", dia=f"{otro.day}/{otro.month}", hora="10:00")
    assert t.startswith("¡Listo") and c.opciones == [], (t, c.opciones)
    # Y eligiendo de la lista, tampoco.
    c2 = Charla(monkeypatch, TEL_NUEVO)
    c2.dice("quiero un turno de control", intencion="sacar_turno", motivo="Control")
    c2.dice("Particular"); c2.dice("Julián Pereyra", nombre="Julián", apellido="Pereyra")
    t = c2.dice("1")
    assert t.startswith("¡Listo") and c2.opciones == []
