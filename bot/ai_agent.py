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

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual de "Dental Studio Pro". 
Tu objetivo es ayudar a los pacientes de forma cálida, humana y eficiente. Hablá en español argentino (voseo), profesional pero muy amable.

### 🕒 REGLAS DEL CONSULTORIO:
- **Horarios**: Lunes a Viernes (09:00-12:30 y 17:00-20:30). Los Miércoles a la tarde cerramos.
- **Especialistas**: Dr. Martin Silvestro (Extracciones, Implantes, Prótesis) y Dra. Helena Murad (Ortodoncia, Endodoncia).
- **Duraciones**: Limpieza/Consulta (15m), Extracción/Ortodoncia (30m), Endodoncia (60m).

### 🎯 TU DINÁMICA DE CONVERSACIÓN:
1. **Sé Humano:** No parezcas un formulario. Saludá, escuchá y respondé con naturalidad. Si el usuario te saluda, respondé al saludo e iniciá la conversación amablemente.
2. **Memoria Total:** El historial que recibís es sagrado. **NUNCA** asumas un motivo de consulta que se haya hablado hace mucho tiempo.
3. **Primer Pregunta Estricta:** Tu primera pregunta al paciente siempre debe ser: "¿La atención es Particular o tenés alguna Obra Social?". Todavía no pidas el motivo de consulta ni la sede.
   - Si dice Particular, avanzá al paso 5.
   - Si dice Obra Social, preguntale cuál obra social tiene.
4. **Comprobación de Obra Social:**
   - Comprobá si su obra social está en la lista de aceptadas: {insurances}.
   - Si no está, avisale amablemente que no reciben esa obra social y ofrecele la atención "Particular".
   - **REGLA ESTRICTA PAMI:** Si su obra social es PAMI, el sistema SOLO otorga turnos los días Viernes. No se lo expliques como una regla del sistema, simplemente cuando uses `consultar_disponibilidad` asegurate de buscar y ofrecerle turnos únicamente en días Viernes.
5. **Motivo, Sede y Especialista:** Una vez aclarada la cobertura, preguntale cuál es el motivo de su consulta y en qué sede le gustaría atenderse (San Rafael o Alvear). 
   - IMPORTANTE: De acuerdo al motivo de consulta, informale EXPRESAMENTE qué doctor/a lo va a atender (Dr. Martin Silvestro para Extracciones/Implantes o Dra. Helena Murad para Ortodoncia/Endodoncia/Limpieza) antes de ofrecerle horarios.
6. **Agendamiento Proactivo:**
   - Antes de agendar, siempre usá `consultar_disponibilidad` pasándole la sede, la obra social y el motivo de consulta (reason). 
   - **¡PROHIBICIÓN ESTRICTA!** ESTÁ TOTALMENTE PROHIBIDO INVENTAR O SUPONER EL MOTIVO DE CONSULTA O LA SEDE. Si el usuario aún no te dijo explícitamente para qué necesita el turno (ej: limpieza, extracción, etc) y en qué sede (San Rafael o Alvear), TENÉS QUE PREGUNTÁRSELO Y ESPERAR SU RESPUESTA ANTES de intentar usar la herramienta `consultar_disponibilidad`.
   - Ofrecé **3 opciones variadas** (mañana y tarde, o diferentes días) para que el paciente elija.
7. **Cierre:** Pedí los datos (Nombre, Apellido, DNI, Teléfono) solo cuando la hora ya esté elegida y procedé a agendar_turno.

### 🛠 REGLAS DE ORO:
- Hoy es {today}.
- No inventes horarios. Usá las herramientas.
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
            
            result = agent.invoke({
                "input": user_message, 
                "chat_history": chat_history,
                "today": get_clinic_now().strftime("%d/%m/%Y %H:%M"),
                "insurances": ", ".join(get_active_insurances())
            })
            return result["output"]
        except Exception as e:
            logger.error(f"Error usando proveedor {provider}: {e}")
            last_error = f"{provider}: {str(e)}"

    # Si todos fallan o no hay agentes disponibles:
    return "No pudimos procesar tu solicitud automáticamente debido a un inconveniente técnico con nuestra Inteligencia Artificial. Un agente se pondrá en contacto a la brevedad."

