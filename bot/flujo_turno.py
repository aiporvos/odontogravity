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

Cancelar, reprogramar y consultar turnos siguen en el agente general
(`ai_agent.chat`), que recibe la charla cuando el paciente pide eso.
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
    elif m := re.search(r"\b(\d{1,2})/(\d{1,2})\b", n):
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
            "sacar_turno", "cancelar_turno", "reprogramar_turno",
            "consultar_mis_turnos", "dar_datos", "pregunta", "saludo_o_cierre", "otro"]},
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

- intencion: sacar_turno si pide un turno; cancelar_turno / reprogramar_turno / consultar_mis_turnos si quiere eso con un turno que YA tiene; dar_datos si responde lo que se le preguntó; pregunta si consulta algo del consultorio (dirección, precios, horarios, si atienden X); saludo_o_cierre; otro.
- motivo: el tipo de consulta que pide, elegido de esta lista (usá el nombre exacto): {tipos}. "sacarme una muela" = Extracción; "arreglo de una caries" = Arreglos; brackets, aparatos o "control de ortodoncia" = Ortodoncia (NUNCA Control); si el turno es para un niño o niña (menor de 14 años) = Odontopediatría, aunque diga control o dolor. Para conducto/endodoncia devolvé "Conducto". Si dice un síntoma sin práctica clara ("me duele una muela") devolvé "Consulta" solo si existe; si no, null.
- para_quien: "yo" si el turno es para quien escribe ("para mí", "mío", "yo", "soy yo"); "otra_persona" si es para otro ("para mi hijo", "para mi mamá Ana"). nombre/apellido: de la persona que se atiende, solo si los dice.
- cobertura: "particular" o "obra_social" si lo dice. obra_social: el nombre o las letras que escribió si responde a qué obra social tiene ("osde", "swi", "pami").
- dia: la expresión de día tal cual la dijo ("el lunes", "mañana", "16/11", "un martes", "la semana que viene"). preferencia_horaria: "mañana", "tarde", "después de las 18", "temprano", etc.
- hora: si elige o nombra una hora, en HH:MM ("a las 5 de la tarde" = 17:00).
- profesional: si pide un profesional por nombre.
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
    return {k: v for k, v in (estado or {}).items() if k != CLAVE}


