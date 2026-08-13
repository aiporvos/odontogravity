"""Dice por qué el bot responde "inconveniente técnico con nuestra IA".

Ese mensaje es el fallback de la cascada: aparece cuando fallan los tres
proveedores configurados. Como el motivo no llega al usuario, este script lo
muestra: qué proveedores están activos, si tienen API Key y de dónde sale
(base de datos o variable de entorno).

Uso:
    python scripts/diagnostico_ia.py            # solo revisa la configuración
    python scripts/diagnostico_ia.py --probar   # además hace una consulta real

--probar gasta unos centavos de tu cuenta: manda un mensaje mínimo a cada
proveedor configurado para ver si la clave sirve de verdad.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.config import AppConfig  # noqa: E402

CLAVES = {
    "openai": ("OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", "google/gemini-flash-1.5"),
    "groq": ("GROQ_API_KEY", "GROQ_MODEL", "llama-3.1-70b-versatile"),
}


def leer(db, key: str):
    """Devuelve (valor, origen) replicando la lógica de get_config del bot."""
    conf = db.query(AppConfig).filter(AppConfig.key == key).first()
    if conf and conf.value:
        return conf.value, "base de datos"
    env = os.getenv(key)
    if env:
        return env, "variable de entorno"
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probar", action="store_true",
                        help="Hace una consulta real a cada proveedor (gasta créditos)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        p1, _ = leer(db, "AI_PROVIDER")
        p2, _ = leer(db, "AI_PROVIDER_2")
        p3, _ = leer(db, "AI_PROVIDER_3")
        p1 = (p1 or "openai").lower()
        p2 = (p2 or "none").lower()
        p3 = (p3 or "none").lower()

        orden, vistos = [], set()
        for p in (p1, p2, p3):
            if p != "none" and p not in vistos:
                vistos.add(p)
                orden.append(p)
        if not orden:
            orden = ["openai"]

        print(f"Cascada configurada: {' -> '.join(orden)}\n")

        utilizables = []
        for proveedor in orden:
            if proveedor not in CLAVES:
                print(f"  {proveedor:<12} ✗ proveedor desconocido (revisá la configuración)")
                continue
            key_name, model_name, model_default = CLAVES[proveedor]
            api_key, origen = leer(db, key_name)
            modelo, _ = leer(db, model_name)
            modelo = modelo or model_default
            if not api_key:
                print(f"  {proveedor:<12} ✗ SIN API KEY  ({key_name} no está ni en la base ni en el entorno)")
                continue
            print(f"  {proveedor:<12} ✓ key de {len(api_key)} chars desde {origen} | modelo: {modelo}")
            utilizables.append(proveedor)

        if not utilizables:
            print("\n>>> Ningún proveedor tiene API Key. El bot va a responder siempre el")
            print(">>> mensaje de 'inconveniente técnico'. Cargá la clave en")
            print(">>> Configuración -> Integraciones (Chatbot).")
            return

        if not args.probar:
            print(f"\nHay {len(utilizables)} proveedor(es) con clave cargada.")
            print("Para comprobar que las claves realmente funcionan: --probar")
            return

        print("\nProbando con una consulta real...")
        from bot.ai_agent import get_agent
        for proveedor in utilizables:
            try:
                agent = get_agent(proveedor)
                if not agent:
                    print(f"  {proveedor:<12} ✗ get_agent() devolvió None")
                    continue
                agent.invoke({
                    "input": "Respondé solamente: ok",
                    "chat_history": [],
                    "today": "test",
                    "insurances": "Particular",
                    "especialistas": "equipo de prueba",
                })
                print(f"  {proveedor:<12} ✓ responde correctamente")
            except Exception as e:
                print(f"  {proveedor:<12} ✗ {type(e).__name__}: {str(e)[:160]}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
