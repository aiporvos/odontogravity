"""Bot-facing API routes - used by DentiBot tools to manage appointments."""
from uuid import UUID
from datetime import datetime, timedelta
from fastapi import Body, APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
import os
import logging

from backend.database import get_db
from backend.services.appointment_service import create_appointment_logic, get_available_slots, route_professional
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
from backend.models.professional import Professional
from backend.schemas.schemas import (
    BotAppointmentRequest, BotCancelRequest, BotRescheduleRequest, BotQueryRequest,
    BotAvailabilityRequest, AppointmentRead, PatientRead,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bot", tags=["Bot"])

# BOT_API_KEY protege los endpoints que el bot usa para operar turnos.
# Sin un valor propio, cualquiera con la key de ejemplo podría agendar,
# cancelar o consultar datos de pacientes, así que la app no debe arrancar
# con el default inseguro.
_INSECURE_BOT_KEY_DEFAULT = "dev-bot-key-change-in-prod"
BOT_API_KEY = os.getenv("BOT_API_KEY")
if not BOT_API_KEY or BOT_API_KEY == _INSECURE_BOT_KEY_DEFAULT:
    raise RuntimeError(
        "BOT_API_KEY no está configurada (o usa el valor de ejemplo). "
        "Definí una BOT_API_KEY propia en las variables de entorno "
        "(debe coincidir en el servicio backend y en el bot)."
    )


def verify_bot_key(x_bot_key: str = Header(...)):
    if x_bot_key != BOT_API_KEY:
        raise HTTPException(403, "Bot API key inválida")


def _phones_match(stored: str | None, requester: str | None) -> bool:
    """Compara dos teléfonos tolerando distintos formatos argentinos.

    Devuelve True si coinciden por E.164 normalizado o por los últimos 8
    dígitos (cubre variantes como 549341..., 0341..., 341..., +54...).
    """
    from backend.services.whatsapp import normalize_to_e164

    if not stored or not requester:
        return False
    if normalize_to_e164(stored) == normalize_to_e164(requester):
        return True
    d_stored = "".join(filter(str.isdigit, stored))
    d_req = "".join(filter(str.isdigit, requester))
    return bool(d_stored) and bool(d_req) and d_stored[-8:] == d_req[-8:]


# Mensaje uniforme cuando el DNI consultado no pertenece a quien escribe.
# No revela si el DNI existe o no, para no filtrar datos.
_OWNERSHIP_ERROR = (
    "Por tu seguridad no puedo gestionar turnos de ese DNI desde este número. "
    "Si es un error, comunicate con la clínica."
)


def _ensure_owns_dni(patient, requester_phone: str | None):
    """Si hay una identidad de canal (WhatsApp), exige que el DNI le pertenezca.

    Si no hay requester_phone (ej. Telegram, que no tiene teléfono), no se
    aplica verificación y se mantiene el comportamiento anterior.
    """
    if requester_phone and not _phones_match(getattr(patient, "phone", None), requester_phone):
        raise HTTPException(403, _OWNERSHIP_ERROR)



def buscar_pacientes_por_telefono(db: Session, requester_phone: str | None) -> list:
    """Pacientes asociados a ese numero de WhatsApp.

    Puede devolver varios: una familia comparte el telefono y el modelo de
    datos lo permite (el DNI es unico, el telefono no). Es el caso real de
    "turno para mi mama Estela Pardo".

    Se busca primero por coincidencia exacta normalizada. Solo si eso no
    encuentra nada se prueba la comparacion flexible (ultimos 8 digitos), y
    unicamente si devuelve UNA persona: con mas de una no hay forma de saber
    cual es y seria peor confundir fichas que pedir el DNI.
    """
    from backend.services.whatsapp import normalize_to_e164

    if not requester_phone:
        return []

    objetivo = normalize_to_e164(requester_phone)
    activos = db.query(Patient).filter(Patient.is_deleted == False).all()  # noqa: E712

    exactos = [p for p in activos if p.phone and normalize_to_e164(p.phone) == objetivo]
    if exactos:
        return exactos

    d_req = "".join(filter(str.isdigit, requester_phone))
    if len(d_req) < 8:
        return []
    flexibles = [
        p for p in activos
        if p.phone and "".join(filter(str.isdigit, p.phone))[-8:] == d_req[-8:]
    ]
    return flexibles if len(flexibles) == 1 else []


@router.post("/identificar", dependencies=[Depends(verify_bot_key)])
def bot_identificar(data: dict = Body(...), db: Session = Depends(get_db)):
    """Quien es el que escribe, segun su numero de WhatsApp.

    Evita pedirle el DNI a alguien que ya es paciente. El telefono es ademas
    la credencial mas fuerte: WhatsApp lo verifica, un DNI lo puede saber
    cualquiera. De hecho el sistema ya confiaba mas en el telefono — pedia el
    DNI y despues lo validaba contra el numero.
    """
    pacientes = buscar_pacientes_por_telefono(db, data.get("requester_phone"))
    return {
        "encontrados": len(pacientes),
        "pacientes": [
            {
                "dni": p.dni,
                "nombre": f"{p.first_name} {p.last_name}".strip(),
                "obra_social": p.insurance_name or "Particular",
            }
            for p in pacientes
        ],
    }


def _clave_persona(p) -> str:
    """Identidad 'blanda' de un paciente, para detectar fichas duplicadas."""
    return f"{(p.first_name or '').strip().lower()}|{(p.last_name or '').strip().lower()}"


def deduplicar_pacientes(db: Session, pacientes: list) -> list:
    """Colapsa las fichas que son la MISMA persona cargada dos veces.

    En produccion aparecieron dos "Claudio Luna" con el mismo telefono y DNIs
    distintos. Preguntarle al paciente cual de los dos "Claudio Luna" es su
    turno es imposible de contestar: se quedaba en un loop sin salida.

    Cuando varias fichas comparten nombre y apellido se toma una sola, la que
    tenga turnos activos (y si empatan, la mas reciente). Solo se considera
    "familia" —y por lo tanto se pregunta— cuando los nombres son distintos.
    """
    if len(pacientes) <= 1:
        return pacientes

    def turnos_activos(p):
        return db.query(Appointment).filter(
            Appointment.patient_id == p.id,
            Appointment.is_deleted == False,  # noqa: E712
            Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
        ).count()

    por_persona: dict[str, list] = {}
    for p in pacientes:
        por_persona.setdefault(_clave_persona(p), []).append(p)

    elegidos = []
    for clave, grupo in por_persona.items():
        if len(grupo) == 1:
            elegidos.append(grupo[0])
            continue
        mejor = max(grupo, key=lambda p: (turnos_activos(p), p.created_at or datetime.min))
        logger.info(
            f"Fichas duplicadas de '{clave}': {len(grupo)} registros, se usa DNI {mejor.dni}"
        )
        elegidos.append(mejor)
    return elegidos


def pacientes_del_numero(db: Session, requester_phone: str | None) -> list:
    """Todos los pacientes de ese numero, ya sin duplicados."""
    return deduplicar_pacientes(db, buscar_pacientes_por_telefono(db, requester_phone))


def resolver_paciente(db: Session, dni: str | None, requester_phone: str | None):
    """Encuentra al paciente sin obligarlo a tipear el DNI.

    Orden: (1) si vino DNI explicito, ese manda —cubre a quien cambio de
    numero—; (2) si no, el telefono. Si el telefono tiene varios pacientes
    asociados, se devuelve la lista para que el bot pregunte de quien se trata,
    en vez de adivinar y tocar la ficha equivocada.

    Devuelve (paciente, opciones). Si paciente es None y opciones tiene varios,
    hay que preguntar; si ambos vienen vacios, no se lo pudo identificar.
    """
    if dni and dni.strip():
        d = "".join(filter(str.isdigit, dni))
        paciente = db.query(Patient).filter(
            Patient.dni == d, Patient.is_deleted == False,  # noqa: E712
        ).first()
        if paciente and requester_phone:
            if not (paciente.phone or "").strip():
                # Ficha cargada desde el panel sin telefono (o con uno vacio):
                # es el primer WhatsApp de este paciente. Se adopta el numero,
                # no hay nadie a quien desplazar.
                paciente.phone = requester_phone
                db.commit()
            elif not _phones_match(paciente.phone, requester_phone):
                # El DNI NO es un secreto: esta impreso en el documento y lo
                # sabe la familia. Dejar que un DNI solo de acceso a los turnos
                # de otro desde un numero desconocido seria un agujero de
                # privacidad en una clinica. El cambio de numero lo hace la
                # clinica desde el panel, no el bot.
                raise HTTPException(403, (
                    "Ese DNI está registrado con otro número de teléfono. "
                    "Por seguridad no puedo mostrar esos turnos desde acá. "
                    "Escribinos desde el número de siempre o llamá a la clínica "
                    "para que actualicen tu contacto."
                ))
        return paciente, []

    candidatos = pacientes_del_numero(db, requester_phone)
    if len(candidatos) == 1:
        return candidatos[0], []
    return None, candidatos


_NO_IDENTIFICADO = (
    "No encuentro turnos asociados a este número. "
    "¿Me pasás tu DNI así te busco?"
)


def _elegir_entre(candidatos) -> str:
    nombres = ", ".join(f"{p.first_name} {p.last_name}".strip() for p in candidatos)
    return f"Hay varias personas registradas con este número ({nombres}). ¿Para quién es?"


# ── Agendar Turno ──────────────────────────────────────
def _solo_digitos(valor):
    return "".join(c for c in (valor or "") if c.isdigit())


def _validar_dni_y_telefono(dni, phone, requester_phone):
    """Valida los datos y devuelve el DNI normalizado a solo digitos.

    Evita que se guarde un telefono en el campo DNI y viceversa.

    El modelo asignaba cada numero al campo que estaba pidiendo en ese momento,
    sin mirar que era: un paciente escribio "Claudio Luna 2604844952" y esos 10
    digitos (un telefono) quedaron como DNI; despues su DNI de 8 digitos quedo
    como telefono. Ademas de ensuciar la ficha, rompe la verificacion de
    identidad para cancelar o reprogramar, que busca al paciente por DNI.

    Un DNI argentino tiene 7 u 8 digitos; un celular con caracteristica, 10.
    """
    d = _solo_digitos(dni)
    t = _solo_digitos(phone)

    parece_telefono = len(d) >= 10
    parece_dni = 7 <= len(t) <= 8

    if parece_telefono and parece_dni:
        raise HTTPException(400, (
            f"El DNI y el telefono parecen estar invertidos: '{dni}' tiene {len(d)} digitos "
            f"(es un telefono) y '{phone}' tiene {len(t)} (es un DNI). "
            "Volve a preguntarle al paciente cual es cada uno y confirmalo antes de agendar."
        ))

    if not 7 <= len(d) <= 8:
        detalle = " (parece un telefono)" if parece_telefono else ""
        raise HTTPException(400, (
            f"El DNI '{dni}' no es valido{detalle}: un DNI argentino tiene 7 u 8 digitos "
            f"y este tiene {len(d)}. Pediselo de nuevo al paciente, solo numeros."
        ))

    # El telefono puede venir vacio: en WhatsApp usamos el numero del remitente.
    if t and not 8 <= len(t) <= 13:
        raise HTTPException(400, (
            f"El telefono '{phone}' no es valido: tiene {len(t)} digitos. "
            "Pediselo de nuevo con caracteristica, por ejemplo 2604123456."
        ))
    if not t and not requester_phone:
        raise HTTPException(400, "Falta el telefono del paciente. Pediselo antes de agendar.")

    # Se devuelve normalizado: "29.759.464" y "29759464" son la misma persona, y
    # sin esto quedaban como dos pacientes distintos en la base.
    return d


@router.post("/appointments", dependencies=[Depends(verify_bot_key)])
def bot_create_appointment(data: BotAppointmentRequest, db: Session = Depends(get_db)):
    # Paciente que ya existe: no hace falta que tipee nada. Si el numero de
    # WhatsApp identifica a una sola persona y no vino DNI, se usa el suyo.
    # Con varias personas en el mismo numero (familia) hay que preguntar.
    nombre = data.patient_name
    apellido = data.patient_last_name
    if not (data.dni or "").strip():
        conocido, opciones = resolver_paciente(db, None, data.requester_phone)
        if conocido:
            dni_normalizado = conocido.dni
            nombre = nombre or conocido.first_name
            apellido = apellido or conocido.last_name
        elif opciones:
            raise HTTPException(400, _elegir_entre(opciones))
        else:
            raise HTTPException(400, (
                "Es la primera vez que este número saca turno. "
                "Pedile nombre, apellido y DNI para crear su ficha."
            ))
    else:
        dni_normalizado = _validar_dni_y_telefono(data.dni, data.phone, data.requester_phone)

    result = create_appointment_logic(
        db=db,
        patient_name=nombre,
        patient_last_name=apellido,
        dni=dni_normalizado,
        phone=data.phone,
        reason=data.reason,
        location=data.location,
        insurance_name=data.insurance_name,
        preferred_date=data.preferred_date,
        duration_minutes=data.duration_minutes,
        channel=AppointmentChannel.bot_whatsapp,
        requester_phone=data.requester_phone,
    )
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


# ── Cancelar Turno ─────────────────────────────────────
@router.post("/cancel", dependencies=[Depends(verify_bot_key)])
async def bot_cancel_appointment(data: BotCancelRequest, db: Session = Depends(get_db)):
    # Igual que al consultar: no se pregunta "¿de quién?". Se juntan los turnos
    # de todas las fichas del número y, si hay más de uno, se le pide al
    # paciente que elija EL TURNO (fecha y hora), que es algo que sí puede
    # contestar, en vez de elegir entre fichas que pueden ser idénticas.
    if (data.dni or "").strip():
        patient, _ = resolver_paciente(db, data.dni, data.requester_phone)
        if not patient:
            raise HTTPException(404, _NO_IDENTIFICADO)
        pacientes = [patient]
    else:
        pacientes = pacientes_del_numero(db, data.requester_phone)
        if not pacientes:
            raise HTTPException(404, _NO_IDENTIFICADO)

    ids = [p.id for p in pacientes]
    query = db.query(Appointment).filter(
        Appointment.patient_id.in_(ids),
        Appointment.is_deleted == False,  # noqa: E712
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
    )

    if data.appointment_id:
        appt = query.filter(Appointment.id == data.appointment_id).first()
        if not appt:
            raise HTTPException(404, "No se encontró el turno especificado para cancelar")
    else:
        appts = query.order_by(Appointment.start_time).all()
        if not appts:
            raise HTTPException(404, "No se encontraron turnos activos para cancelar")
        if len(appts) > 1:
            detalle = "; ".join(
                f"{a.start_time.strftime('%d/%m a las %H:%M')} (id {a.id})" for a in appts
            )
            raise HTTPException(400, (
                f"Hay {len(appts)} turnos activos: {detalle}. "
                "Preguntale al paciente CUÁL quiere cancelar (por fecha y hora) "
                "y volvé a llamar pasando el appointment_id de ese turno."
            ))
        appt = appts[0]
    patient = appt.patient

    appt.status = AppointmentStatus.cancelled
    db.commit()

    # Notificar a los admins (cada número por separado para que un fallo no bloquee al resto)
    from backend.models.config import AppConfig
    from backend.services.whatsapp import send_whatsapp_message
    import os

    def get_val(key):
        conf = db.query(AppConfig).filter(AppConfig.key == key).first()
        return conf.value if conf and conf.value else os.getenv(key, "")

    admin_numbers = get_val("ADMIN_NOTIFY_NUMBERS")
    if admin_numbers:
        numbers = [n.strip() for n in admin_numbers.split(",") if n.strip()]
        msg_text = (
            f"⚠️ Turno Cancelado por Bot:\n"
            f"Paciente: {patient.first_name} {patient.last_name} ({patient.dni})\n"
            f"Fecha original: {appt.start_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"Sede: {appt.location}"
        )
        for number in numbers:
            try:
                await send_whatsapp_message(number, msg_text)
                print(f"Admin notificado de cancelación: {number}")
            except Exception as e:
                print(f"Error notifying admin {number} of cancellation: {e}")

    return {"status": "ok", "message": "Turno cancelado exitosamente", "appointment_id": str(appt.id)}


# ── Reprogramar Turno ──────────────────────────────────
@router.post("/reschedule", dependencies=[Depends(verify_bot_key)])
def bot_reschedule_appointment(data: BotRescheduleRequest, db: Session = Depends(get_db)):
    patient, opciones = resolver_paciente(db, data.dni, data.requester_phone)
    if not patient:
        raise HTTPException(404, _elegir_entre(opciones) if opciones else _NO_IDENTIFICADO)

    appt = db.query(Appointment).filter(
        Appointment.id == data.appointment_id,
        Appointment.patient_id == patient.id,
        Appointment.is_deleted == False,
    ).first()
    if not appt:
        raise HTTPException(404, "Turno no encontrado")

    appt.start_time = data.new_start_time
    # Se mantiene confirmado: si volvia a "pending" el recordatorio dejaba de
    # dispararse, porque el loop solo notifica turnos confirmados.
    appt.status = AppointmentStatus.confirmed
    db.commit()
    return {"status": "ok", "message": f"Turno reprogramado para {data.new_start_time}", "appointment_id": str(appt.id)}


# ── Consultar Turnos ───────────────────────────────────
@router.post("/my-appointments", dependencies=[Depends(verify_bot_key)])
def bot_query_appointments(data: BotQueryRequest, db: Session = Depends(get_db)):
    """Turnos de quien escribe. Nunca pregunta "¿para quién?".

    Antes, si el número tenía varias fichas, se le pedía al paciente que
    eligiera de cuál quería ver los turnos. Con fichas duplicadas eso era
    imposible de contestar ("¿Claudio Luna o Claudio Luna?") y la conversación
    entraba en un loop. No hay motivo para preguntar: se muestran los turnos de
    todos, aclarando de quién es cada uno cuando hay más de una persona.
    """
    if (data.dni or "").strip():
        patient, _ = resolver_paciente(db, data.dni, data.requester_phone)
        if not patient:
            raise HTTPException(404, _NO_IDENTIFICADO)
        pacientes = [patient]
    else:
        pacientes = pacientes_del_numero(db, data.requester_phone)
        if not pacientes:
            raise HTTPException(404, _NO_IDENTIFICADO)

    varios = len(pacientes) > 1
    turnos = []
    for p in pacientes:
        appts = db.query(Appointment).filter(
            Appointment.patient_id == p.id,
            Appointment.is_deleted == False,  # noqa: E712
            Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
        ).order_by(Appointment.start_time).limit(10).all()
        for a in appts:
            turnos.append({
                "id": str(a.id),
                "date": str(a.start_time),
                "status": a.status.value,
                "reason": a.reason,
                "location": a.location,
                "professional": a.professional.full_name if a.professional else "?",
                "paciente": f"{p.first_name} {p.last_name}".strip(),
            })
    turnos.sort(key=lambda t: t["date"])

    nombres = ", ".join(f"{p.first_name} {p.last_name}".strip() for p in pacientes)
    return {
        "patient": nombres,
        "varios_pacientes": varios,
        "appointments": turnos,
    }


@router.post("/verificar-obra-social", dependencies=[Depends(verify_bot_key)])
def bot_verificar_obra_social(data: dict = Body(...), db: Session = Depends(get_db)):
    """Dice si la clinica atiende esa obra social. Lo consulta el bot.

    Antes la comparacion la hacia el modelo contra una lista metida en el prompt
    y se le colaban obras sociales no cubiertas. Esto es deterministico.
    """
    from backend.services.appointment_service import match_insurance
    from backend.models.insurance import Insurance

    consultada = (data.get("obra_social") or "").strip()
    encontrada = match_insurance(consultada, db)
    activas = [
        i.name for i in db.query(Insurance).filter(Insurance.is_active == True).order_by(Insurance.name).all()
        if i.name.lower() != "particular"
    ]
    return {
        "consultada": consultada,
        "cubierta": bool(encontrada),
        "nombre": encontrada.name if encontrada else "Particular",
        "activas": activas,
    }


@router.post("/availability", dependencies=[Depends(verify_bot_key)])
def bot_get_availability(data: BotAvailabilityRequest, db: Session = Depends(get_db)):
    # Always use Argentina timezone (UTC-3) as the reference date, never UTC
    from backend.services.appointment_service import get_clinic_now
    argentina_now = get_clinic_now()
    target_date = data.date if data.date else argentina_now.date().isoformat()
    return get_available_slots(db, target_date, data.location, data.reason,
                              data.obra_social, preferencia_horaria=data.preferencia_horaria)
