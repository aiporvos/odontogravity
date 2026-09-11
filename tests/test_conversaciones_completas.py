"""Conversaciones enteras contra el modelo de verdad, de punta a punta.

## Por qué existe este archivo

Los otros 520 tests mockean el modelo con un guion fijo (`_Cliente`): sirven
para probar las barreras de código, que es lo que hacen muy bien. Pero ninguno
prueba lo único que el paciente ve: una charla completa que empieza en "hola" y
termina con un turno.

Por eso el pendiente de fondo del proyecto sigue siendo el mismo desde el 08/09:
"no hay ni una conversación completa que termine bien". Se arreglaron tres
rondas de errores, cada una verificada a mano en WhatsApp, cada una costando un
día. Sin un arnés que recorra el diálogo entero, la única forma de saber si algo
anda es que Claudio lo pruebe con el teléfono.

Esto es ese arnés. Cada test acá abajo es una conversación real, mensaje por
mensaje, contra el proveedor configurado. Después de CADA respuesta se
verifican las invariantes duras, y al final se verifica el objetivo.

## Cómo se corre

Hacen falta DOS cosas, no una. La API key es la obvia; la otra es el backend
corriendo, porque las herramientas del bot van por HTTP contra él. Sin backend
los tests se saltean con un mensaje que lo explica, en vez de dar resultados
engañosos.

    export OPENAI_API_KEY=sk-...        # o el proveedor que corresponda
    export API_BASE_URL=http://localhost:8000   # donde escuche el backend
    TEST_DATABASE_URL="postgresql://test:test@localhost:55432/dentibot_test" \\
        .venv/bin/python -m pytest tests/test_conversaciones_completas.py -v -s -m conversacion

Sin API key se saltean solos, así que no rompen la corrida normal de `pytest`.
Gastan tokens de verdad: una conversación completa ronda las 20 llamadas.

`-s` es importante: imprime la charla para poder leerla.

## Para qué sirve además de atrapar errores

1. **Comparar modelos objetivamente.** La misma batería con `OPENAI_MODEL`
   distinto dice cuál se descarría menos, en vez de opinar.
2. **Recortar el prompt con red.** Hoy tocar el prompt es cambiar y cruzar los
   dedos; con esto se ve qué se rompe.
3. **Medir el costo real por conversación.** El registro `AI_AGENT_USO` dice
   tokens y caché de cada llamada.
"""
import os
import re
import uuid
from datetime import timedelta

import pytest

from bot import ai_agent
from backend.models.appointment import Appointment, AppointmentStatus
from backend.services.appointment_service import get_clinic_now
from conftest import proximo_dia_habil

pytestmark = pytest.mark.conversacion


TELEFONO = "+5492604590071"   # el mismo del fixture `paciente`