def responder(mensaje: str, history: list[dict], estado: dict, telefono: str,
              dichos: list[str]):
    """(texto, opciones, estado) si el mensaje es del flujo de turnos; si no, None."""
    estado = dict(estado or {})
    t = dict(estado.get(CLAVE) or {})
    respuestas_bot = [m["content"] for m in (history or []) if m.get("role") == "assistant"]
    ultima = respuestas_bot[-1] if respuestas_bot else ""

    # Botones y respuestas cortas que se resuelven sin la IA.
    from bot.tools.appointment_tools import motivo_por_boton_conducto
    motivo_boton = motivo_por_boton_conducto(mensaje, ultima) if t.get("esperando") == "conducto" else None

    datos = extraer(mensaje, ultima if t else "")
    intencion = datos.get("intencion")

    if not t:
        if intencion != "sacar_turno" and not (intencion == "dar_datos" and datos.get("motivo")):
            return None
        t = {"activo": True}
        logger.info("FLUJO_TURNO -> empieza")
    elif intencion in ("cancelar_turno", "reprogramar_turno", "consultar_mis_turnos"):
        logger.info("FLUJO_TURNO -> el paciente pide %s: pasa al agente general", intencion)
        return None

    aparte = ""
    if datos.get("pregunta") and intencion == "pregunta":
        aparte = responder_pregunta(datos["pregunta"])

    _incorporar(t, datos, mensaje, motivo_boton)
    texto, opciones = _siguiente_paso(t, telefono, dichos + [mensaje])

    # Si vuelve a decir exactamente lo mismo, no se entendieron: se aclara una
    # vez y a la tercera se lo manda al teléfono, nunca un círculo sin salida.
    if texto and texto in (ultima or "") and not t.get("terminado"):
        t["repeticiones"] = t.get("repeticiones", 0) + 1
        if t["repeticiones"] >= 2:
            t["terminado"] = True
            set_opciones_ofrecidas(None)
            texto = (f"Perdón, no logro entenderte bien por acá 🙏 Para no hacerte perder "
                     f"tiempo, llamá al consultorio al {telefono_consultorio()} y te dan el "
                     f"turno enseguida.")
        else:
            texto = "Perdón, no te entendí bien. " + texto
    elif not t.get("terminado"):
        t["repeticiones"] = 0

    if t.get("terminado"):
        # Pedido cerrado: el siguiente arranca limpio. Si quedaran el motivo o
        # el día, el próximo turno (o el agente general) los heredaba.
        estado = {k: v for k, v in _cortar_flujo(estado).items()
                  if k not in ("motivo", "fecha_hora", "paciente")}
        if t.get("agendado"):
            estado["accion_hecha"] = True
    else:
        estado[CLAVE] = t
        # Compatibilidad con el agente general, que lee estas claves del estado.
        for k in ("motivo", "obra_social"):
            if t.get(k):
                estado[k] = t[k]
    if not history:
        nombre = t.get("ficha_nombre")
        texto = f"¡{_saludo().capitalize()}{', ' + nombre if nombre else ''}! 😊 {texto}"
    if aparte:
        texto = f"{aparte}\n\n{texto}"
    return texto, tomar_opciones_ofrecidas(), estado


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

    # Para quién
    if esperando == "para_quien" and _es(mensaje, BOTON_PARA_MI):
        t["para_quien"] = "yo"
    elif esperando == "para_quien" and _es(mensaje, BOTON_OTRA_PERSONA):
        t["para_quien"] = "otra_persona"
    elif esperando == "para_quien" and any(_es(mensaje, n) for n in t.get("familia", [])):
        t["para_quien"], t["nombre_elegido"] = "familiar", mensaje.strip()
    elif d.get("para_quien"):
        t["para_quien"] = d["para_quien"]
    if d.get("nombre") and (esperando in ("nombre", "apellido", "para_quien") or d.get("para_quien")):
        t["nombre"] = d["nombre"].strip().title()
    if d.get("apellido") and (esperando in ("nombre", "apellido", "para_quien") or d.get("para_quien")):
        t["apellido"] = d["apellido"].strip().title()

    # Obra social de la ficha: se confirma, no se da por hecha.
    if esperando == "confirmar_os":
        if d.get("obra_social") or d.get("cobertura"):
            t["os_confirmada"] = "cambio"      # dijo cuál tiene ahora: sigue abajo
        elif _es(mensaje, BOTON_SI) or d.get("respuesta_si_no") == "si":
            t["os_confirmada"] = "si"
        elif _es(mensaje, BOTON_CAMBIO) or d.get("respuesta_si_no") == "no":
            t["os_confirmada"] = "cambio"

    # Obra social
    if esperando == "cobertura" and _es(mensaje, BOTON_PARTICULAR):
        t["obra_social"] = "Particular"
    elif esperando == "cobertura" and _es(mensaje, BOTON_TENGO_OS):
        t["cobertura"] = "obra_social"
    elif esperando in ("obra_social", "cobertura") and any(_es(mensaje, o) for o in t.get("os_ofrecidas", [])):
        t["os_dicha"] = next(o for o in t["os_ofrecidas"] if _es(mensaje, o))
    elif esperando == "obra_social":
        # En este paso, lo que escribe ES la obra social (o sus primeras letras).
        if d.get("cobertura") == "particular":
            t["obra_social"] = "Particular"
        else:
            t["os_dicha"] = (d.get("obra_social") or mensaje).strip(" .,;!¡?¿")
    else:
        if d.get("cobertura") == "particular":
            t["obra_social"] = "Particular"
        elif d.get("obra_social"):
            t["os_dicha"] = d["obra_social"]
        elif d.get("cobertura") == "obra_social":
            t["cobertura"] = "obra_social"

    # Día, franja, profesional
    if d.get("dia"):
        iso = _fecha_iso(d["dia"])
        if iso and iso != t.get("dia") and iso != (t.get("oferta") or {}).get("fecha"):
            t["dia"] = iso
            t.pop("oferta", None)
    if d.get("preferencia_horaria") and d["preferencia_horaria"] != t.get("preferencia_horaria"):
        t["preferencia_horaria"] = d["preferencia_horaria"]
        t.pop("oferta", None)
    if d.get("profesional") and d["profesional"] != t.get("profesional"):
        t["profesional"] = d["profesional"]
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
        hora = _hora_elegida(mensaje, oferta.get("slots", []))
        if not hora and d.get("hora") in oferta.get("slots", []):
            hora = d["hora"]
        if hora:
            t["hora"] = hora
    if not t.get("hora") and d.get("hora"):
        # Nombró una hora para otro día ("el martes 24 a las 10:30"): si está
        # libre cuando se busque ese día, se agenda sin volver a preguntar.
        t["hora_pedida"] = d["hora"]


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


