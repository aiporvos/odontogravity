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

OPENAI_API_KEY = get_config("OPENAI_API_KEY")
MODEL_NAME = get_config("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual amigable de "Dental Studio Pro". 
Tu objetivo es ayudar a los pacientes a agendar, cancelar o consultar turnos.
Respondés en español argentino, de forma profesional pero cálida.

### 🎯 TU MISIÓN:
Llevar al paciente de forma fluida a través de la recolección de datos para agendar su turno.

### 🛠 REGLAS DE ORO:
1. **MEMORIA:** Antes de preguntar algo, revisá el historial. No vuelvas a preguntar la sede si el paciente ya la dijo. No vuelvas a preguntar el motivo si ya lo sabés.
2. **DATOS PARA AGENDAR:** Para crear un turno necesitás:
   - **Sede:** San Rafael o Alvear.
   - **Motivo de consulta:** (Extracción, Limpieza, Ortodoncia, etc.)
   - **Datos Personales:** Nombre, Apellido, DNI y Teléfono.
3. **DERIVACIÓN (Informale al paciente):**
   - **Cirugía/Implantes/Prótesis:** Lo atiende el **Dr. Silvestro**.
   - **Ortodoncia/Conductos/Niños:** Lo atiende la **Dra. Murad**.
4. **FLUJO NATURAL:** 
   - Saludá y preguntá cómo podés ayudar.
   - Si quiere un turno, preguntá lo que falte (Sede y Motivo primero).
   - Una vez que tengas sede y motivo, informá quién lo atiende y pedí sus datos personales.
   - **CONFIRMACIÓN:** Antes de usar la herramienta `agendar_turno`, resumí los datos y pedí confirmación final.

### 📅 CONTEXTO:
- Hoy es {today}.
- Si el paciente no especifica fecha, se agenda para el próximo horario disponible (no hace falta que él diga la fecha exacta, vos podés ofrecerla o simplemente agendar).

### 🚫 RECOMENDACIÓN:
Mantené las respuestas breves. Si ya tenés la sede pero te falta el motivo, solo decí: "Perfecto, ¿y cuál es el motivo de tu consulta?".
"""


def build_agent():
    """Create the LangChain agent with tools."""
    llm = ChatOpenAI(
        model=MODEL_NAME,
        api_key=OPENAI_API_KEY,
        temperature=0.3,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT.format(today=datetime.now().strftime("%d/%m/%Y"))),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agent = create_openai_tools_agent(llm, ALL_TOOLS, prompt)
    return AgentExecutor(agent=agent, tools=ALL_TOOLS, verbose=True, max_iterations=5)


# Singleton agent
_agent_executor = None


def get_agent() -> AgentExecutor:
    global _agent_executor
    if _agent_executor is None:
        _agent_executor = build_agent()
    return _agent_executor


def chat(user_message: str, history: list[dict] | None = None) -> str:
    """Process a user message and return agent response.
    
    Args:
        user_message: The user's message
        history: List of dicts with 'role' and 'content' keys
    """
    agent = get_agent()
    chat_history = []
    if history:
        for msg in history:
            if msg["role"] == "user":
                chat_history.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                chat_history.append(AIMessage(content=msg["content"]))

    result = agent.invoke({"input": user_message, "chat_history": chat_history})
    return result["output"]
