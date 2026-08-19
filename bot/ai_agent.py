"""DentiBot AI Agent - OpenAI Function Calling directo (sin LangChain).

Usa la API nativa de OpenAI (compatible con OpenRouter y Groq) para
function calling. Más confiable que LangChain AgentExecutor.
"""
import os
import json
import logging
from openai import OpenAI

from bot.tools.appointment_tools import (
    TOOL_DEFINITIONS, execute_tool, set_requester_phone, tomar_opciones_ofrecidas,
    set_estado_conversacion, get_estado_conversacion, resumen_estado,
)
from backend.database import SessionLocal
from backend.models.config import AppConfig
from backend.models.insurance import Insurance
from backend.services.appointment_service import get_clinic_now

logger = logging.getLogger(__name__)

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MAX_TOOL_ROUNDS = 8  # Máximo de rondas de tool calling por mensaje


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_config(key: str, default: str = ""):
    db = SessionLocal()
    try:
        conf = db.query(AppConfig).filter(AppConfig.key == key).first()
        if conf and conf.value and conf.value.strip():
            # .strip() a proposito: copiar una API Key del panel del proveedor
            # arrastra espacios o un salto de linea con muchisima facilidad, y
            # el 401 que devuelve despues no da ninguna pista de que sobra un
            # caracter invisible.
            return conf.value.strip()
    except Exception:
        pass
    finally:
        db.close()
    valor = os.getenv(key, default)
    return valor.strip() if isinstance(valor, str) else valor


def get_especialistas_texto() -> str:
    """Los profesionales y sus especialidades, tal como estan cargados en el panel.

    Estaba escrito a mano en el prompt y ya no coincidia con la realidad: decia
    que Limpiezas las hacia solo Murad y no mencionaba Cirugia, ademas de tener
    mal el nombre ("Helena" en vez de "Elena"). Ahora sale de la misma fuente
    que usa el ruteo, asi no se pueden contradecir.
    """
    from backend.models.professional import Professional
    db = SessionLocal()
    try:
        profs = db.query(Professional).filter(
            Professional.is_deleted == False,
            Professional.is_active == True,
        ).order_by(Professional.full_name).all()
        partes = [
            f"{p.full_name} ({', '.join(p.specialties)})"
            for p in profs if p.specialties
        ]
        return " y ".join(partes) if partes else "el equipo de la clínica"
    except Exception:
        return "el equipo de la clínica"
    finally:
        db.close()


def get_active_insurances() -> list[str]:
    db = SessionLocal()
    try:
        insurances = db.query(Insurance).filter(Insurance.is_active == True).all()
        return [i.name for i in insurances]
    except Exception:
        return ["PAMI", "OSDE", "Sancor Salud", "Medifé", "Swiss Medical"]
    finally:
        db.close()


# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual de "Silprodent".
Tu objetivo es ayudar a los pacientes de forma cálida, humana y eficiente.
Hablá en español argentino (voseo), profesional pero muy amable.
Sé BREVE y directo en cada respuesta — no más de 3-4 líneas salvo que sea necesario.

### 🕒 DATOS DEL CONSULTORIO:
- **Horarios**: Lunes a Viernes, mañana 09:00-12:30 y tarde 17:00-20:30. Miércoles a la tarde CERRADO.
- **Especialistas**: {especialistas}
- **Duraciones**: Limpieza/Consulta=15min, Extracción/Ortodoncia=30min, Endodoncia=60min.

### 🤖 QUÉ PODÉS HACER (y qué NO):
Podés: agendar turnos, cancelar turnos, consultar turnos existentes, verificar obras sociales.
NO podés: ver imágenes, radiografías ni documentos. Si te mandan algo que no sea texto o audio, decilo.

### 🎯 FLUJO PARA AGENDAR TURNO:

**Paso 1 — Saludo inicial:**
El sistema te avisa si la conversación es nueva con la marca [CONVERSACIÓN NUEVA].
Presentate SOLO si aparece esa marca. Si no está, ya venís hablando con el paciente:
seguí donde quedaron, sin volver a presentarte ni repetir los horarios de atención.
Cuando corresponda presentarte, hacelo así:
"¡Hola! Soy DentiBot 🦷, el asistente de Silprodent.
Puedo ayudarte a:
📅 *Agendar* un turno
❌ *Cancelar* un turno
🔍 *Consultar* tus turnos
¿Qué necesitás?"

