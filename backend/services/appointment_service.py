
from datetime import datetime, timedelta, time as py_time
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from backend.models.patient import Patient
from backend.models.appointment import Appointment, AppointmentStatus, AppointmentChannel
from backend.models.professional import Professional
from backend.models.schedule import ClinicSchedule, ProfessionalSchedule, ProfessionalTimeOff, ClinicHoliday
from backend.models.config import AppConfig

logger = logging.getLogger(__name__)

# El ruteo por motivo sale de las especialidades que cada profesional tiene
# cargadas en su ficha (Profesionales -> Especialidades), no de un mapa fijo en
# el codigo. Asi la clinica lo cambia sola sin tocar el backend.
_STOPWORDS = {"de", "del", "la", "el", "y", "e", "los", "las", "un", "una",
              "en", "para", "por", "con", "al", "a"}


def _sin_acentos(texto: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def _palabras(texto: str) -> list[str]:
    limpio = "".join(c if c.isalnum() else " " for c in _sin_acentos(texto))
    return [p for p in limpio.split() if p not in _STOPWORDS and len(p) >= 3]


def _distancia(a: str, b: str, tope: int = 2) -> int:
    """Distancia de edicion acotada (cuantas letras hay que cambiar)."""
    if abs(len(a) - len(b)) > tope:
        return tope + 1
    previa = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(
                previa[j] + 1,          # borrar
                actual[j - 1] + 1,      # insertar
                previa[j - 1] + (ca != cb),  # sustituir
            ))
        if min(actual) > tope:
            return tope + 1
        previa = actual
    return previa[-1]


def _misma_palabra(a: str, b: str) -> bool:
    """True si son la misma palabra, tolerando plural y errores de tipeo.

    Los pacientes escriben "estraccion", "extraciones" o "limpiesa" y antes
    ninguna de esas coincidia, asi que el turno se ruteaba a cualquiera. Se
    aceptan hasta 1-2 letras de diferencia segun el largo, que cubre los typos
    comunes sin confundir palabras realmente distintas.
    """
    if a == b:
        return True
    # Prefijo comun largo: cubre singular/plural (extraccion / extracciones).
    n = min(len(a), len(b))
    if n >= 5 and a[:n] == b[:n]:
        return True
    # Errores de tipeo: 1 letra en palabras cortas, 2 en las largas.
    if n < 5:
        return False
    tope = 1 if n <= 7 else 2
    return _distancia(a, b, tope) <= tope


# Como dice el paciente lo que necesita, vs. como esta cargada la especialidad.
# Es texto libre en WhatsApp: nadie escribe "Extraccion", escriben "sacar una
# muela". Se puede ampliar sin tocar nada mas.
SINONIMOS = {
    "extraccion": ["sacar", "sacarme", "muela", "cordal", "extraer", "extraigan", "quitar"],
    "limpieza": ["limpiar", "limpieza", "sarro", "profilaxis", "higiene", "blanquear"],
    "arreglos": ["arreglo", "arreglar", "caries", "tapar", "empaste", "roto", "rotura"],
    "conducto": ["conducto", "endodoncia", "nervio", "matar el nervio"],
    "ortodoncia": ["ortodoncia", "brackets", "aparato", "alinear", "invisalign"],
    "protesis": ["protesis", "placa", "dentadura", "puente", "implante"],
    "control": ["control", "revision", "chequeo", "consulta", "ver", "duele", "dolor"],
}


def _expandir_con_sinonimos(palabras: list[str]) -> set[str]:
    """Agrega el termino "canonico" cuando el paciente uso una forma coloquial."""
    ampliado = set(palabras)
    for canonico, variantes in SINONIMOS.items():
        for v in variantes:
            if any(_misma_palabra(_sin_acentos(v), p) for p in palabras):
                ampliado.add(canonico)
                break
    return ampliado


def _especialidad_coincide(especialidad: str, palabras_motivo: list[str]) -> bool:
    """True si todas las palabras significativas de la especialidad estan en el motivo.

    Se exigen todas para evitar falsos positivos: "tratamiento de conducto" no
    matchea con "tratamiento de caries" porque falta "conducto".
    """
    requeridas = _palabras(especialidad)
    if not requeridas:
        return False
    disponibles = _expandir_con_sinonimos(palabras_motivo)
    return all(
        any(_misma_palabra(req, pal) for pal in disponibles)
        for req in requeridas
    )


