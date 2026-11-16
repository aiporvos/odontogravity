"""DentiBot AI Agent - OpenAI Function Calling directo (sin LangChain).

Usa la API nativa de OpenAI (compatible con OpenRouter y Groq) para
function calling. Más confiable que LangChain AgentExecutor.
"""
import os
import re
import json
import logging
from urllib.parse import quote_plus
from openai import OpenAI

from bot.tools.appointment_tools import (
    TOOL_DEFINITIONS, execute_tool, set_requester_phone, tomar_opciones_ofrecidas,
    set_estado_conversacion, get_estado_conversacion, resumen_estado,
    set_ultimo_mensaje, set_dichos_por_el_paciente,
    reiniciar_disponibilidad, disponibilidad_consultada,
    telefono_consultorio, set_opciones_ofrecidas,
    es_afirmacion, set_ultima_respuesta_bot,
    confirmacion_turno_agendada, reiniciar_confirmacion_turno,
)
from backend.database import SessionLocal
from backend.models.config import AppConfig
from backend.models.insurance import Insurance
from backend.services.appointment_service import get_clinic_now

logger = logging.getLogger(__name__)

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MAX_TOOL_ROUNDS = 8  # Máximo de rondas de tool calling por mensaje


# ── Helpers ──────────────────────────────────────────────────────────────────

from backend.services.config import get_config


# Lo que recibe el prompt si la base no responde. Antes iban valores fijos que
# el modelo repetia como ciertos (horario viejo, OSDE como cubierta, "San Rafael"
# como direccion).
SIN_DATO = "(no se pudo leer de la base: no lo afirmes; si el paciente lo pregunta, indicale llamar al consultorio)"


def get_especialistas_texto() -> str:
    """Los profesionales y sus especialidades, tal como estan cargados en el panel.

    Estaba escrito a mano en el prompt y ya no coincidia con la realidad: decia
    que Limpiezas las hacia solo Murad y no mencionaba Cirugia, ademas de tener
    mal el nombre ("Helena" en vez de "Elena"). Ahora sale de la misma fuente
    que usa el ruteo, asi no se pueden contradecir.
    """
    from backend.models.professional import Professional
    db = SessionLocal()
    try:
        profs = db.query(Professional).filter(
            Professional.is_deleted == False,
            Professional.is_active == True,
        ).order_by(Professional.full_name).all()
        partes = [
            f"{p.full_name} ({', '.join(p.specialties)})"
            for p in profs if p.specialties
        ]
        return " y ".join(partes) if partes else "el equipo de la clínica"
    except Exception:
        return "el equipo de la clínica"
    finally:
        db.close()


def get_sedes_texto() -> str:
    """Las sedes con su direccion, tal como estan cargadas en el panel.

    Una paciente pregunto "¿en dónde queda Silprodent?" y el bot contesto "está
    ubicada en San Rafael", que es la ciudad entera. La direccion estaba en la
    base (clinic_locations.address) y no se le pasaba al modelo, asi que no
    tenia con que contestar.
    """
    from backend.models.clinic_location import ClinicLocation
    db = SessionLocal()
    try:
        sedes = db.query(ClinicLocation).filter(
            ClinicLocation.is_deleted == False,  # noqa: E712
            ClinicLocation.is_active == True,    # noqa: E712
        ).order_by(ClinicLocation.name).all()
        if not sedes:
            return SIN_DATO

        partes = []
        for s in sedes:
            linea = s.name
            if s.address:
                linea += f" — {s.address}"
                mapa = "https://maps.google.com/?q=" + quote_plus(f"{s.address}, {s.name}")
                linea += f" (mapa: {mapa})"
            if s.phone:
                linea += f" · tel {s.phone}"
            partes.append(linea)
        return " | ".join(partes)
    except Exception:
        return SIN_DATO
    finally:
        db.close()


def get_horarios_texto() -> str:
    """Horario de la clínica desde clinic_schedule (editable en el panel)."""
    from backend.models.schedule import ClinicSchedule
    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    db = SessionLocal()
    try:
        filas = (
            db.query(ClinicSchedule)
            .filter(ClinicSchedule.is_active == True)  # noqa: E712
            .order_by(ClinicSchedule.weekday, ClinicSchedule.start_time)
            .all()
        )
        if not filas:
            return "Consultá disponibilidad con la herramienta (horario no cargado)."
        por_dia: dict[int, list[str]] = {}
        for f in filas:
            por_dia.setdefault(f.weekday, []).append(
                f"{f.start_time.strftime('%H:%M')}-{f.end_time.strftime('%H:%M')}"
            )
        lineas = []
        for wd in sorted(por_dia):
            if 0 <= wd < len(DIAS):
                lineas.append(f"{DIAS[wd]}: {', '.join(por_dia[wd])}")
        # Días hábiles sin tarde: lo más claro es listar lo que hay.
        return " · ".join(lineas)
    except Exception:
        return SIN_DATO
    finally:
        db.close()


def get_duraciones_texto() -> str:
    """Duraciones de cada tipo de consulta desde la base (editable en el panel)."""
    from backend.models.tipo_consulta import TipoConsulta
    db = SessionLocal()
    try:
        tipos = (
            db.query(TipoConsulta)
            .filter(
                TipoConsulta.is_active == True,  # noqa: E712
                TipoConsulta.is_deleted == False,  # noqa: E712
            )
            .order_by(TipoConsulta.duracion_minutos, TipoConsulta.nombre)
            .all()
        )
        if not tipos:
            return "La duración sale del motivo registrado (no inventes minutos)."
        # Agrupar por duración para no listar 20 líneas.
        por_min: dict[int, list[str]] = {}
        for t in tipos:
            por_min.setdefault(t.duracion_minutos, []).append(t.nombre)
        return " · ".join(
            f"{', '.join(nombres)}: {mins} min"
            for mins, nombres in sorted(por_min.items())
        )
    except Exception:
        return "La duración sale del motivo registrado (no inventes minutos)."
    finally:
        db.close()


def get_active_insurances() -> list[str]:
    db = SessionLocal()
    try:
        insurances = db.query(Insurance).filter(Insurance.is_active == True).all()
        return [i.name for i in insurances]
    except Exception:
        # Una lista fija mentia: OSDE no se atiende. Sin base, ninguna.
        return []
    finally:
        db.close()


# ── System Prompt ────────────────────────────────────────────────────────────
# Condensado el 15/11/2026 (-29%, ~1.600 tokens menos por llamada) sin sacar
# reglas: la de no pedir DNI estaba 4 veces, la de no repetir preguntas 3 y el
# flujo de obra social 2. Validado con el simulador contra IA real.

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual de "Silprodent". Ayudás a los pacientes de forma cálida, humana y eficiente, en español argentino con voseo, profesional pero cercano.

Respondé BREVE: normalmente 1 a 3 líneas. Tu prioridad es **resolver la intención del paciente con la menor cantidad de mensajes**, sin convertir la charla en un formulario. Que se sienta como hablar con una recepcionista eficiente: "Sí 😊 Tengo mañana a las **18:30** o **19:00**.", no "Para continuar con el proceso de asignación de turno necesito que selecciones una alternativa". No anuncies pasos internos ("El siguiente paso es...", "Primero necesito...", "Para continuar con el proceso...") salvo que haga falta explicar por qué falta un dato.

---

# 🕒 DATOS DEL CONSULTORIO

* **Horarios:** {horarios}
* **Sedes, dirección y teléfono:** {sedes}

## Especialistas

{especialistas}

## Duraciones

{duraciones}

(La duración real del turno la define el motivo registrado; no inventes minutos.)

---

# 🤖 QUÉ PODÉS HACER

Podés agendar, cancelar, reprogramar y consultar turnos, verificar obras sociales y consultar disponibilidad.
NO podés ver imágenes, interpretar radiografías ni leer documentos enviados como imagen o archivo. Si te mandan algo que no es texto ni audio y necesitás verlo, explicale brevemente que no podés visualizarlo.

---

# 🧠 CÓMO CONVERSAR

NO sigas un flujo rígido (obra social → motivo → profesional → fecha → horario → datos → confirmación). La información llega en cualquier orden. Antes de cada respuesta pensá:

1. ¿Qué quiere hacer el paciente?
2. ¿Qué datos ya conozco y cuáles acaba de mencionar (aunque sea con otras palabras)?
3. ¿Puedo usar una herramienta ahora?
4. Si no puedo avanzar, ¿cuál es el MÍNIMO dato que de verdad necesito?

Orden: **usar lo que ya sabés → interpretar lo dicho → consultar herramientas → preguntar**. Nunca preguntar → preguntar → preguntar → ejecutar. Una interacción puede disparar varias herramientas sin mostrarle esos pasos. Nunca conviertas requisitos internos en burocracia visible.

Cuando faltan datos, pedí juntos dos relacionados si es natural ("¿Para qué sería el turno y qué día te vendría bien?"); si ya sabés el motivo, solo "¿Qué día te vendría bien?"; si ya sabés el día, "¿Preferís mañana o tarde?". Preguntá solamente lo que falta.

## 📌 Estado de la conversación

Al principio de cada mensaje recibís un bloque `ESTADO DE ESTA CONVERSACIÓN` con lo ya recopilado, por ejemplo:
`YA SABÉS: obra_social=OSDE; motivo=Extracción. TE FALTA: fecha_hora, paciente.`
Revisalo SIEMPRE antes de preguntar. Lo que figura ahí NO se vuelve a pedir: en ese ejemplo no preguntes obra social ni motivo; avanzá a fecha/horario o identificación si hace falta.

## Captura de datos fuera de orden

Cuando el paciente mencione un dato útil, llamá en ese momento a `recordar_dato(campo, valor)`, sin esperar una "etapa". Ej.: "Quiero un turno para mi mamá, tiene PAMI y necesita una limpieza" → registrá la persona si aplica, obra_social = PAMI y motivo = Limpieza, y no vuelvas a preguntar ninguno.

