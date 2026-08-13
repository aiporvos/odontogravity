"""Muestra un resumen y listado detallado de turnos creados por el Bot (WhatsApp / Telegram) vs Dashboard (Web / Teléfono).

Uso:
    python scripts/listar_turnos.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.appointment import Appointment, AppointmentChannel  # noqa: E402
from backend.models.patient import Patient  # noqa: E402
from backend.models.professional import Professional  # noqa: E402


def main():
    db = SessionLocal()
    try:
        turnos = db.query(Appointment).filter(
            Appointment.is_deleted == False
        ).order_by(Appointment.start_time.desc()).all()

        if not turnos:
            print("No hay turnos registrados en la base de datos.")
            return

        conteo_canal = {}
        for t in turnos:
            ch_str = str(t.channel.value) if hasattr(t.channel, 'value') else str(t.channel)
            conteo_canal[ch_str] = conteo_canal.get(ch_str, 0) + 1

        print("==================================================")
        print("📊 RESUMEN DE TURNOS POR CANAL DE ORIGEN")
        print("==================================================")
        print(f"Total turnos activos: {len(turnos)}")
        print(f"  • Bot WhatsApp: {conteo_canal.get('bot_whatsapp', 0)}")
        print(f"  • Bot Telegram: {conteo_canal.get('bot_telegram', 0)}")
        print(f"  • Dashboard / Web: {conteo_canal.get('web', 0)}")
        print(f"  • Teléfono / Presencial: {conteo_canal.get('phone', 0)}")
        print("==================================================\n")

        print("==================================================")
        print("📅 LISTADO DETALLADO DE TURNOS")
        print("==================================================")
        for i, t in enumerate(turnos, 1):
            ch_str = str(t.channel.value) if hasattr(t.channel, 'value') else str(t.channel)
            if ch_str == "bot_whatsapp":
                origen = "🤖 Bot WhatsApp"
            elif ch_str == "bot_telegram":
                origen = "🤖 Bot Telegram"
            elif ch_str == "web":
                origen = "💻 Dashboard Web"
            else:
                origen = "📞 Teléfono / Presencial"

            paciente_nombre = t.patient.full_name if t.patient else "Desconocido"
            paciente_dni = t.patient.dni if t.patient else "-"
            prof_nombre = t.professional.full_name if t.professional else "Sin asignar"
            fecha_str = t.start_time.strftime("%d/%m/%Y %H:%M")
            estado_str = str(t.status.value) if hasattr(t.status, 'value') else str(t.status)
            motivo_str = t.reason or "Sin motivo especificado"
            os_str = t.insurance_name or "Particular"

            print(f"{i}. [{origen}] - {fecha_str}")
            print(f"   • Paciente: {paciente_nombre} (DNI: {paciente_dni})")
            print(f"   • Profesional: {prof_nombre}")
            print(f"   • Estado: {estado_str.upper()} | Cobertura: {os_str}")
            print(f"   • Motivo: {motivo_str}")
            print("-" * 50)

    finally:
        db.close()


if __name__ == "__main__":
    main()
