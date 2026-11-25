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
    assert "llam" not in t.lower()
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
    assert "¿Me decís qué día" in t
    t = c.dice(f"el {otro.day}/{otro.month}, seguro", dia=f"{otro.day}/{otro.month}")
    assert "llamá al consultorio" in t and "repetido" in t
    assert len(_turnos(clinica_completa)) == 1


def test_7_ya_tenia_turno_en_medio_del_pedido_no_pide_motivo(clinica_completa, paciente, monkeypatch):
    """Chat real: citaba "JUEVES 26 A LAS 17:30" y el bot pedía el motivo."""
    turno = _turno_existente(clinica_completa, monkeypatch)
    c = Charla(monkeypatch, TEL_CLAUDIO)
    c.dice("quiero un turno", intencion="sacar_turno")
    t = c.dice(f"ya tenía turno el {_dia(turno)}", intencion="dar_datos", dia=_dia(turno))
    assert "para qué" not in t.lower() and "encontré el turno" in t


def test_10_numero_sin_ficha_manda_a_llamar(clinica_completa, monkeypatch):
    c = Charla(monkeypatch, TEL_NUEVO)
    t = c.dice("ya tenía turno", intencion="ya_tengo_turno")
    assert "llamá al consultorio" in t


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
