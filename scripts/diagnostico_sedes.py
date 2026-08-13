"""Dice por qué el desplegable de Sede aparece vacío al cargar un turno.

Ese desplegable sale de /api/clinic/locations, que solo devuelve sedes con
is_active=True e is_deleted=False. Si no hay ninguna así, el desplegable
queda vacío (ya no bloquea la creación del turno, pero conviene saber por
qué está vacío).

Uso:
    python scripts/diagnostico_sedes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.clinic_location import ClinicLocation  # noqa: E402


def main():
    db = SessionLocal()
    try:
        todas = db.query(ClinicLocation).order_by(ClinicLocation.name).all()
        if not todas:
            print("No hay NINGUNA sede cargada en la base (ni activa ni inactiva).")
            print("Hay que crear al menos una desde Configuración → Sedes.")
            return

        print("Sedes en la base:\n")
        activas = 0
        for s in todas:
            estado = []
            if not s.is_active:
                estado.append("INACTIVA")
            if s.is_deleted:
                estado.append("BORRADA")
            marca = f" ⚠️  {', '.join(estado)}" if estado else " ✓ activa y visible"
            if not estado:
                activas += 1
            print(f"  {s.name}{marca}")

        print(f"\nSedes que el desplegable puede mostrar (activas y no borradas): {activas}")
        if activas == 0:
            print("\n>>> Por eso el desplegable de Sede aparece vacío.")
            print(">>> Solución: en Configuración → Sedes, reactivá o creá al menos una.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