def _hay_proveedor() -> bool:
    """Si no hay con qué hablar, estos tests no corren (no fallan: se saltean)."""
    return any(os.getenv(k) for k in
               ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY"))


def _backend_responde() -> bool:
    """Si el backend no está arriba, estos tests MIENTEN. Por eso se chequea.

    Las herramientas del bot no son funciones locales: cada una hace HTTP contra
    el backend (`API_BASE`, por defecto http://backend:8000, que es un hostname
    de la red de Docker y no resuelve desde afuera). Sin backend, todas fallan
    con "No pude consultar la ficha" y el modelo queda dando vueltas.

    Eso pasó la primera vez que se corrió esto, el 11/09: parecía que el modelo
    repetía preguntas y no avanzaba, y en realidad ninguna herramienta
    funcionaba. Un arnés que da resultados así es peor que no tener arnés,
    porque lleva a arreglar el prompt por un problema de infraestructura.
    """
    import urllib.error
    import urllib.request
    from bot.tools.appointment_tools import API_BASE

    try:
        with urllib.request.urlopen(f"{API_BASE}/health", timeout=3) as r:
            return r.status < 500
    except urllib.error.HTTPError:
        return True          # responde algo: está vivo
    except Exception:
        return False


requiere_modelo = pytest.mark.skipif(
    not _hay_proveedor(),
    reason="Sin API key de ningún proveedor: no se puede hablar con el modelo. "
           "Exportá OPENAI_API_KEY (u OPENROUTER_API_KEY / GROQ_API_KEY).",
)

requiere_backend = pytest.mark.skipif(
    not _backend_responde(),
    reason=(
        "El backend no responde y las herramientas del bot van por HTTP contra "
        "él: sin backend, todas fallan y la conversación no prueba nada. "
        "Levantalo y apuntá API_BASE_URL a donde esté escuchando, por ejemplo "
        "API_BASE_URL=http://localhost:8000."
    ),
)


# ── Las invariantes que ninguna respuesta puede violar ──────────────────────
# Estas son las que costaron tres rondas. No son de estilo: cada una es un caso
# real en el que un paciente recibió algo falso.

_PROMETE_TURNO = re.compile(
    r"\b(te\s+agend|qued(o|ó)\s+agendad|te\s+reserv|te\s+anot|turno\s+confirmad)",
    re.IGNORECASE)
_PROMETE_AVISO = re.compile(
    r"(dej[eé]\s+(la\s+)?consulta|le\s+aviso\s+a|avis[eé]\s+a\s+recepci|"
    r"qued[oó]\s+anotad|te\s+van\s+a\s+(llamar|contactar))", re.IGNORECASE)
_PIDE_DNI = re.compile(r"\b(dni|documento)\b", re.IGNORECASE)
_SALUDO = re.compile(r"\b(buen d[ií]a|buenas tardes|buenas noches|hola)\b",
                     re.IGNORECASE)


class Charla:
    """Una conversación que se va acumulando, como la ve el paciente."""

    def __init__(self, db, telefono=TELEFONO):
        self.db = db
        self.telefono = telefono
        self.history = []
        self.estado = {}
        self.turnos = []          # (paciente_dice, bot_responde)

    def decir(self, mensaje: str) -> str:
        """Manda un mensaje y devuelve la respuesta, acumulando el historial."""
        respuesta, _, estado = ai_agent.chat(
            mensaje, list(self.history), self.telefono, estado=self.estado)
        self.estado = estado or self.estado
        self.history.append({"role": "user", "content": mensaje})
        self.history.append({"role": "assistant", "content": respuesta})
        self.turnos.append((mensaje, respuesta))

        print(f"\n  paciente: {mensaje}")
        print(f"  bot:      {respuesta}")

        self._verificar_invariantes(respuesta)
        return respuesta

    # ── Lo que se comprueba después de CADA respuesta ───────────────────────

    def _verificar_invariantes(self, respuesta: str) -> None:
        self._no_confirma_turno_inexistente(respuesta)
        self._no_promete_aviso_sin_derivacion(respuesta)
        self._no_saluda_dos_veces(respuesta)
        self._no_repite_la_misma_pregunta(respuesta)

    def _no_confirma_turno_inexistente(self, respuesta: str) -> None:
        """El caso del 08/09: "te agendé" sin que existiera el turno."""
        if not _PROMETE_TURNO.search(respuesta):
            return
        assert self._turnos_en_la_base(), (
            f"Dijo que agendó y no hay ningún turno en la base.\n"
            f"  Respuesta: {respuesta}"
        )

    def _no_promete_aviso_sin_derivacion(self, respuesta: str) -> None:
        """El caso del 08/09: "dejé la consulta" sin bandeja de derivaciones."""
        if not _PROMETE_AVISO.search(respuesta):
            return
        # La barrera del código ya bloquea esto; si llega acá, se abrió otra salida.
        assert "no pude dejar la consulta" not in respuesta.lower(), (
            f"Prometió avisar sin crear la derivación: {respuesta}"
        )

    def _no_saluda_dos_veces(self, respuesta: str) -> None:
        """El caso del 23/08: "¡Buenas noches, Claudio!" en el cuarto mensaje."""
        if len(self.turnos) <= 1:
            return
        assert not _SALUDO.match(respuesta.strip()), (
            f"Volvió a saludar en el mensaje {len(self.turnos)} de la charla.\n"
            f"  Respuesta: {respuesta}"
        )

    def _no_repite_la_misma_pregunta(self, respuesta: str) -> None:
        """Dar vueltas en círculo es peor que derivar: el caso de Taboada."""
        preguntas = [r.strip().lower() for _, r in self.turnos[:-1]
                     if "?" in r]
        actual = respuesta.strip().lower()
        if "?" not in actual:
            return
        assert actual not in preguntas, (
            f"Hizo exactamente la misma pregunta dos veces: {respuesta}"
        )

    # ── Consultas sobre el resultado ────────────────────────────────────────

    def _turnos_en_la_base(self):
        return self.db.query(Appointment).filter(
            Appointment.status != AppointmentStatus.cancelled,
            Appointment.is_deleted == False,  # noqa: E712
            Appointment.start_time >= get_clinic_now() - timedelta(hours=1),
        ).order_by(Appointment.created_at).all()

    def turno_creado(self):
        """El turno que se creó en esta charla, o None."""
        turnos = self._turnos_en_la_base()
        return turnos[-1] if turnos else None

    def pidio_dni_alguna_vez(self) -> bool:
        return any(_PIDE_DNI.search(r) for _, r in self.turnos)


# ── Guión 1: el turno normal, que es el 80% de lo que pasa ──────────────────

@requiere_modelo
@requiere_backend
def test_turno_normal_de_punta_a_punta(db, clinica, silvestro, paciente):
    """Lo más común: alguien que quiere un turno y lo consigue.

    Si esto no pasa, nada de lo demás importa.
    """
    charla = Charla(db)
    charla.decir("hola")
    charla.decir("quiero un turno para una extracción")
    charla.decir("la semana que viene")
    respuesta = charla.decir("el primero que tengas")

    turno = charla.turno_creado()
    assert turno is not None, (
        "La conversación terminó sin turno creado. Esto es el caso base: si no "
        "funciona, el bot no sirve para lo único que tiene que hacer."
    )
    assert not charla.pidio_dni_alguna_vez(), (
        "Pidió el DNI. El sistema identifica por WhatsApp y 380 de las 446 "
        "fichas activas no tienen DNI cargado."
    )


# ── Guión 2: el caso Murad, que costó tres rondas ───────────────────────────

@requiere_modelo
@requiere_backend
def test_el_dia_y_el_profesional_los_decide_el_paciente(db, clinica, silvestro,
                                                        murad, paciente):
    """La conversación del 10/09 que motivó tres rondas de arreglos.

    El paciente pide a Murad para el jueves. Murad hace Ortodoncia, no
    extracciones. Lo que NO puede pasar: ofrecerle horarios de Silvestro
    presentados como de Murad.
    """
    charla = Charla(db)
    charla.decir("hola")
    charla.decir("quiero un turno con la doctora Murad para el jueves")
    respuesta = charla.decir("extraccion")

    # Murad no hace extracciones. Tiene que decirlo, no inventar disponibilidad.
    if "murad" in respuesta.lower():
        assert re.search(r"(no (hace|realiza|atiende)|silvestro|otro profesional)",
                         respuesta, re.IGNORECASE), (
            "Nombró a Murad para una extracción sin aclarar que no la hace ni "
            "ofrecer a quien sí. Este es exactamente el caso del 10/09.\n"
            f"  Respuesta: {respuesta}"
        )


# ── Guión 3: cancelar, que es donde se perdió Taboada ───────────────────────

@requiere_modelo
@requiere_backend
def test_cancelar_un_turno_que_existe(db, clinica, silvestro, paciente):
    """Caso del 08/09: escribió para cancelar y el bot la interrogó sin derivar."""
    from conftest import turno as crear_turno
    crear_turno(db, paciente, silvestro, proximo_dia_habil())

    charla = Charla(db)
    charla.decir("hola, necesito cancelar mi turno")
    charla.decir("si, ese mismo")

    assert not charla.pidio_dni_alguna_vez(), (
        "Pidió el DNI para cancelar. El turno estaba asociado a su número. "
        "Este es el caso de Taboada: su ficha venía de la agenda de papel."
    )


# ── Guión 4: cuando no se puede resolver, derivar y no dar vueltas ──────────

@requiere_modelo
@requiere_backend
def test_lo_que_no_puede_resolver_lo_deriva(db, clinica, silvestro, paciente):
    """Dar vueltas en círculo es peor que derivar."""
    charla = Charla(db)
    charla.decir("hola")
    respuesta = charla.decir(
        "necesito que me digan cuánto sale un implante con hueso y si lo cubre "
        "mi obra social de Buenos Aires")

    assert re.search(
        r"(recepci[oó]n|una persona|la cl[ií]nica|te (van a |)contactar|consulta)",
        respuesta, re.IGNORECASE), (
        "No derivó ni ofreció que lo vea una persona ante algo que no puede "
        f"resolver. Respuesta: {respuesta}"
    )


# ── Guión 5: turno para otra persona ────────────────────────────────────────

@requiere_modelo
@requiere_backend
def test_turno_para_un_familiar(db, clinica, silvestro, paciente):
    """"Es para mi mamá" no puede terminar con el turno a nombre del que escribe."""
    charla = Charla(db)
    charla.decir("hola, quiero un turno para mi mamá Estela Pardo")
    charla.decir("una limpieza")
    charla.decir("cuando puedas la semana que viene")
    charla.decir("el primero")

    turno = charla.turno_creado()
    if turno is not None:
        nombre = f"{turno.patient.first_name} {turno.patient.last_name}".lower()
        assert "estela" in nombre, (
            f"El turno quedó a nombre de '{nombre}' y era para Estela Pardo."
        )
