"""Encuentra (y opcionalmente resuelve) turnos que se pisan en el mismo horario.

La migracion f1a2b3c4d5e6 crea un indice unico que impide tener dos turnos
vivos del mismo profesional a la misma hora. Si la base ya venia con
duplicados —cosa posible, porque durante mucho tiempo el bot agendaba sin
validar solapamiento— el indice no se puede crear y la migracion lo saltea
avisando por log. Este script es el paso previo.

NO borra nada a secas: de cada turno cuelga un paciente que espera ser
atendido. Lo que hace es mostrarlos para que alguien de la clinica decida, y
con --resolver deja el mas antiguo (el que reservo primero) y marca los demas
como cancelados, que es reversible desde el panel.

Uso:
    python scripts/detectar_turnos_duplicados.py
    python scripts/detectar_turnos_duplicados.py --resolver --dry-run
    python scripts/detectar_turnos_duplicados.py --resolver
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.appointment import Appointment, AppointmentStatus  # noqa: E402

VIVOS = (AppointmentStatus.pending, AppointmentStatus.confirmed, AppointmentStatus.completed)


def grupos_duplicados(db):
    """Turnos vivos agrupados por (profesional, horario), solo los que repiten."""
    turnos = db.query(Appointment).filter(
        Appointment.is_deleted == False,  # noqa: E712
        Appointment.status.in_(VIVOS),
    ).order_by(Appointment.start_time, Appointment.created_at).all()

    por_hueco = {}
    for t in turnos:
        por_hueco.setdefault((t.professional_id, t.start_time), []).append(t)
    return {k: v for k, v in por_hueco.items() if len(v) > 1}


def describir(t) -> str:
    p = t.patient
    quien = f"{p.first_name} {p.last_name} (DNI {p.dni})" if p else "sin paciente"
    return (f"    · {quien} — {t.reason or 'sin motivo'} — {t.status.value} "
            f"— alta {t.created_at:%d/%m/%Y %H:%M} — id {t.id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolver", action="store_true",
                        help="Deja el turno mas antiguo y cancela los demas.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Muestra que haria, sin escribir.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        grupos = grupos_duplicados(db)
        if not grupos:
            print("✅ No hay turnos duplicados. El indice unico se puede crear sin problema.")
            return

        print(f"⚠️  {len(grupos)} horario(s) con mas de un turno activo:\n")
        a_cancelar = []
        for (prof_id, cuando), turnos in sorted(grupos.items(), key=lambda x: x[0][1]):
            prof = turnos[0].professional
            print(f"  {cuando:%d/%m/%Y %H:%M} — {prof.full_name if prof else prof_id} "
                  f"— {len(turnos)} turnos:")
            for t in turnos:
                print(describir(t))
            # El primero que reservo se queda; el resto se cancela.
            a_cancelar.extend(turnos[1:])
            print()

        if not args.resolver:
            print(f"Se cancelarian {len(a_cancelar)} turno(s) (se conserva el mas antiguo "
                  f"de cada horario).\nCorrelo con --resolver --dry-run para ver el detalle.")
            return

        print(f"{'[DRY-RUN] ' if args.dry_run else ''}Cancelando {len(a_cancelar)} turno(s):")
        for t in a_cancelar:
            print(f"  · id {t.id} — {t.start_time:%d/%m/%Y %H:%M}")
            if not args.dry_run:
                t.status = AppointmentStatus.cancelled
        if args.dry_run:
            print("\nNada se escribio. Sacá --dry-run para aplicarlo.")
        else:
            db.commit()
            print("\n✅ Listo. Avisale a esos pacientes y volvé a desplegar para "
                  "que se cree el indice.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