def match_insurance(nombre: str, db: Session):
    """Busca la obra social entre las activas. Devuelve el registro o None.

    La comparacion la hacia el modelo contra una lista dentro del prompt, y se
    le escapaban casos: aceptaba obras sociales que la clinica no atiende. Aca
    es deterministico. Tolera mayusculas, acentos y variantes como "OSDE 210",
    pero no confunde nombres parecidos: "osep" y "osde" no matchean entre si.
    """
    from backend.models.insurance import Insurance

    buscado = " ".join(_sin_acentos(nombre or "").split())
    if not buscado:
        return None

    # Se compara por palabras completas, no por substring: "OSPE" es una obra
    # social distinta de "OSPELSYM" y no debe darse por cubierta. Ante la duda
    # conviene devolver None: el bot avisa que no esta cubierta y el paciente
    # corrige, que es mejor que agendar con una cobertura que no se atiende.
    palabras_buscado = {p for p in buscado.split() if len(p) >= 3}

    activas = db.query(Insurance).filter(Insurance.is_active == True).all()
    for ins in activas:
        candidato = " ".join(_sin_acentos(ins.name).split())
        if not candidato:
            continue
        if buscado == candidato:
            return ins
        if ins.code and _sin_acentos(ins.code).strip() == buscado:
            return ins

        palabras_candidato = {p for p in candidato.split() if len(p) >= 3}
        if not palabras_buscado or not palabras_candidato:
            continue
        # "OSDE 210" contiene a "OSDE"; "Swiss" es parte de "Swiss Medical".
        if palabras_candidato <= palabras_buscado or palabras_buscado <= palabras_candidato:
            return ins
    return None


def obras_sociales_frecuentes(db: Session, limite: int = 8) -> list[str]:
    """Las obras sociales que mas aparecen en los turnos ya agendados.

    Con 45 cargadas no entran en una lista de WhatsApp (el tope son 10 filas),
    pero en la practica un puñado cubre a casi todos los pacientes. Se ordenan
    por uso real en vez de alfabeticamente, asi el que busca la suya la
    encuentra de una y el resto usa el buscador.
    """
    from backend.models.insurance import Insurance
    from sqlalchemy import func

    activas = {
        _sin_acentos(i.name): i.name
        for i in db.query(Insurance).filter(Insurance.is_active == True).all()  # noqa: E712
        if i.name.lower() != "particular"
    }
    if not activas:
        return []

    usos = (
        db.query(Appointment.insurance_name, func.count(Appointment.id).label("n"))
        .filter(Appointment.insurance_name.isnot(None),
                Appointment.is_deleted == False)  # noqa: E712
        .group_by(Appointment.insurance_name)
        .order_by(func.count(Appointment.id).desc())
        .all()
    )

    ordenadas, vistas = [], set()
    for nombre, _ in usos:
        clave = _sin_acentos(nombre or "")
        if clave in activas and clave not in vistas:
            ordenadas.append(activas[clave])
            vistas.add(clave)
        if len(ordenadas) >= limite:
            return ordenadas

    # Se completa con el resto, alfabetico, hasta llegar al limite.
    for clave, nombre in sorted(activas.items()):
        if clave not in vistas:
            ordenadas.append(nombre)
            if len(ordenadas) >= limite:
                break
    return ordenadas


def _puntaje_obra_social(buscado: str, candidato: str) -> int:
    """Que tan bien matchea lo que escribio el paciente. 0 = no matchea.

    El ranking privilegia el prefijo por sobre la distancia de edicion, porque
    los errores reales no son de una letra: alguien escribe "ospeysin" buscando
    "OSPELSYM" (tres sustituciones), pero acierta las primeras cuatro. Corregir
    tipeos ahi no sirve; buscar por como empieza, si.
    """
    if not buscado or not candidato:
        return 0
    if buscado == candidato:
        return 100
    if candidato.startswith(buscado) or buscado.startswith(candidato):
        return 90
    if buscado in candidato or candidato in buscado:
        return 70
    # Alguna palabra del candidato empieza como lo buscado ("swiss" -> "Swiss Medical").
    if any(p.startswith(buscado) or buscado.startswith(p)
           for p in candidato.split() if len(p) >= 3):
        return 60
    # Prefijo compartido de al menos 4 letras: "ospe" une "ospeysin" y "ospelsym".
    comun = 0
    for a, b in zip(buscado, candidato):
        if a != b:
            break
        comun += 1
    if comun >= 4:
        return 40 + comun
    # Recien al final, un tipeo corto de verdad.
    if len(buscado) >= 5 and _distancia(buscado, candidato, 2) <= 2:
        return 30
    return 0