**Paso 2 — Obra social:**
Lo PRIMERO al pedir turno: "¿La atención es particular o tenés obra social?"
- Apenas diga el nombre → llamá a `verificar_obra_social`. PROHIBIDO asumir que está cubierta.
- Si NO CUBIERTA → avisale con amabilidad que no trabajamos con esa, que sería PARTICULAR.
- **PAMI:** se atiende solo los viernes. Decíselo con naturalidad cuando le ofrezcas el día
  ("Con PAMI atendemos los viernes, te ofrezco el..."). Ocultarlo hacía que el bot inventara
  explicaciones raras como "la clínica está cerrada para PAMI", que confunden más.

**Paso 3 — Motivo:**
DESPUÉS de aclarar la obra social, preguntá: "¿Para qué sería la consulta? (ej: limpieza, extracción, control, etc.)"
⚠️ Si el paciente repite la obra social u otra cosa en vez de responder el motivo, volvé a preguntar con claridad: "Necesito saber el motivo de la consulta para poder buscarte un turno. ¿Es para una limpieza, extracción, control...?"
⚠️ PROHIBIDO avanzar sin el motivo confirmado.

**Paso 4 — Profesional:**
Informá qué especialista lo atenderá según la especialidad: {especialistas}.

**Paso 5 — Buscar disponibilidad:**
Llamá a `consultar_disponibilidad`. Presentá las opciones con la fecha completa y año.

**Paso 6 — Preferencia horaria:**
Si el paciente menciona una franja u hora ("a la tarde", "después de las 18:45", "temprano"),
pasala SIEMPRE en `preferencia_horaria` al llamar `consultar_disponibilidad`.
La herramienta filtra por vos y, si ese día no hay nada en esa franja, busca el día siguiente
que sí tenga y te lo avisa. PROHIBIDO decirle al paciente "solo tengo estos horarios" sin
haber consultado con su preferencia: los horarios que ves son una muestra, no todos los del día.

**Paso 7 — Selección de horario:**
Cuando el paciente elige un horario de los que le ofreciste:
- Usá la fecha ISO que devolvió la herramienta.
- Combiná fecha + hora y pedí los datos personales.
- ✅ NO vuelvas a llamar `consultar_disponibilidad` si ya eligió de las opciones que le diste.

**Paso 8 — Datos personales:**
🚫 NO le pidas el DNI ni el teléfono. El sistema reconoce al paciente por su número
de WhatsApp. Llamá a `agendar_turno` con los campos de datos vacíos.
- Solo si el sistema responde que no reconoce el número, pedile nombre, apellido y DNI.
- Si el sistema avisa que hay varias personas registradas con ese número (una familia),
  preguntá para quién es el turno y volvé a llamar con el nombre de esa persona.
- Si el paciente aclara que es para otra persona ("para mi mamá Estela Pardo"), pasá ese
  nombre en `patient_name` y `patient_last_name`.
- Si tenés que pedir el DNI: son 7-8 dígitos. Si te dan 10, es un teléfono; avisale
  "Ese parece un teléfono 😊 ¿Me pasás tu DNI?"

**Paso 9 — Confirmar y agendar:**
Con todos los datos, llamá a `agendar_turno` con `preferred_date` en formato `YYYY-MM-DD HH:MM`.

### 🛡️ PARA CANCELAR TURNO:
Llamá a `cancelar_turno` directamente, SIN pedir el DNI: el sistema identifica al
paciente por su número. Mostrale qué turno tiene y confirmá antes de cancelarlo.

### 🔍 PARA CONSULTAR TURNOS:
Llamá a `consultar_mis_turnos` directamente, SIN pedir el DNI.

⚠️ Si el paciente TE DA un DNI en cualquier momento, pasalo en la siguiente llamada.
No lo ignores: puede ser justo lo que hace falta para desambiguar.

⚠️ NUNCA repitas dos veces la misma pregunta. Si ya preguntaste algo y la respuesta
no te sirvió, no la vuelvas a hacer igual: probá con `consultar_mis_turnos` sin
parámetros, o decile que lo va a atender una persona de la clínica. Dar vueltas en
círculo es peor que derivar.

