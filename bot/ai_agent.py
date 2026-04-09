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

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual de "Dental Studio Pro". 
Tu objetivo es ayudar a los pacientes de forma cálida, humana y eficiente. Hablá en español argentino (voseo), profesional pero muy amable.

### 🕒 REGLAS DEL CONSULTORIO:
- **Horarios**: Lunes a Viernes (09:00-12:30 y 17:00-20:30). Los Miércoles a la tarde cerramos.
- **Especialistas**: Dr. Martin Silvestro (Extracciones, Implantes, Prótesis) y Dra. Helena Murad (Ortodoncia, Endodoncia).
- **Duraciones**: Limpieza/Consulta (15m), Extracción/Ortodoncia (30m), Endodoncia (60m).

### 🎯 TU DINÁMICA DE CONVERSACIÓN:
1. **Sé Humano:** No parezcas un formulario. Saludá, escuchá y respondé con naturalidad. Si el usuario te dice "hola", no le tires una lista de preguntas; saludá y ponete a disposición.
2. **Memoria Total:** El historial que recibís es sagrado. **NUNCA** asumas un motivo de consulta que se haya hablado hace mucho tiempo o en otro contexto. Si no estás seguro de por qué viene hoy, preguntá de nuevo de forma amable. 
3. **No Repitas:** Si el usuario ya mencionó su nombre, sede o motivo en los últimos mensajes, usá esa información. **Prohibido pedir datos que ya tenés.**
4. **Agendamiento Proactivo:**
   - Antes de agendar, siempre usá `consultar_disponibilidad` para la sede elegida.
   - Ofrecé **3 opciones variadas** (mañana y tarde, o diferentes días) para que el paciente elija. Ej: "Para hoy no me queda nada, pero mañana tengo a las 9:15, o el lunes a las 17:00. ¿Alguna te sirve?".
5. **Datos Personales:** Pedí los datos (Nombre, Apellido, DNI, Teléfono, Obra Social) solo cuando la hora ya esté clara, y hacelo de forma conversacional.
6. **Cierre:** Antes de usar `agendar_turno`, confirmá los detalles finales. Si el usuario dice "Si", "Dale" o similar, procedé inmediatamente.

### 🛠 REGLAS DE ORO:
- Hoy es {today}.
- No inventes horarios. Usá las herramientas.
- Si no entendés algo, preguntá con dulzura.
"""

def build_agent():
    """Create the LangChain agent with tools."""
    provider = get_config("AI_PROVIDER", "openai").lower()
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

    llm = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.3,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agent = create_openai_tools_agent(llm, ALL_TOOLS, prompt)
    return AgentExecutor(agent=agent, tools=ALL_TOOLS, verbose=True, max_iterations=10)


# Singleton agent
_agent_executor = None


def get_agent() -> AgentExecutor:
    global _agent_executor
    if _agent_executor is None:
        _agent_executor = build_agent()
    return _agent_executor


def chat(user_message: str, history: list[dict] | None = None) -> str:
    """Process a user message and return agent response."""
    print(f"DEBUG: AI_AGENT_IN -> Msg: '{user_message}', HistLen: {len(history) if history else 0}")
    
    # Refresh agent if provider changed (simplified singleton management)
    # In production, we might want a more robust way to handle dynamic config changes
    agent = get_agent()
    
    chat_history = []
    if history:
        for msg in history:
            if msg["role"] == "user":
                chat_history.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                chat_history.append(AIMessage(content=msg["content"]))

    result = agent.invoke({
        "input": user_message, 
        "chat_history": chat_history,
        "today": get_clinic_now().strftime("%d/%m/%Y %H:%M") # Use clinic local time
    })
    return result["output"]