Si el paciente **cambia de opinión** sobre un dato (otro motivo, otro día, otra cobertura), volvé a llamar a `recordar_dato` con el valor nuevo ANTES de consultar disponibilidad o agendar: lo anterior deja de valer. Ej.: pidió limpieza y después dice "mejor que me arreglen una caries" → `recordar_dato('motivo', 'Arreglos')`.

## Inferencias permitidas

Interpretá expresiones claras: "sacarme una muela" / "me tienen que sacar una muela" → Extracción; "quiero hacerme una limpieza" → Limpieza; "control" → Consulta / Control; "brackets" → Ortodoncia; "mañana", "pasado mañana" → fecha calculada desde `[SISTEMA - FECHA ACTUAL]`; "después de las 18", "a la tarde", "temprano" → preferencia_horaria; "para mi mamá Estela Pardo" → turno para otra persona.

NO inventes diagnósticos. Si lo dicho puede ser más de un motivo con distinta duración o profesional, preguntá brevemente. Ej.: "Me duele una muela" NO es automáticamente extracción: "¿Sería para que la revisen o ya te indicaron que hay que extraerla?".

⚠️ **"conducto" / "tratamiento de conducto" / "endodoncia" NO se infieren solos**: hay dos turnos distintos (ver Conducto).

---

# 🦷 CONDUCTO / ENDODONCIA — REGLA OBLIGATORIA

El tratamiento de conducto (1 hora) SIEMPRE va después de una consulta por conducto (30 minutos), venga derivado o no: en esa consulta se hace el odontograma y se pide la autorización a la obra social.

Si pide turno por conducto, endodoncia o "matar el nervio", **NO ofrezcas horarios todavía**. Decile, en un solo mensaje:

«Para el tratamiento de conducto primero hay que hacer una consulta de 30 minutos, aunque vengas derivado: ahí se hace el odontograma y se pide la autorización a la obra social. Después, el tratamiento se agenda con 1 hora. ¿Ya hiciste esa consulta con nosotros?»

* todavía no / necesita la consulta / viene derivado → `recordar_dato('motivo', 'Consulta por conducto')` → **30 minutos**
* ya hizo la consulta → `recordar_dato('motivo', 'Conducto')` → **1 hora**. El sistema verifica que la consulta figure; si no figura, te devuelve qué decirle. Nunca insistas con el turno de 1 hora si el sistema lo rechazó.

🚫 PROHIBIDO registrar `Conducto` o `tratamiento de conducto` a secas. 🚫 PROHIBIDO dar 1 hora porque dijo "conducto", "derivado" o "hacerme el conducto".

---

# 🆕 CONVERSACIÓN NUEVA Y QUIEN_ME_ESCRIBE

Solo si el mensaje trae `[CONVERSACIÓN NUEVA]` podés presentarte, y en ese caso llamá SIEMPRE primero a `quien_me_escribe()` antes de pedir datos (es interna, no la anuncies). Devuelve lo que se sepa del paciente: nombre, obra social, próximos turnos, último profesional, tratamientos en curso.

* **Conocido:** usá su nombre si corresponde, NO preguntes la obra social registrada, mencioná un turno próximo si es relevante ("Hola Juan 😊 Veo que ya tenés un turno el **28 de agosto de 2026 a las 18:00**. ¿Querías consultar por ese o sacar otro?") y reutilizá todo lo confiable. Sin presentación larga.
* **Nuevo:** presentate breve, sin empezar pidiendo datos administrativos ("¡Hola! Soy DentiBot 🦷, el asistente de Silprodent. ¿En qué te puedo ayudar?"). No enumeres tus funciones salvo que ayude.

---

# 🦷 MOTIVO

El motivo define duración, profesional y disponibilidad: es un **dato obligatorio del sistema**, NO una etapa de la conversación. Si el paciente ya lo dijo, interpretalo, guardalo con `recordar_dato` y seguí: no preguntes "¿Para qué sería la consulta?" a quien acaba de decir "Quiero sacarme una muela". Si de verdad falta, preguntalo breve ("Claro 😊 ¿Para qué sería el turno?"); si la respuesta es ambigua, pedí solo la aclaración que cambia duración o especialidad.

---

# 🏥 OBRA SOCIAL

Si la cobertura ya está en la ficha (`quien_me_escribe`) o en el estado de la conversación, usala y NO la preguntes. **"Particular" también cuenta**: si la ficha o el estado dicen "Particular", la cobertura YA ESTÁ resuelta; no llames a `preguntar_cobertura`.

Si el paciente menciona una obra social, guardala con `recordar_dato` y llamá a `verificar_obra_social(obra_social)` antes de asumir que está cubierta. Nunca asumas cobertura por similitud de nombre.

🚫 PROHIBIDO llamar a `consultar_disponibilidad` o `agendar_turno` sin haber registrado `obra_social` con `recordar_dato`.

## Si hay que preguntarla (dos escalones, UNA sola vez)

1. `preguntar_cobertura()`: muestra dos botones, "Tengo obra social" y "Particular". NO empieces mostrando obras sociales.
   * **Particular** → `recordar_dato('obra_social', 'Particular')` y seguí.
   * **Tengo obra social** (o escribe "sí, obra social" / "tengo obra social") → llamá YA a `listar_obras_sociales()`. NO vuelvas a preguntar si tiene o no. NO asumas Particular.
   * Otra cosa (una fecha, un horario) → guardá ese dato y pedile la cobertura de nuevo con otras palabras; **no inventes Particular** ni ofrezcas horarios sin cobertura registrada.
2. `listar_obras_sociales()` muestra las más usadas como lista tocable. Decile que elija la suya y que **si no la ve escriba las primeras letras**. 🚫 PROHIBIDO enumerarlas a mano en el mensaje y pedirle el nombre completo.

Con esas letras llamá `listar_obras_sociales(busqueda="...")`. La herramienta resuelve sola: ninguna → no la atendemos, ofrecé particular; una → te la da para confirmar; varias → lista tocable; demasiadas → pide UNA LETRA MÁS (pedila; NO muestres la misma lista de nuevo). Si la escribe a mano, siempre `verificar_obra_social`.

Si NO está cubierta, decilo breve y ofrecé particular: "Esa obra social no la estamos trabajando actualmente. Si querés, podemos buscarte un turno como particular."

## ⚠️ PAMI

PAMI tiene reglas internas de agenda y la herramienta ya devuelve solo fechas y horarios válidos. Ofrecé lo que devuelva. NO expliques cómo funciona: 🚫 nada de "Con PAMI atendemos los viernes" ni "El martes está cerrado para PAMI".

---

# 👨‍⚕️ PROFESIONAL

No obligues a elegir profesional: el motivo determina el especialista. Podés informar quién lo atendería ("Para extracción te atendería el Dr. Martin Silvestro") sin convertirlo en pregunta. Si más de uno puede hacerlo, la disponibilidad lo resuelve.

---

# 📅 DISPONIBILIDAD

`consultar_disponibilidad(...)` busca turnos nuevos. Recibe: motivo_confirmado_por_paciente, location, date, obra_social, preferencia_horaria y profesional (si pidió a alguien por nombre).

* El motivo tiene que haberlo dicho el paciente: 🚫 no la llames si todavía no lo dijo. Si lo dijo con sus palabras ("quiero un turno para una extracción"), **eso ES la confirmación**: registralo y llamá a la herramienta en esa misma ronda. 🚫 PROHIBIDO pedirle que "confirme" un motivo que ya dijo.
* Si ya tenés motivo, obra social cuando corresponda y alguna referencia de fecha o preferencia, buscá sin agregar preguntas. Ej.: "Necesito sacarme una muela mañana después de las 18. Tengo OSDE." → guardá motivo y obra social, verificala, interpretá fecha y preferencia y consultá disponibilidad, todo antes de volver a escribirle: la respuesta siguiente ya ofrece turnos concretos.
* **Preferencia horaria:** cualquier preferencia ("después de las 18:45", "por la tarde", "bien temprano", "antes del mediodía", "después del trabajo") va SIEMPRE como `preferencia_horaria`; la herramienta filtra. 🚫 No digas "solo tengo estos horarios" sin haber consultado con esa preferencia.
* **Fechas naturales:** interpretá "mañana", "pasado mañana", "esta semana", "la semana que viene", "el viernes", "cualquier día", "lo antes posible", "temprano", "a la mañana", "a la tarde" desde `[SISTEMA - FECHA ACTUAL]`. No calcules el nombre del día: la herramienta devuelve la fecha en palabras; copiala tal cual. Todo horario que devuelve es futuro y válido: nunca digas que ya pasó.

## "El primero que tengas"

Si el paciente ya dijo "el primero que tengas", "cuando puedas", "lo antes posible" o equivalente, **ya eligió**: no le muestres la lista para preguntarle cuál. Consultá disponibilidad, tomá el PRIMER horario y agendalo directamente con `agendar_turno`. Después contale qué quedó reservado.

## Presentación de turnos

Ofrecé pocas opciones buenas (normalmente 2 o 3), con fecha completa y año, fechas y horarios en **negrita con asteriscos**: "Tengo **miércoles 26 de agosto de 2026 a las 18:30** o **19:00**. ¿Cuál te sirve?". No expliques cómo los encontraste.

## Cuando elige uno

Reutilizá exactamente la fecha ISO que devolvió la herramienta y combiná fecha + hora. 🚫 PROHIBIDO volver a llamar `consultar_disponibilidad` porque eligió una opción que ya estaba disponible. Elegir ("18:30") ya es intención suficiente: 🚫 no preguntes "¿Confirmás que querés reservar a las 18:30?"; agendá directamente y después: "Listo 😊 Te agendé para **miércoles 26 de agosto de 2026 a las 18:30** con el Dr. Martin Silvestro."

---

# 👤 IDENTIFICACIÓN Y DATOS PERSONALES

El sistema reconoce al paciente por su número de WhatsApp. Al reservar llamá a `agendar_turno` con los campos personales vacíos si no hacen falta.

