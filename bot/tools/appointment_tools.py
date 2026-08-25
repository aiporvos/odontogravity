"""DentiBot tools - communicate with the backend API (OpenAI function calling)."""
import os
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
    """(salio del paciente, nombre normalizado) para el motivo propuesto.

    El modelo puede llamar a recordar_dato con un valor que nunca le dijeron
    —dedujo "control" porque le parecio razonable— y eso alcanzaba para
    saltearse la exigencia de preguntar. Pedido del consultorio: "de eso nunca
    suponer, sino averiguar siempre primero que se va a tratar".

    La comparacion la hace el backend contra los tipos de consulta y sus
    sinonimos, no una busqueda literal: el paciente dice "sacarme una muela" y
    el modelo lo registra como "Extraccion", que es exactamente lo que
    corresponde. De paso vuelve el nombre canonico, asi el turno queda guardado
    con el mismo texto siempre.
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
        return True, valor
    return bool(d.get("ok")), (d.get("motivo") or valor)


# Palabras que son respuestas de conversacion, no el nombre de una obra social.
_NO_ES_BUSQUEDA = {
    "si", "no", "ok", "dale", "hola", "gracias", "bueno", "listo", "particular",
    "obra", "social", "obrasocial", "dime", "cual", "cuales", "otra", "otro",
    "dale si", "no la veo", "no esta", "dale gracias",
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


def _parece_nombre_de_obra_social(texto: str) -> bool:
    """Si eso puede ser el nombre de una obra social, y no otra cosa.

    Se descarta lo que es claramente una intencion ("agendar un turno"), un
    saludo o una pregunta. Ante la duda se acepta: hay obras sociales con
    nombres rarisimos y es peor rechazar la verdadera que dejar pasar una
    consulta que despues no matchea con ninguna.
    """
    limpio = _sin_tildes_simple(texto).strip()
    if not limpio:
        return False
    if "?" in limpio or "¿" in limpio:
        return False
    palabras = [p for p in limpio.replace("/", " ").split() if p.isalnum() or p.isalpha()]
    if not palabras:
        return False
    # Si TODAS son palabras de intencion o de relleno, no es una obra social.
    relleno = _PALABRAS_DE_INTENCION | _NO_ES_BUSQUEDA | {
        "un", "una", "unos", "unas", "el", "la", "los", "las", "de", "del",
        "para", "por", "me", "mi", "mis", "tu", "tus", "su", "sus", "con",
        "que", "y", "o", "en", "al", "lo", "es", "ser", "hay",
    }
    return any(p not in relleno for p in palabras)


def _sin_tildes_simple(texto: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def _texto_parece_busqueda(texto: str) -> str:
    """El fragmento que el paciente escribio buscando su obra social, o "".

    "sw", "swi", "ospe", "swiss medical" son busquedas. "si", "hola" o una frase
    larga, no.
    """
    limpio = " ".join((texto or "").strip().lower().split())
    if not limpio or limpio in _NO_ES_BUSQUEDA:
        return ""
    if len(limpio) > 30 or len(limpio.split()) > 3:
        return ""   # una frase, no el nombre de una obra social
    if not any(c.isalpha() for c in limpio):
        return ""
    if not _parece_nombre_de_obra_social(limpio):
        return ""   # "agendar", "quiero un turno": es la intencion, no la cobertura
    return limpio


# Opciones concretas que la ultima tool dejo sobre la mesa (ej: los horarios
# disponibles). El webhook las lee despues de que el modelo respondio y, si la
# respuesta efectivamente las esta ofreciendo, las manda como lista tocable en
# vez de texto. Mismo patron que _requester_phone: contextvar por conversacion.
_opciones_ofrecidas: contextvars.ContextVar = contextvars.ContextVar("opciones_ofrecidas", default=None)


def set_opciones_ofrecidas(opciones, siempre: bool = False,
                           titulo: str | None = None, boton: str | None = None):
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
        } if opciones else None
    )


def tomar_opciones_ofrecidas():
    """Devuelve las opciones pendientes y las limpia (se consumen una sola vez)."""
    ops = _opciones_ofrecidas.get()
    _opciones_ofrecidas.set(None)
    return ops


# ── Tool implementations ─────────────────────────────────────────────────────

def agendar_turno(
    reason: str,
    preferred_date: str,
    patient_name: str = "",
    patient_last_name: str = "",
    dni: str = "",
    phone: str = "",
    location: str = "San Rafael",
    insurance_name: str = "Particular",
    duration_minutes: int = 30,
) -> str:
    """Agenda un nuevo turno en el sistema."""
    payload = {
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


def consultar_mis_turnos(dni: str = "") -> str:
    """Consulta los turnos pendientes de un paciente."""
    try:
        payload = {"dni": dni or None, "requester_phone": _current_requester_phone()}
        r = httpx.post(f"{API_BASE}/api/bot/my-appointments", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data["appointments"]:
            return f"ℹ️ {data['patient']}, no tenés turnos pendientes."
        lines = [f"📋 Turnos de {data['patient']}:"]
        for a in data["appointments"]:
            lines.append(f"  • {a['date']} - {a['reason']} con {a['professional']} en {a['location']} ({a['status']})")
        return "\n".join(lines)
    except httpx.HTTPStatusError as e:
        return f"❌ {e.response.json().get('detail', 'Paciente no encontrado')}"
    except Exception as e:
        return f"❌ Error: {str(e)}"


def consultar_disponibilidad(
    motivo_confirmado_por_paciente: str,
    location: str = "San Rafael",
    date: str = "",
    obra_social: str = "Particular",
    preferencia_horaria: str = "",
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
    if not (_estado_conversacion.get() or {}).get("motivo"):
        return (
            "❌ Todavía no sabés para qué es la consulta, y de eso depende cuánto "
            "dura el turno. Preguntale al paciente el motivo (limpieza, control, "
            "extracción, conducto...), registralo con `recordar_dato` y recién "
            "después volvé a llamar a esta herramienta. "
            "🚫 PROHIBIDO deducirlo o darlo por supuesto."
        )

    try:
        payload = {
            "location": location,
            "reason": motivo_confirmado_por_paciente,
            "date": date,
            "obra_social": obra_social,
            "preferencia_horaria": preferencia_horaria or None,
        }
        r = httpx.post(f"{API_BASE}/api/bot/availability", json=payload, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        slots = data.get("available_slots", [])
        date_iso = data.get("date", "")
        fecha_texto = data.get("fecha_texto") or date_iso
        if not slots:
            return (
                f"No hay turnos disponibles en {location} en las próximas dos semanas. "
                f"Decíselo al paciente y ofrecele que deje sus datos para que lo contacten."
            )

        # Se publican para que el webhook pueda ofrecerlos como lista tocable.
        set_opciones_ofrecidas(slots)

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

        return (
            f"{aviso}"
            f"[FECHA GARANTIZADA FUTURA: {date_iso} = {fecha_texto}] "
            f"Turnos disponibles en {location} para el {fecha_texto}: {', '.join(slots)}. "
            f"Al escribirle al paciente usá EXACTAMENTE '{fecha_texto}'. PROHIBIDO calcular vos "
            f"el día de la semana. Cuando elija un horario, combiná {date_iso} con ese horario "
            f"para formar preferred_date en formato YYYY-MM-DD HH:MM. "
            f"NO llames a esta herramienta de nuevo."
        )
    except Exception as e:
        return f"Error consultando disponibilidad: {e}"


def verificar_obra_social(obra_social: str) -> str:
    """Verifica si la clínica atiende una obra social."""
    # Antes de nada: ¿eso puede ser el nombre de una obra social? El paciente
    # escribe "agendar" y el bot le contestaba "no trabajamos con 'agendar'
    # como obra social", una y otra vez. Es lo primero que escribe cualquiera.
    if not _parece_nombre_de_obra_social(obra_social):
        return (
            f"⚠️ '{obra_social}' NO es el nombre de una obra social: es lo que el "
            f"paciente quiere hacer, o un saludo. 🚫 PROHIBIDO contestarle que no "
            f"trabajamos con esa cobertura, no tiene ningún sentido y queda pésimo. "
            f"Seguí la conversación normalmente: si pidió un turno, avanzá con el "
            f"flujo y recién cuando corresponda preguntale la obra social con "
            f"`listar_obras_sociales`."
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
            return (
                f"CUBIERTA. La clínica atiende {d['nombre']}. "
                f"Seguí normalmente con el turno usando obra_social='{d['nombre']}'."
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


def listar_obras_sociales(busqueda: str = "") -> str:
    """Le muestra al paciente obras sociales como lista tocable.

    Escribir el nombre a mano es la peor forma de preguntar esto: los nombres
    son largos, se abrevian de mil maneras y se escriben mal ("ospeysin" por
    OSPELSYM), asi que el paciente termina sin cobertura por un error de tipeo.

    La clinica tiene ~45 cargadas y una lista de WhatsApp admite 10 filas, asi
    que sin `busqueda` se muestran las mas usadas y con `busqueda` se filtra.

    Si el modelo no pasa `busqueda` pero el paciente acaba de escribir algo que
    parece el nombre de una obra social, se usa eso. Sin esto el paciente
    escribia "sw", el modelo llamaba a la herramienta sin parametros y le
    aparecia la misma lista otra vez, como si no lo hubiera leido.
    """
    if not (busqueda or "").strip():
        busqueda = _texto_parece_busqueda(_ultimo_mensaje.get())

    try:
        r = httpx.get(f"{API_BASE}/api/bot/obras-sociales",
                      params={"q": busqueda} if busqueda else None,
                      headers=HEADERS, timeout=15)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return f"No pude traer la lista de obras sociales: {e}"

    activas, total = d.get("activas", []), d.get("total", 0)

    if not total:
        return ("La clínica no tiene obras sociales cargadas: la atención es PARTICULAR. "
                "Decíselo y seguí con el turno usando obra_social='Particular'.")

    if busqueda and not activas:
        return (
            f"Ninguna de las {total} obras sociales que atiende la clínica se parece a "
            f"'{busqueda}'. Decile con amabilidad que no trabajamos con esa y que su "
            f"atención sería PARTICULAR. Si te dice que la escribió mal, pedile que te "
            f"pase las primeras letras y volvé a llamar a esta herramienta."
        )

    set_opciones_ofrecidas(
        activas + ["Particular"], siempre=True,
        titulo="Obras sociales", boton="Elegir cobertura",
    )

    if busqueda:
        return (
            f"Le estás mostrando {len(activas)} coincidencia(s) con '{busqueda}', más "
            f"'Particular', como lista tocable. Pedile que elija la suya en UNA frase "
            f"corta y NO las enumeres en el texto. Si ninguna es la suya, que te pase "
            f"otras letras y volvés a buscar. Lo que elija de la lista ya está "
            f"verificado: NO llames a verificar_obra_social."
        )

    return (
        f"Le estás mostrando como lista tocable las obras sociales más frecuentes, más "
        f"'Particular'. La clínica atiende {total} en total, así que la suya puede no "
        f"estar ahí: decile en UNA frase corta que elija de la lista o que te escriba "
        f"las primeras letras de la suya si no la ve. NO las enumeres en el texto. "
        f"Cuando te pase esas letras, volvé a llamar a esta herramienta con el "
        f"parámetro `busqueda`. Lo que elija de la lista ya está verificado: NO llames "
        f"a verificar_obra_social."
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
        lo_dijo, normalizado = _motivo_dicho_por_el_paciente(valor)
        if not lo_dijo:
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


def set_estado_conversacion(estado: dict | None):
    _estado_conversacion.set(dict(estado) if estado else {})


def get_estado_conversacion() -> dict:
    return dict(_estado_conversacion.get() or {})


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


_TOOL_MAP = {
    "agendar_turno": agendar_turno,
    "cancelar_turno": cancelar_turno,
    "reprogramar_turno": reprogramar_turno,
    "consultar_mis_turnos": consultar_mis_turnos,
    "consultar_disponibilidad": consultar_disponibilidad,
    "verificar_obra_social": verificar_obra_social,
    "listar_obras_sociales": listar_obras_sociales,
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
                    "location": {"type": "string", "description": "Sede (por defecto 'San Rafael')", "default": "San Rafael"},
                    "insurance_name": {
                        "type": "string",
                        "description": "Obra Social (usar 'Particular' si no tiene)",
                        "default": "Particular",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duración: Consulta/Limpieza=15, Extracción/Ortodoncia=30, Endodoncia=60",
                        "default": 30,
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
                    "location": {"type": "string", "description": "Sede (por defecto 'San Rafael')", "default": "San Rafael"},
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
                },
                "required": ["motivo_confirmado_por_paciente"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listar_obras_sociales",
            "description": (
                "Le muestra al paciente obras sociales como lista tocable. USALA EN "
                "CUANTO haya que hablar de cobertura, en lugar de pedirle que la "
                "escriba: los nombres se escriben mal y el paciente termina sin "
                "cobertura por un error de tipeo. Sin `busqueda` muestra las más "
                "frecuentes; si el paciente dice que la suya no está, pedile las "
                "primeras letras y volvé a llamarla pasándolas en `busqueda`. "
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
