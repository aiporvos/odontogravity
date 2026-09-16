"""Que "dejé la consulta para recepción" signifique que alguien la va a ver.

H03, I02 y S01 del plan de QA. Caso real del 08/09/2026:

    paciente: Escribo para cancelar mi turno de mañana, se me complica
    bot:      No encuentro turnos asociados a este número. ¿Me pasás tu DNI?
    paciente: 35878761
    bot:      No encuentro turnos asociados a ese DNI. ¿El nombre y apellido?
    paciente: Taboada Estela
    bot:      No encuentro turnos con ese DNI. ¿Podrías darme el nombre y
              apellido de OTRA persona para verificar?

Su turno existía: al día siguiente a las 09:00. Su ficha venía de la agenda de
papel, sin DNI ni teléfono —como 380 de las 446 fichas activas— así que no había
forma de identificarla. Nadie se enteró y el turno siguió en la agenda.

Pausar el bot no es avisarle a nadie: antes eso era todo lo que pasaba.
"""
import pytest

from backend.models.derivacion import Derivacion, EstadoDerivacion, MotivoDerivacion
from backend.services.derivaciones import (
    crear_derivacion, hay_pendiente, pendientes, resolver,
)

JID = "5492604590071@s.whatsapp.net"


# ── El caso queda registrado ────────────────────────────────────────────────

def test_crea_el_caso_con_lo_que_el_paciente_aporto(db):
    d = crear_derivacion(
        db, JID, MotivoDerivacion.identidad,
        "Quiere cancelar su turno de mañana y no se pudo verificar quién es.",
        datos_aportados="DNI 35878761, Taboada Estela, turno de mañana 09:00",
    )
    assert d is not None
    assert d.estado == EstadoDerivacion.pendiente
    assert "35878761" in d.datos_aportados, (
        "Sin los datos que ya dio, recepción se los tiene que volver a pedir"
    )
    assert d.telefono.endswith("590071")


def test_aparece_en_la_bandeja(db):
    crear_derivacion(db, JID, MotivoDerivacion.clinico, "La prótesis le lastima.")
    assert len(pendientes(db)) == 1


def test_dos_mensajes_sobre_lo_mismo_no_son_dos_casos(db):
    """Recepción no tiene que ver el mismo problema cinco veces."""
    crear_derivacion(db, JID, MotivoDerivacion.identidad, "No puede cancelar.")
    crear_derivacion(db, JID, MotivoDerivacion.identidad, "Sigue sin poder cancelar.",
                     datos_aportados="DNI 35878761")
    assert len(pendientes(db)) == 1
    assert pendientes(db)[0].datos_aportados == "DNI 35878761", (
        "El caso tiene que quedarse con lo último que dijo"
    )


def test_problemas_distintos_son_casos_distintos(db):
    crear_derivacion(db, JID, MotivoDerivacion.identidad, "No puede cancelar.")
    crear_derivacion(db, JID, MotivoDerivacion.clinico, "Le duele una muela.")
    assert len(pendientes(db)) == 2


def test_conversaciones_distintas_no_se_mezclan(db):
    crear_derivacion(db, JID, MotivoDerivacion.identidad, "Uno.")
    crear_derivacion(db, "5492604111222@s.whatsapp.net", MotivoDerivacion.identidad, "Otro.")
    assert len(pendientes(db)) == 2


# ── Recepción lo cierra ─────────────────────────────────────────────────────

def test_al_resolverlo_sale_de_la_bandeja(db):
    d = crear_derivacion(db, JID, MotivoDerivacion.identidad, "No puede cancelar.")
    resolver(db, d.id, por="recepcion@silprodent", nota="Cancelado a mano.")

    assert pendientes(db) == []
    guardada = db.query(Derivacion).filter(Derivacion.id == d.id).first()
    assert guardada.estado == EstadoDerivacion.resuelta
    assert guardada.resuelta_at is not None
    assert guardada.nota_de_cierre == "Cancelado a mano."


def test_hay_pendiente_dice_si_queda_algo_abierto(db):
    """El bot no puede reanudar la admisión con una tarea humana sin resolver."""
    assert hay_pendiente(db, JID) is False
    d = crear_derivacion(db, JID, MotivoDerivacion.identidad, "Algo.")
    assert hay_pendiente(db, JID) is True
    resolver(db, d.id)
    assert hay_pendiente(db, JID) is False


