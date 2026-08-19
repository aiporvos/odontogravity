"""Unifica fichas duplicadas del mismo paciente en una sola.

En producción aparecieron dos fichas de "Claudio Luna" con el mismo teléfono y
DNIs distintos. Eso dejaba el historial partido entre las dos y hacía que el
bot no supiera cuál usar.

NO borra a secas: de cada ficha cuelgan turnos, odontograma y conversaciones.
Borrarlas perdería el historial clínico. Lo que hace es:

  1. Agrupar las fichas por nombre + apellido (ignorando mayúsculas y acentos).
  2. Elegir una sobreviviente: la que tenga más turnos; si empatan, la más
     antigua (es la ficha "original").
  3. Mover a la sobreviviente los turnos, entradas de odontograma y
     conversaciones de las demás.
  4. Dar de baja las otras con is_deleted=True. Es borrado lógico: la fila
     queda en la base y se puede revertir.

Uso:
    python scripts/unificar_pacientes_duplicados.py --dry-run
    python scripts/unificar_pacientes_duplicados.py --nombre "claudio luna" --dry-run
    python scripts/unificar_pacientes_duplicados.py --nombre "claudio luna"

Sin --nombre revisa TODOS los duplicados. Siempre conviene correr con
--dry-run primero y leer lo que va a hacer.
"""
import argparse
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.patient import Patient  # noqa: E402
from backend.models.appointment import Appointment  # noqa: E402
from backend.models.odontogram import OdontogramEntry  # noqa: E402
from backend.models.chat_session import ChatSession  # noqa: E402


def _norm(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(sin_acentos.lower().split())


def clave(p: Patient) -> str:
    return f"{_norm(p.first_name)} {_norm(p.last_name)}".strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nombre", default=None,
                        help='Unificar solo este paciente, ej: "claudio luna"')
    parser.add_argument("--dry-run", action="store_true",
                        help="No escribe, solo muestra qué haría")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        activos = db.query(Patient).filter(Patient.is_deleted == False).all()  # noqa: E712

        grupos: dict[str, list] = {}
        for p in activos:
            grupos.setdefault(clave(p), []).append(p)

        objetivo = _norm(args.nombre) if args.nombre else None
        duplicados = {
            k: v for k, v in grupos.items()
            if len(v) > 1 and (objetivo is None or k == objetivo)
        }

        if not duplicados:
            if objetivo:
                print(f"No hay fichas duplicadas de '{args.nombre}'.")
                iguales = grupos.get(objetivo, [])
                if iguales:
                    print(f"Hay una sola ficha: DNI {iguales[0].dni}. Nada que unificar.")
            else:
                print("No hay fichas duplicadas.")
            return

        total_movidos = 0
        for nombre, fichas in duplicados.items():
            def turnos_de(p):
                return db.query(Appointment).filter(Appointment.patient_id == p.id).count()

            # La que más historial tiene; si empatan, la más antigua.
            fichas_ord = sorted(
                fichas,
                key=lambda p: (-turnos_de(p), p.created_at or __import__("datetime").datetime.max),
            )
            sobrevive, resto = fichas_ord[0], fichas_ord[1:]

            print(f"\n{nombre.title()} — {len(fichas)} fichas")
            print(f"  SE QUEDA:  DNI {sobrevive.dni}  ({turnos_de(sobrevive)} turnos, tel {sobrevive.phone})")

            for p in resto:
                n_turnos = db.query(Appointment).filter(Appointment.patient_id == p.id).count()
                n_odo = db.query(OdontogramEntry).filter(OdontogramEntry.patient_id == p.id).count()
                n_chat = db.query(ChatSession).filter(ChatSession.patient_id == p.id).count()
                print(f"  SE UNIFICA: DNI {p.dni}  -> mueve {n_turnos} turno(s), "
                      f"{n_odo} entrada(s) de odontograma, {n_chat} conversación(es)")
                total_movidos += n_turnos + n_odo + n_chat

                if args.dry_run:
                    continue

                db.query(Appointment).filter(Appointment.patient_id == p.id).update(
                    {"patient_id": sobrevive.id}, synchronize_session=False)
                db.query(OdontogramEntry).filter(OdontogramEntry.patient_id == p.id).update(
                    {"patient_id": sobrevive.id}, synchronize_session=False)
                db.query(ChatSession).filter(ChatSession.patient_id == p.id).update(
                    {"patient_id": sobrevive.id}, synchronize_session=False)

                # Conservar datos que la ficha sobreviviente no tenga cargados.
                for campo in ("phone", "email", "insurance_name", "insurance_number", "address"):
                    if not (getattr(sobrevive, campo, None) or "").strip():
                        valor = (getattr(p, campo, None) or "").strip()
                        if valor:
                            setattr(sobrevive, campo, valor)

                p.is_deleted = True

        if args.dry_run:
            print(f"\n--dry-run: no se escribió nada. Se moverían {total_movidos} registros.")
            return

        db.commit()
        print(f"\nListo. Se movieron {total_movidos} registros y se dieron de baja "
              f"{sum(len(v) - 1 for v in duplicados.values())} ficha(s) duplicada(s).")
        print("Es borrado lógico (is_deleted): las filas siguen en la base y se puede revertir.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