def _siguiente_paso(t: dict, telefono: str, dichos: list[str]):
    """Valida lo que haya y pregunta lo primero que falte, en orden fijo."""
    set_opciones_ofrecidas(None)

    # 1. Motivo
    if not t.get("motivo"):
        if t.get("motivo_propuesto"):
            ok, motivo, razon = _validar_motivo(t["motivo_propuesto"], dichos, telefono)
            if ok:
                t["motivo"] = motivo
            else:
                return _motivo_rechazado(t, razon)
        else:
            t["esperando"] = "motivo"
            return ("¿Para qué sería el turno? Por ejemplo: limpieza, control, "
                    "extracción, arreglo o conducto."), None

    # 2. Para quién
    if not t.get("identificado"):
        _identificar(t, telefono)
    falta = _falta_persona(t)
    if falta:
        return falta

    # 3. Obra social
    falta = _falta_obra_social(t)
    if falta:
        return falta

    # 4 y 5. Profesional (lo decide la agenda), día y horario
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
                return _confirmacion(t, d), None
            set_opciones_ofrecidas(t["oferta"]["slots"] + [BOTON_OTRO_DIA], siempre=True,
                                   titulo="Horarios", boton="Elegir horario")
            return f"A las {pedida} ya no tengo lugar ese día. " + texto, opciones
        t["hora"] = pedida
    if not t.get("hora") and t.pop("insiste", None):
        from backend.services.appointment_service import fecha_en_palabras
        from datetime import date
        o = t["oferta"]
        set_opciones_ofrecidas(o["slots"] + [BOTON_OTRO_DIA], siempre=True,
                               titulo="Horarios", boton="Elegir horario")
        return (f"Ya me fijé: el {fecha_en_palabras(date.fromisoformat(t['dia']))} no tengo "
                f"lugar para {t['motivo'].lower()}. Lo más cercano es el *{o['fecha_texto']}* "
                f"con {o['profesional']}. ¿Te sirve alguno de esos horarios, o preferís otro día?"), None
    if not t.get("hora"):
        t["esperando"] = "horario"
        o = t["oferta"]
        set_opciones_ofrecidas(o["slots"] + [BOTON_OTRO_DIA], siempre=True,
                               titulo="Horarios", boton="Elegir horario")
        return (f"Elegí uno de los horarios del *{o['fecha_texto']}* con "
                f"{o['profesional']}, o pedime otro día."), None

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
            "profesional que corresponde (limpieza, control, extracción, arreglo, conducto…)."), None


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


def _falta_persona(t: dict):
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
    if quien == "listo":
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

    # Número nuevo, u otra persona: hacen falta nombre y apellido.
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
        return ("Elegí tu obra social de la lista. Si no la ves, escribime las "
                "primeras letras."), None

    t["esperando"] = "cobertura"
    set_opciones_ofrecidas([BOTON_TENGO_OS, BOTON_PARTICULAR], siempre=True, tipo="botones")
    para = "" if t.get("titular") or t.get("para_quien") == "yo" else f" de {t.get('nombre')}"
    return f"¿La atención{para} sería con obra social o particular?", None


