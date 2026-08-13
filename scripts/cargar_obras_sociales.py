"""Carga las obras sociales del Círculo Odontológico San Rafael.

Fuente: https://cosanrafael.com.ar/lista-obras-sociales/ (48 logos, leídos
manualmente uno por uno porque la página no tiene los nombres en texto, solo
en imágenes-logo sin alt).

Es un upsert por nombre, no un reemplazo total: si el nombre ya existe se
actualiza el código y se reactiva; si no existe se crea. Las obras sociales
que ya tenía la clínica y no están en esta lista (por ejemplo OSDE, OSPELSYM)
NO se tocan ni se borran — el pedido fue cargar estas, no vaciar las otras.

Uso:
    python scripts/cargar_obras_sociales.py --dry-run
    python scripts/cargar_obras_sociales.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.insurance import Insurance  # noqa: E402

# (nombre para mostrar, código) — nombre y código leídos directamente del logo
# de cada obra social, descargando las 48 imágenes de la página y mirándolas
# una por una (los <img> no tienen atributo alt, así que no había forma de
# extraer el texto de otro modo).
OBRAS_SOCIALES = [
    ("AAPM", "AAPM"),
    ("AMINT", "AMINT"),
    ("América Servicios", "AS"),
    ("Avalian", "AVALIAN"),
    ("Cardinal Assistance", "CARDINAL"),
    ("Círculo Oficiales de Mar", "COM"),
    ("Círculo de Suboficiales de la Policía Federal Argentina", "CSPFA"),
    ("D.A.S.U.Te.N.", "DASUTEN"),
    ("Docthos", "DOCTHOS"),
    ("Federada Salud", "FEDERADA"),
    ("Galeno", "GALENO"),
    ("Gerdanna Salud", "GERDANNA"),
    ("Grupo Roisa", "ROISA"),
    ("Hielo y Mercados Particulares", "HYM"),
    ("Jerárquicos Salud", "JERARQUICOS"),
    ("Medicus", "MEDICUS"),
    ("Medifé", "MEDIFE"),
    ("Mutual Personal Hospital Garrahan", "MPHG"),
    ("Mutual 20 de Octubre", "M20O"),
    ("Mutual de Socorros Mutuos", "MSM"),
    ("Asociación Mutual UTA", "UTA"),
    ("Nobis", "NOBIS"),
    ("Omint", "OMINT"),
    ("Omint C.S. Consulmed", "OMINT-CONSULMED"),
    ("Opdea", "OPDEA"),
    ("OSDIPP", "OSDIPP"),
    ("OSDOP", "OSDOP"),
    ("OSEP", "OSEP"),
    ("OSFATLyF", "OSFATLYF"),
    ("OSJERA", "OSJERA"),
    ("OSALARA", "OSALARA"),
    ("O.S.M.A.T.A.", "OSMATA"),
    ("O.S.P.F. (Obra Social del Personal de Farmacia)", "OSPF"),
    ("OSPJN (Obra Social del Poder Judicial de la Nación)", "OSPJN"),
    ("OSSEG", "OSSEG"),
    ("OSSBA (Servicios Sociales Bancarios)", "OSSBA"),
    ("OSTEL", "OSTEL"),
    ("Prevención Salud", "PREVENCION"),
    ("OSTVENDRA", "OSTVENDRA"),
    ("SADAIC", "SADAIC"),
    ("Conferencia Episcopal Argentina (OSPECA)", "OSPECA"),
    ("SCIS", "SCIS"),
    ("SanCor Salud", "SANCOR"),
    ("Superintendencia de Bienestar (Policía Federal)", "SBPF"),
    ("Swiss Medical", "SM"),
    ("Unimed", "UNIMED"),
    ("TV Salud (OSPTV)", "OSPTV"),
    ("William Hope", "WHOPE"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No escribe, solo informa")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existentes = {i.name.lower(): i for i in db.query(Insurance).all()}
        nuevas, actualizadas = 0, 0

        for nombre, codigo in OBRAS_SOCIALES:
            actual = existentes.get(nombre.lower())
            if actual:
                cambia = actual.code != codigo or actual.is_deleted or not actual.is_active
                if cambia:
                    print(f"  actualiza: {nombre} (code {actual.code!r} -> {codigo!r})")
                    if not args.dry_run:
                        actual.code = codigo
                        actual.is_active = True
                        actual.is_deleted = False
                    actualizadas += 1
                else:
                    print(f"  sin cambios: {nombre}")
            else:
                print(f"  nueva: {nombre}")
                if not args.dry_run:
                    db.add(Insurance(name=nombre, code=codigo, is_active=True))
                nuevas += 1

        print(f"\nNuevas: {nuevas}  |  Actualizadas: {actualizadas}  |  "
              f"Sin cambios: {len(OBRAS_SOCIALES) - nuevas - actualizadas}")

        if args.dry_run:
            print("\n--dry-run: no se escribió nada.")
            return

        db.commit()

        print("\nObras sociales activas ahora:")
        for i in db.query(Insurance).filter(Insurance.is_active == True).order_by(Insurance.name).all():  # noqa: E712
            print(f"  {i.name} ({i.code})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
