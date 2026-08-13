"""DentiBot tools - communicate with the backend API."""
import os
import contextvars
import httpx
from langchain_core.tools import tool

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


@tool
def agendar_turno(
    patient_name: str,
    patient_last_name: str,
    dni: str,
    phone: str,
    reason: str,
    preferred_date: str,
    location: str = "San Rafael",
    insurance_name: str = "Particular",
    duration_minutes: int = 30
) -> str:
    """Agenda un nuevo turno en el sistema.
    Args:
        patient_name: Nombre del paciente
        patient_last_name: Apellido del paciente
        dni: DNI del paciente (solo números)
        phone: Teléfono de contacto
        reason: Motivo de la consulta (ej: Limpieza, Extracción)
        preferred_date: OBLIGATORIO. Fecha y hora EXACTA que el paciente eligió, en formato 'YYYY-MM-DD HH:MM'. Ejemplo: '2026-06-18 09:30'. NUNCA dejes este campo vacío.
        location: Sede (Por defecto "San Rafael")
        insurance_name: Obra Social (usar 'Particular' si no tiene)
        duration_minutes: Duración en minutos (Extracción: 30, Endodoncia: 60, Consulta/Limpieza: 15, Ortodoncia: 30)
    """
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
        return f"✅ {data['message']}. Fecha: {data['datetime']}. ID: {data['appointment_id']}. Aclarale al paciente que si desea cancelar el turno, puede escribir 'quiero cancelar mi turno' o ingresar a este link: {cancel_url}"
    except Exception as e:
        return f"❌ Error al agendar: {str(e)}"


@tool
def cancelar_turno(dni: str, appointment_id: str = "") -> str:
    """Cancela un turno existente del paciente.
    Args:
        dni: DNI del paciente.
        appointment_id: ID del turno a cancelar (opcional, cancela el próximo si no se indica).
    """
    payload = {"dni": dni, "requester_phone": _current_requester_phone()}
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


@tool
def reprogramar_turno(dni: str, appointment_id: str, new_datetime: str) -> str:
    """Reprograma un turno existente a una nueva fecha.
    Args:
        dni: DNI del paciente.
        appointment_id: ID del turno a reprogramar.
        new_datetime: Nueva fecha y hora en formato ISO (ej: 2024-03-25T10:00:00).
    """
    payload = {
        "dni": dni,
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


@tool
def consultar_mis_turnos(dni: str) -> str:
    """Consulta los turnos pendientes de un paciente.
    Args:
        dni: DNI del paciente.
    """
    try:
        payload = {"dni": dni, "requester_phone": _current_requester_phone()}
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

@tool
def consultar_disponibilidad(motivo_confirmado_por_paciente: str, location: str = "San Rafael", date: str = "", obra_social: str = "Particular") -> str:
    """Consulta los horarios disponibles para una sede, especialidad y fecha.
    Args:
        motivo_confirmado_por_paciente: Motivo de la consulta dicho por el paciente (ej: Extracción, Limpieza). ¡PROHIBIDO ADIVINAR O INVENTAR! Si el paciente no te ha dicho el motivo de la consulta, TIENES QUE PREGUNTÁRSELO y esperar su respuesta antes de usar esta herramienta.
        location: Sede (Por defecto "San Rafael")
        date: Fecha opcional (YYYY-MM-DD). Si se omite, busca para hoy.
        obra_social: Obra social del paciente (ej: Particular, PAMI, OSDE, etc.)
    """
    try:
        payload = {"location": location, "reason": motivo_confirmado_por_paciente, "date": date, "obra_social": obra_social}
        r = httpx.post(f"{API_BASE}/api/bot/availability", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        slots = data.get("available_slots", [])
        date_iso = data.get("date", "")            # YYYY-MM-DD
        # El día de la semana viene calculado por el backend. NO lo deduzca el
        # modelo a partir de la fecha: lo hacía y se equivocaba (llamó "lunes"
        # al 18/08/2026, que es martes).
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

@tool
def verificar_obra_social(obra_social: str) -> str:
    """Verifica si la clínica atiende una obra social. USAR SIEMPRE apenas el paciente la menciona, antes de seguir con cualquier otra cosa.
    Args:
        obra_social: El nombre de la obra social tal como lo dijo el paciente (ej: OSDE, Swiss Medical, Galeno).
    """
    try:
        r = httpx.post(f"{API_BASE}/api/bot/verificar-obra-social",
                       json={"obra_social": obra_social}, headers=HEADERS, timeout=15)
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


ALL_TOOLS = [agendar_turno, cancelar_turno, reprogramar_turno, consultar_mis_turnos, consultar_disponibilidad, verificar_obra_social]
