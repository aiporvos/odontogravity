"""Dice por qué el bot responde "inconveniente técnico con nuestra IA".

Ese mensaje aparece cuando OpenAI no contesta o falta la clave. Como el motivo
no llega al paciente, este script lo muestra.

Uso (dentro del contenedor del backend):
    python scripts/diagnostico_ia.py            # solo revisa la configuración
    python scripts/diagnostico_ia.py --probar   # además hace una consulta real

--probar gasta una fracción de centavo: manda un mensaje mínimo a OpenAI.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.config import get_config  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probar", action="store_true",
                        help="Hace una consulta real a OpenAI (gasta créditos)")
    args = parser.parse_args()

    api_key = get_config("OPENAI_API_KEY")
    modelo = get_config("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        print("✗ Falta OPENAI_API_KEY en el entorno (Dokploy → Environment).")
        return
    print(f"✓ Clave de {len(api_key)} caracteres en el entorno | modelo: {modelo}")

    if not args.probar:
        print("Para comprobar que la clave funciona de verdad: --probar")
        return

    from bot.ai_agent import _build_client, _parametros_modelo
    client, modelo = _build_client()
    try:
        params = _parametros_modelo(modelo)
        params = {k: (min(v, 20) if "tokens" in k else v) for k, v in params.items()}
        r = client.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": "Respondé solamente: ok"}],
            **params,
        )
        print(f"✓ OpenAI responde ({r.choices[0].message.content!r})")
    except Exception as e:
        # El motivo importa: una clave revocada y un modelo que ya no existe se
        # parecen desde afuera y se arreglan distinto.
        print(f"✗ {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    main()