def buscar_obras_sociales(db: Session, texto: str, limite: int = 10) -> list[str]:
    """Las obras sociales activas que se parecen a lo que escribio el paciente."""
    from backend.models.insurance import Insurance

    buscado = " ".join(_sin_acentos(texto or "").split())
    if not buscado:
        return []

    puntuadas = []
    for ins in db.query(Insurance).filter(Insurance.is_active == True).all():  # noqa: E712
        if ins.name.lower() == "particular":
            continue
        puntaje = _puntaje_obra_social(buscado, " ".join(_sin_acentos(ins.name).split()))
        if ins.code:
            puntaje = max(puntaje, _puntaje_obra_social(buscado, _sin_acentos(ins.code).strip()))
        if puntaje:
            puntuadas.append((puntaje, ins.name))

    puntuadas.sort(key=lambda x: (-x[0], x[1]))
    return [nombre for _, nombre in puntuadas[:limite]]


def find_professionals_for_reason(reason: str, db: Session) -> list[Professional]:
    """Profesionales que atienden ese motivo, segun sus especialidades cargadas.

    Si ninguno matchea (motivo vacio, generico o especialidad no cargada) se
    devuelven todos los activos: es preferible ofrecer turno con cualquiera
    antes que dejar al paciente sin respuesta.
    """
    activos = db.query(Professional).filter(
        Professional.is_deleted == False,
        Professional.is_active == True,
    ).order_by(Professional.full_name).all()

    palabras = _palabras(reason or "")
    if not palabras:
        return activos

    coinciden = [
        p for p in activos
        if any(_especialidad_coincide(e, palabras) for e in (p.specialties or []))
    ]
    return coinciden or activos


def route_professional(reason: str, db: Session) -> Professional | None:
    """El profesional asignado a un motivo. Si lo atienden varios, el primero."""
    candidatos = find_professionals_for_reason(reason, db)
    return candidatos[0] if candidatos else None


import httpx

CLINIC_TZ_OFFSET = -3 # UTC-3 for Argentina
_time_cache = {"time": None, "fetched_at": None}

def get_clinic_now():
    """Returns the current time in the clinic's timezone, guaranteed by external API."""
    global _time_cache
    now_sys = datetime.utcnow()
    
    if _time_cache["time"] and _time_cache["fetched_at"] and (now_sys - _time_cache["fetched_at"]).total_seconds() < 600:
        return _time_cache["time"] + (now_sys - _time_cache["fetched_at"])
        
    try:
        r = httpx.get("http://worldtimeapi.org/api/timezone/America/Argentina/Buenos_Aires", timeout=3.0)
        if r.status_code == 200:
            dt_str = r.json()["datetime"]
            real_time = datetime.fromisoformat(dt_str).replace(tzinfo=None)
            _time_cache["time"] = real_time
            _time_cache["fetched_at"] = now_sys
            return real_time
    except Exception:
        pass
        
    # Fallback
    return datetime.utcnow() + timedelta(hours=CLINIC_TZ_OFFSET)

def get_chairs_per_location(db: Session) -> int:
    """Cuantos turnos pueden solaparse en una misma sede (sillones disponibles).

    Configurable desde el panel con la clave CHAIRS_PER_LOCATION. El default es 1
    (un solo sillon: cualquier solapamiento ocupa el horario), pero una clinica
    con varios sillones puede subirlo sin tocar codigo.
    """
    cfg = db.query(AppConfig).filter(AppConfig.key == "CHAIRS_PER_LOCATION").first()
    try:
        return max(1, int((cfg.value if cfg and cfg.value else "1").strip()))
    except (TypeError, ValueError):
        return 1


def get_day_appointments(db: Session, day, location: str | None):
    """Turnos activos de una sede en un dia, para calcular ocupacion.

    Incluye los que tienen la sede en NULL: son los que se cargaron desde el
    panel antes de que el formulario pidiera sede, y en SQL `location = 'X'`
    nunca matchea NULL, asi que quedaban invisibles y se ofrecian horarios ya
    tomados. Contarlos como ocupados es lo conservador.
    """
    start_of_day = datetime.combine(day, py_time(0, 0))
    end_of_day = datetime.combine(day, py_time(23, 59, 59))
    return db.query(Appointment).filter(
        or_(Appointment.location == location, Appointment.location.is_(None)),
        Appointment.is_deleted == False,
        Appointment.status.in_([AppointmentStatus.pending, AppointmentStatus.confirmed]),
        Appointment.start_time >= start_of_day,
        Appointment.start_time <= end_of_day,
    ).all()


def overlapping_appointments(appointments, start: datetime, duration_minutes: int, exclude_id=None):
    """De una lista ya cargada, los que se pisan con el rango dado."""
    end = start + timedelta(minutes=duration_minutes)
    return [
        a for a in appointments
        if a.id != exclude_id
        and start < a.start_time + timedelta(minutes=a.duration_minutes or 30)
        and a.start_time < end
    ]


