"""DentiBot tools - communicate with the backend API (OpenAI function calling)."""
import os
import json
import contextvars
import httpx

API_BASE = os.getenv("API_BASE_URL", "http://backend:8000")
BOT_KEY = os.getenv("BOT_API_KEY", "dev-bot-key-change-in-prod")
HEADERS = {"x-bot-key": BOT_KEY, "Content-Type": "application/json"}

# Identidad de la conversación actual (número de WhatsApp real del remitente).
# Lo setea chat() antes de invocar al agente; las tools lo leen para que el
# backend pueda verificar que el DNI pertenece a quien escribe. En Telegram
# (que no tiene teléfono) queda None y no se aplica ninguna verificación.
_requester_phone: contextvars.ContextVar = contextvars.ContextVar("requester_phone", default=None)


def set_requester_phone(phone):
    """Registra el teléfono de quien envía el mensaje para la conversación actual."""
    _requester_phone.set(phone or None)


def _current_requester_phone():
    return _requester_phone.get()


# ── Tool implementations ─────────────────────────────────────────────────────

def agendar_turno(
    reason: str,
    preferred_date: str,
    patient_name: str = "",
    patient_last_name: str = "",
    dni: str = "",
    phone: str = "",
    location: str = "San Rafael",
    insurance_name: str = "Particular",
    duration_minutes: int = 30,
) -> str:
    """Agenda un nuevo turno en el sistema."""
    payload = {
        "patient_name": patient_name,
        "patient_last_name": patient_last_name,
        "dni": dni,
        "phone": phone,
        "reason": reason,
        "location": location,
        "insurance_name": insurance_name,
        "preferred_date": preferred_date,
        "duration_minutes": duration_minutes,
        "requester_phone": _current_requester_phone(),
    }
    try:
        r = httpx.post(f"{API_BASE}/api/bot/appointments", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        cancel_url = f"https://odobot.aiporvos.com/api/public/cancel/{data['appointment_id']}"
        return (
            f"✅ {data['message']}. Fecha: {data['datetime']}. ID: {data['appointment_id']}. "
            f"Aclarale al paciente que si desea cancelar el turno, puede escribir "
            f"'quiero cancelar mi turno' o ingresar a este link: {cancel_url}"
        )
    except httpx.HTTPStatusError as e:
        try:
            motivo = e.response.json().get("detail", str(e))
        except Exception:
            motivo = e.response.text or str(e)
        return f"❌ No se pudo agendar: {motivo}"
    except Exception as e:
        return f"❌ Error al agendar: {str(e)}"


def cancelar_turno(dni: str = "", appointment_id: str = "") -> str:
    """Cancela un turno existente del paciente."""
    payload = {"dni": dni or None, "requester_phone": _current_requester_phone()}
    if appointment_id:
        payload["appointment_id"] = appointment_id
    try:
        r = httpx.post(f"{API_BASE}/api/bot/cancel", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return f"✅ {r.json()['message']}"
    except httpx.HTTPStatusError as e:
        return f"❌ {e.response.json().get('detail', 'Error al cancelar')}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


def reprogramar_turno(appointment_id: str, new_datetime: str, dni: str = "") -> str:
    """Reprograma un turno existente a una nueva fecha."""
    payload = {
        "dni": dni or None,
        "appointment_id": appointment_id,
        "new_start_time": new_datetime,
        "requester_phone": _current_requester_phone(),
    }
    try:
        r = httpx.post(f"{API_BASE}/api/bot/reschedule", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return f"✅ {r.json()['message']}"
    except httpx.HTTPStatusError as e:
        return f"❌ {e.response.json().get('detail', 'Error al reprogramar')}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


def consultar_mis_turnos(dni: str = "") -> str:
    """Consulta los turnos pendientes de un paciente."""
    try:
        payload = {"dni": dni or None, "requester_phone": _current_requester_phone()}
        r = httpx.post(f"{API_BASE}/api/bot/my-appointments", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data["appointments"]:
            return f"ℹ️ {data['patient']}, no tenés turnos pendientes."
        lines = [f"📋 Turnos de {data['patient']}:"]
        for a in data["appointments"]:
            lines.append(f"  • {a['date']} - {a['reason']} con {a['professional']} en {a['location']} ({a['status']})")
        return "\n".join(lines)
    except httpx.HTTPStatusError as e:
        return f"❌ {e.response.json().get('detail', 'Paciente no encontrado')}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


def consultar_disponibilidad(
    motivo_confirmado_por_paciente: str,
    location: str = "San Rafael",
    date: str = "",
    obra_social: str = "Particular",
    preferencia_horaria: str = "",
) -> str:
    """Consulta los horarios disponibles para una sede, especialidad y fecha."""
    try:
        payload = {
            "location": location,
            "reason": motivo_confirmado_por_paciente,
            "date": date,
            "obra_social": obra_social,
            "preferencia_horaria": preferencia_horaria or None,
        }
        r = httpx.post(f"{API_BASE}/api/bot/availability", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        slots = data.get("available_slots", [])
        date_iso = data.get("date", "")
        fecha_texto = data.get("fecha_texto") or date_iso
        if not slots:
            return (
                f"No hay turnos disponibles en {location} en las próximas dos semanas. "
                f"Decíselo al paciente y ofrecele que deje sus datos para que lo contacten."
            )

        aviso = ""
        if data.get("movido"):
            motivo = data.get("motivo_salto") or "ese día no había disponibilidad"
            aviso = (
                f"OJO: el paciente pidió el {data.get('fecha_pedida_texto')}, pero {motivo}. "
                f"Avisale esto con naturalidad (no es un error ni pidas disculpas) y ofrecele "
                f"el {fecha_texto}, que es el próximo día con lugar. "
            )

        return (
            f"{aviso}"
            f"[FECHA GARANTIZADA FUTURA: {date_iso} = {fecha_texto}] "
            f"Turnos disponibles en {location} para el {fecha_texto}: {', '.join(slots)}. "
            f"Al escribirle al paciente usá EXACTAMENTE '{fecha_texto}'. PROHIBIDO calcular vos "
            f"el día de la semana. Cuando elija un horario, combiná {date_iso} con ese horario "
            f"para formar preferred_date en formato YYYY-MM-DD HH:MM. "
            f"NO llames a esta herramienta de nuevo."
        )
    except Exception as e:
        return f"Error consultando disponibilidad: {e}"


def verificar_obra_social(obra_social: str) -> str:
    """Verifica si la clínica atiende una obra social."""
    try:
        r = httpx.post(
            f"{API_BASE}/api/bot/verificar-obra-social",
            json={"obra_social": obra_social},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        d = r.json()
        if d["cubierta"]:
            return (
                f"CUBIERTA. La clínica atiende {d['nombre']}. "
                f"Seguí normalmente con el turno usando obra_social='{d['nombre']}'."
            )
        activas = ", ".join(d["activas"]) or "ninguna"
        return (
            f"NO CUBIERTA. La clínica no atiende '{d['consultada']}'. "
            f"Decile al paciente con amabilidad que no trabajamos con esa obra social y que "
            f"su atención sería de forma PARTICULAR, y preguntale si desea avanzar así. "
            f"Si acepta, usá obra_social='Particular'. Si pregunta cuáles se atienden: {activas}. "
            f"PROHIBIDO agendar con '{d['consultada']}'."
        )
    except Exception as e:
        return f"Error verificando la obra social: {e}"


# ── Tool registry ────────────────────────────────────────────────────────────

_TOOL_MAP = {
    "agendar_turno": agendar_turno,
    "cancelar_turno": cancelar_turno,
    "reprogramar_turno": reprogramar_turno,
    "consultar_mis_turnos": consultar_mis_turnos,
    "consultar_disponibilidad": consultar_disponibilidad,
    "verificar_obra_social": verificar_obra_social,
}


def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool by name with the given arguments."""
    func = _TOOL_MAP.get(name)
    if not func:
        return f"❌ Tool desconocida: {name}"
    try:
        return func(**arguments)
    except TypeError as e:
        return f"❌ Argumentos incorrectos para {name}: {e}"
    except Exception as e:
        return f"❌ Error ejecutando {name}: {e}"


# ── OpenAI Function Definitions (JSON Schema) ────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "agendar_turno",
            "description": "Agenda un nuevo turno en el sistema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Nombre del paciente"},
                    "patient_last_name": {"type": "string", "description": "Apellido del paciente"},
                    "dni": {
                        "type": "string",
                        "description": "DNI del paciente. NO se lo pidas: el sistema lo identifica por su número de WhatsApp. Mandalo vacío. Solo completalo si el sistema te avisó que no reconoce el número y el paciente te dio el DNI.",
                    },
                    "phone": {
                        "type": "string",
                        "description": "Teléfono con característica, 10 dígitos (ej: 2604844952). NO es el DNI.",
                    },
                    "reason": {"type": "string", "description": "Motivo de la consulta (ej: Limpieza, Extracción)"},
                    "preferred_date": {
                        "type": "string",
                        "description": "Fecha y hora EXACTA en formato 'YYYY-MM-DD HH:MM' (ej: '2026-06-18 09:30'). OBLIGATORIO.",
                    },
                    "location": {"type": "string", "description": "Sede (por defecto 'San Rafael')", "default": "San Rafael"},
                    "insurance_name": {
                        "type": "string",
                        "description": "Obra Social (usar 'Particular' si no tiene)",
                        "default": "Particular",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duración: Consulta/Limpieza=15, Extracción/Ortodoncia=30, Endodoncia=60",
                        "default": 30,
                    },
                },
                "required": ["reason", "preferred_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancelar_turno",
            "description": "Cancela un turno existente del paciente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dni": {"type": "string", "description": "DNI del paciente. NO se lo pidas: el sistema lo identifica por su número de WhatsApp. Mandalo vacío. Solo completalo si el sistema te avisó que no reconoce el número y el paciente te dio el DNI."},
                    "appointment_id": {
                        "type": "string",
                        "description": "ID del turno a cancelar (opcional, cancela el próximo si no se indica)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reprogramar_turno",
            "description": "Reprograma un turno existente a una nueva fecha.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dni": {"type": "string", "description": "DNI del paciente. NO se lo pidas: el sistema lo identifica por su número de WhatsApp. Mandalo vacío. Solo completalo si el sistema te avisó que no reconoce el número y el paciente te dio el DNI."},
                    "appointment_id": {"type": "string", "description": "ID del turno a reprogramar"},
                    "new_datetime": {
                        "type": "string",
                        "description": "Nueva fecha y hora en formato ISO (ej: 2026-03-25T10:00:00)",
                    },
                },
                "required": ["appointment_id", "new_datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_mis_turnos",
            "description": "Consulta los turnos pendientes de un paciente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dni": {"type": "string", "description": "DNI del paciente. NO se lo pidas: el sistema lo identifica por su número de WhatsApp. Mandalo vacío. Solo completalo si el sistema te avisó que no reconoce el número y el paciente te dio el DNI."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_disponibilidad",
            "description": (
                "Consulta los horarios disponibles para una sede, especialidad y fecha. "
                "SOLO llamar cuando necesités buscar turnos nuevos. "
                "NO llamar si el paciente ya está eligiendo un horario de los que le ofreciste."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo_confirmado_por_paciente": {
                        "type": "string",
                        "description": (
                            "Motivo de la consulta dicho por el paciente (ej: Extracción, Limpieza). "
                            "PROHIBIDO adivinar; si no lo dijo, preguntale primero."
                        ),
                    },
                    "location": {"type": "string", "description": "Sede (por defecto 'San Rafael')", "default": "San Rafael"},
                    "date": {
                        "type": "string",
                        "description": "Fecha opcional (YYYY-MM-DD). Si se omite, busca para hoy.",
                    },
                    "obra_social": {
                        "type": "string",
                        "description": "Obra social del paciente (ej: Particular, PAMI, OSDE)",
                        "default": "Particular",
                    },
                    "preferencia_horaria": {
                        "type": "string",
                        "description": (
                            "Franja u hora que pidió el paciente, tal como la dijo. "
                            "Ejemplos: 'mañana', 'tarde', '18:45' (para 'después de las 18:45'), "
                            "'antes de las 11'. Dejar vacío si no expresó ninguna preferencia. "
                            "SIEMPRE pasarlo si el paciente mencionó un horario: sin esto se le "
                            "ofrecen horarios que no le sirven."
                        ),
                    },
                },
                "required": ["motivo_confirmado_por_paciente"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verificar_obra_social",
            "description": (
                "Verifica si la clínica atiende una obra social. "
                "USAR SIEMPRE apenas el paciente menciona su obra social, antes de seguir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "obra_social": {
                        "type": "string",
                        "description": "Nombre de la obra social tal como lo dijo el paciente (ej: OSDE, PAMI)",
                    },
                },
                "required": ["obra_social"],
            },
        },
    },
]
