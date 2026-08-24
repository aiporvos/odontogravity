"""Cambia la password de un usuario del panel.

Las bases que ya existen fueron sembradas con las passwords de ejemplo
("admin123" / "recepcion123"), que ademas estaban publicadas en el README. El
seed nuevo ya no las usa, pero eso no arregla las cuentas creadas antes: hay
que rotarlas una vez, a mano, en cada instalacion.

Detras de ese login hay historia clinica y odontogramas, asi que conviene
hacerlo antes que cualquier otra cosa.

Uso:
    python scripts/cambiar_password.py --listar
    python scripts/cambiar_password.py --email admin@dentalstudio.com
    python scripts/cambiar_password.py --email admin@dentalstudio.com --password "la-que-quieras"

Sin --password genera una segura al azar y la muestra una sola vez.
"""
import argparse
import getpass
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.security import hash_password, verify_password  # noqa: E402

DEBILES = ["admin123", "recepcion123", "123456", "password"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Email del usuario a modificar.")
    parser.add_argument("--password", help="Password nueva. Si se omite, se genera una.")
    parser.add_argument("--preguntar", action="store_true",
                        help="Pide la password por teclado, sin que quede en el historial.")
    parser.add_argument("--listar", action="store_true",
                        help="Lista los usuarios y marca los que siguen con password de ejemplo.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.listar or not args.email:
            usuarios = db.query(User).order_by(User.email).all()
            if not usuarios:
                print("No hay usuarios cargados.")
                return
            print(f"{len(usuarios)} usuario(s):\n")
            for u in usuarios:
                debil = next(
                    (d for d in DEBILES if verify_password(d, u.hashed_password)), None
                )
                marca = f"  ⚠️  PASSWORD DE EJEMPLO ({debil})" if debil else "  ✅"
                print(f"{marca}  {u.email}  —  {u.full_name}  [{u.role.value}]")
            if not args.email:
                print("\nPara cambiar una: --email <email>")
            return

        usuario = db.query(User).filter(User.email == args.email).first()
        if not usuario:
            print(f"❌ No existe un usuario con email {args.email}")
            sys.exit(1)

        if args.preguntar:
            nueva = getpass.getpass("Password nueva: ")
            if nueva != getpass.getpass("Repetila: "):
                print("❌ No coinciden.")
                sys.exit(1)
            generada = False
        elif args.password:
            nueva, generada = args.password, False
        else:
            nueva, generada = secrets.token_urlsafe(12), True

        if len(nueva) < 8:
            print("❌ Muy corta: usá al menos 8 caracteres.")
            sys.exit(1)

        usuario.hashed_password = hash_password(nueva)
        db.commit()
        print(f"✅ Password actualizada para {usuario.email}")
        if generada:
            print(f"\n   Password generada: {nueva}\n   Anotala: no se vuelve a mostrar.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
