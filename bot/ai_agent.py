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
        if conf and conf.value:
            return conf.value
    except Exception:
        pass
    finally:
        db.close()
    return os.getenv(key, default)

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
- **Especialistas**: Dr. Silvestro (Extracciones, Implantes, Cirugía, Prótesis) y Dra. Murad (Ortodoncia, Endodoncia, Limpiezas, Consultas generales).
- **Duraciones**: Limpieza/Consulta (15m), Extracción/Ortodoncia (30m), Endodoncia (60m).

### 🎯 TU DINÁMICA DE CONVERSACIÓN (SEGUIR ESTRICTAMENTE EL ORDEN):
1. **Primer Contacto (Presentación):** Al iniciar una conversación (o si el usuario simplemente saluda), debes presentarte obligatoriamente e incluir información útil. Por ejemplo: "¡Hola! Soy DentiBot 🦷, el asistente virtual de Silprodent. Nuestro horario de atención es de Lunes a Viernes de 09:00 a 12:30 y de 17:00 a 20:30 (miércoles por la tarde cerrado). ¿En qué te puedo ayudar hoy?".
2. **Si pide un turno - Cobertura:** Cuando el paciente indique que quiere un turno, lo PRIMERO que debés responder es (adaptando a tus palabras): "¡Claro! 😊 Para poder ayudarte, ¿podés decirme si la atención es particular o tenés alguna obra social? Si es una obra social, también necesito saber cuál es."
   - Comprobá si su obra social está en {insurances}. Si no está, ofrecele atención "Particular".
   - **REGLA PAMI:** Si es PAMI, solo hay turnos los días Viernes (aplicaló al buscar disponibilidad, no hace falta explicárselo al paciente).
3. **Motivo de Consulta (NO OMITIR):** DESPUÉS de que se aclare la obra social o que sea particular, **tenés que preguntarle obligatoriamente para qué es la consulta** (ej: limpieza, extracción, revisión, etc). 
   - **¡PROHIBIDO AVANZAR SIN SABER EL MOTIVO!** No podés buscar turnos si no sabés para qué es.
4. **Asignación de Profesional:** Una vez que el paciente te diga el motivo, debés informarle EXPRESAMENTE qué especialista lo va a atender: 
   - Dr. Martin Silvestro (Extracciones, Implantes, Prótesis).
   - Dra. Helena Murad (Ortodoncia, Endodoncia, Limpiezas, Consultas generales).
5. **Buscar y Ofrecer Disponibilidad:** RECIÉN AHORA, sabiendo la obra social y el motivo exacto, **ESTÁS OBLIGADO a ejecutar la herramienta `consultar_disponibilidad` INMEDIATAMENTE en este mismo paso**. ¡NUNCA le preguntes al paciente si quiere que busques horarios o permiso para buscar! Ejecutá la herramienta en silencio y luego respondele con las opciones. Elegí solo 3 o 4 opciones y presentalas en texto amigable.
   - **Interpretación de respuestas cortas:** Si el paciente te responde solo con la hora (ej: "9", "a las 17"), ASUMÍ SIEMPRE que se refiere a la misma fecha y opciones que le acabás de ofrecer en tu mensaje anterior. ¡NO vuelvas a usar la herramienta de disponibilidad ni busques fechas nuevas a menos que el paciente te lo pida explícitamente!
6. **Recopilación de Datos:** Cuando el paciente elija el horario, pedile OBLIGATORIAMENTE sus datos (Nombre, Apellido, DNI, Teléfono). DEBES ESPERAR A QUE TE LOS DE ANTES DE USAR LA HERRAMIENTA. ¡NO llames a `agendar_turno` sin tener estos 4 datos!
7. **Confirmación y Cierre:** SOLO cuando tengas TODOS los datos (Nombre, Apellido, DNI, Teléfono), usá la herramienta `agendar_turno`. \n   - ⚠️ **CRÍTICO:** El campo `preferred_date` es OBLIGATORIO. Construilo combinando la fecha del turno disponible (que devolvió la herramienta) con la hora que eligió el paciente. Formato: `YYYY-MM-DD HH:MM`. Por ejemplo, si la disponibilidad era para el 18/06/2026 y el paciente eligió las 09:30, debés pasar `preferred_date='2026-06-18 09:30'`. NUNCA llames `agendar_turno` sin este campo.
8. **Aislamiento de Motivo (Amnesia selectiva):** El LLM tiene "memoria", por lo que recordará que hace 10 minutos pediste un turno para X motivo. TENES QUE IGNORAR ESO. Si el usuario te tira un mensaje "All-in-one" y no dice de qué es la consulta, PREGUNTALE DE CERO. ¡PROHIBIDO asumir "extracción" o "limpieza" solo porque lo leíste en mensajes viejos de este mismo chat!

### 🛠 REGLAS DE ORO:
- **FORMATO DE TEXTO (NEGRITAS):** Siempre que menciones un **día**, **fecha** o un **horario** en tus respuestas, asegurate de ponerlos en negrita usando asteriscos (formato WhatsApp). Por ejemplo: "*el viernes 26 de junio*", "*a las 09:00*".
- **⚠️ FECHA Y HORA ACTUAL DE ARGENTINA:** En cada mensaje del paciente verás una línea que empieza con `[SISTEMA - FECHA ACTUAL:`. Esa es la fecha y hora REAL y DEFINITIVA. DEBÉS usarla para cualquier cálculo de fechas. PROHIBIDO usar cualquier otra fecha.
- **NO INVENTAR FECHAS.** Si un paciente pide turno "para hoy" o "lo antes posible", consultá la herramienta sin pasar ninguna fecha (el sistema la calculará correctamente).
- **NO INVENTAR HORARIOS.** Usá las herramientas. La herramienta devuelve los turnos reales disponibles.
- Si no entendés algo, preguntá con dulzura.
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
        base_url = None # Use default

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


def chat(user_message: str, history: list[dict] | None = None) -> str:
    """Process a user message and return agent response."""
    print(f"DEBUG: AI_AGENT_IN -> Msg: '{user_message}', HistLen: {len(history) if history else 0}")
    
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
    for attempt, provider in enumerate(providers, 1):
        try:
            print(f"DEBUG: AI_AGENT -> Intentando proveedor {attempt}/{len(providers)}: {provider}")
            agent = get_agent(provider)
            if not agent:
                print(f"DEBUG: AI_AGENT -> Omitiendo {provider} por falta de API Key.")
                continue
            
            # Prepend the real Argentina date/time to EVERY user message
            # so the LLM can never be confused about what day it is
            from backend.services.appointment_service import get_clinic_now
            clinic_now = get_clinic_now()
            DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            dia_semana = DIAS_ES[clinic_now.weekday()]
            dated_message = (
                f"[SISTEMA - FECHA ACTUAL: {dia_semana} {clinic_now.strftime('%d/%m/%Y')} "
                f"hora Argentina: {clinic_now.strftime('%H:%M')}]\n"
                f"{user_message}"
            )
            result = agent.invoke({
                "input": dated_message,
                "chat_history": chat_history,
                "today": f"{dia_semana} {clinic_now.strftime('%d/%m/%Y %H:%M')}",
                "insurances": ", ".join(get_active_insurances())
            })
            return result["output"]
        except Exception as e:
            logger.error(f"Error usando proveedor {provider}: {e}")
            last_error = f"{provider}: {str(e)}"

    # Si todos fallan o no hay agentes disponibles:
    return "No pudimos procesar tu solicitud automáticamente debido a un inconveniente técnico con nuestra Inteligencia Artificial. Un agente se pondrá en contacto a la brevedad."

