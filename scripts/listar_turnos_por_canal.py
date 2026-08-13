"""Lista los turnos separados por quién los creó: el bot o el dashboard.

Se apoya en el campo `channel` que cada turno ya trae guardado:
    web                          -> cargado desde el dashboard (panel)
    phone                        -> cargado desde el dashboard (turno por teléfono)
    bot_whatsapp / bot_telegram  -> agendado por el bot

Por default solo muestra los turnos activos (no borrados). Con --incluir-borrados
se incluyen también los cancelados/eliminados.

Uso:
    python scripts/listar_turnos_por_canal.py
    python scripts/listar_turnos_por_canal.py --desde 2026-08-01 --hasta 2026-08-31
    python scripts/listar_turnos_por_canal.py --csv turnos.csv
    python scripts/listar_turnos_por_canal.py --incluir-borrados
"""
import argparse
import csv
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.appointment import Appointment, AppointmentChannel  # noqa: E402

BOT = {AppointmentChannel.bot_whatsapp, AppointmentChannel.bot_telegram}
DASHBOARD = {AppointmentChannel.web, AppointmentChannel.phone}

CANAL_TEXTO = {
    AppointmentChannel.web: "Dashboard",
    AppointmentChannel.phone: "Dashboard (teléfono)",
    AppointmentChannel.bot_whatsapp: "Bot (WhatsApp)",
    AppointmentChannel.bot_telegram: "Bot (Telegram)",
}


def fila(a):
    paciente = f"{a.patient.last_name}, {a.patient.first_name}" if a.patient else "?"
    profesional = a.professional.full_name if a.professional else "?"
    return {
        "fecha": a.start_time.strftime("%Y-%m-%d %H:%M"),
        "paciente": paciente,
        "profesional": profesional,
        "sede": a.location or "(sin asignar)",
        "estado": a.status.value,
        "motivo": (a.reason or "")[:40],
        "canal": CANAL_TEXTO.get(a.channel, a.channel.value),
    }


def imprimir_tabla(titulo, filas):
    print(f"\n{titulo} ({len(filas)})")
    print("-" * len(f"{titulo} ({len(filas)})"))
    if not filas:
        print("  (ninguno)")
        return
    for f in filas:
        print(f"  {f['fecha']}  {f['paciente']:<28} {f['profesional']:<18} "
              f"{f['sede']:<14} {f['estado']:<10} {f['motivo']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--desde", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--hasta", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--incluir-borrados", action="store_true")
    parser.add_argument("--csv", type=str, default=None, help="Ruta de archivo para exportar en vez de imprimir")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(Appointment)
        if not args.incluir_borrados:
            q = q.filter(Appointment.is_deleted == False)  # noqa: E712
        if args.desde:
            q = q.filter(Appointment.start_time >= datetime.fromisoformat(args.desde))
        if args.hasta:
            # "hasta" es inclusive: si viene solo la fecha (sin hora), se toma
            # hasta el final de ese dia, no desde las 00:00 (que excluiria
            # todo el dia pedido).
            limite = (datetime.fromisoformat(args.hasta) if "T" in args.hasta
                     else datetime.combine(date.fromisoformat(args.hasta), datetime.max.time()))
            q = q.filter(Appointment.start_time <= limite)
        turnos = q.order_by(Appointment.start_time).all()

        bot_filas = [fila(a) for a in turnos if a.channel in BOT]
        dash_filas = [fila(a) for a in turnos if a.channel in DASHBOARD]
        otros_filas = [fila(a) for a in turnos if a.channel not in BOT and a.channel not in DASHBOARD]

        if args.csv:
            with open(args.csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["origen", "fecha", "paciente", "profesional", "sede", "estado", "motivo", "canal"])
                for origen, filas in (("bot", bot_filas), ("dashboard", dash_filas), ("otro", otros_filas)):
                    for r in filas:
                        w.writerow([origen, r["fecha"], r["paciente"], r["profesional"],
                                   r["sede"], r["estado"], r["motivo"], r["canal"]])
            print(f"Exportado a {args.csv}: {len(turnos)} turnos "
                  f"({len(bot_filas)} bot, {len(dash_filas)} dashboard, {len(otros_filas)} otros)")
            return

        print(f"Total: {len(turnos)} turnos "
              f"({len(bot_filas)} del bot, {len(dash_filas)} del dashboard"
              + (f", {len(otros_filas)} de otro canal" if otros_filas else "") + ")")

        imprimir_tabla("CREADOS POR EL BOT", bot_filas)
        imprimir_tabla("CREADOS DESDE EL DASHBOARD", dash_filas)
        if otros_filas:
            imprimir_tabla("OTRO CANAL", otros_filas)
    finally:
        db.close()


if __name__ == "__main__":
    main()
