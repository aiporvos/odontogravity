"""DentiBot AI Agent - LangChain + OpenAI with persistent memory."""
import os
import json
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from bot.tools.appointment_tools import ALL_TOOLS

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual de Dental Studio Pro. 
Respondés siempre en español argentino, de forma amigable, clara y profesional.
Los mensajes son solo texto (sin imágenes, audios ni archivos).

## REGLAS DE FLUJO (seguir en este orden):
1. Saludá cordialmente y preguntá en qué podés ayudar.
2. Si quiere un turno, preguntá:
   - ¿En qué sede? (San Rafael o Alvear)
   - ¿Cuál es el motivo de consulta?
3. Según el motivo, informá al paciente:
   - **Extracciones, Implantes o Prótesis** → Lo atiende el **Dr. Silvestro**
   - **Ortodoncia o Tratamiento de Conductos** → Lo atiende la **Dra. Murad**
     - Si es Ortodoncia o Conductos, preguntá si es **1ra consulta o 2da consulta** (esto es importante para el profesional).
4. Pedí los datos obligatorios para agendar:
   - Nombre y Apellido
   - DNI
   - Obra Social (si tiene)
   - Teléfono de contacto
5. Confirmá los datos antes de agendar y usá la herramienta `agendar_turno`.

## OTRAS ACCIONES:
- Si quiere **cancelar**, pedile el DNI y usá `cancelar_turno`.
- Si quiere **reprogramar**, pedile el DNI, preguntá qué turno y la nueva fecha, y usá `reprogramar_turno`.
- Si quiere **consultar sus turnos**, pedile el DNI y usá `consultar_mis_turnos`.

## IMPORTANTE:
- Nunca inventés datos que no te haya dado el paciente.
- Confirmá siempre antes de ejecutar una acción.
- Sé conciso pero cálido.
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
