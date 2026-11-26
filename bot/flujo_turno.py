"""Sacar turno: guion fijo por código, la IA solo entiende lo que escribe el paciente.

Por qué existe (16/11/2026). Hasta acá el modelo decidía en cada mensaje qué
preguntar, cuándo buscar y cuándo agendar, guiado por un prompt de ~40 reglas.
Cada prueba real encontraba otro desvío: "mío" tomado como obra social, la
lista de horarios repetida después de elegir, la consulta de conducto sin
verificar, un domingo nombrado sin que nadie lo pidiera.

Ahora el orden lo pone el código y no se saltea nunca:

    1. qué necesita (motivo)         → validado contra los tipos de consulta
    2. para quién es                 → titular del número u otra persona
    3. obra social o particular      → botones, lista y búsqueda por letras
    4. profesional                   → lo decide el backend por práctica y día
    5. día y horario                 → solo horarios reales de la agenda
    6. alta del turno y confirmación

El paciente puede decir todo junto y en cualquier orden ("quiero sacarme una
muela el lunes, es para mi mamá Ana Pérez, tiene PAMI"): la IA extrae los
datos de ESE mensaje (JSON estricto) y el código solo pregunta lo que falta.

Cancelar y consultar turnos siguen en el agente general (`ai_agent.chat`).

Pedido unificado del 24/11/2026 (chats reales de Silprodent):

    - Orden: obra social/particular → para qué → especialista → próximo libre.
      Con varias fichas en el número se pregunta antes para quién es, porque
      de eso depende qué obra social mirar.
    - "Ya tenía turno" / cambiar uno: se pregunta el día, se asocia si hay uno
      claro y si no, a llamar (nunca un turno duplicado).
    - Trámites (firmar la historia clínica, retirar la prótesis, traer la
      orden) no son turno: se pasa por el consultorio en horario.
    - Prótesis SÍ es turno: el tipo "Prótesis" del panel define duración y
      profesional (Dr. Silvestro, 30 min).
    - Sin cupo: se ofrece otro día, particular o llamar; nunca el mismo texto.
    - Si la secretaria atendió el chat hace poco, el bot no pisa esa gestión.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata

import httpx

from bot.tools.appointment_tools import (
    API_BASE, HEADERS, set_opciones_ofrecidas, tomar_opciones_ofrecidas,
    telefono_consultorio,
)

logger = logging.getLogger(__name__)

CLAVE = "turno"              # sub-diccionario del estado de la conversación
ACTIVO = True                # los tests del agente general lo apagan (conftest)

BOTON_PARA_MI = "Para mí"
BOTON_OTRA_PERSONA = "Para otra persona"
BOTON_TENGO_OS = "Tengo obra social"
BOTON_PARTICULAR = "Particular"
BOTON_OTRO_DIA = "Otro día"
BOTON_SI = "Sí"
BOTON_CAMBIO = "Cambió"
BOTON_LLAMAR = "Llamar"
BOTON_PRIMERA = "1ª consulta"
BOTON_SEGUNDA = "2ª consulta o más"
BOTON_CONFIRMO = "Lo confirmo"
BOTON_CAMBIAR = "Quiero cambiarlo"
BOTON_CANCELAR_SI = "Sí, cancelarlo"
BOTON_NO = "No"
BOTON_MAS = "Más horarios"

# Gente mayor no se da cuenta de que la lista se toca (pedido de Claudio 25/11).
_COMO_ELEGIR = ""   # la explicación la arma _como_elegir(t) con los horarios reales


def _botones_horarios(t: dict):
    """Botones a la vista (no una lista que hay que abrir): los dos horarios
    más cercanos y "Más horarios"; al final, "Otro día". Pedido de Claudio
    25/11: la gente mayor no abre la lista "Elegir horario"."""
    o = t.get("oferta") or {}
    slots = o.get("slots") or []
    pag = t.get("pagina", 0)
    if pag * 2 >= len(slots):
        pag = t["pagina"] = 0
    # La lista completa va numerada en el texto; los botones son un atajo.
    set_opciones_ofrecidas(slots[:2] + [BOTON_OTRO_DIA], siempre=True, tipo="botones")


def _pocos_o_elegir(t: dict) -> str:
    """Con uno o dos horarios se dice cuáles son, sin "elegí de la lista"."""
    o = t["oferta"]
    slots = o.get("slots") or []
    if 0 < len(slots) <= 2:
        cuales = " y ".join(f"*{h}*" for h in slots)
        return (f"Ese día ({o['fecha_texto']}, con {o['profesional']}) solo me queda {cuales}. "
                f"Si no te sirve, tocá *Otro día* y te busco la fecha siguiente 👇")
    return (f"Para el *{o['fecha_texto']}* con {o['profesional']}." + _como_elegir(t))


_NUMEROS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]


def _como_elegir(t: dict) -> str:
    """Lista numerada, toda a la vista: lo más claro para gente mayor (Claudio
    25/11). WhatsApp no deja mostrar una lista ya desplegada."""
    slots = (t.get("oferta") or {}).get("slots") or []
    if not slots:
        return ""
    filas = "\n".join(f"{_NUMEROS[i]} {h}" for i, h in enumerate(slots[:9]))
    return (f" Horarios libres:\n\n{filas}\n\n✍️ Respondé con el *número* (por ejemplo *1*), o tocá "
            f"un botón. Si ninguno te sirve, tocá *Otro día*.")

CLAVE_PREVIO = "turno_previo"   # "ya tenía turno": buscar y asociar el existente

# "la doctora", "el dentista": no nombran a nadie. El profesional lo decide la
# práctica (ortodoncia → Dra. Murad); buscarlo por nombre terminaba en "no
# encuentro a ese profesional" (chat real 24/11).
_PROFESIONAL_GENERICO = {
    "la doctora", "doctora", "la dra", "dra", "el doctor", "doctor", "el dr", "dr",
    "la odontologa", "el odontologo", "la dentista", "el dentista", "la doc", "el doc",
}

# Trámites que se hacen pasando por el consultorio, sin reservar sillón (caso
# real del 24/11: el bot buscaba "turno de prótesis" para firmar la historia clínica).
_TRAMITES = [
    (re.compile(r"\bfirm\w*\b.{0,40}\b(historia|hc|planilla|papel\w*|ficha|consentimiento)\b"
                r"|\b(historia clinica|hc)\b.{0,30}\bfirm\w*|\b(venir|ir|pasar) a firmar\b"),
     "firmar la historia clínica"),
    (re.compile(r"\b(retir|busc|entreg)\w*\b.{0,30}\b(protesis|placa|dentadura)\b"),
     "retirar la prótesis"),
    (re.compile(r"\b(llev|traer|traig|entreg|dej)\w*\b.{0,30}\b(orden|autorizacion|bono)\w*\b"),
     "traer la orden o la autorización"),
    (re.compile(r"\bpasar por (el )?consultorio\b"), "eso"),
]

_PARTICULAR = re.compile(
    r"\b(particular|sin (la )?obra social|sin os|sin cobertura|no tengo (obra social|os|cobertura)"
    r"|no uso (la )?obra social|lo pago yo|pago yo|lo abono)\b")

_YA_TENIA = re.compile(
    r"\bya (tenia|tengo|habia sacado|saque|me dieron)( un)? turno\b"
    r"|\bmi turno (del|de el|es el|era el|para el|era)\b"
    r"|\btengo( un)? turno (el|para el|del|de el)\b")

_DESPEDIDA = re.compile(r"\b(gracias|grax|chau|saludos|nos vemos|hasta (luego|mañana|el)"
                        r"|buen(a|as|os) (noche|noches|tarde|tardes|dia|dias))\b")
# Preguntas de información del consultorio (no del pedido en curso).
_PREGUNTA_INFO = re.compile(r"\b(donde|direccion|ubicad\w*|queda[n]?|horario de atencion|a que hora (abren|cierran)"
                            r"|abren|cierran|precio\w*|(cuanto|que) (sale|cuesta|cobran|vale)|sale (la|una) consulta|valor|costo|arancel\w*"
                            r"|estacionamiento|telefono)\b")
# Urgencia: se avisa que llame por un sobreturno, además de ofrecer el turno.
_URGENCIA = re.compile(r"\b(urgen\w*|hinchad\w*|hinchazon|sangr\w*|no aguanto|dolor (muy )?(intenso|fuerte)"
                       r"|me muero de dolor|insoportable|flemon|infecci\w*)\b")
# Rechazo / despedida mientras se le ofrece algo.
_RECHAZO = re.compile(r"\b(no gracias|no,? gracias|busco otro|buscar otro|otro lado|otro profesional"
                      r"|dejalo|dejá|no importa|olvidalo|me acerco|voy a pasar|paso por|presencial"
                      r"|personalmente|voy al consultorio|llamo yo|los llamo|voy a llamar)\b")
# "Para mí" tiene que estar dicho: la IA lo deducía de "quiero un turno" y el
# bot no preguntaba para quién era (prueba real 25/11).
_PARA_MI = re.compile(r"\b(para mi|para mi mismo|para mi misma|mio|mia|yo|soy yo|a mi nombre|me duele|me duelen"
                      r"|me quiero|me tengo|necesito sacarme|sacarme|hacerme|atenderme|me atiendan)\b")
_SALUDO = re.compile(r"^(hola|holi|buen dia|buenos dias|buenas)\b")
_PIDE_TURNO = re.compile(r"\b(quiero|necesito|queria|quisiera|me das|me da|pedir|sacar)\b.*\bturno\b")


def es_tramite(texto: str) -> str | None:
    """Qué trámite nombra el mensaje ("firmar la historia clínica"), o None."""
    n = _norm(texto)
    for patron, que in _TRAMITES:
        if patron.search(n):
            return que
    return None


def dice_particular(texto: str) -> bool:
    """"hacelo sin obra social", "particular", "lo pago yo" (chat real)."""
    return bool(_PARTICULAR.search(_norm(texto)))


def _texto_llamar() -> str:
    return (f"Para no hacerte perder tiempo, llamá al consultorio al "
            f"{telefono_consultorio()} y te lo resuelven enseguida 🙏")


# ── Utilidades ───────────────────────────────────────────────────────────────

def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if unicodedata.category(c) != "Mn").lower()
    return " ".join(re.sub(r"[^\w\s:]", " ", t).split())


def _es(texto: str, boton: str) -> bool:
    return _norm(texto) == _norm(boton)


def _post(ruta: str, payload: dict, timeout: int = 30) -> tuple[int, dict]:
    r = httpx.post(f"{API_BASE}{ruta}", json=payload, headers=HEADERS, timeout=timeout)
    try:
        cuerpo = r.json()
    except Exception:
        cuerpo = {"detail": r.text}
    return r.status_code, cuerpo


def _get(ruta: str, params: dict) -> dict:
    r = httpx.get(f"{API_BASE}{ruta}", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _saludo() -> str:
    from backend.services.appointment_service import get_clinic_now
    from bot.ai_agent import saludo_segun_hora
    return saludo_segun_hora(get_clinic_now().hour)[0]


_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_iso(dia_dicho: str) -> str:
    """"martes 24 de noviembre" es el 24, no el próximo martes: la fecha
    explícita manda sobre el día de la semana."""
    from backend.services.appointment_service import fecha_dicha_por_el_paciente, get_clinic_now
    n = _norm(dia_dicho)
    hoy = get_clinic_now().date()
    m = re.search(r"\b(\d{1,2}) de (" + "|".join(_MESES) + r")\b", n)
    if m:
        dia, mes = int(m.group(1)), _MESES.index(m.group(2)) + 1
    elif m := re.search(r"\b(\d{1,2})/(\d{1,2})\b", (dia_dicho or "").lower()):
        dia, mes = int(m.group(1)), int(m.group(2))
    else:
        dia = mes = None
    if dia and mes:
        from datetime import date
        try:
            f = date(hoy.year, mes, dia)
            if f < hoy:
                f = date(hoy.year + 1, mes, dia)
            return f.isoformat()
        except ValueError:
            pass
    try:
        f = fecha_dicha_por_el_paciente(dia_dicho or "")
        return f.isoformat() if f else ""
    except Exception:
        return ""


def _tipos_de_consulta() -> list[dict]:
    from backend.database import SessionLocal
    from backend.models.tipo_consulta import TipoConsulta
    db = SessionLocal()
    try:
        return [
            {"nombre": t.nombre, "sinonimos": t.sinonimos or ""}
            for t in db.query(TipoConsulta).filter(
                TipoConsulta.is_active == True,  # noqa: E712
                TipoConsulta.is_deleted == False,  # noqa: E712
            ).all()
        ]
    except Exception:
        return []
    finally:
        db.close()


# ── La IA: solo extrae lo que dice ESTE mensaje ─────────────────────────────

_ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intencion": {"type": "string", "enum": [
            "sacar_turno", "cancelar_turno", "reprogramar_turno", "ya_tengo_turno",
            "consultar_mis_turnos", "tramite_consultorio", "dar_datos", "pregunta",
            "saludo_o_cierre", "otro"]},
        "motivo": {"type": ["string", "null"]},
        "para_quien": {"type": ["string", "null"], "enum": ["yo", "otra_persona", None]},
        "nombre": {"type": ["string", "null"]},
        "apellido": {"type": ["string", "null"]},
        "cobertura": {"type": ["string", "null"], "enum": ["particular", "obra_social", None]},
        "obra_social": {"type": ["string", "null"]},
        "dia": {"type": ["string", "null"]},
        "preferencia_horaria": {"type": ["string", "null"]},
        "hora": {"type": ["string", "null"]},
        "profesional": {"type": ["string", "null"]},
        "pregunta": {"type": ["string", "null"]},
        "respuesta_si_no": {"type": ["string", "null"], "enum": ["si", "no", None]},
        "quiere_otro_dia": {"type": "boolean"},
    },
    "required": ["intencion", "motivo", "para_quien", "nombre", "apellido", "cobertura",
                 "obra_social", "dia", "preferencia_horaria", "hora", "profesional",
                 "pregunta", "respuesta_si_no", "quiere_otro_dia"],
}

_INSTRUCCIONES = """Sos el módulo que ENTIENDE los mensajes de pacientes de un consultorio odontológico argentino. No respondés al paciente: devolvés en JSON SOLO los datos que dice el ÚLTIMO mensaje. Lo que no dice va en null. Nunca inventes ni deduzcas datos que no están.

