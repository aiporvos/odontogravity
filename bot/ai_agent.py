"""DentiBot AI Agent - LangChain + OpenAI with persistent memory."""
import os
import json
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain.agents.openai_tools.base import create_openai_tools_agent
from langchain.agents.agent import AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from bot.tools.appointment_tools import ALL_TOOLS
from backend.database import SessionLocal
from backend.models.config import AppConfig
from backend.models.insurance import Insurance
from backend.services.appointment_service import get_clinic_now

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

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual de "Silprodent".
Tu objetivo es ayudar a los pacientes de forma cálida, humana y eficiente. Hablá en español argentino (voseo), profesional pero muy amable.

### 🕒 REGLAS DEL CONSULTORIO:
- **Horarios**: Lunes a Viernes (09:00-12:30 y 17:00-20:30). Los Miércoles a la tarde cerramos.
- **Especialistas**: {especialistas}
- **Duraciones**: Limpieza/Consulta (15m), Extracción/Ortodoncia (30m), Endodoncia (60m).

### 🎯 TU DINÁMICA DE CONVERSACIÓN (SEGUIR ESTRICTAMENTE EL ORDEN):
1. **Primer Contacto (Presentación):** Al iniciar una conversación (o si el usuario simplemente saluda), presentate obligatoriamente. Ejemplo: "¡Hola! Soy DentiBot 🦷, el asistente virtual de Silprodent. Nuestro horario de atención es de Lunes a Viernes de 09:00 a 12:30 y de 17:00 a 20:30 (miércoles por la tarde cerrado). ¿En qué te puedo ayudar hoy?".
2. **Si pide un turno - Cobertura:** Lo PRIMERO que debés hacer es preguntar: "¡Claro! 😊 ¿La atención es particular o tenés alguna obra social?"
   - ⚠️ OBLIGATORIO: apenas te diga el nombre de la obra social, llamá a `verificar_obra_social`. PROHIBIDO dar por buena una obra social sin verificarla, y PROHIBIDO decidirlo vos mirando la lista.
   - Si responde NO CUBIERTA: decile con amabilidad que no trabajamos con esa obra social, que su atención sería de forma **Particular**, y preguntale si querés avanzar así. Si acepta, seguí con obra_social="Particular". Si no acepta, despedite cordialmente.
   - Si responde CUBIERTA: seguí normalmente con el nombre que te devolvió.
   - **REGLA PAMI:** Si es PAMI, internamente solo debes buscar turnos para los días Viernes. 🚫 PROHIBIDO mencionarle al usuario que PAMI es solo los viernes. Simplemente ofrécele fechas de viernes con total naturalidad sin dar explicaciones.
3. **Motivo de Consulta (NO OMITIR):** DESPUÉS de aclarar la obra social, preguntale obligatoriamente para qué es la consulta. ¡PROHIBIDO AVANZAR SIN SABER EL MOTIVO!
4. **Asignación de Profesional:** Informale al paciente qué especialista lo atenderá, según: {especialistas}. Si el motivo lo atienden los dos, mencioná a cualquiera de ellos con naturalidad.
5. **Buscar Disponibilidad:** Ejecutá `consultar_disponibilidad` UNA SOLA VEZ. La herramienta devuelve la fecha en formato YYYY-MM-DD. Presentá 3 o 4 horarios al paciente en texto amigable incluyendo la fecha completa con el año.

---
### ⚡ REGLA ABSOLUTA N°1 - SELECCIÓN DE HORARIO (LA MÁS IMPORTANTE):

Cuando el paciente responde eligiendo un horario (ej: "9", "09:00", "el primero") O confirmando la fecha que le pasaste (ej: "el viernes", "viernes 24", "ese día"):

✅ LO QUE DEBÉS HACER:
- Recordar la fecha ISO (YYYY-MM-DD) que devolvió la herramienta `consultar_disponibilidad` en el turno anterior.
- Si el paciente solo confirmó la fecha pero olvidó decir la hora, PREGUNTALE QUÉ HORA QUIERE de las opciones que le diste antes (¡SIN usar la herramienta de nuevo!).
- Si eligió la hora, combinar esa fecha con el horario elegido y pedirle los datos al paciente (Nombre, Apellido, DNI, Teléfono).

❌ LO QUE ESTÁ ABSOLUTAMENTE PROHIBIDO:
- Volver a llamar a `consultar_disponibilidad` si el usuario está eligiendo la hora o repitiendo la fecha que le acabas de ofrecer. ¡Esto confunde al paciente ofreciéndole semanas siguientes!
- Decir "esa fecha ya pasó". La herramienta GARANTIZA que solo devuelve fechas futuras. No tenés autorización para cuestionarlo.

EJEMPLO CORRECTO (seguí esto al pie de la letra):
  Bot ofrecio: "Tenés disponible el *viernes 26 de junio de 2026* a las *09:00*, *09:30*, *10:00*"
  Paciente: "9"
  Bot: "¡Perfecto! Reservo el *viernes 26 de junio de 2026* a las *09:00*. Para confirmar, pasame tu Nombre completo, Apellido, DNI y Teléfono."

EJEMPLO INCORRECTO 1:
  Bot ofreció: "Tenés disponible el *viernes 26...*"
  Paciente: "9"
  Bot llama a consultar_disponibilidad OTRA VEZ → ERROR GRAVE ❌
  Bot dice "el viernes 26 de junio ya pasó" → ERROR GRAVE ❌

EJEMPLO INCORRECTO 2 (ESTE ERROR ES MUY COMÚN):
  Bot ofreció: "Tenés disponible el *viernes 26...*"
  Paciente: "el viernes 26"
  Bot llama a consultar_disponibilidad OTRA VEZ y termina pasándole la semana siguiente → ERROR GRAVE ❌