def slot_conflict(appointments, start: datetime, duration_minutes: int, chairs: int,
                  professional_ids=None, exclude_id=None) -> str | None:
    """Motivo por el que el horario no esta libre, o None si se puede agendar.

    professional_ids son los profesionales que podrian tomar ese turno. Si el
    motivo lo atienden varios (por ejemplo Limpieza, que hacen los dos), el
    horario recien se considera ocupado cuando estan todos ocupados.
    """
    solapan = overlapping_appointments(appointments, start, duration_minutes, exclude_id)

    # El limite de sillones manda: es fisico, no depende de quien atienda.
    if len(solapan) >= chairs:
        if chairs == 1:
            return "Ya hay un turno agendado en ese horario."
        return f"No hay sillones libres en ese horario (hay {chairs})."

    if professional_ids:
        ocupados = {a.professional_id for a in solapan}
        if all(pid in ocupados for pid in professional_ids):
            return "El profesional ya tiene otro turno en ese horario."
    return None


def _nombre_normalizado(nombre: str, apellido: str) -> str:
    """'Claudio  LUNA' y 'claudio luna' son la misma persona."""
    return " ".join(sorted(_palabras(f"{nombre or ''} {apellido or ''}")))


def _misma_persona_ya_cargada(db: Session, telefono: str | None,
                              nombre: str, apellido: str):
    """La ficha existente que corresponde a esta persona, si la hay.

    Se usa justo antes de crear una ficha nueva. Exige que coincidan el telefono
    normalizado Y el nombre: en una familia el numero es el mismo, asi que
    buscar solo por telefono uniria a la madre con el hijo.
    """
    from backend.services.whatsapp import normalize_to_e164

    buscado = _nombre_normalizado(nombre, apellido)
    if not telefono or not buscado:
        return None

    objetivo = normalize_to_e164(telefono)
    if not objetivo:
        return None

    for p in db.query(Patient).filter(Patient.is_deleted == False).all():  # noqa: E712
        if not p.phone or normalize_to_e164(p.phone) != objetivo:
            continue
        if _nombre_normalizado(p.first_name, p.last_name) == buscado:
            return p
    return None


def duracion_para_motivo(reason: str) -> int:
    """Cuanto dura un turno segun el motivo.

    Fuente unica de verdad. Antes esto vivia solo adentro de get_available_slots
    (para OFRECER horarios) mientras que al AGENDAR se guardaba lo que mandara
    el bot, que lo elegia el modelo. Ofrecer un hueco de 15 minutos y despues
    grabar un turno de 30 hace que el chequeo de solapamiento valide sobre
    datos que no son los reales.
    """
    reason_lower = (reason or "").lower()
    if any(x in reason_lower for x in ["extracc", "ortodoncia", "implante", "prótesis", "protesis"]):
        return 30
    if any(x in reason_lower for x in ["conducto", "endodoncia"]):
        return 60
    return 15


def franjas_del_dia(db: Session, day, candidatos):
    """Franjas horarias en las que hay alguien que pueda atender ese dia.

    Extraido de get_available_slots para que la validacion del alta use
    exactamente el mismo criterio con el que se ofrecieron los horarios.
    """
    weekday = day.weekday()
    schedule_rows = db.query(ClinicSchedule).filter(
        ClinicSchedule.weekday == weekday,
        ClinicSchedule.is_active == True,  # noqa: E712
    ).order_by(ClinicSchedule.start_time).all()
    clinic_shifts = [(r.start_time, r.end_time) for r in schedule_rows]

    if not candidatos:
        return clinic_shifts

    def _franjas_si_no_ausente(p):
        ausente = db.query(ProfessionalTimeOff).filter(
            ProfessionalTimeOff.professional_id == p.id,
            ProfessionalTimeOff.date == day,
        ).first()
        if ausente:
            return []
        return _franjas_del_profesional(db, p.id, weekday, clinic_shifts)

    return _unir_franjas([_franjas_si_no_ausente(p) for p in candidatos])


def motivo_regla_obra_social(obra_social: str | None, when: datetime) -> str | None:
    """La regla interna de PAMI, aplicada al momento de escribir.

    Es la contracara de lo que hace get_available_slots al ofrecer: PAMI se
    atiende solo los viernes y los viernes son exclusivos de PAMI. Se validaba
    al sugerir horarios pero no al guardarlos, asi que un turno con una fecha
    que el modelo hubiera armado por su cuenta entraba igual.
    """
    es_pami = bool(obra_social) and obra_social.strip().upper() == "PAMI"
    es_viernes = when.weekday() == 4
    if es_pami and not es_viernes:
        return "Ese dia no hay atencion para esa cobertura."
    if es_viernes and not es_pami:
        return "Ese dia no hay atencion para esa cobertura."
    return None


