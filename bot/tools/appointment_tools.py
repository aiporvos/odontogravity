"""DentiBot tools - communicate with the backend API."""
import os
import httpx
from langchain_core.tools import tool

API_BASE = os.getenv("API_BASE_URL", "http://backend:8000")
BOT_KEY = os.getenv("BOT_API_KEY", "dev-bot-key-change-in-prod")
HEADERS = {"x-bot-key": BOT_KEY, "Content-Type": "application/json"}


@tool
def agendar_turno(
    patient_name: str,
    patient_last_name: str,
    dni: str,
    phone: str,
    reason: str,
    location: str,
    insurance_name: str = "Particular",
    preferred_date: str = "",
    duration_minutes: int = 30
) -> str:
    """Agenda un nuevo turno en el sistema.
    Args:
        patient_name: Nombre del paciente
        patient_last_name: Apellido del paciente
        dni: DNI del paciente (solo números)
        phone: Teléfono de contacto
        reason: Motivo de la consulta (ej: Limpieza, Extracción)
        location: Sede (San Rafael o Alvear)
        insurance_name: Obra Social (usar 'Particular' si no tiene)
        preferred_date: Fecha/Hora sugerida (ej: 2024-03-25 10:00)
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
        "duration_minutes": duration_minutes
    }
    try:
        r = httpx.post(f"{API_BASE}/api/bot/appointments", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        return f"✅ {data['message']}. Fecha: {data['datetime']}. ID: {data['appointment_id']}"
    except Exception as e:
        return f"❌ Error al agendar: {str(e)}"


@tool
def cancelar_turno(dni: str, appointment_id: str = "") -> str:
    """Cancela un turno existente del paciente.
    Args:
        dni: DNI del paciente.
        appointment_id: ID del turno a cancelar (opcional, cancela el próximo si no se indica).
    """
    payload = {"dni": dni}
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
    payload = {"dni": dni, "appointment_id": appointment_id, "new_start_time": new_datetime}
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
        r = httpx.post(f"{API_BASE}/api/bot/my-appointments", json={"dni": dni}, headers=HEADERS, timeout=30)
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
def consultar_disponibilidad(location: str, date: str = "") -> str:
    """Consulta los horarios disponibles para una sede y fecha.
    Args:
        location: Sede (San Rafael o Alvear)
        date: Fecha opcional (YYYY-MM-DD). Si se omite, busca para hoy.
    """
    try:
        payload = {"location": location, "date": date}
        r = httpx.post(f"{API_BASE}/api/bot/availability", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        slots = data.get("available_slots", [])
        if not slots:
            return f"No hay turnos disponibles en {location} para esa fecha."
        return f"Turnos en {location} ({data.get('date')}): " + ", ".join(slots)
    except Exception as e:
        return f"Error consultando disponibilidad: {e}"

ALL_TOOLS = [agendar_turno, cancelar_turno, reprogramar_turno, consultar_mis_turnos, consultar_disponibilidad]