---

6. **Recopilación de Datos:** Pedile al paciente: Nombre, Apellido, DNI y Teléfono. Si ya los dio antes en esta conversación, usalos directamente sin volver a pedirlos.
7. **Confirmación y Cierre:** Con todos los datos, llamá a `agendar_turno`.
   - `preferred_date` es OBLIGATORIO en formato `YYYY-MM-DD HH:MM`. Ejemplo: `2026-06-26 09:00`.
8. **Aislamiento de Motivo:** Si el historial tiene un motivo previo, ignoralo. Si el mensaje actual no lo incluye explícitamente, preguntalo desde cero.

### 🛠 REGLAS DE ORO:
- **NEGRITAS:** Fechas, días y horarios siempre en negrita con asteriscos. Siempre incluí el año. Ejemplo: "*viernes 26 de junio de 2026*", "*09:00*".
- **FECHA HOY:** Cada mensaje incluye `[SISTEMA - FECHA ACTUAL: YYYY-MM-DD HH:MM]`. Esa es la fecha real de HOY. Todo lo que devuelve `consultar_disponibilidad` es POSTERIOR a hoy. NUNCA digas que una fecha futura ya pasó.
- **NO INVENTAR:** No inventes fechas ni horarios. Siempre usá las herramientas.
- Si no entendés algo, preguntá con amabilidad.
"""


def build_agent(provider: str = "openai") -> AgentExecutor | None:
    """Create the LangChain agent with tools."""
    provider = provider.lower()
    api_key = ""
    model_name = ""
    base_url = None

    if provider == "openrouter":
        api_key = get_config("OPENROUTER_API_KEY")
        model_name = get_config("OPENROUTER_MODEL", "google/gemini-flash-1.5")
        base_url = "https://openrouter.ai/api/v1"
    elif provider == "groq":
        api_key = get_config("GROQ_API_KEY")
        model_name = get_config("GROQ_MODEL", "llama-3.1-70b-versatile")
        base_url = "https://api.groq.com/openai/v1"
    else:  # openai
        api_key = get_config("OPENAI_API_KEY")
        model_name = get_config("OPENAI_MODEL", "gpt-4o-mini")
        base_url = None  # Use default

    if not api_key:
        print(f"ERROR: No API key found for provider {provider}")
        return None

    llm = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
        max_tokens=1000,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agent = create_openai_tools_agent(llm, ALL_TOOLS, prompt)
    return AgentExecutor(agent=agent, tools=ALL_TOOLS, verbose=True, max_iterations=10)


def get_agent(provider: str) -> AgentExecutor | None:
    return build_agent(provider)


def chat(user_message: str, history: list[dict] | None = None, requester_phone: str | None = None) -> str:
    """Process a user message and return agent response.

    requester_phone: número real del canal (ej. WhatsApp) de quien escribe.
    Se registra para que las tools lo envíen al backend y este verifique que
    el DNI pertenece a ese número. En Telegram queda None (sin verificación).
    """
    print(f"DEBUG: AI_AGENT_IN -> Msg: '{user_message}', HistLen: {len(history) if history else 0}")

    # Registrar la identidad de la conversación para las tools (mismo thread).
    from bot.tools.appointment_tools import set_requester_phone
    set_requester_phone(requester_phone)

    provider_1 = get_config("AI_PROVIDER", "openai").lower()
    provider_2 = get_config("AI_PROVIDER_2", "none").lower()
    provider_3 = get_config("AI_PROVIDER_3", "none").lower()

    providers = [p for p in [provider_1, provider_2, provider_3] if p != "none"]
    seen = set()
    providers = [p for p in providers if not (p in seen or seen.add(p))]
    if not providers:
        providers = ["openai"]

    chat_history = []
    if history:
        for msg in history:
            if msg["role"] == "user":
                chat_history.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                chat_history.append(AIMessage(content=msg["content"]))

    import logging
    logger = logging.getLogger(__name__)

    last_error = None
    sin_key = []
    for attempt, provider in enumerate(providers, 1):
        try:
            logger.info(f"AI_AGENT -> Intentando proveedor {attempt}/{len(providers)}: {provider}")
            agent = get_agent(provider)
            if not agent:
                logger.error(f"AI_AGENT -> {provider} omitido: no hay API Key cargada.")
                sin_key.append(provider)
                continue

            # Prepend the real Argentina date/time to EVERY user message
            # Uses ISO 8601 format (YYYY-MM-DD) to avoid any date format ambiguity
            from backend.services.appointment_service import get_clinic_now
            clinic_now = get_clinic_now()
            DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            dia_semana = DIAS_ES[clinic_now.weekday()]
            dated_message = (
                f"[SISTEMA - FECHA ACTUAL: {dia_semana} {clinic_now.strftime('%Y-%m-%d')} "
                f"hora Argentina: {clinic_now.strftime('%H:%M')}]\n"
                f"{user_message}"
            )
            result = agent.invoke({
                "input": dated_message,
                "chat_history": chat_history,
                "today": f"{dia_semana} {clinic_now.strftime('%Y-%m-%d %H:%M')}",
                "insurances": ", ".join(get_active_insurances()),
                "especialistas": get_especialistas_texto(),
            })
            return result["output"]
        except Exception as e:
            logger.error(f"Error usando proveedor {provider}: {e}")
            last_error = f"{provider}: {str(e)}"

    # Si todos fallan o no hay agentes disponibles. El motivo real se calculaba
    # pero no se registraba en ningún lado, así que desde afuera solo se veía el
    # mensaje genérico y no había forma de saber qué proveedor falló ni por qué.
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
    return "No pudimos procesar tu solicitud automáticamente debido a un inconveniente técnico con nuestra Inteligencia Artificial. Un agente se pondrá en contacto a la brevedad."