def motivo_no_agendable(db: Session, start: datetime, duration_minutes: int,
                        location: str | None, obra_social: str | None,
                        candidatos=None, exclude_id=None,
                        validar_pasado: bool = True) -> str | None:
    """Motivo por el que ese horario NO se puede agendar, o None si se puede.

    Es la misma regla con la que get_available_slots OFRECE horarios, aplicada
    ahora al momento de ESCRIBIR. Sin esto, entre que el bot ofrece un horario
    y el paciente termina de dar sus datos —varios mensajes de ida y vuelta—
    nadie verificaba que el hueco siguiera libre, y dos pacientes distintos
    podian quedar agendados en el mismo horario.
    """
    if motivo := motivo_regla_obra_social(obra_social, start):
        return motivo

    feriado = db.query(ClinicHoliday).filter(ClinicHoliday.date == start.date()).first()
    if feriado:
        detalle = f" ({feriado.description})" if feriado.description else ""
        return (f"El {start.strftime('%d/%m/%Y')} es feriado{detalle} y la clinica "
                f"esta cerrada.")

    if validar_pasado and start <= get_clinic_now():
        return "Ese horario ya paso. Hay que elegir uno futuro."

    # Dentro del horario de atencion (y de la grilla del profesional, si tiene).
    fin = (datetime.combine(start.date(), py_time(0, 0))
           + timedelta(minutes=start.hour * 60 + start.minute + duration_minutes)).time()
    franjas = franjas_del_dia(db, start.date(), candidatos or [])
    if not franjas:
        return "Ese dia no hay atencion."
    dentro = any(
        desde <= start.time() and (fin <= hasta or (fin == py_time(0, 0)))
        for desde, hasta in franjas
    )
    if not dentro:
        return "Ese horario esta fuera del horario de atencion."

    del_dia = get_day_appointments(db, start.date(), location)
    return slot_conflict(
        del_dia, start, duration_minutes, get_chairs_per_location(db),
        [p.id for p in candidatos] if candidatos else None, exclude_id,
    )