Contexto: la última pregunta del asistente fue: «{pregunta}». Interpretá el mensaje como respuesta a esa pregunta.

- intencion: sacar_turno si pide un turno; cancelar_turno / reprogramar_turno / consultar_mis_turnos si quiere eso con un turno que YA tiene; ya_tengo_turno si dice que ya tenía un turno o cita la fecha de uno que le dieron ("ya tenía turno", "mi turno del jueves 26"); tramite_consultorio si quiere firmar la historia clínica, traer una orden o autorización, o retirar una prótesis ya hecha (eso NO es sacar turno); dar_datos si responde lo que se le preguntó; pregunta si consulta algo del consultorio (dirección, precios, horarios, si atienden X); saludo_o_cierre; otro.
- motivo: el tipo de consulta que pide, elegido de esta lista (usá el nombre exacto): {tipos}. "sacarme una muela" = Extracción; "arreglo de una caries" = Arreglos; brackets, aparatos o "control de ortodoncia" = Ortodoncia (NUNCA Control); si el turno es para un niño o niña (menor de 14 años) = Odontopediatría, aunque diga control o dolor. Para conducto/endodoncia devolvé "Conducto". Prótesis, placa, dentadura o "quiero hacerme una prótesis" = Prótesis. Si dice un síntoma sin práctica clara ("me duele una muela") devolvé "Consulta" solo si existe; si no, null.
- para_quien: "yo" si el turno es para quien escribe ("para mí", "mío", "yo", "soy yo"); "otra_persona" si es para otro ("para mi hijo", "para mi mamá Ana"). nombre/apellido: de la persona que se atiende, solo si los dice.
- cobertura: "particular" o "obra_social" si lo dice. obra_social: el nombre o las letras que escribió si responde a qué obra social tiene ("osde", "swi", "pami").
- dia: la expresión de día tal cual la dijo ("el lunes", "mañana", "16/11", "un martes", "la semana que viene"). preferencia_horaria: "mañana", "tarde", "después de las 18", "temprano", etc.
- hora: si elige o nombra una hora, en HH:MM ("a las 5 de la tarde" = 17:00).
- profesional: si pide un profesional por nombre o apellido. "la doctora" o "el dentista" sin nombre = null.
- pregunta: si además hace una pregunta, la pregunta textual.
- respuesta_si_no: "si" o "no" si contesta afirmativa o negativamente a la última pregunta.
- quiere_otro_dia: true si rechaza el día u horarios ofrecidos o pide otra fecha ("no puedo el 20", "otro día", "necesito antes", "no me sirve"). Si además nombra el día que quiere, ponelo en dia.
Hoy es {hoy}."""


def extraer(mensaje: str, ultima_pregunta: str) -> dict:
    """Los datos que dice el mensaje, en JSON estricto. Ante una falla, vacío."""
    from backend.services.appointment_service import get_clinic_now
    from bot.ai_agent import _build_client
    vacio = {k: None for k in _ESQUEMA["properties"]}
    vacio["intencion"], vacio["quiere_otro_dia"] = "otro", False
    client, modelo = _build_client()
    if not client:
        return vacio
    tipos = ", ".join(t["nombre"] for t in _tipos_de_consulta()) or "(sin lista)"
    try:
        r = client.chat.completions.create(
            model=modelo,
            temperature=0,
            response_format={"type": "json_schema", "json_schema": {
                "name": "datos_del_mensaje", "strict": True, "schema": _ESQUEMA}},
            messages=[
                {"role": "system", "content": _INSTRUCCIONES.format(
                    pregunta=ultima_pregunta or "(conversación nueva)", tipos=tipos,
                    hoy=get_clinic_now().strftime("%A %d/%m/%Y"))},
                {"role": "user", "content": mensaje},
            ],
        )
        datos = json.loads(r.choices[0].message.content or "{}")
        return {**vacio, **datos}
    except Exception as e:
        logger.error("FLUJO_TURNO -> no se pudo interpretar el mensaje: %s", e)
        return vacio


def _dias_de_cada_profesional() -> str:
    from backend.database import SessionLocal
    from backend.models.professional import Professional
    from backend.services.appointment_service import dias_que_atiende
    db = SessionLocal()
    try:
        profs = db.query(Professional).filter(
            Professional.is_active == True, Professional.is_deleted == False).all()  # noqa: E712
        return "; ".join(f"{p.full_name}: {', '.join(dias_que_atiende(db, p))}" for p in profs) or "-"
    except Exception:
        return "-"
    finally:
        db.close()


def responder_pregunta(pregunta: str) -> str:
    """Contesta una pregunta suelta con los datos del consultorio, sin herramientas."""
    from bot.ai_agent import (
        _build_client, get_horarios_texto, get_sedes_texto, get_especialistas_texto,
    )
    client, modelo = _build_client()
    if not client:
        return ""
    try:
        r = client.chat.completions.create(
            model=modelo, temperature=0.2, max_tokens=300,
            messages=[{"role": "system", "content": (
                "Sos la recepción de Silprodent, consultorio odontológico. Respondé en "
                "español argentino con voseo, cálido y en 1 o 2 líneas, SOLO con estos "
                "datos. Si la respuesta no está acá (precios, coberturas, diagnósticos), "
                f"decí que lo consulte llamando al {telefono_consultorio()}. No ofrezcas "
                "turnos ni preguntes nada.\n"
                f"Horarios del consultorio: {get_horarios_texto()}\nSedes: {get_sedes_texto()}\n"
                f"Profesionales: {get_especialistas_texto()}\n"
                f"Días de cada profesional (si preguntan por uno, respondé con esto): "
                f"{_dias_de_cada_profesional()}")},
                {"role": "user", "content": pregunta}],
        )
        return (r.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("FLUJO_TURNO -> no se pudo responder la pregunta: %s", e)
        return ""


# ── El guion ─────────────────────────────────────────────────────────────────

def _cortar_flujo(estado: dict) -> dict:
    return {k: v for k, v in (estado or {}).items() if k not in (CLAVE, CLAVE_PREVIO)}


def _cerrar_pedido(estado: dict) -> dict:
    """Pedido cerrado: el siguiente arranca limpio. Si quedaran el motivo o el
    día, el próximo turno (o el agente general) los heredaba."""
    return {k: v for k, v in _cortar_flujo(estado).items()
            if k not in ("motivo", "fecha_hora", "paciente")}


def _con_saludo(texto: str, history: list[dict], nombre: str | None = None) -> str:
    if history:
        return texto
    return f"¡{_saludo().capitalize()}{', ' + nombre if nombre else ''}! 😊 {texto}"


def _texto_tramite(que: str) -> str:
    from backend.services.config import get_config
    from bot.ai_agent import get_horarios_texto
    try:
        horarios = get_horarios_texto()
    except Exception:
        horarios = ""
    if not horarios or "no cargado" in horarios:
        horarios = ""
    excepcion = (get_config("EXCEPCIONES_TRAMITES", "") or "").strip().rstrip(".")
    que = "eso" if que == "eso" else que
    texto = (f"Para {que} no hace falta sacar turno 😊 Podés pasar por el consultorio "
             f"cualquier día en horario de atención")
    if excepcion:
        texto += f" ({excepcion})"
    texto += f": {horarios}." if horarios else "."
    return texto + f" Si tenés dudas, llamá al {telefono_consultorio()}."


def _seguimiento_tramite(d: dict) -> str:
    from datetime import date
    from bot.ai_agent import get_horarios_texto
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    iso = _fecha_iso(d["dia"]) if d.get("dia") else ""
    if iso:
        nombre = dias[date.fromisoformat(iso).weekday()]
        try:
            franjas = next((x.split(": ", 1)[1] for x in get_horarios_texto().split(" · ")
                            if x.startswith(nombre + ":")), "")
        except Exception:
            franjas = ""
        if franjas:
            return (f"Sí 😊 El {nombre.lower()} podés pasar en este horario: {franjas}. "
                    "No hace falta turno ni avisar antes.")
        return (f"El {nombre.lower()} el consultorio no atiende. Podés pasar otro día en "
                f"horario de atención, o llamar al {telefono_consultorio()}.")
    return ("Podés pasar cuando te quede cómodo dentro del horario de atención 😊 No hace "
            "falta turno ni avisar antes.")


def _texto_secretaria() -> str:
    return ("Ese turno lo está viendo la secretaria por este mismo chat 😊 Te responde "
            "por acá apenas pueda, así no se cruzan dos gestiones.")


def responder(mensaje: str, history: list[dict], estado: dict, telefono: str,
              dichos: list[str]):
    """(texto, opciones, estado) si el mensaje es del flujo de turnos; si no, None."""
    estado = dict(estado or {})
    # Lo agrega el router: alguien de la clínica escribió a mano en este chat
    # en los últimos días. No se guarda en el estado.
    gestion_humana = estado.pop("gestion_humana", False)
    t = dict(estado.get(CLAVE) or {})
    p = dict(estado.get(CLAVE_PREVIO) or {})
    respuestas_bot = [m["content"] for m in (history or []) if m.get("role") == "assistant"]
    ultima = respuestas_bot[-1] if respuestas_bot else ""

    # Botones y respuestas cortas que se resuelven sin la IA.
    from bot.tools.appointment_tools import motivo_por_boton_conducto
    motivo_boton = motivo_por_boton_conducto(mensaje, ultima) if t.get("esperando") == "conducto" else None
    if not motivo_boton and t.get("esperando") == "conducto" and "Te doy un turno para la consulta" in (ultima or "") \
            and re.search(r"\b(bueno|dale|ok|si|sí|listo|de acuerdo|perfecto|esta bien|va)\b", (mensaje or "").lower()):
        # Chat real 25/11: "bueno" volvía a preguntar para qué era el turno.
        from backend.services.appointment_service import MOTIVO_CONSULTA_CONDUCTO
        motivo_boton = MOTIVO_CONSULTA_CONDUCTO

    datos = extraer(mensaje, ultima if (t or p) else "")
    intencion = datos.get("intencion")
    if (t.get("oferta") or {}).get("slots") and _numero_elegido(mensaje, t["oferta"]["slots"]):
        # "3" es la opción 3 de la lista, no el día 3 ni las 03:00.
        datos = {k: None for k in datos} | {"intencion": "dar_datos", "quiere_otro_dia": False}
    if _es(mensaje, BOTON_OTRO_DIA):
        # El botón no trae fecha: la IA a veces "leía" una del mensaje anterior
        # y volvía a ofrecer el mismo día (chat real 25/11).
        datos.update(dia=None, hora=None, quiere_otro_dia=True)

    # Trámites: firmar la historia clínica, retirar la prótesis. No es turno.
    que = es_tramite(mensaje) or ("eso" if intencion == "tramite_consultorio" else None)
    if que:
        logger.info("FLUJO_TURNO -> trámite de consultorio, sin turno")
        set_opciones_ofrecidas(None)
        estado = _cerrar_pedido(estado)
        estado["tramite"] = que
        return _con_saludo(_texto_tramite(que), history), tomar_opciones_ofrecidas(), estado

    # Sigue hablando del trámite ("¿puedo pasar mañana a la mañana?"): no es
    # un pedido de turno nuevo (simulación 24/11).
    if estado.get("tramite") and not t and not datos.get("motivo") \
            and intencion not in ("cancelar_turno", "consultar_mis_turnos", "ya_tengo_turno",
                                  "reprogramar_turno"):
        if intencion == "saludo_o_cierre":
            return "¡De nada! Te esperamos 😊", None, estado
        set_opciones_ofrecidas(None)
        return _seguimiento_tramite(datos), tomar_opciones_ofrecidas(), estado
    estado.pop("tramite", None)

    # "Gracias, nos vemos el jueves" después de confirmar: cierre, no pedido.
    if not t and not p and intencion == "saludo_o_cierre" and history \
            and (ultima.startswith(("¡Listo", "¡Perfecto", "Listo")) or _DESPEDIDA.search(_norm(mensaje))):
        if ultima.startswith(("¡Listo", "¡Perfecto", "Listo")):
            return "¡Gracias a vos! Te esperamos 😊 Cualquier cosa, escribime.", None, estado
        return "¡De nada! Cualquier cosa, escribime 😊", None, estado

    ya_tenia = intencion in ("ya_tengo_turno", "reprogramar_turno") or bool(_YA_TENIA.search(_norm(mensaje)))
    sobre_turnos = ya_tenia or intencion in ("sacar_turno", "cancelar_turno", "consultar_mis_turnos") \
        or (intencion == "dar_datos" and (datos.get("dia") or datos.get("hora")))

    # La secretaria estuvo gestionando este chat: el bot no le pisa la
    # negociación ni trata un turno provisorio como si no existiera (caso
    # real del 24/11).
    if gestion_humana and not t and not p and sobre_turnos:
        logger.info("FLUJO_TURNO -> gestión humana reciente: se deja a la secretaria")
        set_opciones_ofrecidas(None)
        estado["pausar"] = True
        return _texto_secretaria(), tomar_opciones_ofrecidas(), estado

    # "Ya tenía turno" o cambiar uno: buscar el existente, nunca duplicar.
    cancelar = intencion == "cancelar_turno"
    if ya_tenia or cancelar or (p and intencion != "sacar_turno"):
        if cancelar and p.get("esperando") != "cancelar":
            p = {"cancelar": True}
        elif ya_tenia and not p:
            p = {"cambiar": intencion == "reprogramar_turno"}
        if estado.get("previo_llamar") and not p.get("esperando") and not d_dia(datos):
            # Ya se lo mandó a llamar por este turno: no se vuelve a preguntar
            # lo mismo en círculo (simulación 24/11).
            set_opciones_ofrecidas(None)
            return ("Como no lo pude identificar desde acá, lo más seguro es llamar al "
                    f"{telefono_consultorio()} 🙏 Así no se duplica nada."), tomar_opciones_ofrecidas(), estado
        p["ya_llamo"] = bool(estado.get("previo_llamar"))
        r = _turno_previo(p, datos, mensaje, telefono)
        if r[0] == "respuesta":
            _, texto, p = r
            estado = _cortar_flujo(estado) if p is None else {**_cortar_flujo(estado), CLAVE_PREVIO: p}
            if p is None and "llamá al consultorio" in texto:
                estado["previo_llamar"] = True
            return _con_saludo(texto, history), tomar_opciones_ofrecidas(), estado
        # Pasa a buscar horario nuevo para el turno encontrado.
        t = r[1]
        estado.pop(CLAVE_PREVIO, None)
        texto, _ = _siguiente_paso(t, telefono, dichos + [mensaje])
        return _terminar(t, texto, estado, history, ultima, "")
    estado.pop(CLAVE_PREVIO, None)

    if not t and intencion == "pregunta" and datos.get("pregunta") \
            and _PREGUNTA_INFO.search(_norm(datos["pregunta"])):
        texto = responder_pregunta(datos["pregunta"])
        if texto:
            # Sim 24/11: "¿dónde quedan y en qué horario?" → "llamá". Los datos
            # están en el panel: se contestan.
            return _con_saludo(texto, history), None, estado
    ultimo = estado.get("ultimo_turno")
    otro_dia = _es(mensaje, BOTON_OTRO_DIA) or datos.get("quiere_otro_dia")
    if not t and ultimo and (datos.get("hora") or datos.get("dia") or otro_dia) and not datos.get("motivo") \
            and datos.get("para_quien") != "otra_persona" \
            and intencion in ("dar_datos", "reprogramar_turno", "otro", "pregunta", "sacar_turno"):
        # Recién agendado y manda "17:30" u "otro día": es mover ESE turno, no
        # sacar otro (prueba real 25/11: arrancaba un pedido nuevo).
        logger.info("FLUJO_TURNO -> cambia el turno recién agendado")
        t = _t_para_reprogramar(ultimo, datos)
        if otro_dia and not datos.get("dia"):
            # "Otro día" de la lista vieja: el siguiente con lugar después de ese.
            from datetime import date as _d, timedelta as _td
            t["desde"] = (_d.fromisoformat(str(ultimo["date"])[:10]) + _td(days=1)).isoformat()
        else:
            t.setdefault("dia", str(ultimo["date"])[:10])
        if datos.get("hora"):
            t["hora_pedida"] = datos["hora"]
        estado.pop("ultimo_turno", None)
        texto, _ = _siguiente_paso(t, telefono, dichos + [mensaje])
        return _terminar(t, texto, estado, history, ultima, "")
    if not t:
        if intencion != "sacar_turno" and not (intencion == "dar_datos" and datos.get("motivo")):
            return None
        t = {"activo": True, "os_previa": estado.get("os_confirmada")}
        logger.info("FLUJO_TURNO -> empieza")
    elif intencion == "consultar_mis_turnos":
        logger.info("FLUJO_TURNO -> el paciente pide %s: pasa al agente general", intencion)
        return None
    elif intencion == "sacar_turno" and _pedido_nuevo(t, mensaje):
        # "Hola, quiero un turno" con el pedido trabado: se empieza de nuevo
        # conservando quién es y su cobertura, en vez de mandarlo a llamar.
        logger.info("FLUJO_TURNO -> pedido nuevo: se reinicia")
        t = {k: t[k] for k in ("identificado", "fichas", "ficha_nombre", "titular",
                               "obra_social", "para_quien", "nombre", "apellido",
                               "os_previa") if k in t}
        t["activo"], t["reiniciado"] = True, True

    aparte = ""
    if datos.get("pregunta") and intencion == "pregunta" and _PREGUNTA_INFO.search(_norm(datos["pregunta"])):
        aparte = responder_pregunta(datos["pregunta"])
    if not t.get("aviso_urgencia") and _URGENCIA.search(_norm(mensaje)):
        t["aviso_urgencia"] = True
        aparte = (aparte + "\n\n" if aparte else "") + (
            f"Si es una urgencia (dolor fuerte, hinchazón), llamá al {telefono_consultorio()} "
            "así te ven por sobreturno. Igual te busco el turno más cercano:")

    n_msg = _norm(mensaje)
    sin_datos = not any(datos.get(k) for k in ("motivo", "obra_social", "cobertura", "hora", "nombre", "apellido"))
    if t.get("esperando") and not motivo_boton and sin_datos and not _es(mensaje, BOTON_OTRO_DIA) and (
            _RECHAZO.search(n_msg)
            or (intencion == "saludo_o_cierre" and _DESPEDIDA.search(n_msg))
            or (t.get("esperando") in ("horario", "horario_con_otro", "sin_cupo", "dia")
                and not datos.get("dia") and intencion == "saludo_o_cierre")
            or (t.get("esperando") == "horario_con_otro" and datos.get("respuesta_si_no") == "no")):
        # Sim 24/11: dijo "no, gracias" o se despidió y el bot le volvía a
        # ofrecer lo mismo pidiendo perdón.
        t["terminado"] = True
        set_opciones_ofrecidas(None)
        texto = ("Entendido 😊 Si más adelante te sirve otro día u horario, escribime y te lo busco. "
                 f"Si es urgente, llamá al {telefono_consultorio()}.")
        return _terminar(t, texto, estado, history, ultima, "")

    propuesto_antes = t.get("motivo_propuesto")
    _claves = ("motivo_propuesto", "para_quien", "nombre", "apellido", "obra_social", "os_dicha",
               "cobertura", "dia", "preferencia_horaria", "profesional", "hora", "hora_pedida")
    _antes = {k: t.get(k) for k in _claves}
    _incorporar(t, datos, mensaje, motivo_boton)
    if any(t.get(k) != v for k, v in _antes.items()):
        t["aporto"] = True
    if t.get("motivo_propuesto") and (t["motivo_propuesto"] != propuesto_antes or motivo_boton):
        # El motivo se valida con lo dicho HASTA el mensaje que lo pidió. Con la
        # obra social antes que el motivo, el "Sí" que confirmaba la cobertura
        # se tomaba como "sí, ya hice la consulta por conducto".
        t["dichos_motivo"] = dichos + [mensaje]
    oferta_antes = dict(t.get("oferta") or {})
    texto, _ = _siguiente_paso(t, telefono, dichos + [mensaje])
    o = t.get("oferta") or {}
    if oferta_antes and not t.get("terminado") and t.get("esperando") == "horario" \
            and not _es(mensaje, BOTON_MAS) \
            and o.get("fecha") == oferta_antes.get("fecha") and o.get("slots") == oferta_antes.get("slots"):
        t["misma_oferta"] = t.get("misma_oferta", 0) + 1
        if t["misma_oferta"] >= 2:
            # Sim 24/11: insistía "hoy" y el bot repetía lo mismo en círculo.
            t["terminado"] = True
            set_opciones_ofrecidas(None)
            texto = (f"Antes del *{o.get('fecha_texto')}* no me queda lugar, y no quiero hacerte dar "
                     f"vueltas. Si es urgente, llamá al {telefono_consultorio()} así te ven por "
                     "sobreturno. Si te sirve ese día, escribime y te lo agendo 😊")
    else:
        t.pop("misma_oferta", None)
    return _terminar(t, texto, estado, history, ultima, aparte)


def d_dia(d: dict) -> bool:
    return bool(d.get("dia"))


def _pedido_nuevo(t: dict, mensaje: str) -> bool:
    n = _norm(mensaje)
    if not _PIDE_TURNO.search(n):
        return False
    trabado = t.get("repeticiones") or t.get("sin_cupo") or \
        t.get("esperando") in ("dia", "sin_cupo", "horario_con_otro")
    return bool(_SALUDO.search(n)) or bool(trabado)


def _terminar(t: dict, texto: str, estado: dict, history, ultima: str, aparte: str):
    # Si vuelve a decir exactamente lo mismo, no se entendieron: se aclara una
    # vez y a la tercera se lo manda al teléfono, nunca un círculo sin salida.
    reiniciado = t.pop("reiniciado", False)
    aporto = t.pop("aporto", False)
    if texto and texto in (ultima or "") and not t.get("terminado") and aporto and not reiniciado:
        # Dio un dato (el día, la franja) aunque no era lo que se preguntó: se
        # anota y se repite la pregunta, sin "no te entendí" (chat real 25/11).
        texto = "Dale, lo anoto 👍 " + texto
    elif texto and texto in (ultima or "") and not t.get("terminado") and not reiniciado:
        t["repeticiones"] = t.get("repeticiones", 0) + 1
        if t["repeticiones"] >= 2:
            t["terminado"] = True
            set_opciones_ofrecidas(None)
            texto = "Perdón, no logro entenderte bien por acá 🙏 " + _texto_llamar()
        else:
            texto = "Perdón, no te entendí bien. " + texto
    elif not t.get("terminado"):
        t["repeticiones"] = 0

    if t.get("terminado"):
        estado = _cerrar_pedido(estado)
        if t.get("previo_sugerido"):
            estado[CLAVE_PREVIO] = t["previo_sugerido"]
        if t.get("agendado"):
            estado["accion_hecha"] = True
            if (t.get("recien") or {}).get("id"):
                estado["ultimo_turno"] = t["recien"]
        if t.get("obra_social"):
            # Para el próximo pedido de la misma persona: no se repregunta.
            titular = t.get("titular") or {}
            quien = titular.get("nombre_completo") or f"{t.get('nombre') or ''} {t.get('apellido') or ''}".strip()
            if quien:
                estado["os_confirmada"] = {"quien": quien, "os": t["obra_social"]}
    else:
        estado = {k: v for k, v in estado.items() if k != CLAVE_PREVIO}
        estado[CLAVE] = t
        # Compatibilidad con el agente general, que lee estas claves del estado.
        for k in ("motivo", "obra_social"):
            if t.get(k):
                estado[k] = t[k]
    texto = _con_saludo(texto, history, t.get("ficha_nombre"))
    if aparte:
        texto = f"{aparte}\n\n{texto}"
    return texto, tomar_opciones_ofrecidas(), estado


# ── "Ya tenía turno" ─────────────────────────────────────────────────────────

def _mis_turnos(telefono: str) -> list[dict] | None:
    try:
        estado_http, d = _post("/api/bot/my-appointments", {"requester_phone": telefono}, timeout=15)
    except Exception:
        return None
    if estado_http != 200:
        return None
    return d.get("appointments") or []


def _turno_previo(p: dict, d: dict, mensaje: str, telefono: str):
    """("respuesta", texto, p|None) o ("reprogramar", t)."""
    from datetime import datetime
    from backend.services.appointment_service import fecha_en_palabras
    set_opciones_ofrecidas(None)
    # "Quiero pasarlo a la mañana" en el primer mensaje vale para buscar el nuevo.
    if d.get("preferencia_horaria"):
        p["preferencia"] = d["preferencia_horaria"]

    def llamar():
        return ("respuesta", "No llego a identificar ese turno desde acá, y no quiero "
                "sacarte uno repetido. " + _texto_llamar(), None)

    def asociar(turno: dict, cambiar: bool):
        cuando = datetime.fromisoformat(turno["date"])
        turno["fecha_texto"] = fecha_en_palabras(cuando.date())
        turno["hora"] = cuando.strftime("%H:%M")
        if cambiar:
            return ("reprogramar", _t_para_reprogramar(turno, {**d, "preferencia_horaria":
                                                                d.get("preferencia_horaria") or p.get("preferencia")}))
        if p.get("cancelar"):
            set_opciones_ofrecidas([BOTON_CANCELAR_SI, BOTON_NO], siempre=True, tipo="botones")
            return ("respuesta", f"¿Confirmás que cancelo el turno de "
                    f"{(turno.get('reason') or 'consulta').lower()} del *{turno['fecha_texto']} a las "
                    f"{turno['hora']}* con {turno['professional']}?",
                    {"esperando": "cancelar", "turno": turno, "cancelar": True})
        set_opciones_ofrecidas([BOTON_CONFIRMO, BOTON_CAMBIAR], siempre=True, tipo="botones")
        quien = f" de {turno['paciente']}" if p.get("varios") else ""
        return ("respuesta", f"Sí, encontré el turno{quien}: *{turno['fecha_texto']} a las "
                f"{turno['hora']}* con {turno['professional']} ({(turno.get('reason') or 'consulta').lower()}). "
                "¿Lo confirmás o querés cambiarlo?",
                {"esperando": "confirmar", "turno": turno})

    if p.get("esperando") == "es_ese":
        iso_dicho = _fecha_iso(d["dia"]) if d.get("dia") else ""
        if iso_dicho and iso_dicho == str(p["propuesto"]["date"])[:10]:
            return asociar(p["propuesto"], p.get("cambiar"))
        if _es(mensaje, BOTON_SI) or d.get("respuesta_si_no") == "si":
            return asociar(p["propuesto"], p.get("cambiar"))
        if _es(mensaje, BOTON_NO) or d.get("respuesta_si_no") == "no":
            return llamar()
        set_opciones_ofrecidas([BOTON_SI, BOTON_NO], siempre=True, tipo="botones")
        return ("respuesta", "¿Es ese turno?", p)

    if p.get("esperando") == "cancelar":
        turno = p["turno"]
        if _es(mensaje, BOTON_CANCELAR_SI) or d.get("respuesta_si_no") == "si":
            try:
                estado_http, _r = _post("/api/bot/cancel", {"appointment_id": turno["id"],
                                                            "requester_phone": telefono}, timeout=15)
            except Exception:
                estado_http = 0
            if estado_http == 200:
                return ("respuesta", f"Listo, cancelé el turno del *{turno['fecha_texto']} a las "
                        f"{turno['hora']}*. Si querés sacar otro, escribime 😊", None)
            return llamar()
        if _es(mensaje, BOTON_NO) or d.get("respuesta_si_no") == "no":
            return ("respuesta", "Perfecto, el turno queda como está 😊", None)
        set_opciones_ofrecidas([BOTON_CANCELAR_SI, BOTON_NO], siempre=True, tipo="botones")
        return ("respuesta", "¿Lo cancelo?", p)

    if p.get("esperando") == "confirmar":
        turno = p["turno"]
        if _es(mensaje, BOTON_CONFIRMO) or d.get("respuesta_si_no") == "si":
            return ("respuesta", f"¡Perfecto! 😊 Queda confirmado: te esperamos el "
                    f"*{turno['fecha_texto']} a las {turno['hora']}* con {turno['professional']}.", None)
        if _es(mensaje, BOTON_CAMBIAR) or d.get("respuesta_si_no") == "no" \
                or d.get("quiere_otro_dia") or d.get("dia") or d.get("intencion") == "reprogramar_turno":
            return ("reprogramar", _t_para_reprogramar(turno, {**d, "preferencia_horaria":
                                                                d.get("preferencia_horaria") or p.get("preferencia")}))
        set_opciones_ofrecidas([BOTON_CONFIRMO, BOTON_CAMBIAR], siempre=True, tipo="botones")
        return ("respuesta", "¿Lo confirmás o querés cambiarlo?", p)

    turnos = _mis_turnos(telefono)
    if not turnos:
        # Regla del 24/11: primero se pregunta el día; recién si no aparece,
        # a llamar (prueba real: mandaba a llamar de entrada).
        if p.get("esperando") == "dia" or (d.get("dia") and p.get("pregunto_dia")):
            return llamar()
        p["esperando"], p["pregunto_dia"] = "dia", True
        if d.get("dia"):
            return ("respuesta", "No encuentro un turno a tu nombre ese día. ¿Me decís qué día "
                    "y a qué hora lo tenías?", p)
        return ("respuesta", "¿Qué día tenías el turno? Así lo busco en la agenda.", p)
    p["varios"] = len({x.get("paciente") for x in turnos}) > 1
    iso = _fecha_iso(d["dia"]) if d.get("dia") else ""
    if p.get("cancelar") and not iso and len(turnos) == 1:
        return asociar(turnos[0], False)
    if iso:
        candidatos = [x for x in turnos if str(x["date"])[:10] == iso]
        if d.get("hora"):
            candidatos = [x for x in candidatos if str(x["date"])[11:16] == d["hora"]] or candidatos
        if len(candidatos) == 1:
            return asociar(candidatos[0], p.get("cambiar"))
        if len(turnos) == 1 and not p.get("propuesto"):
            # Dijo mal el día, pero tiene un solo turno: se le pregunta si es
            # ese (sim 24/11). Con un "sí" queda claro; si no, a llamar.
            unico = turnos[0]
            cuando = datetime.fromisoformat(str(unico["date"]))
            set_opciones_ofrecidas([BOTON_SI, BOTON_NO], siempre=True, tipo="botones")
            return ("respuesta", f"Ese día no veo turnos a tu nombre. El único que tenés es el "
                    f"*{fecha_en_palabras(cuando.date())} a las {cuando.strftime('%H:%M')}* "
                    f"({(unico.get('reason') or 'consulta').lower()}). ¿Es ese?",
                    {**p, "esperando": "es_ese", "propuesto": unico})
        if p.get("esperando") != "dia" and not p.get("ya_llamo"):
            # Puede haber dicho "en un par de días": se le pide el día una vez.
            p["esperando"], p["pregunto_dia"] = "dia", True
            return ("respuesta", "No encuentro un turno tuyo ese día. ¿Me decís qué día y a "
                    "qué hora lo tenías?", p)
        return llamar()
    if p.get("esperando") == "dia":
        # No recuerda el día: solo se asocia si hay uno solo, sin dudas.
        return asociar(turnos[0], p.get("cambiar")) if len(turnos) == 1 else llamar()
    p["esperando"] = "dia"
    return ("respuesta", "¿Qué día tenías el turno? Así lo busco en la agenda.", p)


def _t_para_reprogramar(turno: dict, d: dict) -> dict:
    nombre, _, apellido = (turno.get("paciente") or "").partition(" ")
    t = {"activo": True, "identificado": True, "para_quien": "listo",
         "reprogramar": turno["id"], "turno_anterior": turno,
         "motivo": turno.get("reason") or "Control",
         "obra_social": turno.get("insurance") or "Particular",
         "profesional": turno.get("professional") if turno.get("professional") != "?" else None,
         "nombre": nombre, "apellido": apellido, "orto_vez": "-"}
    if d.get("dia"):
        iso = _fecha_iso(d["dia"])
        if iso and iso != str(turno["date"])[:10]:
            t["dia"] = iso
    if d.get("preferencia_horaria"):
        t["preferencia_horaria"] = d["preferencia_horaria"]
    return t


def _incorporar(t: dict, d: dict, mensaje: str, motivo_boton: str | None):
    """Suma al estado lo que trajo el mensaje, según el paso en que estamos."""
    esperando = t.get("esperando")

    if motivo_boton:
        t["motivo_propuesto"], t["motivo"] = motivo_boton, None
        t["conducto_resuelto"] = True
    elif d.get("motivo") and _norm(d["motivo"]) != _norm(t.get("motivo") or ""):
        # Cambio de opinión ("mejor que me arreglen la caries"): se recalcula.
        t["motivo_propuesto"], t["motivo"] = d["motivo"], None
        t.pop("oferta", None)
        t.pop("orto_vez", None)

    # Ortodoncia: primera consulta o ya en tratamiento.
    if esperando == "orto_vez":
        n = _norm(mensaje)
        if _es(mensaje, BOTON_PRIMERA) or re.search(r"\b(1|primera|nunca|primer)\b", n):
            t["orto_vez"] = BOTON_PRIMERA
        elif _es(mensaje, BOTON_SEGUNDA) or re.search(
                r"\b(2|segunda|control|ya tengo|ya tiene|tratamiento|aparatos?|alambr\w*)\b", n):
            t["orto_vez"] = BOTON_SEGUNDA

    # Para quién
    if esperando == "para_quien" and _es(mensaje, BOTON_PARA_MI):
        t["para_quien"] = "yo"
    elif esperando == "para_quien" and _es(mensaje, BOTON_OTRA_PERSONA):
        t["para_quien"] = "otra_persona"
    elif esperando == "para_quien" and any(_es(mensaje, n) for n in t.get("familia", [])):
        t["para_quien"], t["nombre_elegido"] = "familiar", mensaje.strip()
    elif d.get("para_quien") and t.get("para_quien") != "listo" \
            and (d["para_quien"] != "yo" or _PARA_MI.search(_norm(mensaje))):
        t["para_quien"] = d["para_quien"]
    if d.get("nombre") and (esperando in ("nombre", "apellido", "para_quien") or d.get("para_quien")):
        t["nombre"] = d["nombre"].strip().title()
    if d.get("apellido") and (esperando in ("nombre", "apellido", "para_quien") or d.get("para_quien")):
        t["apellido"] = d["apellido"].strip().title()

    if esperando == "horario" and _es(mensaje, BOTON_MAS):
        t["pagina"] = t.get("pagina", 0) + 1
        t["mas"] = True
        return

    # Sin cupo: el paciente elige una salida.
    if esperando == "sin_cupo":
        if _es(mensaje, BOTON_LLAMAR):
            t["llamar"] = True
            return
        if _es(mensaje, BOTON_OTRO_DIA) and not d.get("dia"):
            t["pide_dia"] = True

    # Particular dicho con palabras ("hacelo sin obra social"): vale en
    # cualquier paso y se vuelve a buscar la agenda con esa cobertura.
    if _es(mensaje, BOTON_PARTICULAR) or dice_particular(mensaje) or d.get("cobertura") == "particular":
        if t.get("obra_social") and t.get("obra_social") != "Particular":
            t.pop("oferta", None)
            t["paso_a_particular"] = True
        t["obra_social"] = "Particular"
        t.pop("cobertura", None)
        t.pop("os_dicha", None)
    # Obra social de la ficha: se confirma, no se da por hecha.
    elif esperando == "confirmar_os":
        if d.get("obra_social") or d.get("cobertura"):
            t["os_confirmada"] = "cambio"      # dijo cuál tiene ahora: sigue abajo
        elif _es(mensaje, BOTON_SI) or d.get("respuesta_si_no") == "si":
            t["os_confirmada"] = "si"
        elif _es(mensaje, BOTON_CAMBIO) or d.get("respuesta_si_no") == "no":
            t["os_confirmada"] = "cambio"
        if d.get("obra_social"):
            t["os_dicha"] = d["obra_social"]
        elif d.get("cobertura") == "obra_social":
            t["cobertura"] = "obra_social"
    elif esperando == "cobertura" and _es(mensaje, BOTON_TENGO_OS):
        t["cobertura"] = "obra_social"
    elif esperando in ("obra_social", "cobertura") and any(_es(mensaje, o) for o in t.get("os_ofrecidas", [])):
        t["os_dicha"] = next(o for o in t["os_ofrecidas"] if _es(mensaje, o))
    elif esperando == "obra_social":
        # En este paso, lo que escribe ES la obra social (o sus primeras letras).
        t["os_dicha"] = (d.get("obra_social") or mensaje).strip(" .,;!¡?¿")
    elif not t.get("obra_social"):
        if d.get("obra_social"):
            t["os_dicha"] = d["obra_social"]
        elif d.get("cobertura") == "obra_social":
            t["cobertura"] = "obra_social"

    # Día, franja, profesional
    if d.get("dia"):
        iso = _fecha_iso(d["dia"])
        if iso and iso != t.get("dia") and iso != (t.get("oferta") or {}).get("fecha"):
            t["dia"] = iso
            t.pop("oferta", None)
            t.pop("pide_dia", None)
    if d.get("preferencia_horaria") and d["preferencia_horaria"] != t.get("preferencia_horaria"):
        t["preferencia_horaria"] = d["preferencia_horaria"]
        t.pop("oferta", None)
    profesional = d.get("profesional")
    if profesional and _norm(profesional) in _PROFESIONAL_GENERICO:
        profesional = None
    if profesional and profesional != t.get("profesional"):
        t["profesional"] = profesional
        t.pop("oferta", None)
    pide_el_mismo = bool(d.get("dia")) and _fecha_iso(d["dia"]) == (t.get("oferta") or {}).get("fecha")
    # Insiste con el día que pidió y que no tiene lugar ("¿podrían mañana?"):
    # se le explica, no se repite la misma oferta como si no hubiera escuchado.
    if esperando == "horario" and t.get("oferta") and d.get("dia") and t.get("dia") \
            and _fecha_iso(d["dia"]) == t["dia"] != t["oferta"]["fecha"]:
        t["insiste"] = True
        return
    if esperando == "horario" and (_es(mensaje, BOTON_OTRO_DIA) or d.get("quiere_otro_dia")) \
            and not t.get("hora") and not pide_el_mismo:
        anterior = (t.pop("oferta", None) or {}).get("fecha")
        if not d.get("dia") or t.get("dia") == anterior:
            # No dijo cuál: el siguiente con lugar después del que no le sirvió.
            t.pop("dia", None)
            if anterior:
                from datetime import date, timedelta
                t["desde"] = (date.fromisoformat(anterior) + timedelta(days=1)).isoformat()
                t["no_le_sirvio"] = anterior

    # Horario elegido: solo vale uno de los ofrecidos.
    oferta = t.get("oferta")
    if oferta:
        hora = _numero_elegido(mensaje, oferta.get("slots", [])) or _hora_elegida(mensaje, oferta.get("slots", []))
        if not hora and d.get("hora") in oferta.get("slots", []):
            hora = d["hora"]
        if hora:
            t["hora"] = hora
    if not t.get("hora") and d.get("hora"):
        # Nombró una hora para otro día ("el martes 24 a las 10:30"): si está
        # libre cuando se busque ese día, se agenda sin volver a preguntar.
        t["hora_pedida"] = d["hora"]


def _numero_elegido(texto: str, slots: list[str]) -> str | None:
    """"1", "el 2", "opción 3", "3️⃣": el horario de ese número de la lista.
    Solo un número suelto y dentro de la lista; "10" o "17:30" son horas."""
    t = (texto or "").strip()
    for i, emoji in enumerate(_NUMEROS):
        if emoji in t and i < len(slots):
            return slots[i]
    m = re.fullmatch(r"(?:el|la|opci[oó]n|numero|número|nro\.?|n°)?\s*(\d)\s*[.)]?", t.lower())
    if m and ":" not in t:
        n = int(m.group(1))
        if 1 <= n <= len(slots):
            return slots[n - 1]
    return None


def _hora_elegida(texto: str, slots: list[str]) -> str | None:
    """La hora ofrecida que nombra el mensaje. "12:00", "a las 17", "las 5 de la
    tarde" (la IA la pasa como 17:00). Un número suelto solo cuenta en un mensaje
    corto: en "el lunes 30" el 30 es el día, no una hora."""
    t = texto or ""
    for h, m in re.findall(r"\b(\d{1,2})[:.](\d{2})\b", t):
        cand = f"{int(h):02d}:{m}"
        if cand in slots:
            return cand
    if len(t.split()) <= 4:
        for h in re.findall(r"\b(\d{1,2})\s*(?:hs|h)?\b", t):
            cand = f"{int(h):02d}:00"
            if cand in slots:
                return cand
    return None


def _nombre_de_quien_escribe(t: dict) -> str:
    """Para hablarle por su nombre (chat real: el bot nunca usó su nombre)."""
    titular = t.get("titular") or {}
    if t.get("para_quien") in ("yo", None) and titular.get("nombre"):
        return titular["nombre"]
    if t.get("para_quien") == "yo" and t.get("nombre"):
        return t["nombre"]
    return t.get("ficha_nombre") or ""


def _siguiente_paso(t: dict, telefono: str, dichos: list[str]):
    """Valida lo que haya y pregunta lo primero que falte, en orden fijo:
    (para quién, si el número tiene fichas) → obra social o particular → para
    qué → especialista y próximo turno libre."""
    set_opciones_ofrecidas(None)

    if t.pop("llamar", None):
        t["terminado"] = True
        return _texto_llamar(), None

    # 0. Quién escribe (sin preguntar nada: sale del número)
    if not t.get("identificado"):
        _identificar(t, telefono)
    # 1. Para quién, solo si hay fichas: define qué obra social mirar.
    falta = _falta_eleccion_persona(t)
    if falta:
        return falta

    # 2. Obra social o particular
    falta = _falta_obra_social(t)
    if falta:
        return falta

    # 3. Motivo
    if not t.get("motivo"):
        if t.get("motivo_propuesto"):
            ok, motivo, razon = _validar_motivo(t["motivo_propuesto"],
                                                t.get("dichos_motivo") or dichos, telefono)
            if ok:
                t["motivo"] = motivo
            else:
                return _motivo_rechazado(t, razon)
        else:
            t["esperando"] = "motivo"
            return ("¿Para qué sería el turno? Por ejemplo: limpieza, control, "
                    "extracción, arreglo, conducto, ortodoncia o prótesis."), None

    # 3b. Ortodoncia: primera consulta o ya en tratamiento.
    if _norm(t["motivo"]) == "ortodoncia" and not t.get("orto_vez"):
        t["esperando"] = "orto_vez"
        set_opciones_ofrecidas([BOTON_PRIMERA, BOTON_SEGUNDA], siempre=True, tipo="botones")
        return "¿Es la primera consulta de ortodoncia o ya viene en tratamiento?", None

    # 4. Nombre, si es alguien sin ficha
    falta = _falta_nombre(t)
    if falta:
        return falta

    # 5. Profesional (lo decide la agenda), día y horario
    if t.get("pide_dia") and not t.get("dia"):
        t["esperando"] = "dia"
        return ("¿Para qué día lo busco? Decime una fecha, por ejemplo *el 3 de "
                "diciembre*, o una franja (mañana o tarde)."), None
    t.pop("pide_dia", None)
    if not t.get("oferta"):
        texto, opciones = _ofrecer_horarios(t)
        pedida = t.pop("hora_pedida", None)
        if not (t.get("oferta") and pedida):
            return texto, opciones
        if pedida not in t["oferta"]["slots"]:
            # La lista es una seleccion: la hora puede estar libre igual.
            estado_http, d = _alta(t, pedida, telefono)
            if estado_http == 200:
                t["hora"] = pedida
                t["agendado"] = True
                return _confirmacion(t, d), None
            _botones_horarios(t)
            o = t["oferta"]
            return (f"A las {pedida} no tengo lugar el *{o['fecha_texto']}*. " + _pocos_o_elegir(t)), opciones
        t["hora"] = pedida
    if not t.get("hora") and t.pop("insiste", None):
        from backend.services.appointment_service import fecha_en_palabras
        from datetime import date
        o = t["oferta"]
        _botones_horarios(t)
        return (f"Ya me fijé: el {fecha_en_palabras(date.fromisoformat(t['dia']))} no tengo "
                f"lugar para {t['motivo'].lower()}. Lo más cercano es el *{o['fecha_texto']}* "
                f"con {o['profesional']}. ¿Te sirve alguno de esos horarios, o preferís otro día?"
                + _como_elegir(t)), None
    if not t.get("hora") and t.pop("mas", None):
        t["esperando"] = "horario"
        o = t["oferta"]
        _botones_horarios(t)
        pag = t.get("pagina", 0)
        visibles = o["slots"][pag * 2: pag * 2 + 2]
        return (f"Más horarios del *{o['fecha_texto']}* con {o['profesional']}: "
                f"*{' y '.join(visibles)}* 👇 Tocá el que te sirva, o escribime la hora."), None
    if not t.get("hora"):
        t["esperando"] = "horario"
        o = t["oferta"]
        _botones_horarios(t)
        return _pocos_o_elegir(t), None

    # 6. Alta
    return _agendar(t, telefono)


def _validar_motivo(propuesto: str, dichos: list[str], telefono: str):
    try:
        _, d = _post("/api/bot/resolver-motivo",
                     {"motivo": propuesto, "dichos": dichos, "telefono": telefono}, timeout=15)
    except Exception:
        return False, None, None
    return bool(d.get("ok")), d.get("motivo"), d.get("razon")


def _motivo_rechazado(t: dict, razon: str | None):
    from backend.services.appointment_service import (
        PREGUNTA_CONDUCTO_PACIENTE, BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO,
        RAZON_SIN_CONSULTA_PREVIA, TEXTO_SIN_CONSULTA_PREVIA,
    )
    t.pop("motivo_propuesto", None)
    if razon == RAZON_SIN_CONSULTA_PREVIA:
        t["esperando"] = "conducto"
        set_opciones_ofrecidas([BOTON_CONSULTA_CONDUCTO], siempre=True, tipo="botones")
        return TEXTO_SIN_CONSULTA_PREVIA, None
    if razon and "conducto" in razon.lower() and not t.get("conducto_resuelto"):
        t["esperando"] = "conducto"
        set_opciones_ofrecidas([BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO],
                               siempre=True, tipo="botones")
        return PREGUNTA_CONDUCTO_PACIENTE, None
    t["esperando"] = "motivo"
    return ("Contame un poco más para qué sería el turno, así te doy el tiempo y el "
            "profesional que corresponde (limpieza, control, extracción, arreglo, conducto, "
            "ortodoncia, prótesis…)."), None


def _identificar(t: dict, telefono: str):
    try:
        _, d = _post("/api/bot/identificar", {"requester_phone": telefono}, timeout=15)
    except Exception:
        d = {}
    fichas = d.get("pacientes") or []
    t["identificado"] = True
    t["fichas"] = [{"nombre": f.get("nombre"), "nombre_completo": f.get("nombre_completo"),
                    "obra_social": f.get("obra_social")} for f in fichas]
    if fichas:
        t["ficha_nombre"] = fichas[0].get("nombre")


def _falta_eleccion_persona(t: dict):
    """Con fichas en el número: para quién es (de eso depende la obra social)."""
    fichas = t.get("fichas") or []
    quien = t.get("para_quien")

    if quien == "familiar":
        elegida = next((f for f in fichas if _es(f["nombre_completo"], t.get("nombre_elegido", ""))), None)
        if elegida:
            nombre, _, apellido = elegida["nombre_completo"].partition(" ")
            t.update(nombre=nombre, apellido=apellido, titular=elegida)
            t["para_quien"] = "listo"
        else:
            t["para_quien"] = None
            quien = None

    if quien == "yo" and len(fichas) == 1:
        nombre, _, apellido = fichas[0]["nombre_completo"].partition(" ")
        t.setdefault("nombre", nombre)
        t.setdefault("apellido", apellido)
        t["titular"] = fichas[0]
        return None
    if quien in ("listo", "otra_persona"):
        return None

    if fichas and (not quien or (quien == "yo" and len(fichas) > 1)):
        t["esperando"] = "para_quien"
        if len(fichas) == 1:
            set_opciones_ofrecidas([BOTON_PARA_MI, BOTON_OTRA_PERSONA], siempre=True, tipo="botones")
            return f"¿El turno es para vos, {fichas[0]['nombre']}, o para otra persona?", None
        t["familia"] = [f["nombre_completo"] for f in fichas]
        set_opciones_ofrecidas(t["familia"][:9] + [BOTON_OTRA_PERSONA], siempre=True,
                               titulo="Paciente", boton="Elegir")
        return "¿Para quién es el turno?", None
    return None


def _falta_nombre(t: dict):
    """Número nuevo, u otra persona: hacen falta nombre y apellido."""
    if t.get("titular") or t.get("para_quien") == "listo":
        return None
    quien = t.get("para_quien")
    if not t.get("nombre"):
        # Cada vez con otras palabras: repetir la misma frase suena a máquina
        # trabada ("mío", "un lunes" no son un nombre, pero tampoco un error).
        vez = t.get("veces_nombre", 0) if t.get("esperando") == "nombre" else 0
        t["veces_nombre"] = vez + 1
        t["esperando"] = "nombre"
        if quien == "otra_persona":
            frases = ["¿Cómo se llama la persona que se va a atender? Nombre y apellido.",
                      "¿Me pasás el nombre y apellido de quien se va a atender?",
                      "Para reservarlo necesito su nombre y apellido, por ejemplo: *Ana Pérez*."]
        else:
            frases = ["¿A nombre de quién agendo el turno? Necesito nombre y apellido.",
                      "Dale 😊 ¿Cómo es tu nombre y apellido, así lo agendo a tu nombre?",
                      "Para reservarlo necesito tu nombre y apellido, por ejemplo: *Juan Pérez*."]
        return frases[min(vez, len(frases) - 1)], None
    if not t.get("apellido"):
        t["esperando"] = "apellido"
        return f"¿Y el apellido de {t['nombre']}?", None
    return None


def _falta_obra_social(t: dict):
    if t.get("obra_social"):
        return None
    titular = t.get("titular")
    previa = t.get("os_previa") or {}
    if titular and previa.get("os") and _norm(previa.get("quien", "")) == _norm(titular.get("nombre_completo", "")) \
            and not t.get("os_dicha") and not t.get("cobertura") and t.get("os_confirmada") != "cambio":
        # Ya la confirmó en esta misma conversación: no se repregunta.
        t["obra_social"] = previa["os"]
        return None
    if titular and titular.get("obra_social") and t.get("os_confirmada") != "cambio" \
            and not t.get("os_dicha") and not t.get("cobertura"):
        if t.get("os_confirmada") == "si":
            t["obra_social"] = titular["obra_social"]
            return None
        # Pedido de Claudio (16/11): la de la ficha se confirma; puede haber
        # cambiado de obra social desde la última vez.
        t["esperando"] = "confirmar_os"
        set_opciones_ofrecidas([BOTON_SI, BOTON_CAMBIO], siempre=True, tipo="botones")
        os_ficha = titular["obra_social"]
        if os_ficha.lower() == "particular":
            return "¿Seguís atendiéndote como *particular*?", None
        return f"¿Seguís con *{os_ficha}*?", None

    if t.get("os_dicha"):
        dicha = t.pop("os_dicha")
        try:
            _, v = _post("/api/bot/verificar-obra-social", {"obra_social": dicha}, timeout=15)
        except Exception:
            v = {}
        if v.get("cubierta"):
            t["obra_social"] = v["nombre"]
            return None
        try:
            lista = _get("/api/bot/obras-sociales", {"q": dicha})
        except Exception:
            lista = {}
        parecidas = lista.get("activas") or v.get("parecidas") or []
        t["esperando"] = "obra_social"
        if parecidas:
            t["os_ofrecidas"] = parecidas[:9]
            set_opciones_ofrecidas(t["os_ofrecidas"] + [BOTON_PARTICULAR], siempre=True,
                                   titulo="Obras sociales", boton="Elegir")
            if lista.get("hay_mas"):
                return (f"Encontré varias que empiezan con «{dicha}». Elegí la tuya, o "
                        "escribime una letra más para achicar la búsqueda."), None
            return "¿Es alguna de estas?", None
        set_opciones_ofrecidas([BOTON_PARTICULAR, BOTON_TENGO_OS], siempre=True, tipo="botones")
        t["esperando"] = "cobertura"
        return (f"No trabajamos con «{dicha}». Si querés, te doy el turno como "
                "particular, o escribime de nuevo el nombre de tu obra social."), None

    if t.get("cobertura") == "obra_social":
        try:
            lista = _get("/api/bot/obras-sociales", {})
        except Exception:
            lista = {}
        t["os_ofrecidas"] = (lista.get("activas") or [])[:9]
        t["esperando"] = "obra_social"
        set_opciones_ofrecidas(t["os_ofrecidas"], siempre=True, titulo="Obras sociales", boton="Elegir")
        return ("Elegí tu obra social de la lista: tocá *Elegir* acá abajo 👇 Si no la ves, "
                "escribime las primeras letras."), None

    t["esperando"] = "cobertura"
    set_opciones_ofrecidas([BOTON_TENGO_OS, BOTON_PARTICULAR], siempre=True, tipo="botones")
    nombre = t.get("nombre")
    para = f" de {nombre}" if nombre and not t.get("titular") and t.get("para_quien") == "otra_persona" else ""
    return f"¿La atención{para} sería con obra social o particular?", None


def _disponibilidad(t: dict, fecha: str, obra_social: str | None = None) -> tuple[int, dict]:
    payload = {
        "reason": t["motivo"], "date": fecha,
        "obra_social": obra_social or t.get("obra_social") or "Particular",
        "preferencia_horaria": t.get("preferencia_horaria"),
        "profesional_pedido": t.get("profesional"),
    }
    try:
        return _post("/api/bot/availability", payload)
    except Exception as e:
        logger.error("FLUJO_TURNO -> disponibilidad falló: %s", e)
        return 0, {}


def _sin_cupo(t: dict, d: dict):
    """No hay turnos en el horizonte de búsqueda (4 semanas). Nunca el mismo
    texto ni un "llamá" seco: se busca más adelante, se prueba como particular
    y se ofrecen salidas con botones (chat real 24/11)."""
    from datetime import date, timedelta
    from backend.services.appointment_service import get_clinic_now
    base = t.get("dia") or get_clinic_now().date().isoformat()
    if not t.get("busco_lejos"):
        t["busco_lejos"] = True
        lejos = (date.fromisoformat(base) + timedelta(days=28)).isoformat()
        estado_http, d2 = _disponibilidad(t, lejos)
        if estado_http == 200 and d2.get("available_slots"):
            return d2, "En las próximas cuatro semanas no me quedan turnos. "

    opciones = [BOTON_OTRO_DIA]
    extra = ""
    os_actual = t.get("obra_social") or "Particular"
    if os_actual != "Particular" and os_actual.strip().upper() != "PAMI":
        # A un paciente de PAMI no se le ofrece pagar como particular por
        # iniciativa del bot (Claudio 25/11); si lo pide él, igual se puede.
        estado_http, d3 = _disponibilidad(t, t.get("dia") or "", "Particular")
        if estado_http == 200 and d3.get("available_slots"):
            extra = (f" Como *particular* sí tengo lugar desde el "
                     f"{d3.get('fecha_texto') or d3.get('date')}.")
        opciones.append(BOTON_PARTICULAR)
    opciones.append(BOTON_LLAMAR)

    vez = t.get("sin_cupo", 0)
    t["sin_cupo"] = vez + 1
    t["esperando"] = "sin_cupo"
    t.pop("dia", None)
    t.pop("busco_lejos", None)
    set_opciones_ofrecidas(opciones, siempre=True, tipo="botones")
    con = f" con {os_actual}" if os_actual != "Particular" else ""
    franja = " en esa franja" if t.get("preferencia_horaria") else ""
    frases = [
        f"Para {t['motivo'].lower()}{con} no me quedan turnos libres{franja} en las próximas semanas.{extra} "
        f"¿Querés que busque otro día, o preferís llamar al consultorio?",
        f"Sigo sin lugar para {t['motivo'].lower()}{con}{franja}.{extra} Podés elegir otro día "
        f"o una franja distinta, o llamar al {telefono_consultorio()}.",
    ]
    return None, frases[min(vez, len(frases) - 1)]


def _ofrecer_horarios(t: dict):
    desde = t.pop("desde", None) if not t.get("dia") else None
    estado_http, d = _disponibilidad(t, t.get("dia") or desde or "")
    slots = d.get("available_slots") or []
    aviso = ""
    if estado_http != 200 or not slots:
        if d.get("message") and "no hace" in d["message"]:
            # Pidió a alguien que no hace esa práctica: se le dice quién sí.
            t.pop("profesional", None)
            m = re.search(r"Eso lo atiende (.+?)\. Preguntale", d["message"])
            quien = m.group(1) if m else "otro profesional"
            pedido = d["message"].split(" no hace ")[0]
            t["esperando"] = "horario_con_otro"
            return (f"{t['motivo']} no la hace {pedido}: la atiende {quien}. "
                    f"¿Querés que te busque turno con {'ella' if 'Dra' in quien else 'él'}?"), None
        d, aviso = _sin_cupo(t, d)
        if d is None:
            return aviso, None
        slots = d.get("available_slots") or []

    t.pop("sin_cupo", None)
    t.pop("busco_lejos", None)
    t["oferta"] = {"fecha": d["date"], "fecha_texto": d.get("fecha_texto") or d["date"],
                   "profesional": d.get("professional") or "", "slots": slots[:9]}
    t["pagina"] = 0
    t["esperando"] = "horario"
    t.pop("no_le_sirvio", None)
    if t.pop("paso_a_particular", None) and not aviso:
        aviso = "Dale, lo busco como particular. "
    if aviso:
        pass
    elif desde:
        aviso = "Te busco otra fecha. "
    elif d.get("movido") and d.get("fecha_pedida_texto"):
        # Pidió un día y ahí no hay lugar: se le dice claro, sin reglas internas
        # (los viernes PAMI no se explican). Si el motivo es que el profesional
        # no atiende ese día, eso sí le sirve saberlo.
        salto = d.get("motivo_salto") or ""
        if "no atiende" in salto:
            aviso = salto.rstrip(".") + ". "
        else:
            aviso = f"El {d['fecha_pedida_texto']} no tengo turnos para {t['motivo'].lower()}. "
        aviso = aviso[0].upper() + aviso[1:]
    elif not t.get("dia"):
        # No pidió día: si lo primero libre cae en otra semana, se explica el salto.
        from datetime import date
        from backend.services.appointment_service import get_clinic_now
        hoy = get_clinic_now().date()
        try:
            ofrecida = date.fromisoformat(str(d["date"])[:10])
        except ValueError:
            ofrecida = hoy
        if ofrecida.isocalendar()[:2] != hoy.isocalendar()[:2]:
            aviso = (f"Esta semana ya no me quedan turnos para {t['motivo'].lower()}; "
                     f"el primero libre es la semana que viene. "
                     if (ofrecida - hoy).days <= 13 else
                     f"Esta semana ya no me quedan turnos para {t['motivo'].lower()}. ")
    _botones_horarios(t)
    nombre = _nombre_de_quien_escribe(t)
    if t.get("reprogramar"):
        inicio = "Para cambiarlo"
    else:
        inicio = f"Para {t['motivo'].lower()}"
    if nombre:
        inicio = f"{nombre}, {inicio[0].lower()}{inicio[1:]}"
    return (f"{aviso}{inicio} te puede atender {t['oferta']['profesional']} el "
            f"*{t['oferta']['fecha_texto']}*." + _como_elegir(t)), None


def _alta(t: dict, hora: str, telefono: str) -> tuple[int, dict]:
    o = t["oferta"]
    try:
        if t.get("reprogramar"):
            estado_http, d = _post("/api/bot/reschedule", {
                "appointment_id": t["reprogramar"], "new_start_time": f"{o['fecha']}T{hora}:00",
                "requester_phone": telefono})
            return estado_http, {**d, "professional": o.get("profesional")}
        payload = {
            "reason": t["motivo"], "preferred_date": f"{o['fecha']} {hora}",
            "patient_name": t.get("nombre") or "", "patient_last_name": t.get("apellido") or "",
            "insurance_name": t.get("obra_social") or "Particular",
            "profesional_pedido": o.get("profesional") or None,
            "preferencia_horaria": t.get("preferencia_horaria"),
            "requester_phone": telefono,
        }
        if t.get("orto_vez") and t["orto_vez"] != "-":
            payload["notes"] = f"Ortodoncia: {t['orto_vez']}"
        return _post("/api/bot/appointments", payload)
    except Exception as e:
        return 0, {"detail": str(e)}


def _confirmacion(t: dict, d: dict) -> str:
    o = t["oferta"]
    t["terminado"] = True
    # Para entender un "mejor a las 17:30" justo después de confirmar.
    t["recien"] = {
        "id": str(d.get("appointment_id") or t.get("reprogramar") or ""),
        "date": f"{o['fecha']} {t['hora']}:00", "reason": t.get("motivo"),
        "professional": d.get("professional") or o.get("profesional"),
        "insurance": t.get("obra_social"),
        "paciente": f"{t.get('nombre') or ''} {t.get('apellido') or ''}".strip(),
    }
    nombre = _nombre_de_quien_escribe(t)
    listo = f"¡Listo, {nombre}! 😊" if nombre else "¡Listo! 😊"
    profesional = d.get("professional") or o["profesional"]
    if t.get("reprogramar"):
        return (f"{listo} Te pasé el turno de {t['motivo'].lower()} al *{o['fecha_texto']} a las "
                f"{t['hora']}* con {profesional}. El horario anterior quedó libre.")
    para = "" if t.get("titular") or t.get("para_quien") == "yo" else f" para {t.get('nombre')}"
    link = d.get("cancel_url")
    return (f"{listo} Quedó agendado el turno{para} de {t['motivo'].lower()} con "
            f"{profesional} el *{o['fecha_texto']} a las "
            f"{t['hora']}*.\n\nSi querés otro horario, decímelo y lo cambio. Si necesitás "
            f"cancelarlo, escribime"
            + (f" o entrá a este link: {link}" if link else "."))


def _agendar(t: dict, telefono: str):
    estado_http, d = _alta(t, t["hora"], telefono)
    if estado_http == 200:
        t["agendado"] = True
        return _confirmacion(t, d), None

    detalle = str(d.get("detail") or "")
    logger.warning("FLUJO_TURNO -> el alta falló (%s): %s", estado_http, detalle[:200])
    m = re.search(r"appointment_id=([0-9a-f-]{36})", detalle)
    if m and "ya tiene un turno" in detalle:
        # Ya tiene uno del mismo tipo: no se duplica, se le muestra el que tiene
        # (simulación 24/11: terminaba en "problema del sistema").
        existente = next((x for x in (_mis_turnos(telefono) or []) if x["id"] == m.group(1)), None)
        if existente:
            from datetime import datetime as _dt
            from backend.services.appointment_service import fecha_en_palabras
            cuando = _dt.fromisoformat(str(existente["date"]))
            existente.update(fecha_texto=fecha_en_palabras(cuando.date()), hora=cuando.strftime("%H:%M"))
            t["terminado"] = True
            t["previo_sugerido"] = {"esperando": "confirmar", "turno": existente}
            set_opciones_ofrecidas([BOTON_CONFIRMO, BOTON_CAMBIAR], siempre=True, tipo="botones")
            return (f"Ya tenés un turno de {(existente.get('reason') or 'consulta').lower()} el "
                    f"*{existente['fecha_texto']} a las {existente['hora']}* con "
                    f"{existente['professional']}. Para no duplicarlo: ¿lo confirmás o querés "
                    f"cambiarlo?"), None
    if "apellido" in detalle.lower():
        t["esperando"] = "apellido"
        t.pop("apellido", None)
        return f"Me falta el apellido de {t.get('nombre')}. ¿Cuál es?", None
    if "a nombre de quién" in detalle.lower() or "primera vez" in detalle.lower():
        t["esperando"] = "nombre"
        t.pop("nombre", None)
        t.pop("apellido", None)
        return "¿A nombre de quién agendo el turno? Necesito nombre y apellido.", None
    if "ocupado" in detalle.lower() or "disponible" in detalle.lower() or "tomado" in detalle.lower() \
            or "ya tiene otro turno" in detalle.lower() or estado_http == 409:
        o = t.pop("oferta", None) or {}
        fallida = t.pop("hora", None)
        texto, op = _ofrecer_horarios(t)
        nueva = t.get("oferta") or {}
        if fallida and nueva.get("fecha") == o.get("fecha") and fallida in nueva.get("slots", []):
            # Nunca volver a ofrecer la hora que recién falló.
            nueva["slots"] = [h for h in nueva["slots"] if h != fallida]
            _botones_horarios(t)
        return "Ese horario se acaba de ocupar. " + texto, op
    t["terminado"] = True
    return ("No pude confirmar el turno por un problema del sistema. " + _texto_llamar()), None
