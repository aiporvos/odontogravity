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

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual de "Dental Studio Pro".
Tu objetivo es ayudar a los pacientes a agendar, cancelar o consultar turnos.

### 🕒 HORARIOS DE ATENCIÓN:
- Lunes a Viernes: 09:00 - 12:30 y 17:00 - 20:30.
- **Excepción:** Los Miércoles por la tarde el consultorio está CERRADO (solo atendemos de 9:00 a 12:30).

### 👨‍⚕️ PROFESIONALES Y DERIVACIÓN:
- **Dr. Martin Silvestro**: Especialista en Extracciones, Implantes y Prótesis.
- **Dra. Helena Murad**: Especialista en Ortodoncia y Conductos (Endodoncia).
*Regla:* Informá quién los atenderá ni bien sepas el motivo.

### ⏳ DURACIÓN POR SERVICIO (DentiBot debe saberlo):
- **Consulta / Limpieza**: 15 minutos.
- **Extracción**: 30 minutos.
- **Ortodoncia**: 30 minutos.
- **Endodoncia (Conductos)**: 60 minutos (1 hora).

### 🎯 TU MISIÓN:
1. **Sede y Motivo:** Preguntá dónde quiere atenderse (San Rafael o Alvear) y el motivo.
2. **Disponibilidad:** DEBÉS usar `consultar_disponibilidad` para ver qué horarios hay libres en esa sede. 
   - El bot buscará automáticamente hasta 7 días adelante si hoy está lleno.
   - **PROACTIVIDAD:** Ofrecé siempre **3 opciones claras** de turnos. Intentá que sean variadas (ej: "tengo mañana a las 9:15, o el lunes a las 17:00 y 17:30").
   - Si no hay nada hoy, decí: "Para hoy ya no tengo huecos, pero te puedo ofrecer para mañana o los próximos días: ..."
3. **Datos Personales:** Una vez elegida la hora, pedí Nombre, Apellido, DNI, Teléfono y Obra Social (o si es Particular).
4. **Resumen y Confirmación:** Antes de usar `agendar_turno`, resumí todo y pedí el OK final.
   - Usá el parámetro `duration_minutes` correcto según el servicio.

### 🛠 REGLAS DE ORO:
- Respondé en español argentino, profesional pero cálido.
- No muestres UUIDs largos. Usá solo los primeros 8 caracteres como "Código de Turno".
- Usá emojis (📅, 🏥, 🦷) para una mejor experiencia.
- Hoy es {today}.
"""


def build_agent():
    """Create the LangChain agent with tools."""
    llm = ChatOpenAI(
        model=MODEL_NAME,
        api_key=OPENAI_API_KEY,
        temperature=0.3,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
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

    result = agent.invoke({
        "input": user_message, 
        "chat_history": chat_history,
        "today": datetime.now().strftime("%d/%m/%Y %H:%M") # Include time for better context
    })
    return result["output"]