def create_appointment_logic(
    db: Session,
    patient_name: str,
    patient_last_name: str,
    dni: str,
    phone: str,
    reason: str,
    location: str,
    insurance_name: str = None,
    preferred_date: str = None,
    channel: AppointmentChannel = AppointmentChannel.bot_whatsapp,
    duration_minutes: int = 30,
    requester_phone: str = None,
):
    # Garantia dura: si la obra social no esta entre las activas, el turno se
    # agenda como Particular. El prompt le pide al modelo que lo verifique con
    # verificar_obra_social, pero un prompt no es una garantia: sin esto podia
    # quedar agendado con una cobertura que la clinica no atiende.
    if insurance_name:
        encontrada = match_insurance(insurance_name, db)
        insurance_name = encontrada.name if encontrada else "Particular"

    # ── Todo lo que puede fallar se valida ANTES de tocar la base ────────────
    # Antes se creaba el paciente primero y se validaba (poco) despues, asi que
    # un intento fallido dejaba una ficha a medio crear.
    if not preferred_date or not preferred_date.strip():
        return {"error": "Se requiere la fecha y hora del turno (preferred_date). El bot debe pasar la fecha exacta que eligió el paciente."}
    try:
        start = datetime.fromisoformat(preferred_date.strip())
    except Exception:
        return {"error": f"Formato de fecha inválido: '{preferred_date}'. Usar formato YYYY-MM-DD HH:MM."}

    candidatos = find_professionals_for_reason(reason, db)
    prof = candidatos[0] if candidatos else None
    if not prof:
        return {"error": "No hay profesionales disponibles"}

    # La duracion la decide el motivo, no el modelo: es la misma con la que se
    # calculo el hueco que se le ofrecio al paciente.
    duration_minutes = duracion_para_motivo(reason)

    motivo = motivo_no_agendable(
        db, start, duration_minutes, location, insurance_name, candidatos,
    )
    if motivo:
        return {"error": f"{motivo} Ofrecele otro horario al paciente."}

    # Find or create patient
    patient = db.query(Patient).filter(Patient.dni == dni, Patient.is_deleted == False).first()
    if not patient:
        # Antes de dar de alta una ficha nueva: ¿no sera la misma persona que ya
        # esta cargada, con el DNI escrito distinto? Ese es el origen de los
        # duplicados que limpia scripts/unificar_pacientes_duplicados.py: dos
        # fichas de "Claudio Luna" con el mismo telefono y el historial partido.
        # Se exige que coincidan telefono Y nombre: una familia comparte el
        # numero, asi que el telefono solo no alcanza para decidir.
        patient = _misma_persona_ya_cargada(
            db, requester_phone or phone, patient_name, patient_last_name
        )
        if patient:
            logger.warning(
                "Ficha reutilizada para evitar un duplicado: %s %s ya existe con "
                "DNI %s y se pidio dar de alta el DNI %s (mismo telefono y nombre).",
                patient.first_name, patient.last_name, patient.dni, dni,
            )
    if not patient:
        # Para pacientes nuevos preferimos el número real del canal (WhatsApp)
        # como teléfono: es la identidad verificada que luego usamos para
        # comprobar la propiedad de los turnos. Si no lo hay (ej. Telegram),
        # usamos el teléfono que declaró el paciente.
        patient = Patient(
            first_name=patient_name,
            last_name=patient_last_name,
            dni=dni,
            phone=requester_phone or phone,
            insurance_name=insurance_name,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
    else:
        # Paciente existente: refrescar con los datos obligatorios que tomó el
        # bot. Teléfono y obra social se actualizan siempre (el último dato es
        # el más vigente). Nombre/Apellido solo si están vacíos, para no pisar
        # correcciones hechas desde el panel por recepción.
        new_phone = requester_phone or phone
        if new_phone:
            patient.phone = new_phone
        if insurance_name:
            patient.insurance_name = insurance_name
        if patient_name and not (patient.first_name or "").strip():
            patient.first_name = patient_name
        if patient_last_name and not (patient.last_name or "").strip():
            patient.last_name = patient_last_name
        db.commit()
        db.refresh(patient)

    appt = Appointment(
        patient_id=patient.id,
        professional_id=prof.id,
        start_time=start,
        duration_minutes=duration_minutes,
        reason=reason,
        location=location,
        insurance_name=insurance_name,
        channel=channel,
        status=AppointmentStatus.confirmed,
    )
    db.add(appt)
    try:
        db.commit()
    except IntegrityError:
        # Ultima barrera: el indice unico de la base. Si dos pacientes llegaron
        # al mismo hueco al mismo tiempo, la validacion de arriba pudo ver el
        # horario libre en ambos casos y aca gana uno solo.
        db.rollback()
        return {"error": "Ese horario acaba de ser tomado. Ofrecele otro al paciente."}
    db.refresh(appt)

    return {
        "status": "ok",
        "message": f"Turno agendado con {prof.full_name} en {location}",
        "appointment_id": str(appt.id),
        "professional": prof.full_name,
        "datetime": str(appt.start_time),
    }

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_en_palabras(d) -> str:
    """'martes 18 de agosto de 2026'.

    Se calcula aca y no en el prompt: el modelo deducia el dia de la semana a
    partir de la fecha ISO y se equivocaba (llamo "lunes" al 18/08/2026, que es
    martes). Es aritmetica, no tiene por que hacerla un LLM.
    """
    return f"{DIAS_SEMANA[d.weekday()]} {d.day} de {MESES[d.month - 1]} de {d.year}"


def _intersectar_franjas(a, b):
    """Franjas horarias que estan en AMBAS listas a la vez. Cada franja es
    (start_time, end_time). Se usa para acotar el horario general de la
    clinica a lo que un profesional especifico realmente trabaja."""
    resultado = []
    for a_ini, a_fin in a:
        for b_ini, b_fin in b:
            ini = max(a_ini, b_ini)
            fin = min(a_fin, b_fin)
            if ini < fin:
                resultado.append((ini, fin))
    return resultado


def _unir_franjas(listas):
    """Union de varias listas de franjas horarias, fusionando las que se
    superponen o son contiguas. Sirve para cuando un motivo lo atienden varios
    profesionales: el dia esta disponible si CUALQUIERA de ellos trabaja esa
    hora, sin ofrecer el mismo horario duplicado."""
    todas = sorted((s for lista in listas for s in lista), key=lambda x: x[0])
    if not todas:
        return []
    fusionadas = [todas[0]]
    for ini, fin in todas[1:]:
        ult_ini, ult_fin = fusionadas[-1]
        if ini <= ult_fin:
            fusionadas[-1] = (ult_ini, max(ult_fin, fin))
        else:
            fusionadas.append((ini, fin))
    return fusionadas


def _franjas_del_profesional(db: Session, professional_id, weekday: int, clinic_shifts):
    """Franjas efectivas de un profesional puntual en un dia de la semana.

    Interseccion de su propia grilla (ProfessionalSchedule) con el horario
    general de la clinica. Si el profesional no tiene ninguna fila cargada en
    ProfessionalSchedule (en NINGUN dia), se lo trata como disponible en todo
    el horario general, para no romper a profesionales que todavia no
    configuraron sus dias — es el comportamiento que habia antes de que
    existiera esta tabla.
    """
    propias = db.query(ProfessionalSchedule).filter(
        ProfessionalSchedule.professional_id == professional_id,
        ProfessionalSchedule.is_active == True,
    ).all()
    if not propias:
        return clinic_shifts
    del_dia = [(r.start_time, r.end_time) for r in propias if r.weekday == weekday]
    if not del_dia:
        return []  # tiene grilla cargada, pero no trabaja este dia
    return _intersectar_franjas(clinic_shifts, del_dia)


def interpretar_preferencia(preferencia):
    """Traduce lo que pidio el paciente a un rango (desde, hasta) en minutos.

    Acepta "manana"/"tarde" o una hora suelta ("18:45", "18"). Devuelve None
    si no hay preferencia o no se entiende, y en ese caso no se filtra nada.
    """
    if not preferencia:
        return None
    p = _sin_acentos(str(preferencia)).strip()
    if not p:
        return None
    if "manana" in p or "temprano" in p:
        return (0, 12 * 60 + 30)
    if "tarde" in p or "noche" in p:
        return (12 * 60 + 30, 24 * 60)

    # "despues de las 18:45", "18:45", "18hs", "a las 18"
    import re as _re
    m = _re.search(r"(\d{1,2})(?:[:.](\d{2}))?", p)
    if not m:
        return None
    hora = int(m.group(1))
    minuto = int(m.group(2) or 0)
    if hora > 23 or minuto > 59:
        return None
    desde = hora * 60 + minuto
    if "antes" in p:
        return (0, desde)
    return (desde, 24 * 60)


def _a_minutos(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def repartir_slots(slots, maximo=6):
    """Elige hasta `maximo` horarios repartidos a lo largo del dia.

    Antes se devolvian los primeros 4 (`available_slots[:4]`), que son siempre
    los mas tempranos: el bot nunca veia la franja de la tarde y terminaba
    afirmandole al paciente que no habia turnos que en realidad si existian.
    Ahora se toman de forma pareja entre manana y tarde.
    """
    if len(slots) <= maximo:
        return slots

    manana = [s for s in slots if _a_minutos(s) < 12 * 60 + 30]
    tarde = [s for s in slots if _a_minutos(s) >= 12 * 60 + 30]

    def muestrear(lista, cuantos):
        if cuantos <= 0 or not lista:
            return []
        if len(lista) <= cuantos:
            return lista
        paso = (len(lista) - 1) / (cuantos - 1) if cuantos > 1 else 0
        return [lista[round(i * paso)] for i in range(cuantos)]

    if manana and tarde:
        mitad = maximo // 2
        elegidos = muestrear(manana, mitad) + muestrear(tarde, maximo - mitad)
    else:
        elegidos = muestrear(manana or tarde, maximo)
    return sorted(set(elegidos), key=_a_minutos)


# Marca un salto de dia por una regla interna del consultorio (hoy, PAMI solo
# viernes). Se corre la fecha igual, pero al paciente se le ofrece el dia nuevo
# con naturalidad, sin explicarle la regla.
_MOTIVO_INTERNO = "__interno__"


def get_available_slots(db: Session, target_date: str, location: str, reason: str,
                        obra_social: str = "Particular", recursive_depth=0,
                        fecha_pedida=None, motivo_salto=None, preferencia_horaria=None):
    """Calculate free slots for a given date and location based on clinic schedule.

    fecha_pedida y motivo_salto se arrastran entre llamadas recursivas para poder
    contarle al paciente que el dia que pidio no estaba y por que.
    """
    clinic_now = get_clinic_now()
    try:
        # If target_date is a full ISO string, we take the date part
        day_dt = datetime.fromisoformat(target_date)
        day = day_dt.date()
    except Exception:
        day = clinic_now.date()

    if fecha_pedida is None:
        fecha_pedida = day

    rango = interpretar_preferencia(preferencia_horaria)

    def siguiente(motivo):
        """Prueba el dia siguiente, recordando por que se salteo el primero."""
        return get_available_slots(
            db, (day + timedelta(days=1)).isoformat(), location, reason, obra_social,
            recursive_depth + 1, fecha_pedida, motivo_salto or motivo, preferencia_horaria,
        )

    def respuesta(slots, mensaje=None, profesional=None):
        movido = day != fecha_pedida
        return {
            "date": str(day),
            "fecha_texto": fecha_en_palabras(day),
            "fecha_pedida": str(fecha_pedida),
            "fecha_pedida_texto": fecha_en_palabras(fecha_pedida),
            "movido": movido,
            # Los motivos internos (la regla de PAMI) no se exponen: el paciente
            # no tiene por que enterarse de como se organiza la agenda, y al
            # obligar al modelo a justificar el cambio de dia terminaba
            # inventando cosas como "la clinica esta cerrada para PAMI".
            "motivo_salto": (motivo_salto if (movido and motivo_salto != _MOTIVO_INTERNO) else None),
            "salto_sin_explicar": movido and motivo_salto == _MOTIVO_INTERNO,
            "location": location,
            "professional": profesional,
            "available_slots": slots,
            "message": mensaje,
            "preferencia_horaria": preferencia_horaria,
            "preferencia_respetada": rango is None or bool(slots),
        }

    weekday = day.weekday() # 0=Mon, 2=Wed
        
    # Regla PAMI: solo viernes
    if obra_social and obra_social.upper() == "PAMI" and weekday != 4:
        if recursive_depth < 14:
            return siguiente(_MOTIVO_INTERNO)
        return respuesta([], "No hay turnos disponibles para PAMI en las próximas semanas.")

    # Viernes es al reves: exclusivo para PAMI. Es la contracara de la regla de
    # arriba (antes solo se restringia PAMI a viernes; no se restringia viernes
    # a PAMI, asi que un particular podia sacar turno un viernes igual).
    if weekday == 4 and (not obra_social or obra_social.upper() != "PAMI"):
        if recursive_depth < 14:
            return siguiente(_MOTIVO_INTERNO)
        return respuesta([], "Sin disponibilidad en las próximas dos semanas.")

    # Profesionales que pueden atender este motivo. Puede ser mas de uno (ej.
    # "Limpieza" la hacen los dos): el dia esta disponible si CUALQUIERA de
    # ellos trabaja, y se ofrece la union de sus horarios, no solo el de uno.
    candidatos = find_professionals_for_reason(reason, db)
    prof = candidatos[0] if candidatos else None
    prof_name = prof.full_name if prof else "Cualquier profesional disponible"
    prof_ids = [p.id for p in candidatos]

    # ── Feriado: si el día es feriado, saltar directamente al siguiente ──
    is_holiday = db.query(ClinicHoliday).filter(ClinicHoliday.date == day).first()
    if is_holiday:
        detalle = f" ({is_holiday.description})" if is_holiday.description else ""
        if recursive_depth < 14:
            return siguiente(f"el {fecha_en_palabras(day)} es feriado{detalle} y la clínica está cerrada")
        return respuesta([], "No hay turnos disponibles (feriados).")

    # Horario general de la clínica para ese día, acotado a la grilla de cada
    # candidato y descontando sus ausencias. Vive en franjas_del_dia para que la
    # validacion del alta use exactamente el mismo criterio.
    shifts = franjas_del_dia(db, day, candidatos)

    if not shifts:
        # Día cerrado, o ningún candidato trabaja/está disponible ese día.
        if recursive_depth < 14:
            return siguiente(f"el {fecha_en_palabras(day)} no hay nadie disponible para {reason}")
        return respuesta([], "Sin disponibilidad en las próximas dos semanas.")

    # Turnos del dia en esa sede. Antes esta consulta filtraba tambien por
    # profesional, asi que un horario ocupado por el otro profesional se ofrecia
    # como libre aunque hubiera un solo sillon. Ahora se traen todos y la
    # decision la toma slot_conflict segun los sillones configurados.
    existing = get_day_appointments(db, day, location)
    chairs = get_chairs_per_location(db)
    
    duration_minutes = duracion_para_motivo(reason)

    available_slots = []
    for shift_start_time, shift_end_time in shifts:
        current = datetime.combine(day, shift_start_time)
        shift_end = datetime.combine(day, shift_end_time)
        
        while current + timedelta(minutes=duration_minutes) <= shift_end:
            conflicto = slot_conflict(existing, current, duration_minutes, chairs, prof_ids)

            if not conflicto and current > clinic_now:
                available_slots.append(current.strftime("%H:%M"))
            
            current += timedelta(minutes=duration_minutes)
    
    # Filtrar por la franja que pidio el paciente ("a la tarde", "despues de
    # las 18:45"). Si con el filtro no queda nada pero el dia SI tenia turnos,
    # se salta al dia siguiente aclarando el motivo, en vez de decirle al
    # paciente que no hay nada.
    habia_sin_filtrar = bool(available_slots)
    if rango:
        desde, hasta = rango
        available_slots = [h for h in available_slots if desde <= _a_minutos(h) < hasta]

    if not available_slots and recursive_depth < 14:
        if habia_sin_filtrar and rango:
            motivo = (f"el {fecha_en_palabras(day)} no quedaban horarios en la franja "
                     f"que pediste ({preferencia_horaria})")
        else:
            motivo = f"el {fecha_en_palabras(day)} ya no quedaban horarios libres"
        return siguiente(motivo)

    return respuesta(repartir_slots(available_slots), profesional=prof_name)
