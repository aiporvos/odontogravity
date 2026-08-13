"""Carga los días y horarios en que atiende cada profesional.

Datos tal como los pasó el cliente por WhatsApp el 2026-08-13:

    Lunes y martes: Elena (Murad)
    Miércoles por la mañana y jueves todo el día: Martin (Silvestro)
    Viernes: PAMI, los dos, según la especialidad que necesite el paciente

Sin esta grilla, el bot ofrecía turnos de un profesional en cualquier día que
la clínica estuviera abierta, aunque ese profesional puntualmente no
trabajara ese día (ej. ofrecía Ortodoncia un miércoles, aunque Murad solo
atienda lunes y martes). El backend ahora hace la intersección de esta grilla
con el horario general de la clínica; el viernes es aparte, exclusivo para
PAMI (regla ya existente, no de esta tabla).

Es un reemplazo total por profesional, no un merge: corriéndolo de nuevo dos
veces dejando los mismos datos no cambia nada, pero si se vuelve a correr con
otros horarios, reemplaza los anteriores para ese profesional (no los suma).

Uso:
    python scripts/cargar_horarios_profesionales.py --dry-run
    python scripts/cargar_horarios_profesionales.py
"""
import argparse
import os
import sys
from datetime import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.professional import Professional  # noqa: E402
from backend.models.schedule import ProfessionalSchedule  # noqa: E402

LUN, MAR, MIE, JUE, VIE = 0, 1, 2, 3, 4
MANANA = (time(9, 0), time(12, 30))
TARDE = (time(17, 0), time(20, 30))

# Se busca por apellido, igual que en cargar_especialidades: el nombre
# completo puede variar entre instalaciones ("Dra. Elena Murad", "Dra. Murad").
HORARIOS_POR_APELLIDO = {
    "murad": [
        (LUN, *MANANA), (LUN, *TARDE),
        (MAR, *MANANA), (MAR, *TARDE),
        (VIE, *MANANA), (VIE, *TARDE),  # PAMI
    ],
    "silvestro": [
        (MIE, *MANANA),  # solo la mañana
        (JUE, *MANANA), (JUE, *TARDE),
        (VIE, *MANANA), (VIE, *TARDE),  # PAMI
    ],
}

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def describir(bloques):
    por_dia = {}
    for wd, ini, fin in bloques:
        por_dia.setdefault(wd, []).append(f"{ini.strftime('%H:%M')}-{fin.strftime('%H:%M')}")
    return ", ".join(f"{DIAS[wd]} ({'/'.join(horas)})" for wd, horas in sorted(por_dia.items()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No escribe, solo informa")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        for prof in db.query(Professional).filter(Professional.is_deleted == False).order_by(Professional.full_name).all():  # noqa: E712
            nombre = prof.full_name.lower()
            bloques = next(
                (v for apellido, v in HORARIOS_POR_APELLIDO.items() if apellido in nombre),
                None,
            )
            if bloques is None:
                print(f"  {prof.full_name}: sin regla conocida, no se toca")
                continue

            print(f"  {prof.full_name}: {describir(bloques)}")
            if args.dry_run:
                continue

            db.query(ProfessionalSchedule).filter(
                ProfessionalSchedule.professional_id == prof.id
            ).delete()
            for wd, ini, fin in bloques:
                db.add(ProfessionalSchedule(
                    professional_id=prof.id, weekday=wd, start_time=ini, end_time=fin,
                ))

        if args.dry_run:
            print("\n--dry-run: no se escribió nada.")
            return

        db.commit()

        print("\nGrilla final por profesional:")
        for prof in db.query(Professional).filter(Professional.is_deleted == False).order_by(Professional.full_name).all():  # noqa: E712
            filas = db.query(ProfessionalSchedule).filter(
                ProfessionalSchedule.professional_id == prof.id,
            ).order_by(ProfessionalSchedule.weekday, ProfessionalSchedule.start_time).all()
            if not filas:
                print(f"  {prof.full_name}: (sin grilla propia — disponible en todo el horario general)")
            else:
                print(f"  {prof.full_name}: " + describir([(f.weekday, f.start_time, f.end_time) for f in filas]))
    finally:
        db.close()


if __name__ == "__main__":
    main()
