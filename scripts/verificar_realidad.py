"""Qué está realmente corriendo y qué protecciones tienen efecto.

El encargo lo pide antes que cualquier otra cosa, y con razón: en este proyecto
ya pasó dos veces que algo figuraba aplicado y no lo estaba. Estar en el head de
Alembic NO prueba que la restricción exista — la migración del sobreturno se
saltea a sí misma si la base tiene solapamientos previos, y eso es exactamente
lo que ocurre en producción.

Solo lee. No modifica nada.

    python scripts/verificar_realidad.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from backend.database import SessionLocal  # noqa: E402

RESTRICCION = "no_solapar_turnos_por_profesional"

SOLAPADOS = text("""
    SELECT count(*) FROM appointments a
    JOIN appointments b ON a.professional_id = b.professional_id AND a.id < b.id
     AND tsrange(a.start_time, a.start_time + make_interval(mins => COALESCE(a.duration_minutes, 30)))
      && tsrange(b.start_time, b.start_time + make_interval(mins => COALESCE(b.duration_minutes, 30)))
    WHERE a.is_deleted = false AND b.is_deleted = false
      AND a.status NOT IN ('cancelled', 'no_show')
      AND b.status NOT IN ('cancelled', 'no_show')
""")


def _titulo(t):
    print(f"\n── {t} " + "─" * max(0, 66 - len(t)))


def main():
    db = SessionLocal()
    try:
        _titulo("Versión del código")
        print(f"  GIT_COMMIT (env)   : {os.getenv('GIT_COMMIT') or '(no la pasa el build)'}")
        print(f"  Proveedores IA     : {os.getenv('AI_PROVIDER_ORDER') or '(default del código)'}")

        _titulo("Migraciones")
        version = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        print(f"  alembic_version    : {version}")

        _titulo("Protecciones EFECTIVAS en la base (no lo que dice la migración)")
        definicion = db.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"
        ), {"n": RESTRICCION}).scalar()
        if definicion:
            print(f"  {RESTRICCION}: PRESENTE")
            print(f"    {definicion}")
            print(f"    exceptúa sobreturnos: "
                  f"{'sí' if 'is_overbooking' in definicion else 'NO'}")
        else:
            print(f"  {RESTRICCION}: ⚠️  AUSENTE")
            print("    La agenda NO está protegida a nivel base contra turnos")
            print("    superpuestos. Solo valida el código de la aplicación.")

        solapados = db.execute(SOLAPADOS).scalar()
        print(f"  Pares de turnos vivos superpuestos: {solapados}")
        if solapados and not definicion:
            print("    ← esta es la razón por la que la restricción no se pudo crear:")
            print("      la migración detecta los solapamientos previos y se saltea.")

        _titulo("Configuración efectiva")
        filas = db.execute(text(
            "SELECT key, value FROM app_configs ORDER BY key"
        )).fetchall() if _existe_tabla(db, "app_configs") else []
        if filas:
            for k, v in filas:
                oculto = any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
                print(f"  {k:32} = {'(oculto)' if oculto else v}")
        else:
            print("  (sin tabla de configuración legible)")

        _titulo("Reglas de agenda cargadas")
        for etiqueta, consulta in [
            ("Profesionales activos", "SELECT count(*) FROM professionals WHERE is_deleted=false AND is_active=true"),
            ("Con grilla propia cargada", "SELECT count(DISTINCT professional_id) FROM professional_schedule WHERE is_active=true"),
            ("Franjas de clínica activas", "SELECT count(*) FROM clinic_schedule WHERE is_active=true"),
            ("Tipos de consulta cargados", "SELECT count(*) FROM tipos_consulta"),
            ("Obras sociales activas", "SELECT count(*) FROM insurances WHERE is_active=true AND is_deleted=false"),
            ("Sedes", "SELECT count(*) FROM clinic_locations"),
            ("Feriados cargados", "SELECT count(*) FROM clinic_holidays"),
        ]:
            try:
                print(f"  {etiqueta:32}: {db.execute(text(consulta)).scalar()}")
            except Exception as e:
                print(f"  {etiqueta:32}: (no se pudo leer: {str(e)[:60]})")

        _titulo("Huecos que el encargo pide exponer, no rellenar")
        sin_grilla = db.execute(text("""
            SELECT p.full_name FROM professionals p
            WHERE p.is_deleted=false AND p.is_active=true
              AND NOT EXISTS (SELECT 1 FROM professional_schedule s
                              WHERE s.professional_id=p.id AND s.is_active=true)
        """)).fetchall()
        print(f"  Profesionales SIN grilla propia: {len(sin_grilla)}")
        for (nombre,) in sin_grilla:
            print(f"    - {nombre}  (hoy hereda el horario de la clínica)")

        duplicados = db.execute(text("""
            SELECT count(*) FROM (
              SELECT lower(trim(first_name))||' '||lower(trim(last_name)) AS k
              FROM patients WHERE is_deleted=false
              GROUP BY k HAVING count(*) > 1
            ) t
        """)).scalar()
        print(f"  Nombres de paciente repetidos: {duplicados}")

        sin_contacto = db.execute(text("""
            SELECT count(*) FROM patients
            WHERE is_deleted=false
              AND coalesce(trim(dni),'') = '' AND coalesce(trim(phone),'') = ''
        """)).scalar()
        total = db.execute(text(
            "SELECT count(*) FROM patients WHERE is_deleted=false")).scalar()
        print(f"  Fichas sin DNI ni teléfono: {sin_contacto} de {total}")
        print("    ← ninguna de estas personas puede identificarse sola en el bot")
    finally:
        db.close()


def _existe_tabla(db, nombre) -> bool:
    return bool(db.execute(text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :n"
    ), {"n": nombre}).scalar())


if __name__ == "__main__":
    main()