### 🧠 NO VUELVAS A PREGUNTAR LO QUE YA SABÉS:
Apenas el paciente mencione un dato —aunque sea de pasada y fuera de orden—
llamá a `recordar_dato` en ese mismo momento.
Ejemplo: "turno para mi mamá, ya hicimos el trámite del PAMI" → guardá
obra_social='PAMI' enseguida, y NO se lo preguntes después.
Al principio de cada mensaje vas a ver ESTADO DE ESTA CONVERSACIÓN con lo que
ya está registrado: fijate ahí antes de preguntar cualquier cosa.

### 📋 REGLAS GENERALES:
- **Negritas:** Fechas y horarios siempre en negrita con *asteriscos* e incluí el año.
- **NO calcules el día de la semana:** `consultar_disponibilidad` te devuelve la fecha en palabras. Copiala tal cual.
- **Pedir otro día:** Si el paciente quiere otro día, llamá a `consultar_disponibilidad` con esa fecha sin drama.
- **Fecha corrida:** Si la herramienta avisa que se movió la fecha, explicalo naturalmente.
- **FECHA HOY:** Cada mensaje trae `[SISTEMA - FECHA ACTUAL]`. Todo lo que devuelve la herramienta es futuro. NUNCA digas que una fecha ya pasó.
- **Emojis:** Si el paciente manda solo un emoji (👍, ❤️, etc.), interpretalo como confirmación o acuse de recibo. Si no queda claro a qué se refiere, preguntá: "¿Querés que avancemos con el turno?"
- **NO inventar:** Si no tenés la información, usá las herramientas. No inventes fechas ni horarios.
- **Mensajes cortos:** Respondé siempre de forma concisa. No repitas info que ya dijiste.
"""


# ── Provider client builder ──────────────────────────────────────────────────

def _build_client(provider: str):
    """Return (OpenAI client, model_name) or (None, None) if no key."""
    provider = provider.lower()

    if provider == "openrouter":
        api_key = get_config("OPENROUTER_API_KEY")
        model = get_config("OPENROUTER_MODEL", "google/gemini-flash-1.5")
        base_url = "https://openrouter.ai/api/v1"
    elif provider == "groq":
        api_key = get_config("GROQ_API_KEY")
        model = get_config("GROQ_MODEL", "llama-3.1-70b-versatile")
        base_url = "https://api.groq.com/openai/v1"
    else:  # openai
        api_key = get_config("OPENAI_API_KEY")
        model = get_config("OPENAI_MODEL", "gpt-4o-mini")
        base_url = None

    if not api_key:
        logger.error(f"AI_AGENT -> {provider} omitido: no hay API Key cargada.")
        return None, None

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    return OpenAI(**kwargs), model


def _get_providers() -> list[str]:
    """Return ordered list of providers to try."""
    p1 = get_config("AI_PROVIDER", "openai").lower()
    p2 = get_config("AI_PROVIDER_2", "none").lower()
    p3 = get_config("AI_PROVIDER_3", "none").lower()

    providers = [p for p in [p1, p2, p3] if p != "none"]
    # Deduplicate preserving order
    seen = set()
    providers = [p for p in providers if not (p in seen or seen.add(p))]
    return providers or ["openai"]


# ── Main chat function ───────────────────────────────────────────────────────

def chat(user_message: str, history: list[dict] | None = None,
         requester_phone: str | None = None,
         estado: dict | None = None) -> tuple[str, list | None, dict]:
    """Process a user message and return agent response.

    requester_phone: número real del canal (ej. WhatsApp) de quien escribe.
    Se registra para que las tools lo envíen al backend y este verifique que
    el DNI pertenece a ese número. En Telegram queda None (sin verificación).
    """
    logger.info(f"AI_AGENT_IN -> Msg: '{user_message}', HistLen: {len(history) if history else 0}")

    set_requester_phone(requester_phone)
    # Datos que el paciente ya dio en esta conversacion. Viajan por parametro y
    # no por contextvar: chat() corre en un executor (otro hilo) y el webhook
    # no veria lo que se setea adentro.
    set_estado_conversacion(estado)

    providers = _get_providers()
    clinic_now = get_clinic_now()
    dia_semana = DIAS_ES[clinic_now.weekday()]

    # Build system prompt with dynamic data
    system_content = SYSTEM_PROMPT.format(
        especialistas=get_especialistas_texto(),
    )
    # Lo que ya se sabe de este paciente, para que no lo vuelva a preguntar.
    system_content += f"\n\n### 📌 ESTADO DE ESTA CONVERSACIÓN:\n{resumen_estado(estado or {})}"

    # Build messages array (OpenAI format)
    messages = [{"role": "system", "content": system_content}]
    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # Prepend real date/time to user message
    # Si no hay historial, es el primer mensaje: el codigo lo sabe con certeza,
    # el modelo no (solo ve una lista de mensajes sin marcas). Antes lo decidia
    # el modelo y ante la duda se presentaba, hasta a alguien que solo queria
    # cancelar un turno.
    marca_nueva = "[CONVERSACIÓN NUEVA]\n" if not history else ""
    dated_message = (
        f"{marca_nueva}"
        f"[SISTEMA - FECHA ACTUAL: {dia_semana} {clinic_now.strftime('%Y-%m-%d')} "
        f"hora Argentina: {clinic_now.strftime('%H:%M')}]\n"
        f"{user_message}"
    )
    messages.append({"role": "user", "content": dated_message})

    # Try each provider with fallback
    last_error = None
    sin_key = []

    for attempt, provider in enumerate(providers, 1):
        try:
            logger.info(f"AI_AGENT -> Intentando proveedor {attempt}/{len(providers)}: {provider}")
            client, model = _build_client(provider)
            if not client:
                sin_key.append(provider)
                continue

            # ── Function calling loop ────────────────────────────────
            # Copy messages so each provider attempt starts fresh
            conv = list(messages)

            for round_num in range(MAX_TOOL_ROUNDS):
                response = client.chat.completions.create(
                    model=model,
                    messages=conv,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=1000,
                )

                choice = response.choices[0]
                msg = choice.message

                # No tool calls → final text response
                if not msg.tool_calls:
                    result = msg.content or ""
                    logger.info(f"AI_AGENT -> Respuesta final (ronda {round_num + 1}): {result[:80]}...")
                    return result, tomar_opciones_ofrecidas(), get_estado_conversacion()

                # Execute each tool call
                logger.info(f"AI_AGENT -> Ronda {round_num + 1}: {len(msg.tool_calls)} tool call(s)")

                # Add assistant message with tool calls to conversation
                assistant_entry = {"role": "assistant", "content": msg.content or ""}
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
                conv.append(assistant_entry)

                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    tool_result = execute_tool(tc.function.name, args)
                    logger.info(f"  🔧 {tc.function.name}({json.dumps(args, ensure_ascii=False)[:120]}) → {tool_result[:100]}...")
                    conv.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    })

            # Exhausted tool rounds — get final response without tools
            logger.warning(f"AI_AGENT -> Agotó {MAX_TOOL_ROUNDS} rondas de tools, pidiendo respuesta final")
            response = client.chat.completions.create(
                model=model,
                messages=conv,
                temperature=0.3,
                max_tokens=1000,
            )
            return (response.choices[0].message.content or "",
                    tomar_opciones_ofrecidas(), get_estado_conversacion())

        except Exception as e:
            logger.error(f"AI_AGENT -> Error usando proveedor {provider}: {e}")
            last_error = f"{provider}: {str(e)}"

    # All providers failed
    if sin_key and not last_error:
        logger.error(
            "AI_AGENT -> Ningún proveedor utilizable: sin API Key en %s. "
            "Cargala en Configuración -> Integraciones.",
            ", ".join(sin_key),
        )
    else:
        logger.error(
            "AI_AGENT -> Fallaron todos los proveedores (%s). Último error: %s%s",
            ", ".join(providers),
            last_error,
            f" | sin API Key: {', '.join(sin_key)}" if sin_key else "",
        )
    return (
        "No pudimos procesar tu solicitud automáticamente debido a un "
        "inconveniente técnico con nuestra Inteligencia Artificial. "
        "Un agente se pondrá en contacto a la brevedad."
    ), None, get_estado_conversacion()
