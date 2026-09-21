"""DentiBot tools - communicate with the backend API (OpenAI function calling)."""
import os
import re
import json
import contextvars
import httpx

API_BASE = os.getenv("API_BASE_URL", "http://backend:8000")
BOT_KEY = os.getenv("BOT_API_KEY", "dev-bot-key-change-in-prod")
HEADERS = {"x-bot-key": BOT_KEY, "Content-Type": "application/json"}

# Identidad de la conversación actual (número de WhatsApp real del remitente).
# Lo setea chat() antes de invocar al agente; las tools lo leen para que el
# backend pueda verificar que el DNI pertenece a quien escribe. En Telegram
# (que no tiene teléfono) queda None y no se aplica ninguna verificación.
_requester_phone: contextvars.ContextVar = contextvars.ContextVar("requester_phone", default=None)


def set_requester_phone(phone):
    """Registra el teléfono de quien envía el mensaje para la conversación actual.

    También limpia las opciones del mensaje anterior: se llama al inicio de
    cada turno, así no se arrastran horarios viejos a una respuesta nueva.
    """
    _requester_phone.set(phone or None)
    _opciones_ofrecidas.set(None)


def _current_requester_phone():
    return _requester_phone.get()


# Lo ultimo que escribio el paciente, tal cual. Las tools lo necesitan porque el
# modelo no siempre reenvia lo que le dijeron: se le pide que pase "sw" como
# busqueda y llama a la herramienta sin parametros, mostrando la misma lista de
# nuevo. Teniendo el mensaje original, el codigo lo resuelve igual.
_ultimo_mensaje: contextvars.ContextVar = contextvars.ContextVar("ultimo_mensaje", default="")


def set_ultimo_mensaje(texto: str):
    _ultimo_mensaje.set(texto or "")


# Todo lo que dijo el paciente en esta conversacion. Se usa para verificar que
# un dato lo dijo EL y no lo invento el modelo.
_dichos_por_el_paciente: contextvars.ContextVar = contextvars.ContextVar(
    "dichos_paciente", default=()
)


def set_dichos_por_el_paciente(textos):
    _dichos_por_el_paciente.set(tuple(t for t in (textos or []) if t))


def _motivo_dicho_por_el_paciente(valor: str):
    """(salio_del_paciente, nombre_normalizado, razon_si_rechaza).

    El modelo puede llamar a recordar_dato con un valor que nunca le dijeron
    —dedujo "control" porque le parecio razonable— y eso alcanzaba para
    saltearse la exigencia de preguntar. Pedido del consultorio: "de eso nunca
    suponer, sino averiguar siempre primero que se va a tratar".

    La comparacion la hace el backend contra los tipos de consulta y sus
    sinonimos, no una busqueda literal: el paciente dice "sacarme una muela" y
    el modelo lo registra como "Extraccion", que es exactamente lo que
    corresponde. De paso vuelve el nombre canonico, asi el turno queda guardado
    con el mismo texto siempre.

    Si el rechazo trae `razon` (ej. conducto ambiguo), se la devolvemos al
    modelo para que pregunte lo correcto en vez de un mensaje generico.
    """
    try:
        r = httpx.post(
            f"{API_BASE}/api/bot/resolver-motivo",
            json={"motivo": valor, "dichos": list(_dichos_por_el_paciente.get())},
            headers=HEADERS, timeout=15,
        )
        r.raise_for_status()
        d = r.json()
    except Exception:
        # Si el backend no responde, no se bloquea al paciente por esto.
        return True, valor, None
    return bool(d.get("ok")), (d.get("motivo") or valor), d.get("razon")


# Palabras que son respuestas de conversacion, no el nombre de una obra social.
_NO_ES_BUSQUEDA = {
    "si", "no", "ok", "dale", "hola", "gracias", "bueno", "listo", "particular",
    "obra", "social", "obrasocial", "dime", "cual", "cuales", "otra", "otro",
    "dale si", "no la veo", "no esta", "dale gracias", "tengo", "tengo obra",
}

# Palabras con las que el paciente dice QUE QUIERE HACER, no como se llama su
# obra social. Un paciente escribe "agendar" y el sistema le contestaba "no
# trabajamos con 'agendar' como obra social", tres veces seguidas. Es lo primero
# que escribe cualquiera.
_PALABRAS_DE_INTENCION = {
    "agendar", "agenda", "turno", "turnos", "sacar", "pedir", "reservar",
    "cancelar", "consultar", "reprogramar", "cambiar", "modificar", "anular",
    "necesito", "quiero", "queria", "quisiera", "buenas", "buenos", "dias",
    "tardes", "noches", "consulta", "hora", "horario", "atencion", "atender",
    "ayuda", "informacion", "info", "precio", "precios", "costo", "cuanto",
    "donde", "direccion", "ubicacion", "telefono",
}

# Motivo odontológico / pedidos de día / profesional. Caso real 21/09: el
# paciente dijo "Tratamiento de conducto" y el bot contestó "No trabajamos con
# esa obra social" porque `verificar_obra_social` lo tomó como cobertura.
_PALABRAS_DE_MOTIVO_O_AGENDA = {
    "tratamiento", "tratamientos", "conducto", "endodoncia", "nervio",
    "limpieza", "limpiar", "sarro", "profilaxis", "control", "revision",
    "chequeo", "extraccion", "extraer", "muela", "muelas", "cordal",
    "ortodoncia", "brackets", "implante", "implantes", "protesis", "caries",
    "arreglo", "arreglos", "dolor", "duele", "urgente", "urgencia",
    "evaluacion", "evaluar", "derivado", "derivada", "odontopediatria",
    "blanqueamiento", "radiografia", "placa",
    "doctor", "doctora", "dr", "dra", "profesional",
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
    "manana", "tarde", "noche", "hoy", "pasado", "semana", "proximo",
    "proxima", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
}


def _parece_nombre_de_obra_social(texto: str) -> bool:
    """Si eso puede ser el nombre de una obra social, y no otra cosa.

    Se descarta lo que es claramente una intencion ("agendar un turno"), un
    saludo, un motivo odontológico ("tratamiento de conducto") o una pregunta.
    Ante la duda se acepta: hay obras sociales con nombres rarisimos y es peor
    rechazar la verdadera que dejar pasar una consulta que despues no matchea.
    """
    limpio = _sin_tildes_simple(texto).strip()
    if not limpio:
        return False
    if "?" in limpio or "¿" in limpio:
        return False
    palabras = [p for p in limpio.replace("/", " ").split() if p.isalnum() or p.isalpha()]
    if not palabras:
        return False
    # Si TODAS son palabras de intencion, motivo o relleno, no es una obra social.
    relleno = (
        _PALABRAS_DE_INTENCION | _NO_ES_BUSQUEDA | _PALABRAS_DE_MOTIVO_O_AGENDA | {
            "un", "una", "unos", "unas", "el", "la", "los", "las", "de", "del",
            "para", "por", "me", "mi", "mis", "tu", "tus", "su", "sus", "con",
            "que", "y", "o", "en", "al", "lo", "es", "ser", "hay",
        }
    )
    return any(p not in relleno for p in palabras)


