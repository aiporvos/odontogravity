"""Normaliza turnos existentes: asigna la sede faltante y confirma los pendientes.

Arregla dos cosas que venían de antes:

1. Los turnos cargados desde el panel se guardaban sin sede (`location = NULL`),
   porque el formulario no pedía sede. En SQL `location = 'San Rafael'` nunca
   matchea NULL, así que esos turnos eran invisibles al calcular disponibilidad
   y el bot ofrecía horarios ya ocupados.

2. Los turnos quedaban en estado `pending`, y el loop de recordatorios solo
   notifica los `confirmed`, así que nunca disparaban el aviso de WhatsApp.

Es idempotente: correrlo dos veces no cambia nada la segunda vez.

Uso:
    python scripts/normalizar_turnos.py --dry-run     # solo muestra qué haría
    python scripts/normalizar_turnos.py               # aplica los cambios

La sede por defecto se puede cambiar con --sede "Otra Sede".

Con --sede-unica además da de baja las demás sedes, para que dejen de aparecer
en el desplegable al cargar un turno. Es un borrado lógico (is_deleted), así que
se puede revertir; no toca los turnos históricos que las tengan asignadas.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.appointment import Appointment, AppointmentStatus  # noqa: E402
from backend.models.clinic_location import ClinicLocation  # noqa: E402


def resumen(db):
    filas = (
        db.query(Appointment.location, Appointment.status)
        .filter(Appointment.is_deleted == False)  # noqa: E712
        .all()
    )
    conteo = {}
    for location, status in filas:
        clave = (location or "<<sin sede>>", status.value if status else "?")
        conteo[clave] = conteo.get(clave, 0) + 1
    for (loc, st), n in sorted(conteo.items(), key=lambda x: -x[1]):
        print(f"    {loc:<16} {st:<12} {n}")
    if not conteo:
        print("    (sin turnos activos)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sede", default="San Rafael", help="Sede a asignar a los turnos sin sede")
    parser.add_argument("--dry-run", action="store_true", help="No escribe, solo informa")
    parser.add_argument("--sede-unica", action="store_true",
                        help="Da de baja las demás sedes (borrado lógico, reversible)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        print("Antes:")
        resumen(db)

        sin_sede = db.query(Appointment).filter(
            Appointment.location.is_(None),
            Appointment.is_deleted == False,  # noqa: E712
        ).all()
        pendientes = db.query(Appointment).filter(
            Appointment.status == AppointmentStatus.pending,
            Appointment.is_deleted == False,  # noqa: E712
        ).all()

        sobrantes = []
        if args.sede_unica:
            sobrantes = db.query(ClinicLocation).filter(
                ClinicLocation.name != args.sede,
                ClinicLocation.is_deleted == False,  # noqa: E712
            ).all()

        print(f"\nA cambiar: {len(sin_sede)} sin sede -> '{args.sede}' | "
              f"{len(pendientes)} pendientes -> confirmados")
        if args.sede_unica:
            nombres = ", ".join(s.name for s in sobrantes) or "ninguna"
            print(f"           sedes a dar de baja: {nombres}")
            con_turnos = [
                s.name for s in sobrantes
                if db.query(Appointment).filter(Appointment.location == s.name).count()
            ]
            if con_turnos:
                print(f"           ⚠️  tienen turnos asociados: {', '.join(con_turnos)} "
                      f"(los turnos NO se tocan, solo deja de ofrecerse la sede)")

        if args.dry_run:
            print("\n--dry-run: no se escribió nada.")
            return

        for a in sin_sede:
            a.location = args.sede
        for a in pendientes:
            a.status = AppointmentStatus.confirmed
        for s in sobrantes:
            s.is_deleted = True
            s.is_active = False
        db.commit()

        print("\nDespués:")
        resumen(db)
        activas = db.query(ClinicLocation).filter(
            ClinicLocation.is_deleted == False,  # noqa: E712
        ).order_by(ClinicLocation.name).all()
        print(f"    sedes activas: {', '.join(s.name for s in activas) or 'ninguna'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
