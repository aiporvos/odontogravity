"""Elegir un horario de la lista agenda por código, sin pasar por la IA.

Prueba real 15/11/2026: el bot ofreció "lunes 30 de noviembre de 2026 a las
12:00, 17:00 o 19:00", el paciente tocó "12:00" y el modelo, en vez de agendar,
volvió a consultar y le mostró la misma lista. Tuvo que elegir dos veces.
"""
import pytest

from bot import ai_agent
from bot.tools import appointment_tools as tools
from bot.tools.appointment_tools import eleccion_de_horario

OFERTA = ("Tengo turno con Dra. Elena Murad el lunes 30 de noviembre de 2026 a "
          "las 12:00, 17:00 o 19:00. ¿Cuál te sirve?")


@pytest.mark.parametrize("dicho,hora", [
    ("12:00", "12:00"), ("a las 17", "17:00"), ("19", "19:00"), ("17:00 por favor", "17:00"),
])
def test_reconoce_la_eleccion(dicho, hora):
    assert eleccion_de_horario(dicho, OFERTA) == ("2026-11-30", hora, "Dra. Elena Murad")


def test_la_fecha_es_la_escrita_no_el_proximo_lunes():
    """"lunes" no es "el próximo lunes": la fecha sale completa del mensaje."""
    fecha, _, _ = eleccion_de_horario("12:00", OFERTA)
    assert fecha == "2026-11-30"


@pytest.mark.parametrize("dicho", [
    "15:00",                                   # no se le ofreció
    "mejor el martes a las 12:00 si se puede",  # pide otra cosa
    "hola",
])
def test_lo_que_no_es_elegir_de_la_lista_va_a_la_ia(dicho):
    assert eleccion_de_horario(dicho, OFERTA) is None


def test_sin_oferta_previa_no_hay_eleccion():
    assert eleccion_de_horario("12:00", "¿Tenés obra social?") is None


def _chat(monkeypatch, resultado, confirmacion):
    from tests.test_no_confirmar_lo_que_no_se_hizo import _Cliente, _Mensaje
    llamadas = []

    def tool(nombre, args):
        llamadas.append((nombre, args))
        if confirmacion:
            tools.registrar_confirmacion_turno(confirmacion)
        return resultado

    monkeypatch.setattr(ai_agent, "execute_tool", tool)
    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda: (_Cliente([_Mensaje("¿A nombre de quién agendo el turno?")]), "m"))
    monkeypatch.setattr(ai_agent, "corregir_apellidos", lambda t: t)
    history = [{"role": "user", "content": "Necesito la consulta"},
               {"role": "assistant", "content": OFERTA}]
    texto, _, _ = ai_agent.chat("12:00", history, "5492604046245",
                                {"motivo": "Consulta por conducto", "obra_social": "Particular"})
    return texto, llamadas


def test_elegir_agenda_de_una(monkeypatch):
    conf = "Listo 😊 Te agendé para el **lunes 30 de noviembre de 2026 a las 12:00** con la Dra. Elena Murad."
    texto, llamadas = _chat(monkeypatch, "✅ Turno agendado", conf)
    assert texto == conf
    assert llamadas[0] == ("agendar_turno", {
        "reason": "Consulta por conducto", "preferred_date": "2026-11-30 12:00",
        "profesional": "Dra. Elena Murad",
    })


def test_si_falta_el_nombre_lo_pide_la_ia_sin_repetir_la_lista(monkeypatch):
    texto, llamadas = _chat(monkeypatch, "❌ Preguntale a nombre de quién agendás el turno.", None)
    assert llamadas[0][0] == "agendar_turno"
    assert "12:00, 17:00" not in texto


@pytest.mark.parametrize("dicho,esperado", [
    ("Florencia Ramos", ("Florencia", "Ramos")),
    ("A nombre de Florencia Ramos, por favor.", ("Florencia", "Ramos")),
    ("maría josé de la torre", ("María", "José De La Torre")),
])
def test_reconoce_un_nombre(dicho, esperado):
    from bot.tools.appointment_tools import nombre_dicho
    assert nombre_dicho(dicho) == esperado


@pytest.mark.parametrize("dicho", ["si", "Sí, por favor, como particular.", "17:00", "Swiss Medical sí", "hola"])
def test_no_confunde_otra_cosa_con_un_nombre(dicho):
    from bot.tools.appointment_tools import nombre_dicho
    assert nombre_dicho(dicho) is None


def test_numero_nuevo_elige_y_despues_dice_el_nombre(monkeypatch):
    """Simulación 15/11: eligió 17:00, se le pidió el nombre, lo dijo, y el
    bot lo buscó como obra social. Ahora se agenda con el horario guardado."""
    from tests.test_no_confirmar_lo_que_no_se_hizo import _Cliente, _Mensaje
    oferta = ("Tengo turno con Dra. Elena Murad el martes 17 de noviembre de 2026 a las "
              "17:00, 17:45 o 18:15. ¿Cuál te sirve?")
    llamadas = []
    conf = "Listo 😊 Te agendé para el **martes 17 de noviembre de 2026 a las 17:00**."

    def tool(nombre, args):
        llamadas.append(args)
        if args.get("patient_name"):
            tools.registrar_confirmacion_turno(conf)
            return "✅"
        return "❌ Es la primera vez que este número saca turno. Preguntale a nombre de quién."

    monkeypatch.setattr(ai_agent, "execute_tool", tool)
    monkeypatch.setattr(ai_agent, "_build_client",
                        lambda: (_Cliente([_Mensaje("¿A nombre de quién agendo el turno?")]), "m"))
    monkeypatch.setattr(ai_agent, "corregir_apellidos", lambda t: t)
    estado0 = {"motivo": "Arreglos", "obra_social": "Particular"}

    texto1, _, estado1 = ai_agent.chat("17:00", [{"role": "assistant", "content": oferta}],
                                       "5492605550114", estado0)
    assert estado1.get("turno_elegido") == {"fecha": "2026-11-17", "hora": "17:00",
                                            "profesional": "Dra. Elena Murad"}

    historia = [{"role": "assistant", "content": oferta}, {"role": "user", "content": "17:00"},
                {"role": "assistant", "content": texto1}]
    texto2, _, estado2 = ai_agent.chat("Florencia Ramos", historia, "5492605550114", estado1)

    assert texto2 == conf
    assert llamadas[-1]["patient_name"] == "Florencia"
    assert llamadas[-1]["preferred_date"] == "2026-11-17 17:00"
    assert "turno_elegido" not in estado2


def test_frase_larga_con_la_hora_tambien_es_elegir():
    assert eleccion_de_horario("Me viene bien a las 17:00.", OFERTA) == ("2026-11-30", "17:00", "Dra. Elena Murad")