* Si lo reconoce, reservá.
* Si no reconoce el número, preguntá UNA sola cosa: "¿A nombre de quién agendo el turno?". Con nombre y apellido alcanza.
* Si hay varias personas en el mismo teléfono: "Veo más de una persona asociada a este número 😊 ¿Para quién sería el turno?", y volvé a llamar con ese nombre.
* Si ya dijo que es para otra persona ("Es para mi mamá Estela Pardo"), pasá `patient_name=Estela` y `patient_last_name=Pardo` y no vuelvas a preguntar para quién es.

🚫 PROHIBIDO pedir DNI (ni al reservar, ni al cancelar, ni al consultar), teléfono, fecha de nacimiento o cualquier otro dato administrativo: el resto lo completa la clínica cuando el paciente llega, y cada dato de más es una persona que abandona antes de tener el turno. Si el paciente ofrece un DNI por su cuenta, guardalo y usalo en la siguiente llamada relevante: no lo ignores, no lo pidas. Si no aparece un turno que dice tener, llamá a `indicar_llamar_consultorio`; no sigas pidiendo DNI, nombre ni más datos.

---

# ✅ AGENDAR, CANCELAR, REPROGRAMAR, CONSULTAR

* **Agendar:** `agendar_turno(patient_name, patient_last_name, dni, phone, reason, preferred_date, location, insurance_name, duration_minutes)`. Obligatorios: `reason` y `preferred_date` (`YYYY-MM-DD HH:MM`). Intentá primero con lo que ya tiene el sistema; no pidas lo que la herramienta no requiere.
* **Cancelar:** `cancelar_turno(dni, appointment_id)`, identificando por WhatsApp. Identificá el turno; si hay ambigüedad, confirmá cuál antes de esta acción irreversible ("Tenés un turno el **28 de agosto de 2026 a las 18:00**. ¿Querés cancelar ese?"). Si hay uno solo y la intención es inequívoca, seguí el flujo de la herramienta.
* **Reprogramar:** identificá el turno, averiguá la nueva preferencia si falta, consultá disponibilidad y con la elección usá `reprogramar_turno(dni, appointment_id, new_datetime)` (obligatorios: `appointment_id`, `new_datetime`). No canceles y crees otro.
* **Consultar** ("¿Cuándo tengo turno?", "¿Tengo algo pendiente?", "¿A qué hora era?"): llamá directo a `consultar_mis_turnos(dni)` identificando por WhatsApp.

---

# 📍 DIRECCIÓN

Si preguntan dónde queda, dá la dirección COMPLETA con calle y número y el link del mapa de DATOS DEL CONSULTORIO. 🚫 Nunca solo "Estamos en San Rafael": no alcanza para llegar. Si hay más de una sede y no está claro, preguntá a cuál quiere ir.

---

# 🕒 FECHA, SALUDOS Y RESPUESTAS CORTAS

Cada mensaje trae algo como `[SISTEMA - FECHA ACTUAL: martes 2026-08-25 hora Argentina: 10:30...]`: es la fuente de verdad para hoy, mañana, pasado mañana, saludos y referencias temporales. El bloque `[SISTEMA]` indica qué saludo o despedida corresponde según la hora: usalo (🚫 nada de "Buen día" a la noche ni "Buenas noches" a la mañana). No vuelvas a saludar en medio de una conversación ni repitas el nombre del paciente en cada respuesta.

Si responde solo 👍, ❤️, 👌, "sí", "dale" u "ok", interpretalo en el contexto inmediato: si confirma la última opción, avanzá; solo si no está claro preguntá "¿Querés que avancemos con el turno?".

---

# 🛡️ NO INVENTAR, NO REPETIR, SALIDA

Nunca inventes horarios, fechas, cobertura, profesionales, turnos, dirección ni datos del paciente. Si una herramienta puede darte el dato, usala; si no hay información ni herramienta, decilo breve.

🚫 NUNCA hagas la misma pregunta dos veces con las mismas palabras. Si la respuesta no resolvió, reinterpretala, guardá con `recordar_dato` lo nuevo que dijo, consultá una herramienta, reformulá incorporándolo o avanzá sin esa pregunta. Dar vueltas en círculo es peor que derivar.

Si no podés avanzar de forma segura (sin loops, sin inventar, sin interrogar indefinidamente), **llamá a `indicar_llamar_consultorio(motivo, resumen)`**: es la herramienta de salida (sin llamarla no hay teléfono ni registro) y te devuelve el teléfono. Decile que llame: "Para eso necesitás llamar al consultorio al *2604-590071*." (usá el teléfono que devolvió, no otro). 🚫 NO digas que dejaste la consulta anotada ni que alguien lo va a contactar: no hay bandeja.

Usala SOLO si el tema NO es de los que resolvés vos (turnos, disponibilidad, cancelar, reprogramar, obras sociales). Si no hay turnos libres, decilo y listo: eso sí lo resolviste. Casos típicos: precios, presupuestos y costos; coberturas que no podés verificar; urgencias o situaciones clínicas que exceden un turno; un turno que dice tener y no aparece (🚫 no pidas DNI).

---

# 🎯 ANTES DE ENVIAR

¿Ya sé lo que estoy por preguntar? ¿Lo dijo con otras palabras? ¿Lo puedo obtener con una herramienta? ¿Puedo avanzar sin preguntarlo? ¿Estoy agregando un paso que no cambia la acción siguiente? ¿Estoy repitiendo una pregunta? Si alguna respuesta dice que la pregunta sobra, NO la hagas.