def _sin_tildes_simple(texto: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()



# Como pide el paciente una franja horaria. El modelo tiene instruccion de
# pasarla en preferencia_horaria y no siempre lo hace: mismo patron que ya
# fallo con la obra social ("sw") y con el motivo. Si no la reenvia, se saca
# del mensaje del paciente, que es el unico lugar donde de verdad esta.
_PALABRAS_DE_FRANJA = (
    "manana", "tarde", "noche", "temprano", "mediodia",
    "despues de", "antes de", "a partir de", "pasadas las", "cerca de",
    "al mediodia", "a la salida", "despues del trabajo", "antes del trabajo",
)


def _franja_en_el_texto(texto: str) -> str:
    """El pedido de horario que hizo el paciente, o "" si no pidio ninguno.

    Devuelve el texto tal cual: interpretar_preferencia (en el backend) ya sabe
    traducir "a la tarde", "despues de las 18:45" o "temprano" a un rango.
    """
    limpio = _sin_tildes_simple(texto).strip()
    if not limpio:
        return ""

    import re
    # "despues de las 18", "a partir de las 9:30", "antes de las 12"
    m = re.search(r"(despues|antes|a partir|pasadas?)\s+(?:de\s+)?(?:las?\s+)?(\d{1,2})(?:[:.](\d{2}))?", limpio)
    if m:
        return texto.strip()

    if any(f in limpio for f in _PALABRAS_DE_FRANJA):
        return texto.strip()
    return ""


def _texto_parece_busqueda(texto: str) -> str:
    """El fragmento que el paciente escribio buscando su obra social, o "".

    "sw", "swi", "ospe", "swiss medical" son busquedas. "si", "hola" o una frase
    larga, no. Tampoco un apellido de profesional ("Silvestre", "Murad").
    """
    limpio = " ".join((texto or "").strip().lower().split())
    if not limpio or limpio in _NO_ES_BUSQUEDA:
        return ""
    if len(limpio) > 30 or len(limpio.split()) > 3:
        return ""   # una frase, no el nombre de una obra social
    if not any(c.isalpha() for c in limpio):
        return ""
    if not _parece_nombre_de_obra_social(limpio):
        return ""   # "agendar", "quiero un turno", "tratamiento de conducto"
    # "Tengo obra social" / "obra social" es el boton, no el nombre de una.
    # Arnes 21/09: listar_obras_sociales busco 'tengo obra social' y contesto
    # "no trabajamos con esa obra social".
    if _paciente_eligio_tiene_obra_social(limpio) or _paciente_eligio_particular(limpio):
        return ""
    # "Silvestre" / "Murad" / "Sosa": es pedir profesional, no cobertura.
    if _profesional_en(limpio):
        return ""
    return limpio


# Opciones concretas que la ultima tool dejo sobre la mesa (ej: los horarios
# disponibles). El webhook las lee despues de que el modelo respondio y, si la
# respuesta efectivamente las esta ofreciendo, las manda como lista tocable en
# vez de texto. Mismo patron que _requester_phone: contextvar por conversacion.
_opciones_ofrecidas: contextvars.ContextVar = contextvars.ContextVar("opciones_ofrecidas", default=None)

# Lo que consultar_disponibilidad devolvio de verdad en este turno.
#
# Existe porque el modelo escribio horarios y fechas que ninguna herramienta le
# habia dado. Conversacion real del 10/09: le ofrecio al paciente "el lunes 12
# de septiembre" —que era sabado— y despues, cuando pregunto por la Dra. Murad,
# repitio los horarios del Dr. Silvestro sin volver a consultar. Murad no
# atiende los miercoles.
#
# Con esto, lo que sale por WhatsApp se puede comparar contra lo que el sistema
# realmente respondio.
_disponibilidad_del_turno: contextvars.ContextVar = contextvars.ContextVar(
    "disponibilidad_del_turno", default=None)


def reiniciar_disponibilidad():
    _disponibilidad_del_turno.set([])


def registrar_disponibilidad(profesional, fecha_iso, fecha_texto, slots, motivo=None):
    actuales = list(_disponibilidad_del_turno.get() or [])
    actuales.append({
        "profesional": profesional or "",
        "fecha": fecha_iso or "",
        "fecha_texto": fecha_texto or "",
        "slots": list(slots or []),
        "motivo": motivo or "",
    })
    _disponibilidad_del_turno.set(actuales)


def disponibilidad_consultada():
    return list(_disponibilidad_del_turno.get() or [])


_confirmacion_turno: contextvars.ContextVar = contextvars.ContextVar(
    "confirmacion_turno", default=None)


def reiniciar_confirmacion_turno():
    _confirmacion_turno.set(None)


def registrar_confirmacion_turno(texto: str):
    _confirmacion_turno.set(texto)


def confirmacion_turno_agendada() -> str | None:
    return _confirmacion_turno.get()


def set_opciones_ofrecidas(opciones, siempre: bool = False,
                           titulo: str | None = None, boton: str | None = None,
                           tipo: str = "lista"):
    """Publica opciones para que el webhook las mande como lista tocable.

    `siempre=True` fuerza el envio aunque el texto del modelo no las nombre. Es
    lo que hace falta para las obras sociales: la gracia es justamente que el
    paciente NO tenga que leerlas ni escribirlas, asi que el modelo pregunta
    "¿cual es tu obra social?" y la lista va igual.
    """
    _opciones_ofrecidas.set(
        {
            "opciones": list(opciones),
            "siempre": siempre,
            "titulo": titulo,
            "boton": boton,
            # "botones" son hasta 3 respuestas rapidas que se tocan sin abrir
            # nada; "lista" abre un menu. Para una eleccion binaria los botones
            # son un toque contra tres.
            "tipo": tipo,
        } if opciones else None
    )


def tomar_opciones_ofrecidas():
    """Devuelve las opciones pendientes y las limpia (se consumen una sola vez)."""
    ops = _opciones_ofrecidas.get()
    _opciones_ofrecidas.set(None)
    return ops


# ── Tool implementations ─────────────────────────────────────────────────────

# Lo ultimo que dijo el BOT. Sirve para saber que horarios le ofrecio: si le
# ofrecio uno solo y el paciente dice "dale", ese es el elegido.
_ultima_respuesta_bot: contextvars.ContextVar = contextvars.ContextVar(
    "ultima_respuesta_bot", default="")


def set_ultima_respuesta_bot(texto: str | None):
    _ultima_respuesta_bot.set(texto or "")


_AFIRMACIONES = {
    "si", "sí", "dale", "ok", "okey", "bueno", "claro", "obvio", "perfecto",
    "genial", "joya", "listo", "va", "sip", "por favor", "porfa", "busca",
    "buscá", "buscalo", "hacelo", "de acuerdo", "esta bien", "está bien",
    "ese", "esa", "ese mismo", "esa misma", "me sirve", "sirve",
}
_RELLENO_AFIRMATIVO = {"por", "favor", "gracias", "que", "muy", "bien", "me"}


def es_afirmacion(texto: str) -> bool:
    """True si el mensaje es un sí corto y nada más ("sí", "dale", "sí, por favor")."""
    t = (texto or "").lower()
    for signo in "!¡.,;:":
        t = t.replace(signo, " ")
    partes = t.split()
    if not partes or len(partes) > 3:
        return False
    if " ".join(partes) in _AFIRMACIONES:
        return True
    return partes[0] in _AFIRMACIONES and all(
        p in _AFIRMACIONES or p in _RELLENO_AFIRMATIVO for p in partes
    )


_HHMM = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_LAS_H = re.compile(r"\b(?:a\s+las?|las?|el\s+de\s+las?)\s+([01]?\d|2[0-3])(?::([0-5]\d))?\b")
_H_HS = re.compile(r"\b([01]?\d|2[0-3])\s*(?:hs|h|horas?)\b")


def _hora_elegida(texto: str) -> str | None:
    """La hora que nombra el paciente, en HH:MM. "10:00", "a las 10", "10hs", "10"."""
    t = (texto or "").strip().lower()
    if not t:
        return None
    if m := _HHMM.search(t):
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    if m := _LAS_H.search(t):
        return f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    if m := _H_HS.search(t):
        return f"{int(m.group(1)):02d}:00"
    if t.isdigit() and 0 <= int(t) <= 23:
        return f"{int(t):02d}:00"
    return None


def _quiere_el_primero(texto: str) -> bool:
    from backend.services.appointment_service import _sin_acentos
    return bool(re.search(
        r"\b(el\s+)?primer[oa]?(\s+que\s+(tengas|haya|salga))?\b"
        r"|cualquier(a|\s+horario)|el\s+que\s+sea|lo\s+antes\s+posible",
        _sin_acentos(texto or "").lower(),
    ))


def _horarios_ofrecidos() -> set[str]:
    """Los horarios que el bot puso sobre la mesa: los consultados en este turno
    y los que nombro en su ultima respuesta."""
    ofrecidos = {s for d in disponibilidad_consultada() for s in (d.get("slots") or [])}
    ofrecidos |= {f"{int(h):02d}:{m}" for h, m in _HHMM.findall(_ultima_respuesta_bot.get() or "")}
    return ofrecidos


def _paciente_eligio_horario(preferred_date: str) -> str | None:
    """Bloquea el alta si el horario no lo eligio el paciente.

    Arnes 21/09: ofrecio lunes 10:00/11:00, el paciente dijo "El jueves con
    Silvestre" y el modelo agendo "2026-09-22 10:00". El horario del turno lo
    dice el paciente; si no lo dijo, no hay turno.
    """
    ultimo = _ultimo_mensaje.get() or ""
    pedida = (preferred_date or "")[11:16]
    dia_pedido = (preferred_date or "")[:10]

    if hora := _hora_elegida(ultimo):
        if pedida and hora != pedida:
            return (
                f"❌ El paciente eligió las {hora} y vos mandás las {pedida}. "
                f"Agendá a las {hora} (mismo día que se le ofreció)."
            )
        fecha_dicha = _fecha_en(ultimo)
        if fecha_dicha and dia_pedido and fecha_dicha != dia_pedido:
            return (
                f"❌ El paciente pidió el {fecha_dicha} y vos mandás {dia_pedido}. "
                f"Consultá disponibilidad para el {fecha_dicha} y ofrecele esos horarios."
            )
        return None

    if _quiere_el_primero(ultimo):
        return None

    ofrecidos = _horarios_ofrecidos()
    if es_afirmacion(ultimo) and len(ofrecidos) == 1:
        (unico,) = ofrecidos
        if pedida and unico != pedida:
            return f"❌ Le ofreciste las {unico} y aceptó eso; vos mandás las {pedida}."
        return None

    return (
        f"❌ El paciente todavía NO eligió un horario: su último mensaje fue "
        f"'{ultimo.strip()[:80]}'. 🚫 PROHIBIDO agendar por él. "
        f"Si nombró un día o un profesional, llamá a `consultar_disponibilidad` "
        f"con eso y ofrecele los horarios; si le ofreciste varios, preguntale cuál."
    )


def _lo_que_pidio() -> str:
    """Lo ultimo que el paciente dijo sobre dia u horario, tal como lo dijo.

    Se usa al agendar para revalidar la restriccion: entre que se ofrecen los
    horarios y se crea el turno, el modelo puede no reenviarla, y ahi es donde
    se colaba un dia que el paciente habia descartado.
    """
    for dicho in reversed(_dichos_por_el_paciente.get() or (_ultimo_mensaje.get(),)):
        if not dicho:
            continue
        from backend.services.appointment_service import dias_excluidos
        if _franja_en_el_texto(dicho) or dias_excluidos(dicho):
            return dicho
    return ""


def agendar_turno(
    reason: str,
    preferred_date: str,
    patient_name: str = "",
    patient_last_name: str = "",
    dni: str = "",
    phone: str = "",
    location: str = "",
    insurance_name: str = "Particular",
    duration_minutes: int = 30,
    profesional: str = "",
    preferencia_horaria: str = "",
) -> str:
    """Agenda un nuevo turno en el sistema."""
    if bloqueo := _exigir_cobertura("agendar"):
        return bloqueo
    # La cobertura manda desde el estado: el default Particular del parametro
    # ya no puede pisar lo que el paciente eligio (ni inventar Particular).
    insurance_name = _cobertura_registrada() or insurance_name
    # Idem el motivo: es el que define la duracion del turno.
    reason = _motivo_registrado() or reason
    # Y el horario: lo elige el paciente, no el modelo.
    if bloqueo := _paciente_eligio_horario(preferred_date):
        return bloqueo
    # Si nombro a un profesional y el modelo no lo reenvio, viaja igual: el
    # backend es quien sabe si esa persona hace ese tratamiento.
    profesional = profesional or _profesional_en(_ultimo_mensaje.get() or "")

    payload = {
        "profesional_pedido": profesional or None,
        # Si el modelo no la reenvia, se busca en lo que dijo el paciente: la
        # restriccion no puede perderse entre ofrecer y agendar.
        "preferencia_horaria": (preferencia_horaria or "").strip() or _lo_que_pidio() or None,
        "patient_name": patient_name,
        "patient_last_name": patient_last_name,
        "dni": dni,
        "phone": phone,
        "reason": reason,
        "location": location,
        "insurance_name": insurance_name,
        "preferred_date": preferred_date,
        "duration_minutes": duration_minutes,
        "requester_phone": _current_requester_phone(),
    }
    try:
        r = httpx.post(f"{API_BASE}/api/bot/appointments", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        # Lo arma el backend: es el unico que conoce el dominio publico, y
        # tenerlo escrito aca lo dejaba desincronizado del resto del sistema.
        cancel_url = data.get("cancel_url", "")
        # Texto listo para el paciente: el modelo no inventa fecha ni profesional.
        cuando = data.get("datetime") or preferred_date
        mensaje_base = (data.get("message") or "Turno agendado").rstrip(".")
        confirmacion = (
            f"Listo 😊 {mensaje_base}. Fecha: {cuando}. "
            f"Si necesitás cancelar, escribime 'quiero cancelar mi turno'"
            + (f" o usá este link: {cancel_url}" if cancel_url else ".")
        )
        registrar_confirmacion_turno(confirmacion)
        return (
            f"✅ {data['message']}. Fecha: {data['datetime']}. ID: {data['appointment_id']}. "
            f"Aclarale al paciente que si desea cancelar el turno, puede escribir "
            f"'quiero cancelar mi turno' o ingresar a este link: {cancel_url}"
        )
    except httpx.HTTPStatusError as e:
        try:
            motivo = e.response.json().get("detail", str(e))
        except Exception:
            motivo = e.response.text or str(e)
        return f"❌ No se pudo agendar: {motivo}"
    except Exception as e:
        return f"❌ Error al agendar: {str(e)}"


def cancelar_turno(dni: str = "", appointment_id: str = "") -> str:
    """Cancela un turno existente del paciente."""
    payload = {"dni": dni or None, "requester_phone": _current_requester_phone()}
    if appointment_id:
        payload["appointment_id"] = appointment_id
    try:
        r = httpx.post(f"{API_BASE}/api/bot/cancel", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return f"✅ {r.json()['message']}"
    except httpx.HTTPStatusError as e:
        return f"❌ {e.response.json().get('detail', 'Error al cancelar')}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


def reprogramar_turno(appointment_id: str, new_datetime: str, dni: str = "") -> str:
    """Reprograma un turno existente a una nueva fecha."""
    payload = {
        "dni": dni or None,
        "appointment_id": appointment_id,
        "new_start_time": new_datetime,
        "requester_phone": _current_requester_phone(),
    }
    try:
        r = httpx.post(f"{API_BASE}/api/bot/reschedule", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return f"✅ {r.json()['message']}"
    except httpx.HTTPStatusError as e:
        return f"❌ {e.response.json().get('detail', 'Error al reprogramar')}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


# Lo que el modelo tiene que hacer cuando el turno no aparece. No es lo mismo
# "no existe" que "no lo puedo ver": el 85% de las fichas activas vienen de la
# agenda de papel, sin DNI ni telefono, asi que a la mayoria de los pacientes el
# sistema no los puede identificar aunque su turno este cargado.
#
# Una paciente pidio cancelar el suyo del dia siguiente y la conversacion
# termino en "¿podrías darme el nombre y apellido de otra persona?". El turno
# existia. Nadie se entero. No hay bandeja de derivaciones: se indica llamar.
_NO_APARECE = (
    "\n\n🚫 NO le digas que no tiene turnos ni que nunca los tuvo: puede tenerlos "
    "en una ficha que el sistema no puede vincular a este número. "
    "Decile que NO LO ENCONTRÁS EN ESTA AGENDA y llamá a "
    "`indicar_llamar_consultorio` con un motivo breve."
)


def telefono_consultorio() -> str:
    """Teléfono que se le pasa al paciente cuando el bot no puede resolver.

    Configurable desde el panel (TELEFONO_CONSULTORIO). Por defecto el número
    productivo de WhatsApp del consultorio.
    """
    default = os.getenv("TELEFONO_CONSULTORIO") or os.getenv("YCLOUD_FROM_PHONE") or "2604590071"
    try:
        from backend.database import SessionLocal
        from backend.models.config import AppConfig
        db = SessionLocal()
        try:
            conf = db.query(AppConfig).filter(AppConfig.key == "TELEFONO_CONSULTORIO").first()
            if conf and (conf.value or "").strip():
                return conf.value.strip()
        finally:
            db.close()
    except Exception:
        pass
    digitos = "".join(c for c in default if c.isdigit())
    if len(digitos) >= 10:
        # 5492604590071 → 2604-590071; 2604590071 → 2604-590071
        local = digitos[-10:]
        return f"{local[:4]}-{local[4:]}"
    return default.strip()


def consultar_mis_turnos(dni: str = "") -> str:
    """Consulta los turnos pendientes de un paciente."""
    try:
        payload = {"dni": dni or None, "requester_phone": _current_requester_phone()}
        r = httpx.post(f"{API_BASE}/api/bot/my-appointments", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data["appointments"]:
            return f"ℹ️ No hay turnos vinculados a {data['patient']}." + _NO_APARECE
        lines = [f"📋 Turnos de {data['patient']}:"]
        for a in data["appointments"]:
            lines.append(
                f"  • ID {a.get('id', '?')} — {a['date']} - {a['reason']} "
                f"con {a['professional']} en {a['location']} ({a['status']})"
            )
        return "\n".join(lines)
    except httpx.HTTPStatusError as e:
        detalle = e.response.json().get("detail", "Paciente no encontrado")
        # No poder identificar a alguien no es un error del paciente: es un
        # limite del sistema, y se resuelve derivando, no interrogandolo.
        return f"❌ {detalle}" + _NO_APARECE
    except Exception as e:
        return f"❌ Error de conexión: {e}. Esto NO significa que no tenga turnos."


def _profesional_en(texto: str) -> str:
    """El profesional que nombra ese texto, resuelto contra las fichas cargadas.

    Contra las fichas y no contra una lista escrita a mano: si mañana entra
    otro profesional, esto lo reconoce igual.
    """
    from backend.database import SessionLocal
    from backend.services.appointment_service import buscar_profesional

    if not (texto or "").strip():
        return ""
    db = SessionLocal()
    try:
        encontrado = buscar_profesional(db, texto)
        return encontrado.full_name if encontrado else ""
    except Exception:
        return ""
    finally:
        db.close()


def _profesional_ofrecido_en(texto: str) -> str:
    """El profesional que el bot ESTÁ ofreciendo, no el que acaba de descartar.

    "Silvestro no hace conductos. ¿Querés con la Dra. Murad?" menciona a los
    dos. `buscar_profesional` devuelve el primero que encuentra en la base;
    el paciente aceptó al que el bot ofreció al final (Murad).
    """
    from backend.database import SessionLocal
    from backend.models.professional import Professional
    from difflib import SequenceMatcher
    from backend.services.appointment_service import _palabras

    if not (texto or "").strip():
        return ""
    tratamientos = {"dr", "dra", "doctor", "doctora", "el", "la", "con", "drama",
                    "del", "de", "los", "las"}
    db = SessionLocal()
    try:
        activos = db.query(Professional).filter(
            Professional.is_deleted == False,  # noqa: E712
            Professional.is_active == True,    # noqa: E712
        ).all()
        apariciones: list[tuple[int, str]] = []
        texto_n = " ".join(_palabras(texto))
        for p in activos:
            for apellido in set(_palabras(p.full_name)) - tratamientos:
                if len(apellido) < 4:
                    continue
                pos = texto_n.find(apellido)
                if pos < 0:
                    # Typo leve ("Silvestre").
                    for palabra in texto_n.split():
                        if (len(palabra) >= 5
                                and SequenceMatcher(None, palabra, apellido).ratio() >= 0.85):
                            pos = texto_n.find(palabra)
                            break
                if pos >= 0:
                    apariciones.append((pos, p.full_name))
                    break
        if not apariciones:
            return ""
        apariciones.sort(key=lambda x: x[0])
        return apariciones[-1][1]
    except Exception:
        return ""
    finally:
        db.close()


def _fecha_en(texto: str) -> str:
    """El dia que nombra ese texto, en YYYY-MM-DD, o vacio."""
    from backend.services.appointment_service import fecha_dicha_por_el_paciente

    try:
        fecha = fecha_dicha_por_el_paciente(texto)
        return fecha.isoformat() if fecha else ""
    except Exception:
        return ""


def _buscando_en_todo(extraer) -> str:
    """Lo mas reciente que el paciente dijo al respecto en toda la charla."""
    for dicho in reversed(_dichos_por_el_paciente.get() or (_ultimo_mensaje.get(),)):
        if not dicho:
            continue
        if valor := extraer(dicho):
            return valor
    return ""


def consultar_disponibilidad(
    motivo_confirmado_por_paciente: str,
    location: str = "",
    date: str = "",
    obra_social: str = "Particular",
    preferencia_horaria: str = "",
    profesional: str = "",
) -> str:
    """Consulta los horarios disponibles para una sede, especialidad y fecha."""
    # El motivo tiene que haberlo dicho el paciente, no deducirlo el modelo: de
    # el sale la duracion del turno (control 15', extraccion 30', endodoncia
    # 60'), asi que ofrecer horarios sin saberlo reserva el tiempo equivocado.
    # Pedido explicito del consultorio: "los turnos no darlos sin preguntar para
    # que son porque tienen una duracion diferente dependiendo para que es".
    #
    # El prompt ya lo pedia y el modelo igual inventaba un motivo, asi que se
    # exige que este registrado en el estado de la conversacion via
    # recordar_dato: eso solo pasa si el paciente lo dijo.
    # Si el modelo no reenvio la franja que pidio el paciente, se la saca del
    # mensaje. Sin esto le ofrecia horarios de la manana a alguien que pidio
    # "despues de las 17", que es un pedido explicito del consultorio:
    # "si piden para la tarde, buscar el dia que tenga libre a la tarde".
    if not (preferencia_horaria or "").strip():
        for dicho in reversed(_dichos_por_el_paciente.get() or (_ultimo_mensaje.get(),)):
            if franja := _franja_en_el_texto(dicho):
                preferencia_horaria = franja
                break

    # ── El profesional y el dia los decide el paciente, no el modelo ──────
    #
    # Conversacion real del 10/09:
    #
    #   paciente: quiero un turno con Murad para el jueves
    #   paciente: extraccion
    #   bot:      no hay disponibilidad para extracción el martes 15...
    #             pero tengo turnos para el miércoles 16 a las 10:30...
    #
    # El paciente dijo JUEVES y el modelo mando date=2026-09-15, que era
    # martes. Y no mando el profesional, asi que la busqueda salio generica y
    # devolvio los horarios del otro profesional. Reproducido: con esos dos
    # parametros, el backend produce ese mensaje palabra por palabra.
    #
    # Lo que el paciente dijo EN ESTE MENSAJE gana sobre lo que mande el
    # modelo. Lo que dijo antes solo completa si el modelo no mando nada: si no,
    # un "jueves" de tres mensajes atras pisaria el dia que acaba de aceptar.
    ahora = _ultimo_mensaje.get() or ""

    if prof_ahora := _profesional_en(ahora):
        profesional = prof_ahora
    elif es_afirmacion(ahora):
        # "¿Querés con la Dra. Murad?" → "Sí". El que aceptó es el que el bot
        # ofreció (el último nombrado), no el que había pedido antes ni el que
        # el bot acaba de descartar (arnés 21/09: "Silvestre" volvía a pisar).
        profesional = (
            _profesional_ofrecido_en(_ultima_respuesta_bot.get() or "")
            or (profesional or "").strip()
        )
    elif not (profesional or "").strip():
        profesional = _buscando_en_todo(_profesional_en)

    if fecha_ahora := _fecha_en(ahora):
        date = fecha_ahora
    elif not (date or "").strip():
        date = _buscando_en_todo(_fecha_en)

    if not (_estado_conversacion.get() or {}).get("motivo"):
        return (
            "❌ Todavía no sabés para qué es la consulta, y de eso depende cuánto "
            "dura el turno. Preguntale al paciente el motivo (limpieza, control, "
            "extracción, conducto...), registralo con `recordar_dato` y recién "
            "después volvé a llamar a esta herramienta. "
            "🚫 PROHIBIDO deducirlo o darlo por supuesto."
        )

    if bloqueo := _exigir_cobertura("consultar disponibilidad"):
        return bloqueo
    obra_social = _cobertura_registrada() or obra_social
    # La duracion sale del motivo, y el motivo es el registrado (ya verificado
    # contra lo que dijo el paciente), no lo que el modelo escriba aca:
    # "tratamiento de conducto" daria 60' aunque el estado diga "Consulta por
    # conducto" (30').
    motivo_confirmado_por_paciente = _motivo_registrado() or motivo_confirmado_por_paciente

    try:
        payload = {
            "location": location,
            "reason": motivo_confirmado_por_paciente,
            "date": date,
            "obra_social": obra_social,
            "preferencia_horaria": preferencia_horaria or None,
            "profesional_pedido": profesional or None,
        }
        r = httpx.post(f"{API_BASE}/api/bot/availability", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        slots = data.get("available_slots", [])
        date_iso = data.get("date", "")
        fecha_texto = data.get("fecha_texto") or date_iso
        if not slots:
            # El backend explica POR QUE no hay lugar ("Murad no hace Extracción,
            # eso lo atiende Silvestro..."). Pisar esa explicación con un texto
            # genérico dejaba al modelo sin la información: en producción dijo
            # "no tengo turnos con la Dra. Murad" sin aclarar que ella no hace
            # extracciones ni ofrecer al que sí.
            if data.get("message"):
                return data["message"]
            return (
                f"No hay turnos disponibles en {location} en las próximas semanas. "
                f"Decíselo al paciente con claridad. "
                f"🚫 NO ofrezcas dejar datos, que lo contacten ni que lo anotes en "
                f"ninguna bandeja. Sin turnos NO es motivo para indicar_llamar_consultorio: "
                f"eso es algo que sí resolviste (no hay lugar)."
            )

        # Se publican para que el webhook pueda ofrecerlos como lista tocable.
        set_opciones_ofrecidas(slots)
        # Y se registra lo que se devolvio, para poder verificar despues que el
        # mensaje al paciente no diga horarios ni fechas que nadie le dio.
        registrar_disponibilidad(
            data.get("professional"), date_iso, fecha_texto, slots,
            # Por que se corrio el dia: "el Dr. Silvestro no atiende el lunes
            # 14. Atiende miercoles, jueves y viernes". Se guarda para poder
            # decirselo al paciente aunque el modelo se lo saltee.
            motivo=data.get("motivo_salto") if data.get("movido") else None)

        aviso = ""
        if data.get("salto_sin_explicar"):
            # Se corrió la fecha por una regla interna del consultorio. Se le
            # ofrece el día nuevo con total naturalidad, sin justificar nada:
            # el paciente no tiene por qué conocer cómo se organiza la agenda.
            aviso = (
                f"El día que pidió el paciente no estaba disponible. Ofrecele el "
                f"{fecha_texto} con naturalidad, como si fuera lo normal. "
                f"🚫 PROHIBIDO explicarle por qué cambió la fecha, PROHIBIDO mencionar "
                f"reglas internas del consultorio y PROHIBIDO decir que algo está "
                f"'cerrado'. Simplemente ofrecé el día y los horarios. "
            )
        elif data.get("movido"):
            motivo = data.get("motivo_salto") or "ese día no había disponibilidad"
            aviso = (
                f"OJO: el paciente pidió el {data.get('fecha_pedida_texto')}, pero {motivo}. "
                f"Avisale esto con naturalidad (no es un error ni pidas disculpas) y ofrecele "
                f"el {fecha_texto}, que es el próximo día con lugar. "
            )

        # Si el paciente ya dijo "el primero que tengas", volver a preguntarle
        # cuál es dar la vuelta en círculo que este mensaje mismo prohíbe. Se
        # detecta acá porque es el punto exacto donde el modelo decide entre
        # listar y agendar, y las tres corridas del arnés mostraron que sin
        # esto lista y repregunta.
        import re as _re
        from backend.services.appointment_service import _sin_acentos
        quiere_el_primero = any(
            _re.search(r"\b(el\s+)?primer[oa]?(\s+que\s+(tengas|haya|salga))?\b"
                       r"|cualquier\s+horario|el\s+que\s+sea|lo\s+antes\s+posible",
                       _sin_acentos(d or "").lower())
            for d in ((_dichos_por_el_paciente.get() or ()) or (_ultimo_mensaje.get(),))
        )
        elegir_por_el = ""
        if quiere_el_primero and slots:
            elegir_por_el = (
                f"⚡ El paciente YA DIJO que quiere el primer turno disponible: "
                f"llamá `agendar_turno` AHORA con preferred_date='{date_iso} {slots[0]}' "
                f"sin volver a preguntarle cuál. "
            )
        return (
            f"{aviso}{elegir_por_el}"
            f"[FECHA GARANTIZADA FUTURA: {date_iso} = {fecha_texto}] "
            f"Turnos disponibles en {location} para el {fecha_texto}: {', '.join(slots)}. "
            f"Al escribirle al paciente usá EXACTAMENTE '{fecha_texto}'. PROHIBIDO calcular vos "
            f"el día de la semana. Cuando elija un horario, combiná {date_iso} con ese horario "
            f"para formar preferred_date en formato YYYY-MM-DD HH:MM. "
            f"No la vuelvas a llamar para LO MISMO. Pero SÍ tenés que llamarla de "
            f"nuevo si cambia el profesional, el motivo, la fecha o la franja: "
            f"cada profesional atiende días distintos, así que estos horarios NO "
            f"valen para otro. 🚫 PROHIBIDO reusar estos horarios para responder "
            f"por otro profesional."
        )
    except Exception as e:
        return f"Error consultando disponibilidad: {e}"


def verificar_obra_social(obra_social: str) -> str:
    """Verifica si la clínica atiende una obra social."""
    # "Tengo obra social" no es una obra social: es la respuesta al boton. El
    # modelo la manda aca igual (arnes 21/09: "No trabajamos con esa obra
    # social, tu atencion seria PARTICULAR"). Se hace lo que corresponde:
    # mostrar la lista.
    ultimo = _ultimo_mensaje.get() or ""
    if _paciente_eligio_tiene_obra_social(obra_social) or (
        _paciente_eligio_tiene_obra_social(ultimo) and not _texto_parece_busqueda(ultimo)
    ):
        return listar_obras_sociales()
    # Antes de nada: ¿eso puede ser el nombre de una obra social? El paciente
    # escribe "agendar" y el bot le contestaba "no trabajamos con 'agendar'
    # como obra social", una y otra vez. Es lo primero que escribe cualquiera.
    # Caso 21/09: "Tratamiento de conducto" → "No trabajamos con esa obra social".
    if not _parece_nombre_de_obra_social(obra_social):
        return (
            f"⚠️ '{obra_social}' NO es el nombre de una obra social: es un motivo "
            f"de consulta, una intención o un saludo. 🚫 PROHIBIDO contestarle que "
            f"no trabajamos con esa cobertura, no tiene ningún sentido y queda "
            f"pésimo. Seguí la conversación: si pidió un turno, avanzá con el "
            f"flujo (motivo → cobertura → horarios). Si todavía falta la obra "
            f"social, usá `listar_obras_sociales`."
        )
    # Tampoco un apellido de profesional ("Sosa", "Silvestro").
    if _profesional_en(obra_social):
        return (
            f"⚠️ '{obra_social}' es un profesional, no una obra social. "
            f"🚫 PROHIBIDO tratarlo como cobertura. Si el paciente pidió turno "
            f"con esa persona, seguí con motivo/cobertura y después "
            f"`consultar_disponibilidad` pasando ese profesional."
        )

    try:
        r = httpx.post(
            f"{API_BASE}/api/bot/verificar-obra-social",
            json={"obra_social": obra_social},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        d = r.json()
        if d["cubierta"]:
            _registrar_cobertura(d["nombre"])
            return (
                f"CUBIERTA. La clínica atiende {d['nombre']} y ya quedó registrada "
                f"en el estado (no hace falta `recordar_dato`). Seguí con el turno."
            )
        # No cubierta. Pero antes de darla por perdida: puede ser un fragmento
        # ("swi") o estar mal escrita ("ospeysin"), asi que se buscan las que se
        # parecen. El modelo llama a esta herramienta cuando deberia llamar a
        # listar_obras_sociales con busqueda, y el paciente no tiene por que
        # pagar ese error: se resuelve igual.
        parecidas = list(d.get("parecidas") or [])
        if parecidas:
            set_opciones_ofrecidas(
                parecidas + ["Particular"], siempre=True,
                titulo="Obras sociales", boton="Elegir cobertura",
            )
            return (
                f"'{d['consultada']}' no es exactamente el nombre de ninguna, pero "
                f"encontré {len(parecidas)} que se le parecen y ya se las estás "
                f"mostrando como lista tocable. Preguntale si alguna es la suya, en "
                f"UNA frase corta. NO las enumeres en el texto. "
                f"🚫 NO le digas todavía que no está cubierta ni le ofrezcas Particular: "
                f"lo más probable es que la escribió incompleta."
            )

        activas = list(d["activas"])
        if activas:
            set_opciones_ofrecidas(
                activas + ["Particular"], siempre=True,
                titulo="Obras sociales", boton="Ver cuáles atendemos",
            )
        return (
            f"NO CUBIERTA. La clínica no atiende '{d['consultada']}' ni nada parecido. "
            f"Decile con amabilidad que no trabajamos con esa y que su atención sería "
            f"PARTICULAR. Ya le estás mostrando la lista de las que sí se atienden: "
            f"invitalo a elegir una de ahí, o Particular si prefiere. "
            f"NO enumeres las obras sociales en el texto, la lista ya se las muestra. "
            f"Si acepta particular, usá obra_social='Particular'. "
            f"PROHIBIDO agendar con '{d['consultada']}'."
        )
    except Exception as e:
        return f"Error verificando la obra social: {e}"


# Frases con las que el paciente dice que su obra social no esta en la lista.
_NO_LA_VEO = (
    "no esta", "no está", "no la veo", "no aparece", "no la encuentro",
    "ninguna", "no figura", "no sale", "no es ninguna", "no estan",
)

# Elegir el escalon "tengo obra social" (boton o texto libre).
_ELIGIO_TIENE_OBRA = (
    "tengo obra social", "tenogo obra social", "si obra social", "sí obra social",
    "con obra social", "por obra social", "obra social si", "obra social sí",
    "si, obra social", "sí, obra social", "si tengo obra", "sí tengo obra",
)

_ELIGIO_PARTICULAR = (
    "particular", "sin obra social", "no tengo obra", "pago yo",
    "voy particular", "como particular", "atencion particular",
)


def _sin_acentos_txt(texto: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def _paciente_eligio_tiene_obra_social(texto: str = "") -> bool:
    """True si eligio el camino 'tengo obra social' (boton o frase)."""
    t = _sin_acentos_txt(texto or _ultimo_mensaje.get() or "")
    if not t.strip():
        return False
    # "no tengo obra social" es particular, no este camino.
    if "no tengo obra" in t or "sin obra" in t:
        return False
    if any(f in t for f in _ELIGIO_TIENE_OBRA):
        return True
    limpio = " ".join(t.split())
    return limpio in {"obra social", "obrasocial"}


def _paciente_eligio_particular(texto: str = "") -> bool:
    t = _sin_acentos_txt(texto or _ultimo_mensaje.get() or "")
    if not t.strip():
        return False
    # El boton se llama exactamente "Particular".
    if t.strip() == "particular":
        return True
    return any(f in t for f in _ELIGIO_PARTICULAR)


def _cobertura_registrada() -> str:
    return ((_estado_conversacion.get() or {}).get("obra_social") or "").strip()


def _registrar_cobertura(nombre: str) -> None:
    """Deja la cobertura en el estado sin pasar por el modelo.

    Charla real 21/09: el paciente escribio "Avalian", el bot dijo "ya tengo que
    tenes Avalian" y nunca la registro. Cuando la coincidencia es exacta no hay
    decision que tomar, asi que la toma el codigo.
    """
    estado = dict(_estado_conversacion.get() or {})
    estado["obra_social"] = (nombre or "").strip()
    estado.pop("cobertura_preguntada", None)
    _estado_conversacion.set(estado)


def _resolver_cobertura_dicha(texto: str) -> str | None:
    """Si `texto` es exactamente una obra social atendida, la registra y la devuelve."""
    busqueda = _texto_parece_busqueda(texto)
    if not busqueda:
        return None
    try:
        r = httpx.get(f"{API_BASE}/api/bot/obras-sociales",
                      params={"q": busqueda}, headers=HEADERS, timeout=15)
        r.raise_for_status()
        exacta = r.json().get("exacta")
    except Exception:
        return None
    if exacta:
        _registrar_cobertura(exacta)
    return exacta


def _exigir_cobertura(para: str) -> str | None:
    """Bloquea disponibilidad/agenda si todavia no hay cobertura en el estado.

    Caso real 21/09: pregunto dos veces la obra social y agendo igual como
    Particular por el default del parametro, sin que el paciente la eligiera.
    """
    if _cobertura_registrada():
        return None
    ultimo = _ultimo_mensaje.get() or ""
    if _paciente_eligio_particular(ultimo):
        return (
            f"❌ El paciente eligió Particular pero todavía no lo registraste. "
            f"Llamá `recordar_dato('obra_social', 'Particular')` y recién después "
            f"volvé a {para}."
        )
    if _paciente_eligio_tiene_obra_social(ultimo):
        return (
            f"❌ El paciente DIJO que tiene obra social, pero todavía no eligió "
            f"CUÁL. Llamá a `listar_obras_sociales()` ahora, esperá que elija, "
            f"registrala con `recordar_dato` y recién después {para}. "
            f"🚫 PROHIBIDO asumir Particular ni inventar un nombre."
        )
    # El paciente acaba de nombrar su obra social ("Avalian", "ospe"). Si es
    # exacta, se registra aca y se sigue; si es un fragmento, se lista. Lo que
    # NO se hace es volver a preguntarle si tiene obra social.
    if busqueda := _texto_parece_busqueda(ultimo):
        if _resolver_cobertura_dicha(ultimo):
            return None
        return (
            f"❌ El paciente escribió '{busqueda}' buscando su obra social. "
            f"Llamá a `listar_obras_sociales(busqueda='{busqueda}')` para que "
            f"elija cuál, y recién después {para}. "
            f"🚫 PROHIBIDO volver a preguntar si tiene obra social o es particular. "
            f"🚫 PROHIBIDO asumir Particular."
        )
    return (
        f"❌ Todavía no sabés la cobertura del paciente y de eso puede depender "
        f"el día (PAMI) y cómo queda el turno. "
        f"Si no preguntaste, llamá a `preguntar_cobertura()`. "
        f"Si ya dijo que tiene obra social, llamá a `listar_obras_sociales()`. "
        f"Si eligió Particular, `recordar_dato('obra_social', 'Particular')`. "
        f"🚫 PROHIBIDO {para} sin cobertura registrada. "
        f"🚫 PROHIBIDO asumir Particular."
    )


def preguntar_cobertura() -> str:
    """Le pregunta al paciente si tiene obra social o es particular.

    Va ANTES de mostrar ninguna lista. Dos botones que se tocan sin abrir nada:
    el que viene como particular resuelve en un toque y nunca ve los 45 nombres
    que no le sirven.

    Ademas convierte "Particular" en una eleccion explicita del paciente. Antes
    se asignaba en silencio por dos caminos —el default del parametro y el
    fallback cuando el nombre no matcheaba— sin que nadie lo decidiera.

    Barrera contra el loop de cobertura (15/09): el modelo llamaba a esta
    herramienta dos veces seguidas y el paciente recibia la MISMA pregunta
    textual aunque hubiera contestado otra cosa en el medio. Como la pregunta
    la arma la herramienta, la barrera va aca y no en el prompt: si la
    cobertura ya se conoce o ya se pregunto, la herramienta se niega y le dice
    al modelo como seguir.
    """
    estado = _estado_conversacion.get() or {}
    ultimo = _ultimo_mensaje.get() or ""

    # Quiere cambiar a obra social aunque la ficha diga Particular: limpiar y listar.
    if _paciente_eligio_tiene_obra_social(ultimo):
        if (estado.get("obra_social") or "").strip():
            estado = dict(estado)
            estado.pop("obra_social", None)
            _estado_conversacion.set(estado)
        return (
            "El paciente DIJO que tiene obra social. "
            "Llamá a `listar_obras_sociales()` YA para que elija cuál. "
            "🚫 PROHIBIDO volver a preguntar si tiene o no. "
            "🚫 PROHIBIDO asumir Particular ni consultar horarios sin la obra elegida."
        )

    if estado.get("obra_social"):
        return (
            f"✋ La cobertura ya se conoce: {estado['obra_social']}. "
            "NO se la preguntes de nuevo: seguí con el turno usando esa cobertura."
        )

    # Aunque todavia no haya marcado cobertura_preguntada, si el paciente ya
    # eligio Particular, no repreguntar: avanzar.
    if _paciente_eligio_particular(ultimo):
        return (
            "El paciente eligió Particular. Registrá obra_social='Particular' "
            "con `recordar_dato` y seguí con el turno. "
            "🚫 NO vuelvas a preguntar la cobertura."
        )

    if estado.get("cobertura_preguntada"):
        # Caso real 21/09: la barrera vieja mandaba a usar Particular
        # "provisorio" y el bot agendo sin obra social. Ya no.
        return (
            "✋ Ya le preguntaste si tiene obra social o es particular. "
            "🚫 PROHIBIDO repetir esa pregunta. "
            "Según lo que contestó: "
            "• tiene obra social / 'Tengo obra social' → `listar_obras_sociales()`; "
            "• Particular → `recordar_dato('obra_social', 'Particular')`; "
            "• otra cosa (fecha, horario, motivo) → anotala con `recordar_dato` "
            "y pedile de nuevo que elija cobertura (lista o Particular), sin "
            "repetir la misma frase. "
            "🚫 PROHIBIDO inventar Particular. "
            "🚫 PROHIBIDO `consultar_disponibilidad` / `agendar_turno` sin "
            "cobertura registrada con `recordar_dato`."
        )
    estado = dict(estado)
    estado["cobertura_preguntada"] = True
    _estado_conversacion.set(estado)
    set_opciones_ofrecidas(
        ["Tengo obra social", "Particular"], siempre=True, tipo="botones",
    )
    return (
        "Le estás mostrando dos botones: 'Tengo obra social' y 'Particular'. "
        "Preguntale en UNA frase corta cómo sería la atención. "
        "NO enumeres obras sociales todavía. "
        "Si elige Particular, registrá obra_social='Particular' con `recordar_dato` "
        "y seguí. Si elige que tiene obra social, llamá a `listar_obras_sociales`."
    )


def listar_obras_sociales(busqueda: str = "") -> str:
    """Muestra obras sociales como lista tocable, en dos escalones.

    Sin `busqueda` muestra las mas usadas. Con `busqueda` filtra entre las ~45.

    El escalonado importa por un detalle del mercado argentino: casi todas
    empiezan con "OS" (OSDE, OSEP, OSPE, OSPELSYM, OSPRERA, OSECAC...). En esta
    clinica hay 12 con ese prefijo, y una lista de WhatsApp admite 10 filas, asi
    que con dos letras el caso mas comun desborda. Por eso la respuesta depende
    de cuantas coincidencias haya, y nunca deja al paciente sin salida.
    """
    if not (busqueda or "").strip():
        # El modelo suele no reenviar lo que escribio el paciente.
        busqueda = _texto_parece_busqueda(_ultimo_mensaje.get())

    # Si está eligiendo obra social, Particular de la ficha no puede quedar
    # pegado: si no, `_exigir_cobertura` deja pasar y agenda sin la OS nueva.
    estado = dict(_estado_conversacion.get() or {})
    if (estado.get("obra_social") or "").strip().lower() == "particular":
        estado.pop("obra_social", None)
    estado["cobertura_preguntada"] = True
    _estado_conversacion.set(estado)

    try:
        r = httpx.get(f"{API_BASE}/api/bot/obras-sociales",
                      params={"q": busqueda} if busqueda else None,
                      headers=HEADERS, timeout=15)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return f"No pude traer la lista de obras sociales: {e}"

    activas = d.get("activas", [])
    total = d.get("total", 0)
    hay_mas = d.get("hay_mas", False)

    if not total:
        return ("La clínica no tiene obras sociales cargadas: la atención es PARTICULAR. "
                "Decíselo y seguí con el turno usando obra_social='Particular'.")

    # ── Coincidencia exacta: escribio el nombre o toco la lista ─────────────
    # No hay nada que confirmar ni que el modelo tenga que registrar.
    if busqueda and d.get("exacta"):
        _registrar_cobertura(d["exacta"])
        return (
            f"✅ Cobertura registrada: {d['exacta']}. Ya quedó guardada en el "
            f"estado (no llames a `recordar_dato` ni a `verificar_obra_social`). "
            f"Confirmásela en media frase y seguí con el turno: motivo si falta, "
            f"si no, horarios."
        )

    # ── Con búsqueda ────────────────────────────────────────────────────────
    if busqueda:
        if not activas:
            return (
                f"Ninguna de las {total} obras sociales que atiende la clínica empieza "
                f"como '{busqueda}'. Decile con amabilidad que no trabajamos con esa y "
                f"que su atención sería PARTICULAR, y preguntale si quiere avanzar así. "
                f"Si te dice que la escribió mal, pedile que te la escriba de nuevo."
            )

        if len(activas) == 1:
            # Una sola: se confirma de palabra, sin abrir ninguna lista.
            unica = activas[0]
            set_opciones_ofrecidas([unica, "No es esa"], siempre=True, tipo="botones")
            return (
                f"Hay una sola que coincide con '{busqueda}': {unica}. "
                f"Preguntale si es esa, en una frase corta. Le estás mostrando dos "
                f"botones para que confirme. Si dice que sí, registrala con "
                f"`recordar_dato` y seguí; no hace falta verificarla aparte."
            )

        set_opciones_ofrecidas(activas, siempre=True,
                               titulo="Obras sociales", boton="Elegir la mía")
        if hay_mas:
            return (
                f"Hay más de {len(activas)} que empiezan como '{busqueda}'. Le estás "
                f"mostrando las {len(activas)} más usadas como lista tocable. "
                f"Decile en UNA frase que elija la suya, y que si no la ve te escriba "
                f"UNA LETRA MÁS. NO las enumeres en el texto."
            )
        return (
            f"Le estás mostrando las {len(activas)} que coinciden con '{busqueda}', "
            f"como lista tocable. Pedile que elija la suya en UNA frase corta. "
            f"NO las enumeres en el texto. Lo que elija ya está verificado."
        )

    # ── Primer listado, sin búsqueda ────────────────────────────────────────
    set_opciones_ofrecidas(activas, siempre=True,
                           titulo="Obras sociales", boton="Elegir la mía")
    return (
        f"Le estás mostrando las {len(activas)} obras sociales más usadas, como lista "
        f"tocable. La clínica atiende {total} en total, así que la suya puede no estar. "
        f"Decile en UNA frase corta que elija la suya de la lista, y que si NO la ve "
        f"escriba las PRIMERAS LETRAS de la suya. NO las enumeres en el texto. "
        f"Cuando te pase esas letras, volvé a llamar a esta herramienta con `busqueda`. "
        f"Lo que elija de la lista ya está verificado: NO llames a verificar_obra_social."
    )

# ── Tool registry ────────────────────────────────────────────────────────────

def quien_me_escribe() -> str:
    """Ficha del paciente que esta escribiendo, segun su numero de WhatsApp.

    Evita tratarlo como un desconocido: el sistema ya sabe su nombre, su obra
    social, quien lo atendio la ultima vez y si tiene un turno proximo. Todo
    eso estaba en la base y no se estaba usando.
    """
    try:
        r = httpx.post(f"{API_BASE}/api/bot/identificar",
                       json={"requester_phone": _current_requester_phone()},
                       headers=HEADERS, timeout=15)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return f"No pude consultar la ficha: {e}"

    if d["encontrados"] == 0:
        return ("PACIENTE NUEVO: este número no está registrado. Pedile nombre, "
                "apellido y DNI recién cuando vayas a agendar, no antes.")

    # Sembrar la cobertura de la ficha en el estado: si no, el modelo saluda
    # "registrado como particular" y dos mensajes después vuelve a preguntar
    # obra social / particular (caso real 21/09).
    estado = dict(_estado_conversacion.get() or {})
    if not (estado.get("obra_social") or "").strip():
        os_ficha = (d["pacientes"][0].get("obra_social") or "").strip()
        if os_ficha:
            estado["obra_social"] = os_ficha
            _estado_conversacion.set(estado)

    partes = []
    for p_ in d["pacientes"]:
        linea = [f"{p_['nombre_completo']} (obra social: {p_['obra_social']})"]
        if p_.get("proximo_turno"):
            t = p_["proximo_turno"]
            linea.append(
                f"YA TIENE UN TURNO: {t['fecha']}"
                + (f" con {t['profesional']}" if t.get("profesional") else "")
                + (f" para {t['motivo']}" if t.get("motivo") else "")
            )
        if p_.get("ultimo_profesional"):
            ultima = f"la última vez lo atendió {p_['ultimo_profesional']}"
            if p_.get("ultima_visita"):
                ultima += f" el {p_['ultima_visita']}"
            if p_.get("ultimo_motivo"):
                ultima += f", por {p_['ultimo_motivo']}"
            linea.append(ultima)
        previas = [c for c in (p_.get("consultas_previas") or []) if c.get("motivo")]
        if len(previas) > 1:
            linea.append("antes vino por: " + ", ".join(
                f"{c['motivo']} ({c['fecha']})" for c in previas[1:]
            ))
        if p_.get("tratamientos_pendientes"):
            linea.append("tratamientos en curso: " + ", ".join(p_["tratamientos_pendientes"]))
        if p_.get("franja_preferida"):
            linea.append(f"suele venir a la {p_['franja_preferida']}")
        if p_.get("es_paciente_nuevo"):
            linea.append("nunca vino todavía (está en el sistema pero sin visitas)")
        partes.append(" | ".join(linea))

    encabezado = (
        "PACIENTE CONOCIDO. Saludalo por su nombre y NO le preguntes la obra social: "
        "ya la sabés. Si tiene un turno próximo, mencionalo antes de ofrecerle otro.\n"
        "USÁ SU HISTORIA: si sabés por qué vino la última vez o qué tratamiento tiene "
        "en curso, mencionalo con naturalidad ('¿seguimos con el conducto?', "
        "'¿otra limpieza como la de marzo?'). Es la diferencia entre un asistente "
        "que lo conoce y un formulario. PROHIBIDO inventar: si acá no dice el motivo, "
        "no te lo imagines.\n"
    )
    return encabezado + "\n".join(f"- {x}" for x in partes)


# ── Estado de la conversacion ────────────────────────────────────────────────
# El flujo vivia solo en el prompt: el modelo tenia que releer el historial en
# cada mensaje y deducir en que paso estaba. De ahi salian las re-preguntas y
# los mensajes seguidos que se contradicen. Ahora los datos que se van
# juntando quedan guardados, y el codigo puede decir con certeza que falta.

DATOS_DEL_TURNO = ("obra_social", "motivo", "fecha_hora", "paciente")


def recordar_dato(campo: str, valor: str) -> str:
    """Guarda un dato que el paciente ya dio, para no volver a preguntarlo.

    Se llama apenas el paciente lo menciona, aunque sea de pasada y fuera de
    orden: "turno para mi mama, ya hicimos el tramite del PAMI" deja registrada
    la obra social antes de que el bot la pregunte.
    """
    campo = (campo or "").strip().lower()
    if campo not in DATOS_DEL_TURNO:
        return f"❌ Campo desconocido: {campo}. Válidos: {', '.join(DATOS_DEL_TURNO)}"
    if not (valor or "").strip():
        return f"❌ Falta el valor para {campo}"

    # El motivo define la duracion del turno y a que profesional va, asi que no
    # puede salir de una deduccion: tiene que haberlo dicho el paciente.
    if campo == "motivo":
        lo_dijo, normalizado, razon = _motivo_dicho_por_el_paciente(valor)
        if not lo_dijo:
            if razon:
                # La pregunta de conducto va con dos botones: una respuesta
                # de un toque en vez de texto libre que despues hay que
                # interpretar. El texto del boton se resuelve por codigo.
                if "conducto" in razon.lower() and "30" in razon:
                    from backend.services.appointment_service import (
                        BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO,
                    )
                    set_opciones_ofrecidas(
                        [BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO],
                        siempre=True, tipo="botones",
                    )
                    razon += (
                        " Le estás mostrando dos botones (Consulta 30 min / "
                        "Tratamiento 1 hora): hacé la pregunta en UNA frase corta."
                    )
                return f"❌ {razon}"
            return (
                f"❌ El paciente nunca dijo '{valor}'. No lo deduzcas: preguntale "
                f"explícitamente para qué sería la consulta y esperá su respuesta. "
                f"De eso dependen la duración del turno y qué profesional lo atiende."
            )
        valor = normalizado

    estado = dict(_estado_conversacion.get() or {})
    estado[campo] = valor.strip()
    _estado_conversacion.set(estado)

    faltan = [c for c in DATOS_DEL_TURNO if not estado.get(c)]
    if faltan:
        return f"✅ Anotado {campo}='{valor.strip()}'. Todavía falta: {', '.join(faltan)}."
    return f"✅ Anotado {campo}='{valor.strip()}'. Ya tenés todos los datos para agendar."


_estado_conversacion: contextvars.ContextVar = contextvars.ContextVar("estado_conv", default=None)


def motivo_por_boton_conducto(texto: str) -> str | None:
    """El motivo que corresponde si el paciente toco un boton de conducto.

    Solo el texto exacto del boton: el texto libre ("consulta", "una hora")
    lo interpreta el backend en resolver-motivo, con el contexto de la charla.
    """
    from backend.services.appointment_service import (
        BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO,
        MOTIVO_CONSULTA_CONDUCTO, MOTIVO_TRATAMIENTO_CONDUCTO,
    )
    t = " ".join((texto or "").strip().lower().split())
    if t == BOTON_TRATAMIENTO_CONDUCTO.lower():
        return MOTIVO_TRATAMIENTO_CONDUCTO
    if t == BOTON_CONSULTA_CONDUCTO.lower():
        return MOTIVO_CONSULTA_CONDUCTO
    return None


def _motivo_registrado() -> str:
    return ((_estado_conversacion.get() or {}).get("motivo") or "").strip()


def set_estado_conversacion(estado: dict | None):
    _estado_conversacion.set(dict(estado) if estado else {})


def get_estado_conversacion() -> dict:
    return dict(_estado_conversacion.get() or {})


def pregunta_por_lo_que_falta(estado: dict | None, dichos: list[str] | None = None,
                              ) -> tuple[str, dict | None] | None:
    """La pregunta determinística del primer dato que falta, con botones.

    La usan el rescate de loops (webhook) y el "sí" sin ejecutar (agente):
    cuando el modelo se traba redactando, el código sabe exactamente qué falta.
    Devuelve (texto, opciones) o None si no falta nada que se pueda preguntar así.
    """
    estado = estado or {}
    if not (estado.get("obra_social") or "").strip():
        return (
            "Para seguir necesito un dato: ¿tenés obra social o la atención sería particular?",
            {"opciones": ["Tengo obra social", "Particular"], "siempre": True, "tipo": "botones"},
        )
    if not (estado.get("motivo") or "").strip():
        junto = _sin_acentos_txt(" ".join(dichos or []))
        if any(p in junto for p in ("conducto", "endodoncia", "nervio")):
            from backend.services.appointment_service import (
                BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO,
            )
            return (
                "Para el conducto: ¿es una consulta (30 min, por ejemplo si venís "
                "derivado) o ya el tratamiento (1 hora)?",
                {"opciones": [BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO],
                 "siempre": True, "tipo": "botones"},
            )
        return (
            "¿Para qué sería la consulta? Por ejemplo: limpieza, control, "
            "extracción, conducto, ortodoncia.",
            None,
        )
    return None


def resumen_estado(estado: dict) -> str:
    """Texto para el prompt: que ya se sabe y que falta."""
    estado = estado or {}
    tenemos = {c: v for c, v in estado.items() if c in DATOS_DEL_TURNO and v}
    faltan = [c for c in DATOS_DEL_TURNO if not estado.get(c)]
    if not tenemos:
        return "Todavía no tenés ningún dato de este paciente en esta conversación."
    ya = "; ".join(f"{c}={v}" for c, v in tenemos.items())
    if faltan:
        return f"YA SABÉS: {ya}. TE FALTA: {', '.join(faltan)}. No vuelvas a preguntar lo que ya sabés."
    return f"YA SABÉS TODO: {ya}. Podés agendar."


def indicar_llamar_consultorio(motivo: str, resumen: str = "") -> str:
    """Indica al modelo que ofrezca llamar: no hay bandeja ni promesa de contacto.

    Solo para lo que el bot NO puede resolver (clínico, precios, identidad
    imposible, pedido explícito de persona). Turnos, disponibilidad y
    cancelaciones NO pasan por acá.
    """
    tel = telefono_consultorio()
    detalle = (resumen or motivo or "").strip()
    return (
        f"✅ Indicá llamar. Decile al paciente, en una o dos frases, que para "
        f"esto necesita hablar por teléfono con el consultorio al *{tel}*. "
        f"🚫 PROHIBIDO decir que dejaste la consulta anotada, que recepción lo "
        f"va a contactar o que lo van a llamar. No hay bandeja: solo el teléfono. "
        f"Motivo interno (no se lo leas): {detalle[:200]}"
    )


# Alias: flujos viejos / tests que todavía nombran la tool anterior.
def derivar_a_recepcion(motivo: str, resumen: str, datos_aportados: str = "") -> str:
    return indicar_llamar_consultorio(motivo, resumen or datos_aportados or "")


_TOOL_MAP = {
    "indicar_llamar_consultorio": indicar_llamar_consultorio,
    "derivar_a_recepcion": derivar_a_recepcion,
    "agendar_turno": agendar_turno,
    "cancelar_turno": cancelar_turno,
    "reprogramar_turno": reprogramar_turno,
    "consultar_mis_turnos": consultar_mis_turnos,
    "consultar_disponibilidad": consultar_disponibilidad,
    "verificar_obra_social": verificar_obra_social,
    "listar_obras_sociales": listar_obras_sociales,
    "preguntar_cobertura": preguntar_cobertura,
    "recordar_dato": recordar_dato,
    "quien_me_escribe": quien_me_escribe,
}


def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool by name with the given arguments."""
    func = _TOOL_MAP.get(name)
    if not func:
        return f"❌ Tool desconocida: {name}"
    try:
        return func(**arguments)
    except TypeError as e:
        return f"❌ Argumentos incorrectos para {name}: {e}"
    except Exception as e:
        return f"❌ Error ejecutando {name}: {e}"


# ── OpenAI Function Definitions (JSON Schema) ────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "quien_me_escribe",
            "description": (
                "Ficha del paciente que está escribiendo: nombre, obra social, si ya tiene "
                "un turno, quién lo atendió la última vez y sus tratamientos en curso. "
                "LLAMALA SIEMPRE al principio de una conversación nueva, ANTES de preguntar "
                "nada. Evita pedirle datos que el sistema ya tiene."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recordar_dato",
            "description": (
                "Guarda un dato que el paciente YA dijo, para no volver a preguntárselo. "
                "Llamala APENAS el paciente menciona algo, aunque sea de pasada y fuera de orden. "
                "Ejemplo: si dice 'turno para mi mamá, ya hicimos el trámite del PAMI', "
                "guardá obra_social='PAMI' en ese mismo momento."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "campo": {
                        "type": "string",
                        "enum": ["obra_social", "motivo", "fecha_hora", "paciente"],
                        "description": "Qué dato es.",
                    },
                    "valor": {
                        "type": "string",
                        "description": "El dato, tal como lo dijo el paciente.",
                    },
                },
                "required": ["campo", "valor"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "agendar_turno",
            "description": "Agenda un nuevo turno en el sistema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Nombre del paciente"},
                    "patient_last_name": {"type": "string", "description": "Apellido del paciente"},
                    "dni": {
                        "type": "string",
                        "description": "DNI del paciente. Normalmente va VACÍO: el sistema lo identifica por su número de WhatsApp. Completalo SOLO si el paciente te dio un DNI explícitamente (porque el sistema no reconoció el número, o para aclarar de quién se trata).",
                    },
                    "phone": {
                        "type": "string",
                        "description": "Teléfono con característica, 10 dígitos (ej: 2604844952). NO es el DNI.",
                    },
                    "reason": {"type": "string", "description": "Motivo de la consulta (ej: Limpieza, Extracción)"},
                    "preferred_date": {
                        "type": "string",
                        "description": "Fecha y hora EXACTA en formato 'YYYY-MM-DD HH:MM' (ej: '2026-06-18 09:30'). OBLIGATORIO.",
                    },
                    "location": {"type": "string", "description": "Sede. Dejar VACÍO: el consultorio tiene una sola y la resuelve el sistema."},
                    "insurance_name": {
                        "type": "string",
                        "description": "Obra Social (usar 'Particular' si no tiene)",
                        "default": "Particular",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duración: Consulta/Limpieza=15, Extracción/Ortodoncia/Consulta por conducto=30, Conducto (realizar)=60",
                        "default": 30,
                    },
                    "profesional": {
                        "type": "string",
                        "description": (
                            "Profesional que pidió el paciente, tal como lo nombró "
                            "(ej: 'Silvestro', 'Dra. Murad'). Dejar VACÍO si no pidió a "
                            "ninguno en particular. Si lo pidió, es OBLIGATORIO pasarlo: "
                            "sin esto el turno se le asigna a quien esté libre, que puede "
                            "no ser el que el paciente pidió."
                        ),
                    },
                    "preferencia_horaria": {
                        "type": "string",
                        "description": (
                            "Lo que el paciente pidió sobre día y hora, TAL COMO lo dijo "
                            "(ej: 'a la tarde, menos martes y jueves'). Se vuelve a "
                            "verificar al crear el turno: sin esto se puede agendar un "
                            "día que el paciente descartó."
                        ),
                    },
                },
                "required": ["reason", "preferred_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancelar_turno",
            "description": "Cancela un turno existente del paciente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dni": {"type": "string", "description": "DNI del paciente. Normalmente va VACÍO: el sistema lo identifica por su número de WhatsApp. Completalo SOLO si el paciente te dio un DNI explícitamente (porque el sistema no reconoció el número, o para aclarar de quién se trata)."},
                    "appointment_id": {
                        "type": "string",
                        "description": "ID del turno a cancelar (opcional, cancela el próximo si no se indica)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reprogramar_turno",
            "description": "Reprograma un turno existente a una nueva fecha.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dni": {"type": "string", "description": "DNI del paciente. Normalmente va VACÍO: el sistema lo identifica por su número de WhatsApp. Completalo SOLO si el paciente te dio un DNI explícitamente (porque el sistema no reconoció el número, o para aclarar de quién se trata)."},
                    "appointment_id": {"type": "string", "description": "ID del turno a reprogramar"},
                    "new_datetime": {
                        "type": "string",
                        "description": "Nueva fecha y hora en formato ISO (ej: 2026-03-25T10:00:00)",
                    },
                },
                "required": ["appointment_id", "new_datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "indicar_llamar_consultorio",
            "description": (
                "ÚNICA salida cuando el tema NO es de los que podés resolver "
                "(turnos, disponibilidad, cancelar, reprogramar, obras sociales). "
                "Usala SOLO si: pide hablar con una persona; no encontrás un turno "
                "que dice tener; no podés verificar quién es; dolor/prótesis/urgencia "
                "clínica; o falta un dato operativo que no tenés (precio, alias). "
                "🚫 NO la uses porque no haya turnos libres: eso sí lo resolviste. "
                "🚫 NUNCA prometas que recepción lo va a contactar ni que anotaste nada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {
                        "type": "string",
                        "enum": ["identidad", "pedido_de_persona", "clinico",
                                 "dato_faltante", "otro"],
                        "description": (
                            "identidad: no se pudo verificar quién escribe. "
                            "pedido_de_persona: pidió hablar con alguien. "
                            "clinico: dolor, molestia, urgencia. "
                            "dato_faltante: falta precio, alias u otro dato operativo."
                        ),
                    },
                    "resumen": {
                        "type": "string",
                        "description": "Qué necesita, en una o dos frases y con sus palabras.",
                    },
                },
                "required": ["motivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_mis_turnos",
            "description": "Consulta los turnos pendientes de un paciente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dni": {"type": "string", "description": "DNI del paciente. Normalmente va VACÍO: el sistema lo identifica por su número de WhatsApp. Completalo SOLO si el paciente te dio un DNI explícitamente (porque el sistema no reconoció el número, o para aclarar de quién se trata)."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_disponibilidad",
            "description": (
                "Consulta los horarios disponibles para una sede, especialidad y fecha. "
                "SOLO llamar cuando necesités buscar turnos nuevos. "
                "NO llamar si el paciente ya está eligiendo un horario de los que le ofreciste."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo_confirmado_por_paciente": {
                        "type": "string",
                        "description": (
                            "Motivo de la consulta dicho por el paciente (ej: Extracción, Limpieza). "
                            "PROHIBIDO adivinar; si no lo dijo, preguntale primero."
                        ),
                    },
                    "location": {"type": "string", "description": "Sede. Dejar VACÍO: el consultorio tiene una sola y la resuelve el sistema."},
                    "date": {
                        "type": "string",
                        "description": "Fecha opcional (YYYY-MM-DD). Si se omite, busca para hoy.",
                    },
                    "obra_social": {
                        "type": "string",
                        "description": "Obra social del paciente (ej: Particular, PAMI, OSDE)",
                        "default": "Particular",
                    },
                    "preferencia_horaria": {
                        "type": "string",
                        "description": (
                            "Franja u hora que pidió el paciente, tal como la dijo. "
                            "Ejemplos: 'mañana', 'tarde', '18:45' (para 'después de las 18:45'), "
                            "'antes de las 11'. Dejar vacío si no expresó ninguna preferencia. "
                            "SIEMPRE pasarlo si el paciente mencionó un horario: sin esto se le "
                            "ofrecen horarios que no le sirven."
                        ),
                    },
                    "profesional": {
                        "type": "string",
                        "description": (
                            "Profesional que pidió el paciente, tal como lo nombró "
                            "(ej: 'Silvestro', 'la Dra. Murad'). Dejar vacío si no pidió a "
                            "ninguno. PROHIBIDO decir que unos horarios son de un profesional "
                            "sin haberlo pasado acá: cada uno atiende días distintos."
                        ),
                    },
                },
                "required": ["motivo_confirmado_por_paciente"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preguntar_cobertura",
            "description": (
                "Le muestra al paciente dos botones: 'Tengo obra social' y "
                "'Particular'. USALA ANTES de mostrar ninguna lista de obras "
                "sociales, apenas haya que hablar de cobertura. El que viene como "
                "particular resuelve en un toque y no ve 45 nombres que no le "
                "sirven, y 'Particular' pasa a ser una elección suya y no una "
                "suposición del sistema."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_obras_sociales",
            "description": (
                "Segundo escalón de cobertura: lista tocable de obras sociales. "
                "USALA DESPUÉS de `preguntar_cobertura`, cuando el paciente eligió "
                "'Tengo obra social' (o escribió las primeras letras). NO la uses "
                "como primer paso ni para pedirle que escriba el nombre completo. "
                "Sin `busqueda` muestra las más frecuentes; si dice que la suya no "
                "está, pedile las primeras letras y volvé a llamarla con `busqueda`. "
                "Lo que elija de la lista ya está verificado."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "busqueda": {
                        "type": "string",
                        "description": (
                            "Las letras o el nombre que dijo el paciente, tal cual. "
                            "Dejar vacío la primera vez, para mostrarle las frecuentes."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verificar_obra_social",
            "description": (
                "Verifica si la clínica atiende una obra social. "
                "USAR SIEMPRE apenas el paciente menciona su obra social, antes de seguir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "obra_social": {
                        "type": "string",
                        "description": "Nombre de la obra social tal como lo dijo el paciente (ej: OSDE, PAMI)",
                    },
                },
                "required": ["obra_social"],
            },
        },
    },
]
