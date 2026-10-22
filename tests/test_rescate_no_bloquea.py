"""El rescate anti-loop no puede bloquear el servidor.

Simulación con IA real, 21-22/10: siete veces el paciente recibió "Error
consultando disponibilidad: timed out". El rescate por horarios corría dentro
del event loop y consultaba la agenda por HTTP a este mismo servidor, que no
podía atenderse a sí mismo hasta que vencían los 30 s. Mientras tanto, nadie
más recibía respuesta.
"""
import asyncio
import threading
import time

from backend.routers import evolution_router as er


def test_el_rescate_corre_fuera_del_event_loop(db, monkeypatch):
    hilos = {}
    latidos = []

    def chat_falso(text, history, requester_phone, estado_previo):
        return "Te ofrezco el jueves a las 10.", None, {}

    def rescate_lento(*args):
        hilos["rescate"] = threading.get_ident()
        time.sleep(0.6)            # como un HTTP al propio servidor
        return None, None, None

    async def responder_falso(*a, **k):
        return True

    monkeypatch.setattr(er, "chat", chat_falso)
    monkeypatch.setattr(er, "resolver_loop", rescate_lento)
    monkeypatch.setattr(er, "_responder", responder_falso)
    monkeypatch.setattr(er, "send_whatsapp_message", responder_falso)

    async def corazon():
        while "fin" not in hilos:
            latidos.append(time.monotonic())
            await asyncio.sleep(0.05)

    async def escenario():
        hilos["loop"] = threading.get_ident()
        latido = asyncio.create_task(corazon())
        await er.handle_text_message("5492605550999@s.whatsapp.net", "hola")
        hilos["fin"] = True
        await latido

    asyncio.run(escenario())

    assert hilos["rescate"] != hilos["loop"], "El rescate corrió en el event loop"
    # Durante los 0,6 s del rescate el loop siguió atendiendo otras cosas.
    assert len(latidos) >= 8, f"El event loop quedó bloqueado: {len(latidos)} latidos"