El objetivo no es completar un flujo: es **resolver la necesidad del paciente de forma natural, segura y con la menor fricción posible**.
"""


_NOMBRE_PROF = r"(?:Dra?\.\s*)?[^.\n\"]+?"
_NO_HACE = re.compile(rf"(?P<pedido>{_NOMBRE_PROF}) no hace (?P<motivo>[^.\n]+)\. "
                      rf"Eso lo atiende (?P<quien>{_NOMBRE_PROF}(?: o {_NOMBRE_PROF})*)\.(?:\s|$)")


def ofrecer_quien_lo_atiende(resultados_tools: list[str]) -> str | None:
    """Si una herramienta dijo "X no hace Y; lo atiende Z", eso es lo que hay que decir.

    Simulacion 22/10: pidio un control de ortodoncia con Silvestro. El backend
    contesto bien ("Silvestro no hace Ortodoncia. Eso lo atiende Murad"), el
    modelo invento horarios de Murad, el filtro los bloqueo y salio el generico
    "no pude confirmar los horarios": el paciente nunca supo por que, y termino
    derivado a llamar.
    """
    for r in reversed(resultados_tools or []):
        if m := _NO_HACE.search(r or ""):
            quien = m.group("quien").strip()
            return (f"{m.group('pedido').strip()} no hace {m.group('motivo').strip().lower()}; "
                    f"eso lo atiende {quien}. ¿Querés que te busque turno con {quien}?")
    return None


def _pregunta_conducto_sin_resolver(texto: str) -> bool:
    """El paciente habló de conducto y todavía no se sabe si es consulta o tratamiento."""
    from bot.tools import appointment_tools as t
    if ((t._estado_conversacion.get() or {}).get("motivo") or "").strip():
        return False
    dichos = " ".join(list(t._dichos_por_el_paciente.get() or []) + [t._ultimo_mensaje.get() or ""])
    junto = t._sin_acentos_txt(dichos)
    return any(p in junto for p in ("conducto", "endodoncia", "nervio"))


def saludo_segun_hora(hora: int) -> tuple[str, str]:
    """Devuelve (saludo, despedida) correctos para esa hora.

    El modelo tenía la hora en el mensaje y aun así despedía con "que tengas un
    buen día" a las 23. Calcularlo acá y decírselo textual es más confiable que
    esperar que lo deduzca.
    """
    # La madrugada (00:00-05:59) sigue siendo "buenas noches": a las 2 AM nadie
    # saluda con "buen día".
    if hora < 6 or hora >= 20:
        return "buenas noches", "que tengas una buena noche"
    if hora < 13:
        return "buen día", "que tengas un buen día"
    return "buenas tardes", "que tengas una buena tarde"


def clinica_abierta_ahora(db_now) -> bool:
    """Si la clínica está atendiendo en este preciso momento."""
    from backend.database import SessionLocal
    from backend.models.schedule import ClinicSchedule

    db = SessionLocal()
    try:
        bloques = db.query(ClinicSchedule).filter(
            ClinicSchedule.weekday == db_now.weekday(),
            ClinicSchedule.is_active == True,  # noqa: E712
        ).all()
        ahora = db_now.time()
        return any(b.start_time <= ahora < b.end_time for b in bloques)
    except Exception:
        return True   # ante la duda, no afirmar que está cerrada
    finally:
        db.close()


# ── Parámetros según el modelo ───────────────────────────────────────────────

def _parametros_modelo(model: str) -> dict:
    """Los gpt-5.x y los o-series no aceptan temperature ni max_tokens: piden
    max_completion_tokens, y con margen porque el razonamiento también consume
    de ese tope. El resto (gpt-4o, gpt-4.1, Gemini, Llama...) sigue igual.
    El modelo se elige desde el panel, así que esto tiene que andar con todos."""
    nombre = (model or "").split("/")[-1].lower()
    if nombre.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": 4000}
    return {"temperature": 0.3, "max_tokens": 1000}


# ── Cliente de OpenAI ────────────────────────────────────────────────────────
# Hubo una cascada OpenAI -> OpenRouter -> Groq. En la practica solo andaba
# OpenAI (las otras claves estaban vencidas o revocadas) y la cascada sumaba
# codigo, claves y configuracion. Si OpenAI falla, el paciente recibe el
# mensaje de disculpa, igual que cuando fallaba toda la cascada.

def _build_client():
    """(cliente, modelo) de OpenAI, o (None, None) si falta la clave."""
    api_key = get_config("OPENAI_API_KEY")
    model = get_config("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        logger.error("AI_AGENT -> falta OPENAI_API_KEY en el entorno (Dokploy).")
        return None, None

    # Sin timeout, OpenAI trabado deja al paciente esperando sin limite. Con
    # max_retries=1 se reintenta una sola vez antes de dar el mensaje de disculpa.
    try:
        timeout_s = float(get_config("AI_TIMEOUT_SECONDS", "45"))
    except (TypeError, ValueError):
        timeout_s = 45.0

    return OpenAI(api_key=api_key, timeout=timeout_s, max_retries=1), model


# ── Nombres reales de los profesionales ─────────────────────────────────────
# Charla 21/09: el paciente escribio "Silvestre" y el bot repitio "el Dr.
# Silvestre" tres veces. La busqueda tolera el typo (fuzzy), el texto que sale
# no puede repetirlo. Y "el doctor Sosa" no existe: eso se dice, no se suaviza
# a "no esta disponible".

def _apellidos_reales() -> dict[str, str]:
    """{apellido normalizado: Apellido como esta en la ficha} de los activos."""
    import unicodedata
    tratamientos = {"dr", "dra", "doctor", "doctora", "de", "la", "el", "del"}

    def _norm(t):
        return "".join(c for c in unicodedata.normalize("NFD", t)
                       if unicodedata.category(c) != "Mn").lower()

    db = SessionLocal()
    try:
        from backend.models.professional import Professional
        activos = db.query(Professional).filter(
            Professional.is_deleted == False,  # noqa: E712
            Professional.is_active == True,    # noqa: E712
        ).all()
        # El apellido es la ultima palabra del nombre completo.
        return {
            _norm(p.full_name.split()[-1]): p.full_name.split()[-1]
            for p in activos
            if p.full_name and _norm(p.full_name.split()[-1]) not in tratamientos
        }
    except Exception:
        return {}
    finally:
        db.close()


_TRATAMIENTO_Y_APELLIDO = re.compile(
    r"\b(dr\.?|dra\.?|doctor|doctora|drama)\s+([A-Za-zÁÉÍÓÚáéíóúñÑ]{4,})",
    re.IGNORECASE,
)


def corregir_apellidos(texto: str) -> str:
    """Reemplaza 'Dr. Silvestre' por 'Dr. Silvestro' si es un typo de un activo.

    Solo detras de un tratamiento (Dr./Dra./doctor/doctora): asi 'silvestre'
    como palabra comun no se toca.
    """
    if not texto:
        return texto
    reales = _apellidos_reales()
    if not reales:
        return texto
    from difflib import SequenceMatcher
    import unicodedata

    def _norm(t):
        return "".join(c for c in unicodedata.normalize("NFD", t)
                       if unicodedata.category(c) != "Mn").lower()

    def _fix(m):
        trat, apellido = m.group(1), m.group(2)
        n = _norm(apellido)
        if n in reales:
            return f"{trat} {reales[n]}"
        for real_n, real in reales.items():
            if len(n) >= 5 and SequenceMatcher(None, n, real_n).ratio() >= 0.8:
                return f"{trat} {real}"
        return m.group(0)

    return _TRATAMIENTO_Y_APELLIDO.sub(_fix, texto)


def profesional_inexistente_en(texto: str) -> str | None:
    """El apellido que el paciente pide con tratamiento y que no es de nadie.

    "Un turno con el doctor Sosa" → "Sosa". "Con el drama Silvestre" → None
    (typo de Silvestro). Se detecta ANTES de llamar al modelo: en la charla del
    21/09 el modelo no llamó a ninguna tool y siguió como si Sosa existiera.
    """
    if not texto:
        return None
    reales = _apellidos_reales()
    if not reales:
        return None
    from difflib import SequenceMatcher
    import unicodedata

    def _norm(t):
        return "".join(c for c in unicodedata.normalize("NFD", t)
                       if unicodedata.category(c) != "Mn").lower()

    for m in _TRATAMIENTO_Y_APELLIDO.finditer(texto):
        apellido = m.group(2)
        n = _norm(apellido)
        if n in reales:
            continue
        if any(len(n) >= 5 and SequenceMatcher(None, n, r).ratio() >= 0.8 for r in reales):
            continue
        if n in {"para", "pero", "como", "cuando", "donde", "quien", "algo", "alguno", "alguna"}:
            continue
        return apellido
    return None


def mensaje_profesional_inexistente(pedido: str) -> str:
    reales = list(_apellidos_reales().values())
    db = SessionLocal()
    try:
        from backend.services.appointment_service import nombres_profesionales_activos
        quienes = nombres_profesionales_activos(db)
    except Exception:
        quienes = " y ".join(reales)
    finally:
        db.close()
    return (
        f"No tenemos ningún profesional llamado {pedido}. "
        + (f"Atienden {quienes}. " if quienes else "")
        + "¿Con quién querés el turno?"
    )


_NO_HAY_PROFESIONAL = re.compile(r"no hay ning[uú]n profesional llamado '([^']+)'", re.IGNORECASE)
_SUAVIZA = re.compile(r"no\s+(est[aá]|se\s+encuentra)\s+disponible", re.IGNORECASE)


def suaviza_inexistente(texto: str, resultados_tools: list[str]) -> bool:
    """True si una tool dijo que el profesional no existe y el modelo lo suavizo."""
    if not texto:
        return False
    if not any(_NO_HAY_PROFESIONAL.search(r or "") for r in resultados_tools):
        return False
    return bool(_SUAVIZA.search(texto))


def mensaje_inexistente_desde_tool(resultados_tools: list[str]) -> str | None:
    """Arma la respuesta al paciente a partir de lo que dijo la tool."""
    for r in resultados_tools:
        m = _NO_HAY_PROFESIONAL.search(r or "")
        if not m:
            continue
        quienes = re.search(r"Atienden:\s*([^.]+)\.", r)
        pedido = m.group(1)
        lista = quienes.group(1).strip() if quienes else ""
        return (
            f"No tenemos ningún profesional llamado {pedido}. "
            + (f"Atienden {lista}. " if lista else "")
            + "¿Con quién querés el turno?"
        )
    return None


# ── Un "sí" a una oferta del bot se ejecuta ─────────────────────────────────
# Charla 21/09: "¿Te gustaría que busque disponibilidad?" → "Sí" → la misma
# pregunta, tres veces. Y "¿Te gustaría que lo agende?" sin ningún horario
# ofrecido. El modelo redacta; ejecutar es del código.

_OFERTA_DEL_BOT = re.compile(
    r"(busque|buscar|buscamos|busco)\s+(la\s+)?(disponibilidad|horarios?|turnos?)|"
    r"que\s+lo\s+agende|agendarlo|agendamos|lo\s+agendo|reservarlo|que\s+lo\s+reserve|"
    r"(te\s+gustar[ií]a|quer[eé]s|quiere[sn]?)\s+(agendar|que\s+(lo\s+)?agende)|"
    r"agendar\s+con",
    re.IGNORECASE,
)


def ultima_oferta(history: list[dict] | None) -> bool:
    """True si lo último que dijo el bot fue ofrecer buscar horarios o agendar."""
    ultimos = [m for m in (history or []) if m.get("role") == "assistant"]
    if not ultimos:
        return False
    return bool(_OFERTA_DEL_BOT.search(ultimos[-1].get("content") or ""))


# El modelo ofrece "¿querés que lo agende?" sin haber mostrado ni un horario.
_OFRECE_AGENDAR = re.compile(
    r"(que\s+(te\s+)?lo\s+agende|agendarlo|lo\s+agendo|agendamos|que\s+lo\s+reserve|"
    r"reservarlo|te\s+lo\s+reservo|"
    r"(te\s+gustar[ií]a|quer[eé]s)\s+agendar|"
    r"agendar\s+con)\??",
    re.IGNORECASE,
)


def ofrece_agendar_sin_horario(texto: str, consultado: list) -> bool:
    if not texto or consultado:
        return False
    return bool(_OFRECE_AGENDAR.search(texto))


# ── Main chat function ───────────────────────────────────────────────────────

def chat(user_message: str, history: list[dict] | None = None,
         requester_phone: str | None = None,
         estado: dict | None = None) -> tuple[str, list | None, dict]:
    """Process a user message and return agent response.

    requester_phone: número real del canal (ej. WhatsApp) de quien escribe.
    Se registra para que las tools lo envíen al backend y este verifique que
    el DNI pertenece a ese número. En Telegram queda None (sin verificación).
    """
    logger.info(f"AI_AGENT_IN -> Msg: '{user_message}', HistLen: {len(history) if history else 0}")

    set_requester_phone(requester_phone)
    # El mensaje crudo del paciente, para las tools que lo necesitan cuando el
    # modelo no reenvia lo que le dijeron (ej: buscar una obra social por "sw").
    set_ultimo_mensaje(user_message)
    # Todo lo que dijo el paciente, para poder verificar que un dato salio de el
    # y no de una deduccion del modelo.
    set_dichos_por_el_paciente(
        [m["content"] for m in (history or []) if m.get("role") == "user"] + [user_message]
    )
    # Y lo ultimo que dijo el bot: si ofrecio UN horario y el paciente dice
    # "dale", agendar_turno sabe cual es.
    respuestas_bot = [m["content"] for m in (history or []) if m.get("role") == "assistant"]
    set_ultima_respuesta_bot(respuestas_bot[-1] if respuestas_bot else "")
    # Datos que el paciente ya dio en esta conversacion. Viajan por parametro y
    # no por contextvar: chat() corre en un executor (otro hilo) y el webhook
    # no veria lo que se setea adentro.
    set_estado_conversacion(estado)

    # Sacar turno va por el guion fijo (bot/flujo_turno.py): el orden y las
    # reglas del consultorio los pone el codigo, la IA solo entiende el mensaje.
    # Si el guion falla por lo que sea, el mensaje lo atiende el agente general:
    # el paciente nunca se queda sin respuesta.
    from bot import flujo_turno
    if flujo_turno.ACTIVO:
        from bot.tools.appointment_tools import _current_requester_phone
        try:
            r = flujo_turno.responder(
                user_message, history or [], estado or {}, _current_requester_phone(),
                [m["content"] for m in (history or []) if m.get("role") == "user"],
            )
            if r is not None:
                set_estado_conversacion(r[2])
                return r
        except Exception:
            logger.exception("FLUJO_TURNO -> falló; atiende el agente general")
            estado = {k: v for k, v in (estado or {}).items() if k != flujo_turno.CLAVE}
            set_estado_conversacion(estado)

    clinic_now = get_clinic_now()
    dia_semana = DIAS_ES[clinic_now.weekday()]

    # Build system prompt with dynamic data
    #
    # Este texto tiene que quedar IDENTICO byte a byte en todas las llamadas: es
    # el prefijo que OpenAI cachea (mitad de precio arriba de 1024 tokens), y son
    # ~10.000 tokens entre el prompt y las 11 herramientas que se reenvian hasta
    # 8 veces por cada mensaje del paciente. El caché funciona por prefijo: se
    # corta en el primer byte que cambia y desde ahi se paga todo entero.
    #
    # Por eso el estado de la conversacion ya NO se pega aca. Estaba como un
    # `system_content +=` y cambiaba dentro de la misma charla cada vez que el
    # paciente daba un dato, o sea que metia un bloque mutable justo delante de
    # las herramientas. Ahora viaja en el bloque [SISTEMA] del ultimo mensaje,
    # que es donde ya viajaban la fecha, el saludo y si la clinica esta abierta.
    system_content = SYSTEM_PROMPT.format(
        especialistas=get_especialistas_texto(),
        sedes=get_sedes_texto(),
        horarios=get_horarios_texto(),
        duraciones=get_duraciones_texto(),
    )

    # Build messages array (OpenAI format)
    messages = [{"role": "system", "content": system_content}]
    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    # Prepend real date/time to user message
    # Si no hay historial, es el primer mensaje: el codigo lo sabe con certeza,
    # el modelo no (solo ve una lista de mensajes sin marcas). Antes lo decidia
    # el modelo y ante la duda se presentaba, hasta a alguien que solo queria
    # cancelar un turno.
    marca_nueva = "[CONVERSACIÓN NUEVA]\n" if not history else ""
    saludo, despedida = saludo_segun_hora(clinic_now.hour)
    abierta = clinica_abierta_ahora(clinic_now)
    estado_clinica = (
        "La clínica está ATENDIENDO en este momento."
        if abierta else
        "La clínica está CERRADA en este momento (fuera del horario de atención). "
        "Podés agendar turnos igual, pero no le digas al paciente que venga ahora."
    )
    # La instruccion de saludar solo va en el primer mensaje. Antes viajaba en
    # TODOS, asi que el modelo abria con "¡Buenas noches, Claudio!" una y otra
    # vez dentro de la misma charla: le estabamos pidiendo que saludara de nuevo
    # en cada vuelta y despues nos quejabamos de que saludaba de nuevo.
    if history:
        instruccion_saludo = (
            f"La conversación YA ESTÁ EMPEZADA: NO saludes de nuevo, no digas "
            f"\"{saludo}\" ni vuelvas a nombrar al paciente como si recién llegara. "
            f"Seguí la charla donde quedó. Si te despedís, usá \"{despedida}\". "
        )
    else:
        # "Saludá con X y despedite con Y" era una sola orden con dos verbos, y
        # un modelo literal la cumple entera en la misma respuesta: el primer
        # mensaje salia "Buen día, ¿en qué te puedo ayudar? Que tengas un buen
        # día." — saludando y despidiendo a alguien que recien llegaba.
        # La despedida es condicional, como ya decia la rama de arriba.
        instruccion_saludo = (
            f"Saludá diciendo \"{saludo}\" — usá EXACTAMENTE esa fórmula, no "
            f"inventes otra. NO te despidas: la conversación recién empieza. "
            f"Si más adelante hay que despedirse, la fórmula es \"{despedida}\". "
        )

    # Lo que ya se sabe de este paciente, para que no lo vuelva a preguntar.
    # Viaja aca y no en el system prompt para no romperle el caché al prefijo.
    #
    # Barreras de cobertura (caso real 21/09): el modelo preguntaba 3 veces
    # obra/particular, trataba "tratamiento de conducto" como OS, y si el
    # paciente escribía las primeras letras no llamaba a listar. Acá se lo
    # ordena en el bloque [SISTEMA] del turno, que el modelo no puede ignorar
    # tan fácil como una regla del prompt largo.
    from bot.tools.appointment_tools import (
        _paciente_eligio_tiene_obra_social,
        _texto_parece_busqueda,
        motivo_por_boton_conducto,
    )
    estado_ahora = estado or {}
    forzadas = []
    # Toco un boton de la pregunta de conducto: el motivo queda decidido por
    # codigo. El modelo solo tiene que seguir (horarios), no interpretarlo.
    motivo_boton = motivo_por_boton_conducto(user_message, respuestas_bot[-1] if respuestas_bot else "")
    if motivo_boton:
        from backend.services.appointment_service import MOTIVO_TRATAMIENTO_CONDUCTO
        from bot.tools.appointment_tools import _motivo_dicho_por_el_paciente
        from bot.tools.appointment_tools import set_opciones_ofrecidas as _botones_conducto
        if motivo_boton == MOTIVO_TRATAMIENTO_CONDUCTO:
            # "Ya hice la consulta": el turno de 1 hora solo si el sistema
            # registra esa consulta. Lo verifica el backend con el historial.
            ok, normalizado, razon = _motivo_dicho_por_el_paciente(motivo_boton)
            if ok:
                motivo_boton = normalizado
            else:
                # No figura la consulta: se le dice por codigo, sin pasar por
                # el modelo (lo parafraseaba hasta perder el "no la encuentro").
                from backend.services.appointment_service import (
                    BOTON_CONSULTA_CONDUCTO, RAZON_SIN_CONSULTA_PREVIA, TEXTO_SIN_CONSULTA_PREVIA,
                )
                _botones_conducto([BOTON_CONSULTA_CONDUCTO], siempre=True, tipo="botones")
                if razon == RAZON_SIN_CONSULTA_PREVIA:
                    return TEXTO_SIN_CONSULTA_PREVIA, tomar_opciones_ofrecidas(), get_estado_conversacion()
                motivo_boton = None
                forzadas.append(razon or "No se pudo verificar la consulta por conducto.")
    if motivo_boton:
        estado_ahora = {**estado_ahora, "motivo": motivo_boton}
        estado = estado_ahora
        set_estado_conversacion(estado)
        forzadas.append(
            f"El paciente eligió con un botón: motivo = '{motivo_boton}', ya "
            f"registrado en el estado (no llames a `recordar_dato`). Seguí con "
            f"lo que falte: cobertura si no está, si no, `consultar_disponibilidad`."
        )
    # Eligio un horario de los que se le acaban de ofrecer: se agenda por
    # codigo. Si el sistema pide algo mas (el nombre, en un numero nuevo), el
    # modelo sigue desde ahi con esa respuesta en la mano.
    # Si para agendar falta el nombre (numero nuevo), el horario elegido queda
    # guardado y cuando el paciente lo dice se agenda con eso. Simulacion 15/11:
    # "Florencia Ramos" se tomo como busqueda de obra social y termino derivado.
    from bot.tools.appointment_tools import (
        eleccion_de_horario, confirmacion_turno_agendada, nombre_dicho,
    )
    eleccion = eleccion_de_horario(user_message, respuestas_bot[-1] if respuestas_bot else "")
    elegido = estado_ahora.get("turno_elegido")
    nombre = nombre_dicho(user_message) if (elegido and not eleccion) else None
    if (eleccion or nombre) and (estado_ahora.get("motivo") or "").strip():
        if eleccion:
            elegido = dict(zip(("fecha", "hora", "profesional"), eleccion))
        args = {"reason": estado_ahora["motivo"],
                "preferred_date": f"{elegido['fecha']} {elegido['hora']}",
                "profesional": elegido.get("profesional", "")}
        if nombre:
            args.update(patient_name=nombre[0], patient_last_name=nombre[1])
        reiniciar_confirmacion_turno()
        resultado = execute_tool("agendar_turno", args)
        if conf := confirmacion_turno_agendada():
            logger.info("AI_AGENT -> Turno agendado por código con el horario elegido de la lista")
            estado_ahora = {k: v for k, v in (get_estado_conversacion() or estado_ahora).items()
                            if k != "turno_elegido"}
            set_estado_conversacion(estado_ahora)
            return conf, tomar_opciones_ofrecidas(), estado_ahora
        estado_ahora = {**(get_estado_conversacion() or estado_ahora), "turno_elegido": elegido}
        estado = estado_ahora
        set_estado_conversacion(estado_ahora)
        hora, fecha = elegido["hora"], elegido["fecha"]
        forzadas.append(
            f"El paciente eligió las {hora} del {fecha}. Ya se intentó agendar y el "
            f"sistema respondió: {resultado} — seguí desde ahí. 🚫 PROHIBIDO volver "
            f"a mostrarle la lista de horarios."
        )
    if _paciente_eligio_tiene_obra_social(user_message):
        forzadas.append(
            "OBLIGATORIO AHORA: el paciente dijo que tiene obra social. "
            "Llamá a `listar_obras_sociales()` en esta misma respuesta. "
            "🚫 PROHIBIDO volver a preguntar si es particular u obra social. "
            "🚫 PROHIBIDO preguntar el motivo antes de mostrarle la lista."
        )
    elif not nombre and (busq := _texto_parece_busqueda(user_message)):
        # Primeras letras de una OS que no estaba en la lista tocable.
        # Aunque la ficha diga Particular, si escribe "ava"/"ospe" está buscando.
        os_actual = (estado_ahora.get("obra_social") or "").strip().lower()
        eligiendo = (
            estado_ahora.get("cobertura_preguntada")
            or not os_actual
            or os_actual == "particular"
        )
        if eligiendo and not (
            os_actual and os_actual not in {"particular", ""} and busq in os_actual
        ):
            forzadas.append(
                f"OBLIGATORIO AHORA: el paciente escribió '{busq}' buscando su "
                f"obra social. Llamá a `listar_obras_sociales(busqueda='{busq}')`. "
                f"🚫 PROHIBIDO asumir Particular ni seguir sin registrar la cobertura."
            )
    # Pidió a alguien que no existe ("doctor Sosa"). Se le dice, con los que sí
    # atienden. Si el modelo igual sigue como si existiera, lo corrige _pulir.
    inexistente = profesional_inexistente_en(user_message)
    if inexistente:
        forzadas.append(
            f"OBLIGATORIO AHORA: NO existe ningún profesional llamado "
            f"'{inexistente}' en la clínica. Decíselo con esas palabras y "
            f"nombrá a los que sí atienden (los del listado de PROFESIONALES). "
            f"🚫 PROHIBIDO decir que '{inexistente}' 'no está disponible' o "
            f"seguir la charla como si existiera. Preguntale con quién quiere."
        )
    # "Sí" a "¿querés que busque disponibilidad?": se busca. Si el modelo igual
    # no lo hace, más abajo lo hace el código (_rescatar_afirmacion).
    acepto_oferta = es_afirmacion(user_message) and ultima_oferta(history)
    if acepto_oferta:
        if estado_ahora.get("motivo") and estado_ahora.get("obra_social"):
            forzadas.append(
                "OBLIGATORIO AHORA: el paciente ACEPTÓ tu oferta. Llamá a "
                "`consultar_disponibilidad` en esta misma respuesta y ofrecé los "
                "horarios que devuelva. 🚫 PROHIBIDO volver a preguntar si quiere "
                "que busques. 🚫 PROHIBIDO ofrecer agendar sin mostrar horarios."
            )
        else:
            forzadas.append(
                "El paciente ACEPTÓ tu oferta pero falta un dato para buscar "
                f"({resumen_estado(estado_ahora)}). Preguntá SOLO lo que falta, "
                "una vez. 🚫 PROHIBIDO volver a ofrecer buscar o agendar."
            )
    bloque_forzadas = (("\n" + "\n".join(forzadas) + "\n") if forzadas else "")

    dated_message = (
        f"{marca_nueva}"
        f"[SISTEMA - FECHA ACTUAL: {dia_semana} {clinic_now.strftime('%Y-%m-%d')} "
        f"hora Argentina: {clinic_now.strftime('%H:%M')}. "
        f"{instruccion_saludo}"
        f"{estado_clinica}\n"
        f"📌 ESTADO DE ESTA CONVERSACIÓN: {resumen_estado(estado or {})}]"
        f"{bloque_forzadas}\n"
        f"{user_message}"
    )
    messages.append({"role": "user", "content": dated_message})

    # ── Un "te agendé" tiene que tener un turno detrás ──────────────────────
    # Pasó en producción: el paciente pidió turno con el Dr. Silvestro, y el
    # modelo le contestó "tengo disponibilidad el lunes 14 a las 11:00" y
    # después "te agendé para el lunes 14 a las 11:00 con el Dr. Martin
    # Silvestro" — sin llamar a ninguna herramienta. El log de esa conversación
    # no tiene ni un POST a /availability ni a /appointments despues del primer
    # turno, y el link de cancelacion era el del turno ANTERIOR, copiado.
    #
    # O sea que el paciente se fue creyendo que tenia un turno que no existia, y
    # ademas con un profesional que los lunes no atiende. Un prompt no alcanza:
    # esto lo tiene que garantizar el codigo.
    # El lookbehind de "que " distingue la oferta de la confirmación:
    # "¿Te gustaría que te agende con el Dr. Silvestro?" es una pregunta a
    # futuro y bloquearla dejaba al paciente con el mensaje enlatado de error
    # (falso positivo del 15/09, caso Murad). "Te agendé para el lunes" sí es
    # una afirmación y se sigue bloqueando si el turno no existe.
    _CONFIRMA_TURNO = re.compile(
        r"((?<!que\s)\bte\s+agend|\bqued(o|ó)\s+agendad|(?<!que\s)\bte\s+reserv|"
        r"(?<!que\s)\bte\s+anot|\bturno\s+confirmad|\bagendad[oa]\s+para)",
        re.IGNORECASE,
    )

    def _promete_sin_cumplir(texto: str, agendo_de_verdad: bool) -> bool:
        return bool(texto) and not agendo_de_verdad and bool(_CONFIRMA_TURNO.search(texto))

    # Lo mismo para promesas vacías de "te van a contactar" / "dejé la consulta":
    # ya no hay bandeja de derivaciones. La única salida válida es indicar llamar
    # (herramienta indicar_llamar_consultorio).
    _PROMETE_AVISO = re.compile(
        r"(dej[eé]\s+(la\s+)?consulta|le\s+aviso\s+a|avis[eé]\s+a\s+recepci|"
        r"qued[oó]\s+anotad|lo\s+deriv[eé]|te\s+van\s+a\s+(llamar|contactar)|"
        r"recepci[oó]n\s+(te|lo|la)\s+(va\s+a\s+)?(llamar|contactar|revisar)|"
        r"dej(e|ar)\s+tus\s+datos|cuando\s+haya\s+(disponibilidad|un\s+turno)|"
        r"te\s+avise\s+cuando|para\s+que\s+te\s+contacten)",
        re.IGNORECASE,
    )

    _AVISO_SIN_CASO = (
        "Para eso necesitás hablar por teléfono con el consultorio. "
        f"Podés llamar al *{telefono_consultorio()}* y te atienden directamente."
    )

    # ── Los horarios que salen tienen que ser los que devolvio el sistema ──
    #
    # Conversacion real del 10/09, con el bot ya corregido:
    #
    #   paciente: lunes
    #   bot:      No hay disponibilidad para el lunes 12 de septiembre. Pero
    #             tengo turnos para el miércoles 16 a las 10:30, 11:30 o 12:00.
    #   paciente: y para la doctora murad?
    #   bot:      Para la Dra. Murad, tengo disponibilidad el miércoles 16 a las
    #             10:30, 11:30 o 12:00.
    #
    # Tres inventos en dos mensajes: el 12 de septiembre era SABADO, no lunes;
    # la segunda respuesta no consulto nada —el log tiene UNA sola llamada a
    # /availability en toda la conversacion— y Murad no atiende los miercoles.
    #
    # El agregar el parametro `profesional` no alcanzo: era un pedido, no una
    # garantia. Esto compara lo que sale con lo que el sistema realmente
    # devolvio, y si no coincide no sale.

    def _sin_tildes(texto: str) -> str:
        import unicodedata
        return "".join(
            c for c in unicodedata.normalize("NFD", texto or "")
            if unicodedata.category(c) != "Mn"
        )

    _OFRECE_HORARIOS = re.compile(
        r"(tengo|hay|queda[nr]?|disponibilidad|disponibles?|turnos?\s+para|"
        r"horarios?)", re.IGNORECASE,
    )
    _HORA = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")

    def _horarios_inventados(texto: str, consultado: list) -> list[str]:
        """Los horarios del mensaje que ninguna herramienta devolvio."""
        if not texto or not _OFRECE_HORARIOS.search(texto):
            return []
        dichos = {f"{int(h):02d}:{m}" for h, m in _HORA.findall(texto)}
        if not dichos:
            return []
        reales = {s for d in consultado for s in d.get("slots", [])}
        return sorted(dichos - reales)

    def _apellidos_activos() -> set[str]:
        """Los apellidos de los profesionales, para reconocerlos en el texto."""
        tratamientos = {"dr", "dra", "doctor", "doctora", "de", "la", "el", "del"}
        db = SessionLocal()
        try:
            from backend.models.professional import Professional
            activos = db.query(Professional).filter(
                Professional.is_deleted == False,  # noqa: E712
                Professional.is_active == True,    # noqa: E712
            ).all()
            return {
                palabra
                for p in activos
                for palabra in _sin_tildes(p.full_name).lower().split()
                if palabra not in tratamientos and len(palabra) >= 4
            }
        except Exception:
            return set()
        finally:
            db.close()

    def _atribucion_falsa(texto: str, consultado: list) -> str | None:
        """El profesional que el mensaje nombra sin haberlo consultado.

        Es el caso exacto del 10/09: los horarios eran REALES —los de
        Silvestro— pero el mensaje los presentaba como de la Dra. Murad, que no
        atiende ese dia. Verificar los horarios no alcanza cuando el invento
        esta en a quien se le atribuyen.
        """
        if not texto or not _OFRECE_HORARIOS.search(texto) or not _HORA.search(texto):
            return None

        palabras = set(_sin_tildes(texto).lower().replace(",", " ").replace(".", " ").split())
        nombrados = palabras & _apellidos_activos()
        if not nombrados:
            return None   # no le atribuye los horarios a nadie en particular

        consultados = {
            palabra
            for d in consultado
            for palabra in _sin_tildes(d.get("profesional") or "").lower().split()
        }
        sin_consultar = nombrados - consultados
        return ", ".join(sorted(sin_consultar)) if sin_consultar else None

    def _mensaje_con_los_horarios_reales(consultado: list) -> str | None:
        """Rearma el ofrecimiento desde el ultimo resultado real.

        Si el dia pedido no era del profesional, se lo dice y se le ofrece el
        proximo que si atiende: "el Dr. Silvestro no atiende el lunes 14.
        Atiende miercoles, jueves y viernes". Eso lo calcula el backend y viene
        en `motivo`; sin incluirlo, el paciente ve que le cambian el dia y no
        entiende por que.
        """
        if not consultado:
            return None
        ultimo = consultado[-1]
        slots = ultimo.get("slots") or []
        if not slots:
            return None
        quien = ultimo.get("profesional") or ""
        con_quien = f" con {quien}" if quien and "cualquier" not in quien.lower() else ""
        horarios = (slots[0] if len(slots) == 1
                    else ", ".join(slots[:-1]) + f" o {slots[-1]}")

        aclaracion = ""
        motivo = (ultimo.get("motivo") or "").strip()
        if motivo:
            aclaracion = motivo.rstrip(".") + ". "

        return (f"{aclaracion}Tengo turno{con_quien} el {ultimo.get('fecha_texto')} "
                f"a las {horarios}. ¿Cuál te sirve?")

    # Caso real 16/09 (…0140): el backend devolvió lunes 5/10 10:00 y 11:00, y
    # el modelo contestó "no tengo disponibilidad". Si hay slots reales, eso
    # no puede salir.
    _NIEGA_DISPONIBILIDAD = re.compile(
        r"(no\s+(tengo|hay)\s+(disponibilidad|turnos?)|"
        r"sin\s+disponibilidad|"
        r"no\s+encuentro\s+(turnos?|disponibilidad)|"
        r"no\s+quedan?\s+turnos?|"
        r"no\s+hay\s+turnos?\s+disponibles)",
        re.IGNORECASE,
    )

    def _niega_habiendo_horarios(texto: str, consultado: list) -> str | None:
        if not texto or not _NIEGA_DISPONIBILIDAD.search(texto):
            return None
        return _mensaje_con_los_horarios_reales(consultado)

    def _consultar_yo_mismo() -> str | None:
        """Si el modelo no consulto, consulta el codigo y arma la respuesta.

        Antes esto devolvia "dejame que lo verifique y te confirmo en un
        momento", y ese momento no llegaba nunca: el paciente quedaba esperando
        una respuesta que nadie iba a mandar. Era la misma promesa vacia que se
        saco de todo el resto del sistema, y la habia puesto yo.

        El motivo sale del estado de la conversacion —ya verificado contra lo
        que dijo el paciente— y el profesional y el dia, de sus propias
        palabras. Con eso alcanza para preguntarle al sistema de verdad.
        """
        motivo = (get_estado_conversacion() or {}).get("motivo")
        if not motivo:
            return None
        try:
            from bot.tools.appointment_tools import consultar_disponibilidad
            reiniciar_disponibilidad()
            consultar_disponibilidad(motivo_confirmado_por_paciente=motivo)
        except Exception as e:
            logger.error("AI_AGENT -> No se pudo consultar disponibilidad por "
                         "nuestra cuenta: %s", e, exc_info=True)
            return None
        return _mensaje_con_los_horarios_reales(disponibilidad_consultada())

    _SIN_HORARIOS = (
        "Perdón, no pude confirmar los horarios en este momento. "
        "¿Me repetís qué día te viene bien y con qué profesional?"
    )

    def _rescatar_afirmacion(texto: str, consultado: list, agendo: bool) -> str | None:
        """Si dijo "sí" a buscar/agendar y el modelo no ejecutó, ejecuta el código.

        Con el estado completo, consulta disponibilidad y arma la respuesta.
        Si falta un dato, hace la pregunta determinística de ese dato (con
        botones). Devuelve None si no hay nada que rescatar.
        """
        ofrece_vacio = ofrece_agendar_sin_horario(texto, consultado)
        if not (acepto_oferta or ofrece_vacio):
            return None
        if agendo:
            return None
        # Si el modelo sigue ofreciendo ("¿querés con Murad?") en vez de
        # mostrar horarios, no alcanzó: aunque haya slots viejos de un turno
        # anterior en el buffer, hay que consultar de nuevo (arnés 21/09).
        sigue_ofreciendo = bool(_OFERTA_DEL_BOT.search(texto or ""))
        if consultado and not sigue_ofreciendo and not ofrece_vacio:
            return None
        estado_hoy = get_estado_conversacion() or {}
        if estado_hoy.get("motivo") and estado_hoy.get("obra_social"):
            logger.error(
                "AI_AGENT -> El paciente aceptó buscar/agendar y el modelo no "
                "ofreció horarios. Consulta el código. Mensaje: %d caracteres (texto omitido)", len(texto),
            )
            reiniciar_disponibilidad()
            return _consultar_yo_mismo() or _SIN_HORARIOS
        from bot.tools.appointment_tools import pregunta_por_lo_que_falta
        dichos = [m["content"] for m in (history or []) if m.get("role") == "user"] + [user_message]
        pregunta = pregunta_por_lo_que_falta(estado_hoy, dichos)
        if not pregunta:
            return None
        logger.error(
            "AI_AGENT -> El paciente aceptó pero falta un dato y el modelo no lo "
            "pidió. Pregunta el código. Mensaje: %d caracteres (texto omitido)", len(texto),
        )
        texto_p, botones = pregunta
        if botones:
            set_opciones_ofrecidas(botones["opciones"], siempre=True, tipo=botones.get("tipo", "lista"))
        return texto_p

    _SIN_RESPALDO = (
        "Perdón, no llegué a confirmar ese turno: todavía no quedó agendado. "
        "¿Me repetís el día y la hora que querés y con qué profesional, así lo "
        "cargo bien?"
    )

    # ── Cuánto consume cada mensaje ─────────────────────────────────────────
    # Nadie estaba midiendo esto, y sin medirlo cualquier decisión sobre el
    # modelo o sobre MAX_TOOL_ROUNDS es a ciegas. Lo que importa acá no es el
    # total sino `cached`: el prompt y las 11 herramientas son ~10.000 tokens
    # que se reenvían en cada ronda, y si el caché está pegando salen a mitad
    # de precio. Si `cached` da 0 sostenido, algo volvió a romper el prefijo.
    uso = {"llamadas": 0, "in": 0, "cached": 0, "out": 0}

    def _registrar_uso(response, etapa: str) -> None:
        u = getattr(response, "usage", None)
        if not u:
            return
        detalle = getattr(u, "prompt_tokens_details", None)
        cached = getattr(detalle, "cached_tokens", 0) or 0
        uso["llamadas"] += 1
        uso["in"] += u.prompt_tokens or 0
        uso["cached"] += cached
        uso["out"] += u.completion_tokens or 0
        pct = round(100 * cached / u.prompt_tokens) if u.prompt_tokens else 0
        logger.info(
            "AI_AGENT_USO -> %s | %s | in=%s (cache %s = %s%%) out=%s | "
            "acumulado del mensaje: %s llamadas, in=%s cache=%s out=%s",
            etapa, model, u.prompt_tokens, cached, pct,
            u.completion_tokens, uso["llamadas"], uso["in"], uso["cached"],
            uso["out"],
        )

    client, model = _build_client()
    if client:
        try:
            # ── Function calling loop ────────────────────────────────
            conv = list(messages)
            # Lo que devolvio consultar_disponibilidad en este mensaje.
            reiniciar_disponibilidad()
            reiniciar_confirmacion_turno()
            # Si en este turno se creo un turno de verdad. Lo unico que cuenta
            # es que agendar_turno haya devuelto exito, no que el modelo diga
            # que lo hizo.
            agendo_de_verdad = False
            derivo_de_verdad = False
            # Lo que devolvieron las tools en este intento, para contrastar
            # la redaccion final con lo que el sistema dijo de verdad.
            resultados_tools: list[str] = []

            def _respuesta_con_plantillas(texto: str, consultado: list, agendo: bool) -> str:
                """Datos duros por plantilla: horarios y confirmación.

                El modelo decide qué hacer; el código arma el texto con números.
                Así no se inventa un horario ni se confirma un turno inventado.
                """
                if agendo:
                    conf = confirmacion_turno_agendada()
                    if conf:
                        logger.info("AI_AGENT -> Confirmación de turno por plantilla")
                        return conf
                plantilla = _mensaje_con_los_horarios_reales(consultado)
                if plantilla and (
                    _OFRECE_HORARIOS.search(texto or "")
                    or _HORA.search(texto or "")
                ):
                    logger.info("AI_AGENT -> Horarios por plantilla (camino normal)")
                    return plantilla
                return texto

            def _pulir(texto: str) -> str:
                """Ultimo filtro del texto que sale: nombres reales y nada suavizado."""
                if suaviza_inexistente(texto, resultados_tools):
                    logger.error(
                        "AI_AGENT -> Suavizó a 'no disponible' un profesional que NO "
                        "existe. Mensaje: %d caracteres (texto omitido)", len(texto),
                    )
                    texto = mensaje_inexistente_desde_tool(resultados_tools) or texto
                # Dijo que ya hizo la consulta por conducto y NO figura: eso se le
                # dice tal cual. Prueba real 15/11: el sistema lo rechazo bien y
                # el modelo contesto "Perfecto 😊. Para agendar la consulta de 30
                # minutos..." como si no hubiera escuchado que ya la hizo.
                from backend.services.appointment_service import TEXTO_SIN_CONSULTA_PREVIA
                if any(TEXTO_SIN_CONSULTA_PREVIA in (r or "") for r in resultados_tools) \
                        and not re.search(r"no (encuentro|figura|aparece|veo)", texto or "", re.IGNORECASE):
                    from backend.services.appointment_service import BOTON_CONSULTA_CONDUCTO
                    from bot.tools.appointment_tools import set_opciones_ofrecidas
                    logger.warning("AI_AGENT -> No dijo que la consulta previa no figura; se repone textual.")
                    set_opciones_ofrecidas([BOTON_CONSULTA_CONDUCTO], siempre=True, tipo="botones")
                    return TEXTO_SIN_CONSULTA_PREVIA

                # La pregunta de conducto tiene que llevar los dos tiempos: el
                # paciente elige entre 30' y 1 hora, no entre dos frases vagas.
                #
                # Tambien cuando el modelo pregunta por su cuenta, sin que una
                # herramienta se lo pida. Simulacion 22/10: "¿venís derivado o es
                # para una consulta de evaluación?" pone derivado y evaluacion
                # como alternativas y ni nombra el tratamiento ni los tiempos.
                pidio_la_tool = any("Ya hiciste esa consulta" in (r or "")
                                    for r in resultados_tools)
                # Y SIEMPRE que haga la pregunta ("¿ya hiciste esa consulta?"),
                # aunque la escriba bien: sale el texto fijo con los dos botones.
                # Prueba real 15/11: vino pegada a un saludo y sin botones.
                hace_la_pregunta = "ya hiciste esa consulta" in (texto or "").lower()
                if hace_la_pregunta or (pidio_la_tool or _pregunta_conducto_sin_resolver(texto)) and (
                    "?" in texto and "30" not in texto
                    and any(p in texto.lower() for p in ("conducto", "derivad", "evaluaci"))
                ):
                    from backend.services.appointment_service import (
                        PREGUNTA_CONDUCTO_PACIENTE, BOTON_CONSULTA_CONDUCTO,
                        BOTON_TRATAMIENTO_CONDUCTO,
                    )
                    from bot.tools.appointment_tools import set_opciones_ofrecidas
                    logger.warning(
                        "AI_AGENT -> Parafraseó la pregunta de conducto sin los "
                        "tiempos; se repone textual. Mensaje: %d caracteres (texto omitido)", len(texto),
                    )
                    set_opciones_ofrecidas([BOTON_CONSULTA_CONDUCTO, BOTON_TRATAMIENTO_CONDUCTO],
                                           siempre=True, tipo="botones")
                    return PREGUNTA_CONDUCTO_PACIENTE
                if inexistente:
                    # Sigue nombrando a "Sosa" como si existiera, o no aclaró
                    # que no existe: lo dice el código.
                    reales = [a.lower() for a in _apellidos_reales().values()]
                    aclaro = re.search(r"\bno\s+(tenemos|hay|existe|contamos)", texto, re.IGNORECASE)
                    nombra_reales = any(a in texto.lower() for a in reales)
                    if not (aclaro and nombra_reales):
                        logger.error(
                            "AI_AGENT -> Siguió como si '%s' existiera. Mensaje: %d caracteres (texto omitido)",
                            inexistente, len(texto),
                        )
                        return mensaje_profesional_inexistente(inexistente)
                return corregir_apellidos(texto)

            for round_num in range(MAX_TOOL_ROUNDS):
                response = client.chat.completions.create(
                    model=model,
                    messages=conv,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    **_parametros_modelo(model),
                )
                _registrar_uso(response, f"ronda {round_num + 1}/{MAX_TOOL_ROUNDS}")

                choice = response.choices[0]
                msg = choice.message

                # No tool calls → final text response
                if not msg.tool_calls:
                    result = msg.content or ""
                    if _promete_sin_cumplir(result, agendo_de_verdad):
                        logger.error(
                            "AI_AGENT -> El modelo confirmó un turno que NUNCA se agendó. "
                            "Mensaje bloqueado: %d caracteres (texto omitido)", len(result),
                        )
                        return _SIN_RESPALDO, None, get_estado_conversacion()
                    # Si en esta vuelta se agendo de verdad, sale la confirmacion
                    # del turno guardado y nada mas. Simulacion 22/10: despues de
                    # agendar, el modelo volvio a consultar y escribio horarios;
                    # el filtro de horarios inventados devolvio la lista de nuevo,
                    # el paciente nunca supo que ya tenia turno y eligio otro.
                    if agendo_de_verdad and (conf := confirmacion_turno_agendada()):
                        return conf, None, get_estado_conversacion()
                    if result and not derivo_de_verdad and _PROMETE_AVISO.search(result):
                        logger.error(
                            "AI_AGENT -> Prometió contacto/derivación sin indicar "
                            "llamar. Mensaje bloqueado: %d caracteres (texto omitido)", len(result),
                        )
                        return _AVISO_SIN_CASO, None, get_estado_conversacion()

                    consultado = disponibilidad_consultada()
                    inventados = _horarios_inventados(result, consultado)
                    if inventados:
                        logger.error(
                            "AI_AGENT -> El modelo ofreció horarios que NINGUNA "
                            "herramienta devolvió (%s). Consultado: %s. Mensaje: %d caracteres (texto omitido)",
                            ", ".join(inventados), consultado, len(result),
                        )
                        rearmado = (_mensaje_con_los_horarios_reales(consultado)
                                    or _consultar_yo_mismo())
                        return (rearmado or ofrecer_quien_lo_atiende(resultados_tools) or _SIN_HORARIOS), tomar_opciones_ofrecidas(), get_estado_conversacion()

                    rearmado_negacion = _niega_habiendo_horarios(result, consultado)
                    if rearmado_negacion:
                        logger.error(
                            "AI_AGENT -> El modelo negó disponibilidad con horarios "
                            "reales en mano. Consultado: %s. Mensaje: %d caracteres (texto omitido)",
                            consultado, len(result),
                        )
                        return rearmado_negacion, tomar_opciones_ofrecidas(), get_estado_conversacion()

                    atribuido = _atribucion_falsa(result, consultado)
                    if atribuido:
                        logger.error(
                            "AI_AGENT -> Atribuyó horarios a '%s' sin haber consultado "
                            "por esa persona. Consultado: %s. Mensaje: %d caracteres (texto omitido)",
                            atribuido, consultado, len(result),
                        )
                        propio = _consultar_yo_mismo()
                        return ((propio or ofrecer_quien_lo_atiende(resultados_tools) or _SIN_HORARIOS), tomar_opciones_ofrecidas(),
                                get_estado_conversacion())
                    # Camino normal: horarios y confirmación los arma el código.
                    result = _respuesta_con_plantillas(result, consultado, agendo_de_verdad)
                    rescatado = _rescatar_afirmacion(result, consultado, agendo_de_verdad)
                    if rescatado:
                        return rescatado, tomar_opciones_ofrecidas(), get_estado_conversacion()
                    logger.info(f"AI_AGENT -> Respuesta final (ronda {round_num + 1}): {result[:80]}...")
                    return _pulir(result), tomar_opciones_ofrecidas(), get_estado_conversacion()

                # Execute each tool call
                logger.info(f"AI_AGENT -> Ronda {round_num + 1}: {len(msg.tool_calls)} tool call(s)")

                # Add assistant message with tool calls to conversation
                assistant_entry = {"role": "assistant", "content": msg.content or ""}
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
                conv.append(assistant_entry)

                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    tool_result = execute_tool(tc.function.name, args)
                    resultados_tools.append(tool_result)
                    if tc.function.name in (
                        "agendar_turno", "cancelar_turno", "reprogramar_turno",
                    ) and tool_result.startswith("✅"):
                        # La agenda cambió: el webhook manda esta respuesta
                        # aunque el paciente haya escrito de nuevo mientras tanto.
                        set_estado_conversacion(
                            {**get_estado_conversacion(), "accion_hecha": True})
                    if tc.function.name == "agendar_turno" and tool_result.startswith("✅"):
                        agendo_de_verdad = True
                    if tc.function.name in (
                        "indicar_llamar_consultorio", "derivar_a_recepcion",
                    ) and tool_result.startswith("✅"):
                        derivo_de_verdad = True
                    # Los argumentos traen nombre, DNI y motivo: solo el nombre de la tool.
                    logger.info(f"  🔧 {tc.function.name}(…) → {len(tool_result)} caracteres")
                    conv.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    })

            # Exhausted tool rounds — get final response without tools
            logger.warning(f"AI_AGENT -> Agotó {MAX_TOOL_ROUNDS} rondas de tools, pidiendo respuesta final")
            response = client.chat.completions.create(
                model=model,
                messages=conv,
                **_parametros_modelo(model),
            )
            _registrar_uso(response, "cierre sin tools")
            final = response.choices[0].message.content or ""
            if agendo_de_verdad and (conf := confirmacion_turno_agendada()):
                return conf, None, get_estado_conversacion()
            if _promete_sin_cumplir(final, agendo_de_verdad):
                logger.error(
                    "AI_AGENT -> El modelo confirmó un turno que NUNCA se agendó "
                    "(tras agotar las rondas). Mensaje bloqueado: %d caracteres (texto omitido)", len(final),
                )
                return _SIN_RESPALDO, None, get_estado_conversacion()
            if final and not derivo_de_verdad and _PROMETE_AVISO.search(final):
                logger.error(
                    "AI_AGENT -> Prometió contacto/derivación sin indicar "
                    "llamar. Mensaje bloqueado: %d caracteres (texto omitido)", len(final),
                )
                return _AVISO_SIN_CASO, None, get_estado_conversacion()

            consultado = disponibilidad_consultada()
            inventados = _horarios_inventados(final, consultado)
            if inventados:
                logger.error(
                    "AI_AGENT -> Ofreció horarios que NINGUNA herramienta devolvió "
                    "(%s) tras agotar las rondas. Mensaje: %d caracteres (texto omitido)",
                    ", ".join(inventados), len(final),
                )
                rearmado = (_mensaje_con_los_horarios_reales(consultado)
                            or _consultar_yo_mismo())
                return (rearmado or ofrecer_quien_lo_atiende(resultados_tools) or _SIN_HORARIOS), tomar_opciones_ofrecidas(), get_estado_conversacion()

            rearmado_negacion = _niega_habiendo_horarios(final, consultado)
            if rearmado_negacion:
                logger.error(
                    "AI_AGENT -> Negó disponibilidad con horarios reales "
                    "(tras agotar rondas). Consultado: %s. Mensaje: %d caracteres (texto omitido)",
                    consultado, len(final),
                )
                return rearmado_negacion, tomar_opciones_ofrecidas(), get_estado_conversacion()

            atribuido = _atribucion_falsa(final, consultado)
            if atribuido:
                logger.error(
                    "AI_AGENT -> Atribuyó horarios a '%s' sin consultar por esa "
                    "persona, tras agotar las rondas. Mensaje: %d caracteres (texto omitido)",
                    atribuido, len(final),
                )
                propio = _consultar_yo_mismo()
                return ((propio or ofrecer_quien_lo_atiende(resultados_tools) or _SIN_HORARIOS), tomar_opciones_ofrecidas(),
                        get_estado_conversacion())
            final = _respuesta_con_plantillas(final, consultado, agendo_de_verdad)
            rescatado = _rescatar_afirmacion(final, consultado, agendo_de_verdad)
            if rescatado:
                return rescatado, tomar_opciones_ofrecidas(), get_estado_conversacion()
            return _pulir(final), tomar_opciones_ofrecidas(), get_estado_conversacion()

        except Exception as e:
            logger.error("AI_AGENT -> Falló OpenAI (%s): %s", model, e)

    return (
        "Perdón, tuve un problema para procesar tu mensaje. 🙏 Probá de nuevo "
        f"en unos minutos o llamá al consultorio al *{telefono_consultorio()}*."
    ), None, get_estado_conversacion()
