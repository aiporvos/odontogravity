from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import timedelta
import logging

from backend.database import get_db, SessionLocal
from backend.models.appointment import Appointment, AppointmentStatus
from backend.services.reminders_loop import notify_admins

router = APIRouter(prefix="/api/public", tags=["Public"])
logger = logging.getLogger(__name__)

@router.get("/cancel/{appointment_id}", response_class=HTMLResponse)
async def cancel_appointment_page(appointment_id: UUID, db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.is_deleted == False).first()
    if not appt:
        return "<h1>Error</h1><p>Turno no encontrado o ya fue eliminado.</p>"
        
    if appt.status == AppointmentStatus.cancelled:
        return "<h1>Turno Cancelado</h1><p>Este turno ya había sido cancelado anteriormente.</p>"

    patient = appt.patient
    # Times are already stored in local time, no need to convert
    local_time = appt.start_time
    time_str = local_time.strftime("%d/%m/%Y a las %H:%M")
    
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
                <p>Hola <b>{patient.first_name}</b>,</p>
                <p>¿Estás seguro que querés cancelar tu turno del <b>{time_str}</b> en <b>{appt.location}</b>?</p>
                <form method="POST" action="/api/public/cancel/{appointment_id}/confirm">
                    <button type="submit" class="btn">Sí, cancelar turno</button>
                </form>
            </div>
        </body>
    </html>
    """
    return html_content

@router.post("/cancel/{appointment_id}/confirm", response_class=HTMLResponse)
async def confirm_cancel_appointment(appointment_id: UUID, db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(Appointment.id == appointment_id, Appointment.is_deleted == False).first()
    if not appt:
        return "<h1>Error</h1><p>Turno no encontrado.</p>"
        
    if appt.status == AppointmentStatus.cancelled:
        return "<h1>Turno Cancelado</h1><p>El turno ya estaba cancelado.</p>"

    appt.status = AppointmentStatus.cancelled
    db.commit()
    
    # Notify admin
    patient = appt.patient
    local_time = appt.start_time
    time_str = local_time.strftime("%d/%m/%Y a las %H:%M")
    admin_msg = f"⚠️ *TURNO CANCELADO*\nEl paciente {patient.first_name} {patient.last_name} canceló su turno para el {time_str} en {appt.location}."
    
    # This is async
    import asyncio
    asyncio.create_task(notify_admins(SessionLocal(), admin_msg))

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
