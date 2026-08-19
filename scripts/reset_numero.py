"""Deja un número de WhatsApp como si nunca hubiera escrito, para poder probar.

Escribir "reset" en el chat borra la conversación, pero deja la ficha del
paciente: el bot te sigue reconociendo y nunca vas a poder probar el flujo de
alguien nuevo. Este script permite eso también.

Uso:
    # Ver qué hay asociado a ese número (no toca nada)
    python scripts/reset_numero.py 2604844952

    # Borrar la conversación: historial, datos recolectados y pausa
    python scripts/reset_numero.py 2604844952 --conversacion

    # Además, borrar la ficha del paciente y sus turnos, para probar
    # el flujo de "paciente nuevo" desde cero
    python scripts/reset_numero.py 2604844952 --todo

--todo borra turnos y odontograma de ese paciente de forma DEFINITIVA. Está
pensado para números de prueba. No lo uses con el número de un paciente real.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import SessionLocal  # noqa: E402
from backend.models.patient import Patient  # noqa: E402
from backend.models.appointment import Appointment  # noqa: E402
from backend.models.odontogram import OdontogramEntry  # noqa: E402
from backend.models.chat_session import ChatSession, ChatMessage  # noqa: E402
from backend.services.whatsapp import normalize_to_e164  # noqa: E402


def pacientes_del_numero(db, numero: str) -> list:
    objetivo = normalize_to_e164(numero)
    digitos = "".join(filter(str.isdigit, numero))
    encontrados = []
    for p in db.query(Patient).filter(Patient.is_deleted == False).all():  # noqa: E712
        if not p.phone:
            continue
        if normalize_to_e164(p.phone) == objetivo:
            encontrados.append(p)
        elif len(digitos) >= 8 and "".join(filter(str.isdigit, p.phone))[-8:] == digitos[-8:]:
            encontrados.append(p)
    return encontrados


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("numero", help="Número de WhatsApp, en cualquier formato")
    parser.add_argument("--conversacion", action="store_true",
                        help="Borrar historial, datos recolectados y pausa")
    parser.add_argument("--todo", action="store_true",
                        help="Además, borrar la ficha del paciente y sus turnos")
    args = parser.parse_args()

    digitos = "".join(filter(str.isdigit, args.numero))
    jid = f"{digitos}@s.whatsapp.net"

    db = SessionLocal()
    try:
        sesiones = db.query(ChatSession).filter(
            ChatSession.platform_user_id == jid
        ).all()
        pacientes = pacientes_del_numero(db, args.numero)

        print(f"Número: {args.numero}  (JID {jid})\n")

        print("Conversación:")
        if not sesiones:
            print("  sin conversación registrada")
        for s in sesiones:
            n = db.query(ChatMessage).filter(ChatMessage.session_id == s.id).count()
            print(f"  {n} mensaje(s) | datos guardados: {s.context_data or 'ninguno'} "
                  f"| pausado hasta: {s.paused_until or 'no'}")

        print("\nFicha(s) de paciente:")
        if not pacientes:
            print("  ninguna: para el bot este número es un paciente nuevo")
        for p in pacientes:
            t = db.query(Appointment).filter(Appointment.patient_id == p.id).count()
            o = db.query(OdontogramEntry).filter(OdontogramEntry.patient_id == p.id).count()
            print(f"  {p.first_name} {p.last_name} (DNI {p.dni}) — {t} turno(s), {o} odontograma")

        if not (args.conversacion or args.todo):
            print("\nNo se tocó nada. Usá --conversacion o --todo para borrar.")
            return

        for s in sesiones:
            db.query(ChatMessage).filter(ChatMessage.session_id == s.id).delete()
            s.context_data = None
            s.paused_until = None
        print("\n✓ Conversación borrada (historial, datos y pausa)")

        if args.todo:
            for p in pacientes:
                db.query(Appointment).filter(Appointment.patient_id == p.id).delete()
                db.query(OdontogramEntry).filter(OdontogramEntry.patient_id == p.id).delete()
                for s in db.query(ChatSession).filter(ChatSession.patient_id == p.id).all():
                    s.patient_id = None
                db.delete(p)
            print(f"✓ {len(pacientes)} ficha(s) de paciente y sus turnos borrados")
            print("  Ahora el bot te va a tratar como paciente nuevo.")

        db.commit()
        print("\nListo.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
