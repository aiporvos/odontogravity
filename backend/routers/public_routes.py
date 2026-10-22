from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import timedelta
from html import escape
import logging

from backend.database import get_db, SessionLocal
from backend.models.appointment import Appointment, AppointmentStatus
from backend.services.reminders_loop import notify_admins

router = APIRouter(prefix="/api/public", tags=["Public"])
logger = logging.getLogger(__name__)

# Los links que ya se mandaron no tienen firma. Siguen valiendo para los turnos
# creados hasta esta fecha (la del deploy de la firma); los nuevos, solo firmados.
import os  # noqa: E402
from datetime import datetime  # noqa: E402
LINKS_SIN_FIRMA_HASTA = datetime.fromisoformat(os.getenv("LINKS_SIN_FIRMA_HASTA", "2026-10-24T00:00"))

_LINK_INVALIDO = ("<h1>Link no válido</h1><p>Este link de cancelación no es válido. "
                  "Si querés cancelar tu turno, escribinos por WhatsApp.</p>")
_TURNO_PASADO = ("<h1>Turno pasado</h1><p>Este turno ya pasó. Para cualquier cambio "
                 "escribinos por WhatsApp.</p>")


async def _avisar_a_recepcion(mensaje: str):
    db = SessionLocal()
    try:
        await notify_admins(db, mensaje)
    finally:
        db.close()


def _link_rechazado(appt, t: str | None) -> str | None:
    """El HTML de rechazo, o None si el link sirve para ese turno."""
    from backend.services.urls import firma_valida
    from backend.services.appointment_service import get_clinic_now
    if not firma_valida(appt.id, t) and not (appt.created_at and appt.created_at < LINKS_SIN_FIRMA_HASTA):
        return _LINK_INVALIDO
    if appt.start_time <= get_clinic_now():
        return _TURNO_PASADO
    return None

@router.get("/cancel/{appointment_id}", response_class=HTMLResponse)
async def cancel_appointment_page(appointment_id: UUID, t: str | None = None,
                                  db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.is_deleted == False).first()
    if not appt:
        return "<h1>Error</h1><p>Turno no encontrado o ya fue eliminado.</p>"
    if rechazo := _link_rechazado(appt, t):
        return rechazo

    if appt.status == AppointmentStatus.cancelled:
        return "<h1>Turno Cancelado</h1><p>Este turno ya había sido cancelado anteriormente.</p>"

    patient = appt.patient
    # Times are already stored in local time, no need to convert
    local_time = appt.start_time
    time_str = local_time.strftime("%d/%m/%Y a las %H:%M")

    # Escapar datos que provienen de la base para evitar inyección de HTML/JS
    safe_first_name = escape(patient.first_name or "")
    safe_location = escape(appt.location or "")

    html_content = f"""
    <html>
        <head>
            <title>Cancelar Turno</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; background-color: #f9f9f9; }}
                .container {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); max-width: 400px; margin: auto; }}
                h2 {{ color: #333; }}
                .btn {{ background-color: #d9534f; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; margin-top: 20px; text-decoration: none; display: inline-block; }}
                .btn:hover {{ background-color: #c9302c; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Cancelar Turno</h2>
                <p>Hola <b>{safe_first_name}</b>,</p>
                <p>¿Estás seguro que querés cancelar tu turno del <b>{time_str}</b> en <b>{safe_location}</b>?</p>
                <form method="POST" action="/api/public/cancel/{appointment_id}/confirm?t={escape(t or '')}">
                    <button type="submit" class="btn">Sí, cancelar turno</button>
                </form>
            </div>
        </body>
    </html>
    """
    return html_content

@router.post("/cancel/{appointment_id}/confirm", response_class=HTMLResponse)
async def confirm_cancel_appointment(appointment_id: UUID, t: str | None = None,
                                     db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.is_deleted == False).first()
    if not appt:
        return "<h1>Error</h1><p>Turno no encontrado.</p>"
    if rechazo := _link_rechazado(appt, t):
        return rechazo

    if appt.status == AppointmentStatus.cancelled:
        return "<h1>Turno Cancelado</h1><p>El turno ya estaba cancelado.</p>"

    appt.status = AppointmentStatus.cancelled
    db.commit()
    
    # Notify admin
    patient = appt.patient
    local_time = appt.start_time
    time_str = local_time.strftime("%d/%m/%Y a las %H:%M")
    admin_msg = f"⚠️ *TURNO CANCELADO*\nEl paciente {patient.first_name} {patient.last_name} canceló su turno para el {time_str} en {appt.location}."
    
    # La sesion del aviso se cierra al terminar. Antes quedaba abierta: cada
    # cancelacion por link se llevaba una conexion del pool para siempre.
    import asyncio
    asyncio.create_task(_avisar_a_recepcion(admin_msg))

    html_content = """
    <html>
        <head>
            <title>Turno Cancelado</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background-color: #f9f9f9; }
                .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); max-width: 400px; margin: auto; }
                h2 { color: #5cb85c; }
            </style>
        </head>
        <body>
            <div class="container">
                <h2>✅ Turno Cancelado Exitosamente</h2>
                <p>Tu turno ha sido cancelado. Gracias por avisarnos.</p>
                <p>Podés cerrar esta ventana.</p>
            </div>
        </body>
    </html>
    """
    return html_content