def _ofrecer_horarios(t: dict):
    desde = t.pop("desde", None) if not t.get("dia") else None
    payload = {
        "reason": t["motivo"], "date": t.get("dia") or desde or "",
        "obra_social": t.get("obra_social") or "Particular",
        "preferencia_horaria": t.get("preferencia_horaria"),
        "profesional_pedido": t.get("profesional"),
    }
    try:
        estado_http, d = _post("/api/bot/availability", payload)
    except Exception as e:
        logger.error("FLUJO_TURNO -> disponibilidad falló: %s", e)
        estado_http, d = 0, {}
    slots = d.get("available_slots") or []
    if estado_http != 200 or not slots:
        t["esperando"] = "dia"
        t.pop("dia", None)
        if d.get("message") and "no hace" in d["message"]:
            # Pidió a alguien que no hace esa práctica: se le dice quién sí.
            t.pop("profesional", None)
            m = re.search(r"Eso lo atiende (.+?)\. Preguntale", d["message"])
            quien = m.group(1) if m else "otro profesional"
            pedido = d["message"].split(" no hace ")[0]
            t["esperando"] = "horario_con_otro"
            return (f"{t['motivo']} no la hace {pedido}: la atiende {quien}. "
                    f"¿Querés que te busque turno con {'ella' if 'Dra' in quien else 'él'}?"), None
        return (f"No encontré turnos libres para {t['motivo'].lower()} en las próximas "
                f"semanas{' con esa preferencia' if t.get('preferencia_horaria') else ''}. "
                f"Podés pedirme otro día o franja, o llamar al consultorio al "
                f"{telefono_consultorio()}."), None

    t["oferta"] = {"fecha": d["date"], "fecha_texto": d.get("fecha_texto") or d["date"],
                   "profesional": d.get("professional") or "", "slots": slots[:9]}
    t["esperando"] = "horario"
    aviso = ""
    no_sirvio = t.pop("no_le_sirvio", None)
    if desde:
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
    set_opciones_ofrecidas(t["oferta"]["slots"] + [BOTON_OTRO_DIA], siempre=True,
                           titulo="Horarios", boton="Elegir horario")
    return (f"{aviso}Para {t['motivo'].lower()} te puede atender {t['oferta']['profesional']} el "
            f"*{t['oferta']['fecha_texto']}*. ¿Qué horario te queda mejor?"), None


def _alta(t: dict, hora: str, telefono: str) -> tuple[int, dict]:
    o = t["oferta"]
    payload = {
        "reason": t["motivo"], "preferred_date": f"{o['fecha']} {hora}",
        "patient_name": t.get("nombre") or "", "patient_last_name": t.get("apellido") or "",
        "insurance_name": t.get("obra_social") or "Particular",
        "profesional_pedido": o.get("profesional") or None,
        "preferencia_horaria": t.get("preferencia_horaria"),
        "requester_phone": telefono,
    }
    try:
        return _post("/api/bot/appointments", payload)
    except Exception as e:
        return 0, {"detail": str(e)}


def _confirmacion(t: dict, d: dict) -> str:
    o = t["oferta"]
    t["terminado"] = True
    para = "" if t.get("titular") or t.get("para_quien") == "yo" else f" para {t.get('nombre')}"
    link = d.get("cancel_url")
    return (f"¡Listo! 😊 Quedó agendado el turno{para} de {t['motivo'].lower()} con "
            f"{d.get('professional') or o['profesional']} el *{o['fecha_texto']} a las "
            f"{t['hora']}*.\n\nSi necesitás cancelarlo, escribime"
            + (f" o entrá a este link: {link}" if link else "."))


def _agendar(t: dict, telefono: str):
    estado_http, d = _alta(t, t["hora"], telefono)
    if estado_http == 200:
        t["agendado"] = True
        return _confirmacion(t, d), None

    detalle = str(d.get("detail") or "")
    logger.warning("FLUJO_TURNO -> el alta falló (%s): %s", estado_http, detalle[:200])
    if "apellido" in detalle.lower():
        t["esperando"] = "apellido"
        t.pop("apellido", None)
        return f"Me falta el apellido de {t.get('nombre')}. ¿Cuál es?", None
    if "a nombre de quién" in detalle.lower() or "primera vez" in detalle.lower():
        t["esperando"] = "nombre"
        t.pop("nombre", None)
        t.pop("apellido", None)
        return "¿A nombre de quién agendo el turno? Necesito nombre y apellido.", None
    if "ocupado" in detalle.lower() or "disponible" in detalle.lower() or estado_http == 409:
        t.pop("oferta", None)
        t.pop("hora", None)
        texto, op = _ofrecer_horarios(t)
        return "Ese horario se acaba de ocupar. " + texto, op
    t["terminado"] = True
    return (f"No pude confirmar el turno por un problema del sistema. Para no hacerte "
            f"perder tiempo, llamá al consultorio al {telefono_consultorio()} y te lo dan "
            f"enseguida."), None