# ── Si no se pudo crear, no se puede prometer ──────────────────────────────

def test_si_falla_devuelve_None_para_que_no_se_prometa(db, monkeypatch):
    def _explota(*a, **k):
        raise RuntimeError("base caída")

    monkeypatch.setattr(db, "add", _explota)
    assert crear_derivacion(db, JID, MotivoDerivacion.otro, "algo") is None


# ── El bot no puede decir que avisó sin haber avisado ──────────────────────

def _correr(monkeypatch, texto, resultado_tool="✅ ok", tool="indicar_llamar_consultorio"):
    from bot import ai_agent
    from tests.test_no_confirmar_lo_que_no_se_hizo import (
        _Cliente, _LlamadaAHerramienta, _Mensaje,
    )

    guion = [_Mensaje("", tool_calls=[_LlamadaAHerramienta(tool)]), _Mensaje(texto)] \
        if tool else [_Mensaje(texto)]
    monkeypatch.setattr(ai_agent, "_build_client", lambda p: (_Cliente(guion), "m"))
    monkeypatch.setattr(ai_agent, "execute_tool", lambda n, a: resultado_tool)
    monkeypatch.setattr(ai_agent, "tomar_opciones_ofrecidas", lambda: None)
    monkeypatch.setattr(ai_agent, "get_estado_conversacion", lambda: {})
    return ai_agent.chat("hola", [], "5492604590071")[0]


PROMESA = "No lo encuentro en esta agenda. Dejé la consulta para que recepción lo revise."


def test_no_deja_pasar_un_aviso_que_no_ocurrio(monkeypatch):
    texto = _correr(monkeypatch, PROMESA, tool=None)
    assert "Dejé la consulta" not in texto
    assert "llamar" in texto.lower() or "2604" in texto


@pytest.mark.parametrize("promesa", [
    "Ya le avisé a recepción.",
    "Quedó anotado para que lo revisen.",
    "Lo derivé al equipo.",
    "Te van a llamar en un rato.",
    "Recepción te va a contactar.",
    "Si querés puedo dejar tus datos para que te contacten.",
    "¿Te gustaría que te avise cuando haya un turno disponible?",
])
def test_reconoce_las_formas_de_prometer_el_aviso(monkeypatch, promesa):
    texto = _correr(monkeypatch, promesa, tool=None)
    assert "Dejé la consulta" not in texto
    assert "van a contactar" not in texto.lower()
    assert "llamar" in texto.lower() or "2604" in texto


def test_si_indico_llamar_el_mensaje_sale(monkeypatch):
    assert _correr(monkeypatch, PROMESA) == PROMESA


def test_si_la_herramienta_fallo_no_se_promete(monkeypatch):
    texto = _correr(monkeypatch, PROMESA, resultado_tool="❌ NO se pudo")
    assert "Dejé la consulta" not in texto
    assert "llamar" in texto.lower() or "2604" in texto


def test_un_mensaje_normal_no_se_toca(monkeypatch):
    """Sin horarios: la barrera de disponibilidad no tiene nada que verificar."""
    normal = "Perfecto, ¿tenés obra social?"
    assert _correr(monkeypatch, normal, tool=None) == normal


# ── Ya no se silencia por bandeja de derivaciones ───────────────────────────

def test_una_derivacion_pendiente_ya_no_silencia_al_bot(db, monkeypatch):
    """La bandeja dejó de usarse: el bot no se calla por filas viejas."""
    from backend.routers import evolution_router as er

    class _Sesion:
        paused_until = None

    monkeypatch.setattr(er, "get_config", lambda k, d="": "true")
    monkeypatch.setattr(er, "get_or_create_session", lambda d, j: _Sesion())
    monkeypatch.setattr(er, "SessionLocal", lambda: db)

    crear_derivacion(db, JID, MotivoDerivacion.identidad, "Algo viejo.")
    assert er.bot_silenciado(JID) is False, (
        "Una derivación pendiente no puede dejar mudo al bot: ya no hay bandeja"
    )
