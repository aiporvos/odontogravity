"""Las 6 pruebas que Claudio hace por WhatsApp, con la IA real entendiendo cada
mensaje (solo `-m conversacion` y con OPENAI_API_KEY; centavos). Se corren
antes de pedirle una prueba: si acá no sale bien, no se le pide nada."""
import os

import pytest

from bot import ai_agent, flujo_turno
from tests.test_flujo_turno import TEL_CLAUDIO, _turnos, consultorio  # noqa: F401
from tests.test_pedido_unificado_24_11 import clinica_completa  # noqa: F401

pytestmark = [pytest.mark.conversacion,
              pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="Sin OPENAI_API_KEY")]


class Real:
    def __init__(self):
        self.history, self.estado, self.opciones, self.log = [], {}, [], []

    def dice(self, m):
        texto, op, self.estado = ai_agent.chat(m, self.history, TEL_CLAUDIO, self.estado)
        self.estado.pop("_guion", None)
        self.history += [{"role": "user", "content": m}, {"role": "assistant", "content": texto}]
        self.opciones = (op or {}).get("opciones") or []
        self.log.append(f"P: {m}\nB: {texto}  {self.opciones}")
        return texto

    def toca(self, pred):
        return self.dice(next(o for o in self.opciones if pred(o)))


def _ver(c):
    print("\n" + "\n".join(c.log))


def test_1_protesis(clinica_completa, paciente):
    c = Real()
    t = c.dice("Hola, quiero un turno"); assert "para vos, Claudio" in t
    t = c.dice("Para mí"); assert "particular" in t.lower()
    t = c.dice("Sí"); assert "¿Para qué sería el turno?" in t
    t = c.dice("para hacerme una prótesis"); assert "Silvestro" in t, t
    t = c.dice("prefiero a la tarde"); assert "Silvestro" in t
    t = c.toca(lambda o: ":" in o); _ver(c)
    assert t.startswith("¡Listo, Claudio!")
    (turno,) = _turnos(clinica_completa)
    assert turno.reason == "Prótesis" and turno.duration_minutes == 30


def test_2_ortodoncia_osep_a_particular(clinica_completa, paciente):
    from backend.models.insurance import Insurance
    if not clinica_completa.query(Insurance).filter(Insurance.name == "OSEP").first():
        clinica_completa.add(Insurance(name="OSEP", is_active=True))
        clinica_completa.commit()
    c = Real()
    c.dice("Hola, se me soltó un alambre de los aparatos, quiero turno con la doctora. Tengo OSEP")
    for _ in range(4):
        if flujo_turno.BOTON_SEGUNDA in c.opciones:
            c.toca(lambda o: o == flujo_turno.BOTON_SEGUNDA)
        elif "Para mí" in c.opciones:
            c.dice("Para mí")
        elif "Sí" in c.opciones:
            c.dice("Sí")
        else:
            break
    t = c.dice("hacelo sin obra social")
    assert "llamá" not in t.lower() and "Murad" in t, t
    t = c.toca(lambda o: ":" in o); _ver(c)
    assert t.startswith("¡Listo")
    (turno,) = _turnos(clinica_completa)
    assert turno.insurance_name == "Particular" and "Murad" in turno.professional.full_name


def test_3_firma_hc(clinica_completa, paciente):
    c = Real()
    t = c.dice("Hola, tengo que ir a firmar la historia clínica de la prótesis, ¿cuándo puedo pasar?")
    assert "no hace falta sacar turno" in t
    t = c.dice("¿puedo ir el miércoles a la mañana?"); _ver(c)
    assert "obra social" not in t.lower() and "para qué" not in t.lower()
    assert _turnos(clinica_completa) == []


def test_3_firma_hc_todo_pegado(clinica_completa, paciente):
    c = Real()
    t = c.dice("reset\nHola, tengo que ir a firmar la historia clínica de la prótesis, ¿cuándo puedo pasar?\n"
               "¿puedo ir el miércoles a la mañana?"); _ver(c)
    assert "no hace falta sacar turno" in t


def _sacar_turno(db):
    c = Real()
    c.dice("Hola, quiero un turno"); c.dice("Para mí"); c.dice("Sí")
    c.dice("para sacarme una muela"); c.toca(lambda o: ":" in o)
    (turno,) = _turnos(db)
    return turno


def test_4_ya_tenia_turno_y_lo_cambia(clinica_completa, paciente):
    turno = _sacar_turno(clinica_completa)
    antes = turno.start_time
    from backend.services.appointment_service import fecha_en_palabras
    dia = fecha_en_palabras(antes.date()).split(" de 20")[0]      # "miércoles 25 de noviembre"
    c = Real()
    t = c.dice("Hola, ya tenía turno"); assert "qué día" in t.lower(), t
    t = c.dice(f"el {dia}"); assert "encontré el turno" in t, t
    t = c.toca(lambda o: o == flujo_turno.BOTON_CAMBIAR)
    t = c.toca(lambda o: ":" in o and o != antes.strftime("%H:%M")); _ver(c)
    assert "Te pasé el turno" in t
    (movido,) = _turnos(clinica_completa)
    assert movido.id == turno.id and movido.start_time != antes


def test_4_ya_tenia_turno_dia_equivocado_y_pegado(clinica_completa, paciente):
    turno = _sacar_turno(clinica_completa)
    c = Real()
    t = c.dice("reset\nHola, ya tenía turno\nel 15 de diciembre")
    assert "El único que tenés" in t and "llam" not in t.lower(), t
    t = c.dice("Sí"); _ver(c)
    assert "encontré el turno" in t


def test_5_dia_que_no_existe(clinica_completa, paciente):
    c = Real()
    t = c.dice("Hola, mi turno del 15 de diciembre")
    t = c.dice("sí, el 15 de diciembre"); _ver(c)
    assert "llamá al consultorio" in t and _turnos(clinica_completa) == []


def test_6_pedido_trabado(clinica_completa, paciente):
    c = Real()
    c.dice("quiero un turno"); c.dice("mmm")
    t = c.dice("Hola, quiero un turno"); _ver(c)
    assert "llam" not in t.lower() and not t.startswith("Perdón")
