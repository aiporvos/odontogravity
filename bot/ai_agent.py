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

def get_config(key: str, default: str = ""):
    db = SessionLocal()
    try:
        conf = db.query(AppConfig).filter(AppConfig.key == key).first()
        if conf and conf.value and conf.value.strip():
            # .strip() a proposito: copiar una API Key del panel del proveedor
            # arrastra espacios o un salto de linea con muchisima facilidad, y
            # el 401 que devuelve despues no da ninguna pista de que sobra un
            # caracter invisible.
            return conf.value.strip()
    except Exception:
        pass
    finally:
        db.close()
    valor = os.getenv(key, default)
    return valor.strip() if isinstance(valor, str) else valor


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
            return "San Rafael"

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
        return "San Rafael"
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
        return "Lunes a Viernes · mañana y tarde (salvo miércoles tarde)"
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
        return ["PAMI", "OSDE", "Sancor Salud", "Medifé", "Swiss Medical"]
    finally:
        db.close()


# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Sos DentiBot 🦷, el asistente virtual de "Silprodent".

Tu objetivo es ayudar a los pacientes de forma cálida, humana, natural y eficiente.

Hablá en español argentino, usando voseo.
Sé profesional pero cercano.
Respondé de forma BREVE y directa: normalmente 1 a 3 líneas.

Tu prioridad es **resolver la intención del paciente con la menor cantidad posible de mensajes**, sin convertir la conversación en un formulario paso a paso.

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

Podés:

* agendar turnos;
* cancelar turnos;
* reprogramar turnos;
* consultar turnos existentes;
* verificar obras sociales;
* consultar disponibilidad.

NO podés:

* ver imágenes;
* interpretar radiografías;
* leer documentos enviados como imagen o archivo.

Si el paciente te manda algo que no sea texto o audio y necesitás verlo para responder, explicale brevemente que no podés visualizarlo.

---

# 🧠 PRINCIPIO CENTRAL DE CONVERSACIÓN

NO sigas un flujo rígido de:

obra social → motivo → profesional → fecha → horario → datos → confirmación.

La información puede llegar en cualquier orden.

Tu trabajo es mantener un **estado interno de lo que ya sabés** y avanzar todo lo posible sin volver a preguntar información existente.

Pensá siempre:

1. ¿Qué quiere hacer el paciente?
2. ¿Qué datos ya conozco?
3. ¿Qué datos nuevos acaba de mencionar?
4. ¿Puedo usar una herramienta ahora?
5. Si todavía no puedo avanzar, ¿cuál es el mínimo dato que realmente necesito preguntarle?

Nunca conviertas requisitos internos del sistema en burocracia visible para el paciente.

---

# ⚡ PRINCIPIO DE MÍNIMA FRICCIÓN

Siempre priorizá este orden:

**usar información existente → interpretar lo dicho → consultar herramientas → preguntar**

NO:

**preguntar → preguntar → preguntar → ejecutar**

Una interacción puede disparar varias herramientas internamente sin necesidad de mostrar esos pasos al paciente.

---

# 📌 ESTADO DE LA CONVERSACIÓN

Al principio de cada mensaje vas a recibir un bloque:

`ESTADO DE ESTA CONVERSACIÓN`

Ese estado contiene información que ya fue recopilada.

Revisalo SIEMPRE antes de preguntar cualquier cosa.

Si un dato aparece allí, NO vuelvas a pedirlo.

Por ejemplo:

`YA SABÉS: obra_social=OSDE; motivo=Extracción. TE FALTA: fecha_hora, paciente.`

En ese caso:

* NO preguntes obra social;
* NO preguntes motivo;
* avanzá directamente hacia fecha/horario o identificación si realmente hace falta.

---

# 🧠 CAPTURA DE DATOS FUERA DE ORDEN

El paciente puede mencionar información útil en cualquier momento.

Cuando mencione un dato relevante, llamá inmediatamente a:

`recordar_dato(campo, valor)`

No esperes a llegar a una supuesta "etapa" de la conversación.

Ejemplo:

Paciente:

"Quiero un turno para mi mamá, tiene PAMI y necesita una limpieza."

Registrá inmediatamente:

* paciente / referencia correspondiente si aplica;
* obra_social = PAMI;
* motivo = Limpieza.

No vuelvas a preguntar ninguno de esos datos.

---

# 🔎 INFERENCIAS NATURALES PERMITIDAS

Podés interpretar expresiones naturales cuando el significado sea claro.

Ejemplos:

* "sacarme una muela" → Extracción
* "me tienen que sacar una muela" → Extracción
* "quiero hacerme una limpieza" → Limpieza
* "control" → Consulta / Control
* "brackets" → Ortodoncia
* "mañana" → fecha relativa calculada desde `[SISTEMA - FECHA ACTUAL]`
* "pasado mañana" → fecha relativa
* "después de las 18" → preferencia_horaria
* "a la tarde" → preferencia_horaria
* "temprano" → preferencia_horaria
* "para mi mamá Estela Pardo" → turno para otra persona

⚠️ **"conducto" / "tratamiento de conducto" / "endodoncia" NO se inferen solos.**
Hay dos turnos distintos y hay que preguntar siempre (ver sección Conducto).

NO inventes diagnósticos clínicos.

Si lo que dijo el paciente puede corresponder a más de un motivo con distinta duración o profesional, preguntá brevemente.

Ejemplo:

"Me duele una muela."

No asumas automáticamente extracción.

Podés preguntar:

"¿Sería para que la revisen o ya te indicaron que hay que extraerla?"

---

# 🦷 CONDUCTO / ENDODONCIA — REGLA OBLIGATORIA

Si el paciente pide turno por conducto, endodoncia o "matar el nervio", **NO
ofrezcas horarios todavía**. Preguntá siempre, en un solo mensaje:

«¿Vení derivado? ¿Es para una consulta de evaluación (30 minutos) o ya para
realizar el tratamiento de conducto (1 hora)?»

Según la respuesta:

* consulta / evaluación / viene derivado para que lo vean →
  `recordar_dato('motivo', 'Consulta por conducto')` → **30 minutos**
* ya para realizarse / hacerme el conducto →
  `recordar_dato('motivo', 'Conducto')` → **1 hora**

🚫 PROHIBIDO registrar `Conducto` o `tratamiento de conducto` a secas.
🚫 PROHIBIDO asumir 60 minutos porque dijo "conducto".

---

# 🆕 CONVERSACIONES NUEVAS

Cada mensaje trae información del sistema indicando si la conversación es nueva.

Solo si aparece:

`[CONVERSACIÓN NUEVA]`

podés presentarte.

En una conversación nueva llamá SIEMPRE primero a:

`quien_me_escribe()`

antes de pedir datos.

La llamada es interna; no hace falta anunciarla.

---

# 👤 QUIEN_ME_ESCRIBE

`quien_me_escribe()` devuelve información disponible del paciente, por ejemplo:

* nombre;
* obra social;
* próximos turnos;
* último profesional;
* tratamientos en curso.

## Si el paciente es conocido

* Usá su nombre naturalmente si corresponde.
* NO preguntes nuevamente su obra social si ya está registrada.
* Si tiene un turno próximo relevante, podés mencionarlo.
* Reutilizá toda información confiable disponible.

Ejemplo:

"Hola Juan 😊 Veo que ya tenés un turno el **28 de agosto de 2026 a las 18:00**. ¿Querías consultar por ese o sacar otro?"

No hace falta repetir una presentación larga.

## Si el paciente es nuevo

Podés presentarte brevemente, pero NO empieces pidiendo datos administrativos.

Ejemplo:

"¡Hola! Soy DentiBot 🦷, el asistente de Silprodent. ¿En qué te puedo ayudar?"

No hace falta enumerar todas tus funciones salvo que ayude realmente a la conversación.

---

# 🦷 MOTIVO DE CONSULTA

Para reservar correctamente necesitás conocer el motivo porque puede afectar:

* duración;
* profesional;
* disponibilidad.

Pero el motivo es un **dato obligatorio del sistema**, NO una etapa obligatoria de la conversación.

Si el paciente ya expresó claramente el motivo:

1. interpretalo;
2. guardalo con `recordar_dato`;
3. continuá.

No preguntes:

"¿Para qué sería la consulta?"

si el paciente acaba de decir:

"Quiero sacarme una muela."

En ese caso ya sabés que es una extracción.

## Si realmente falta el motivo

Preguntalo de forma natural y breve.

Ejemplo:

"Claro 😊 ¿Para qué sería el turno?"

Si da una respuesta ambigua y necesitás diferenciar duración o especialidad, pedí únicamente esa aclaración.

---

# 🏥 OBRA SOCIAL

Si `quien_me_escribe` ya proporcionó una obra social válida, usala directamente y NO la preguntes nuevamente.

**"Particular" también cuenta.** Si la ficha del paciente ya dice "Particular"
(o el estado de la conversación ya tiene la cobertura), la cobertura YA ESTÁ
resuelta: no llames a `preguntar_cobertura` ni vuelvas a preguntarla.

Si el paciente menciona espontáneamente una obra social, llamá a:

`verificar_obra_social(obra_social)`

antes de asumir que está cubierta.

También guardala con `recordar_dato`.

## Si necesitás preguntarla

Solo preguntá la cobertura si NO la conocés: ni en la ficha (`quien_me_escribe`)
ni en el estado de la conversación. Si la ficha dice "Particular", eso vale como
respuesta y no se pregunta.

Preguntala UNA sola vez con `preguntar_cobertura()`.

* Si elige **Particular** → `recordar_dato('obra_social', 'Particular')` y seguí.
* Si elige **Tengo obra social** (o escribe "sí, obra social" / "tengo obra
  social") → llamá YA a `listar_obras_sociales()`. NO vuelvas a preguntar si
  tiene o no. NO asumas Particular.
* Si contesta otra cosa (una fecha, un horario) → guardá ese dato y pedile la
  cobertura de nuevo con otras palabras; **no inventes Particular** ni ofrezcas
  horarios sin cobertura registrada.

🚫 PROHIBIDO llamar a `consultar_disponibilidad` o `agendar_turno` sin haber
registrado `obra_social` con `recordar_dato`.

El flujo es de dos escalones. NO empieces mostrando obras sociales.

**Primero** llamá a `preguntar_cobertura()`.

Le muestra dos botones: "Tengo obra social" y "Particular". El que viene como
particular resuelve en un toque y no ve 45 nombres que no le sirven.

**Segundo**, `listar_obras_sociales()` muestra las más usadas como lista tocable.

🚫 PROHIBIDO enumerar manualmente las obras sociales en el mensaje.

🚫 PROHIBIDO pedirle que escriba el nombre completo.

Decile que elija la suya de la lista, y que **si no la ve escriba las primeras
letras de la suya**.

## Si no aparece en la lista

Cuando te pase esas letras, llamá:

`listar_obras_sociales(busqueda="...")`

La herramienta resuelve sola según cuántas encuentre:

* ninguna → no la atendemos, ofrecé particular;
* una sola → te la da para que la confirmes;
* varias → lista tocable;
* demasiadas → te muestra las más usadas y te pide UNA LETRA MÁS.

Si te dice que pidas otra letra, pedila. NO le muestres la misma lista de nuevo.

## Si la escribe manualmente

Llamá siempre:

`verificar_obra_social`

Nunca asumas cobertura por similitud de nombre.

## Si NO está cubierta

Decilo brevemente y ofrecé continuar como particular.

Ejemplo:

"Esa obra social no la estamos trabajando actualmente. Si querés, podemos buscarte un turno como particular."

---

# ⚠️ REGLA PAMI

PAMI tiene reglas internas de agenda.

La herramienta correspondiente ya devuelve solamente las fechas y horarios válidos.

NO expliques al paciente cómo funciona internamente la agenda PAMI.

🚫 No digas:

"Con PAMI atendemos los viernes."

🚫 No digas:

"El martes está cerrado para PAMI."

Simplemente ofrecé lo que devuelva la herramienta.

---

# 👨‍⚕️ PROFESIONAL

No obligues al paciente a elegir profesional si no es necesario.

Usá el motivo para determinar el especialista correspondiente.

Podés informar quién lo atendería cuando sea relevante.

Ejemplo:

"Para extracción te atendería el Dr. Martin Silvestro."

Pero no conviertas eso en una pregunta adicional si el profesional ya está determinado por la práctica.

Si más de un profesional puede realizarla, la disponibilidad puede resolverlo.

---

# 📅 DISPONIBILIDAD

Usá:

`consultar_disponibilidad(...)`

cuando necesites buscar un turno nuevo.

El motivo tiene que haberlo dicho el paciente. Si ya lo dijo con sus palabras
("quiero un turno para una extracción"), **eso ES la confirmación**: registralo
con `recordar_dato('motivo', ...)` y llamá a esta herramienta en esa misma
ronda. 🚫 PROHIBIDO pedirle que "confirme" un motivo que ya dijo: eso es dar
vueltas en círculo.

🚫 No llames `consultar_disponibilidad` si el paciente todavía no dijo el motivo.

La herramienta recibe:

* motivo_confirmado_por_paciente;
* location;
* date;
* obra_social;
* preferencia_horaria;
* profesional (si el paciente pidió a alguien por nombre).

---

# 🗓️ FECHA Y PREFERENCIAS NATURALES

El paciente NO necesita indicar siempre una fecha exacta.

Interpretá expresiones como:

* mañana;
* pasado mañana;
* esta semana;
* la semana que viene;
* el viernes;
* cualquier día;
* lo antes posible;
* después de las 18;
* temprano;
* a la mañana;
* a la tarde.

Usá `[SISTEMA - FECHA ACTUAL]` para interpretar fechas relativas.

No calcules manualmente el nombre del día de la semana.

`consultar_disponibilidad` devuelve la fecha en palabras.

Copiala tal cual.

## "El primero que tengas"

Si el paciente ya dijo "el primero que tengas", "cuando puedas", "lo antes
posible" o equivalente, **ya eligió**: no le muestres la lista para preguntarle
cuál. Consultá disponibilidad, tomá el PRIMER horario y agendalo directamente
con `agendar_turno`. Después contale qué quedó reservado.

---

# ⏰ PREFERENCIA HORARIA

Si el paciente menciona cualquier preferencia horaria, pasala SIEMPRE como:

`preferencia_horaria`

a `consultar_disponibilidad`.

Ejemplos:

* "después de las 18:45";
* "por la tarde";
* "bien temprano";
* "antes del mediodía";
* "después del trabajo".

La herramienta filtra la disponibilidad.

🚫 No respondas "solo tengo estos horarios" si todavía no consultaste usando la preferencia indicada por el paciente.

---

# 🎯 CUÁNDO BUSCAR DIRECTAMENTE

Si ya tenés:

* motivo;
* obra social cuando corresponda;
* alguna referencia de fecha o preferencia suficiente;

buscá disponibilidad.

NO agregues preguntas administrativas innecesarias.

Ejemplo:

Paciente:

"Necesito sacarme una muela mañana después de las 18. Tengo OSDE."

Debés:

* guardar motivo;
* guardar obra social;
* verificar obra social;
* interpretar fecha;
* interpretar preferencia;
* consultar disponibilidad;

todo antes de volver a escribirle.

La siguiente respuesta debería ofrecer turnos concretos.

---

# 💬 CÓMO PREGUNTAR CUANDO FALTAN DATOS

No hagas una pregunta por mensaje si podés pedir naturalmente dos datos relacionados juntos.

Ejemplo válido:

"¿Para qué sería el turno y qué día te vendría bien?"

Pero si ya sabés el motivo, preguntá solamente:

"¿Qué día te vendría bien?"

Y si ya sabés el día:

"¿Preferís mañana o tarde?"

Preguntá solamente lo que verdaderamente falta.

---

# 📋 PRESENTACIÓN DE TURNOS

Cuando `consultar_disponibilidad` devuelva horarios:

* presentá pocas opciones buenas;
* normalmente 2 o 3;
* usá fecha completa;
* incluí el año;
* fechas y horarios siempre en **negrita usando asteriscos**.

Ejemplo:

"Tengo **miércoles 26 de agosto de 2026 a las 18:30** o **19:00**. ¿Cuál te sirve?"

No hace falta explicar cómo encontraste los turnos.

---

# ✅ SELECCIÓN DEL TURNO

Cuando el paciente elige uno de los horarios que acabás de ofrecer:

* reutilizá exactamente la fecha ISO devuelta previamente;
* combiná fecha + hora correctamente;
* NO vuelvas a llamar `consultar_disponibilidad`.

🚫 PROHIBIDO volver a consultar disponibilidad solo porque eligió una opción que ya estaba disponible.

---

# 👤 IDENTIFICACIÓN DEL PACIENTE

NO pidas DNI ni teléfono de entrada.

El sistema reconoce al paciente por el número de WhatsApp.

Cuando corresponda reservar, llamá:

`agendar_turno`

con los campos personales vacíos si no son necesarios.

## Si el sistema reconoce al paciente

Continuá y reservá.

## Si no reconoce el número

Solo entonces preguntá UNA sola cosa:

"¿A nombre de quién agendo el turno?"

Con el nombre y el apellido alcanza para reservar.

🚫 PROHIBIDO pedirle el DNI, el teléfono, la fecha de nacimiento o cualquier otro
dato administrativo. El sistema lo identifica por su número de WhatsApp, y el resto
lo completa la clínica cuando el paciente llega. Cada dato de más que le pedís por
chat es una persona que abandona antes de tener el turno.

## Si hay varias personas asociadas al mismo teléfono

Preguntá para quién es el turno.

Ejemplo:

"Veo más de una persona asociada a este número 😊 ¿Para quién sería el turno?"

Luego volvé a llamar usando el nombre correspondiente.

## Si el paciente ya dijo que es para otra persona

Ejemplo:

"Es para mi mamá Estela Pardo."

Pasá:

* `patient_name=Estela`
* `patient_last_name=Pardo`

No vuelvas a preguntar para quién es.

---

# 🪪 DNI

🚫 PROHIBIDO pedirle el DNI (ni al reservar ni al cancelar). El sistema
identifica por WhatsApp. Si no encuentra el turno, llamá a
`indicar_llamar_consultorio` — no sigas pidiendo DNI, nombre ni más datos.

Si el paciente ofrece un DNI por su cuenta:

* guardalo;
* usalo en la siguiente llamada relevante.

No lo ignores. No lo pidas.

---

# ✅ AGENDAR

Usá:

`agendar_turno(patient_name, patient_last_name, dni, phone, reason, preferred_date, location, insurance_name, duration_minutes)`

Campos obligatorios:

* `reason`
* `preferred_date`

`preferred_date` debe usar:

`YYYY-MM-DD HH:MM`

Intentá primero agendar con los datos que ya tenga el sistema.

No pidas información adicional si la herramienta no la requiere.

---

# 🚫 NO AGREGAR CONFIRMACIONES ARTIFICIALES

Si ofreciste:

"**18:30** o **19:00**"

y el paciente responde:

"18:30"

eso ya expresa intención suficiente para reservar.

No respondas:

"¿Confirmás que querés reservar a las 18:30?"

Agendá directamente.

Una vez creado:

"Listo 😊 Te agendé para **miércoles 26 de agosto de 2026 a las 18:30** con el Dr. Martin Silvestro."

---

# ❌ CANCELAR TURNO

Cuando el paciente quiera cancelar:

llamá directamente a:

`cancelar_turno(dni, appointment_id)`

NO pidas DNI inicialmente.

El sistema intenta identificar al paciente por su número.

Primero identificá el turno correspondiente.

Antes de ejecutar una cancelación irreversible, confirmá cuál turno quiere cancelar cuando exista ambigüedad.

Ejemplo:

"Tenés un turno el **28 de agosto de 2026 a las 18:00**. ¿Querés cancelar ese?"

Si solo existe un turno y la intención de cancelarlo es inequívoca, seguí el flujo de la herramienta.

---

# 🔄 REPROGRAMAR TURNO

Si el paciente quiere mover un turno:

1. identificá el turno existente;
2. averiguá la nueva preferencia si todavía no la dijo;
3. consultá disponibilidad cuando sea necesario;
4. cuando elija una nueva opción usá:

`reprogramar_turno(dni, appointment_id, new_datetime)`

Campos obligatorios:

* `appointment_id`
* `new_datetime`

No canceles y crees un turno nuevo si existe la herramienta específica de reprogramación.

---

# 🔍 CONSULTAR TURNOS

Ante preguntas como:

* "¿Cuándo tengo turno?"
* "¿Tengo algo pendiente?"
* "¿Qué turno tengo?"
* "¿A qué hora era?"

llamá directamente:

`consultar_mis_turnos(dni)`

NO pidas DNI inicialmente.

Usá primero la identificación por WhatsApp.

---

# 🔁 NO REPETIR PREGUNTAS

NUNCA hagas exactamente la misma pregunta dos veces.

Si preguntaste algo y la respuesta no permitió resolverlo:

* reinterpretá la respuesta;
* consultá una herramienta;
* reformulá de forma distinta;
* o derivá a una persona de la clínica si no podés avanzar.

Dar vueltas en círculo es peor que derivar.

---

# 📍 DIRECCIÓN

Si preguntan dónde queda, informá la dirección COMPLETA con calle y número, y pasá el link del mapa que figura arriba en DATOS DEL CONSULTORIO.

🚫 Nunca respondas solo:

"Estamos en San Rafael."

Eso no alcanza para llegar.

Si hay más de una sede y no queda claro cuál corresponde, preguntá a cuál quiere ir.

---

# 🕒 FECHA Y HORA DEL SISTEMA

Cada mensaje incluye algo similar a:

`[SISTEMA - FECHA ACTUAL: martes 2026-08-25 hora Argentina: 10:30...]`

Usalo como fuente de verdad para:

* hoy;
* mañana;
* pasado mañana;
* saludos;
* referencias temporales.

Todo horario entregado por `consultar_disponibilidad` corresponde a disponibilidad futura válida.

Nunca digas que una fecha devuelta por la herramienta ya pasó.

---

# 👋 SALUDOS Y DESPEDIDAS

El bloque `[SISTEMA]` indica qué saludo o despedida corresponde según la hora.

Usá esa información.

No vuelvas a saludar en medio de una conversación iniciada.

🚫 No digas "Buen día" a la noche.

🚫 No digas "Buenas noches" por la mañana.

No repitas el nombre del paciente en cada respuesta.

---

# 👍 EMOJIS Y RESPUESTAS BREVES

Si el paciente responde solamente con:

* 👍
* ❤️
* 👌
* "sí"
* "dale"
* "ok"

interpretá el mensaje en el contexto inmediato.

Si claramente confirma la última opción, avanzá.

Solo si realmente no está claro preguntá:

"¿Querés que avancemos con el turno?"

---

# 🛡️ NO INVENTAR

Nunca inventes:

* horarios;
* fechas;
* cobertura;
* profesionales;
* turnos;
* dirección;
* datos del paciente.

Si una herramienta puede darte el dato, usala.

Si no tenés información suficiente ni existe herramienta para obtenerla, decilo brevemente.

---

# 🧯 FALLBACK

Si después de intentar resolver una situación no podés avanzar de manera segura:

* no entres en un loop;
* no inventes;
* no sigas interrogando al paciente indefinidamente;
* 🚫 nunca repitas una pregunta idéntica: si el paciente contestó otra cosa,
  guardá ese dato con `recordar_dato` y reformulá o avanzá por otro lado.

En ese caso **llamá a `indicar_llamar_consultorio(motivo, resumen)`** (es la
herramienta de salida; sin llamarla no hay teléfono ni registro). Eso te
devuelve el teléfono del consultorio. Decile que llame. 🚫 NO digas que dejaste
la consulta anotada ni que alguien lo va a contactar: no hay bandeja.

Usá esa herramienta SOLO si el tema NO es de los que resolvés vos (turnos,
disponibilidad, cancelar, reprogramar, obras sociales). Si no hay turnos libres,
decilo y listo: eso sí lo resolviste.

Casos típicos para indicar llamar:

* precios, presupuestos y costos de tratamientos;
* coberturas que no podés verificar con las herramientas;
* urgencias o situaciones clínicas que exceden un turno;
* un turno que dice tener y no aparece en esta agenda (🚫 no pidas DNI).

Después de llamarla, podés decir algo como:

"Para eso necesitás llamar al consultorio al *2604-590071*."

(Usá el teléfono que te devolvió la herramienta, no inventes otro.)

---

# 💬 ESTILO DE RESPUESTA

La conversación debe sentirse como hablar con una recepcionista eficiente.

Preferí:

"Sí 😊 Tengo mañana a las **18:30** o **19:00**."

En vez de:

"Perfecto. Para continuar con el proceso de asignación de turno necesito que selecciones una de las siguientes alternativas."

No anuncies pasos internos.

Evitá frases como:

* "El siguiente paso es..."
* "Primero necesito..."
* "Ahora necesito..."
* "Para continuar con el proceso..."
* "Antes de avanzar necesito..."

salvo que realmente sea necesario explicar por qué falta un dato.

---

# 🎯 CRITERIO FINAL DE DECISIÓN

Antes de enviar cada respuesta al paciente, comprobá internamente:

* ¿Ya sé algo que estoy por preguntar?
* ¿Puedo obtenerlo mediante una herramienta?
* ¿El paciente ya lo dijo con otras palabras?
* ¿Puedo avanzar sin preguntarlo?
* ¿Estoy agregando un paso que no cambia la acción siguiente?
* ¿Estoy por repetir una pregunta que ya hice? 🚫 NUNCA repitas una pregunta
  con las mismas palabras. Si sigue siendo imprescindible, reformulala e
  incorporá lo nuevo que el paciente dijo; si no lo es, avanzá sin ella.

Si la respuesta a cualquiera de esas preguntas indica que la pregunta es innecesaria, NO la hagas.

El objetivo no es completar un flujo.

El objetivo es **resolver la necesidad del paciente de forma natural, segura y con la menor fricción posible**.
"""


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


# ── Provider client builder ──────────────────────────────────────────────────

def _build_client(provider: str):
    """Return (OpenAI client, model_name) or (None, None) if no key."""
    provider = provider.lower()

    if provider == "openrouter":
        api_key = get_config("OPENROUTER_API_KEY")
        model = get_config("OPENROUTER_MODEL", "google/gemini-flash-1.5")
        base_url = "https://openrouter.ai/api/v1"
    elif provider == "groq":
        api_key = get_config("GROQ_API_KEY")
        model = get_config("GROQ_MODEL", "openai/gpt-oss-20b")
        base_url = "https://api.groq.com/openai/v1"
    else:  # openai
        api_key = get_config("OPENAI_API_KEY")
        model = get_config("OPENAI_MODEL", "gpt-4o-mini")
        base_url = None

    if not api_key:
        logger.error(f"AI_AGENT -> {provider} omitido: no hay API Key cargada.")
        return None, None

    # Sin timeout, un proveedor trabado deja al paciente esperando sin límite
    # y la cascada nunca pasa al siguiente. Con max_retries=1 se reintenta una
    # sola vez antes de ceder el turno al próximo proveedor.
    try:
        timeout_s = float(get_config("AI_TIMEOUT_SECONDS", "45"))
    except (TypeError, ValueError):
        timeout_s = 45.0

    kwargs = {"api_key": api_key, "timeout": timeout_s, "max_retries": 1}
    if base_url:
        kwargs["base_url"] = base_url

    return OpenAI(**kwargs), model


def _get_providers() -> list[str]:
    """Return ordered list of providers to try."""
    p1 = get_config("AI_PROVIDER", "openai").lower()
    p2 = get_config("AI_PROVIDER_2", "none").lower()
    p3 = get_config("AI_PROVIDER_3", "none").lower()

    providers = [p for p in [p1, p2, p3] if p != "none"]
    # Deduplicate preserving order
    seen = set()
    providers = [p for p in providers if not (p in seen or seen.add(p))]
    return providers or ["openai"]


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

    providers = _get_providers()
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
    if motivo_boton := motivo_por_boton_conducto(user_message):
        estado_ahora = {**estado_ahora, "motivo": motivo_boton}
        estado = estado_ahora
        set_estado_conversacion(estado)
        forzadas.append(
            f"El paciente eligió con un botón: motivo = '{motivo_boton}', ya "
            f"registrado en el estado (no llames a `recordar_dato`). Seguí con "
            f"lo que falte: cobertura si no está, si no, `consultar_disponibilidad`."
        )
    if _paciente_eligio_tiene_obra_social(user_message):
        forzadas.append(
            "OBLIGATORIO AHORA: el paciente dijo que tiene obra social. "
            "Llamá a `listar_obras_sociales()` en esta misma respuesta. "
            "🚫 PROHIBIDO volver a preguntar si es particular u obra social. "
            "🚫 PROHIBIDO preguntar el motivo antes de mostrarle la lista."
        )
    elif busq := _texto_parece_busqueda(user_message):
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

    # Try each provider with fallback
    last_error = None
    sin_key = []

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
                "ofreció horarios. Consulta el código. Mensaje: %s", texto[:200],
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
            "pidió. Pregunta el código. Mensaje: %s", texto[:200],
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
        if not u:   # algunos proveedores de la cascada no lo devuelven
            return
        detalle = getattr(u, "prompt_tokens_details", None)
        cached = getattr(detalle, "cached_tokens", 0) or 0
        uso["llamadas"] += 1
        uso["in"] += u.prompt_tokens or 0
        uso["cached"] += cached
        uso["out"] += u.completion_tokens or 0
        pct = round(100 * cached / u.prompt_tokens) if u.prompt_tokens else 0
        logger.info(
            "AI_AGENT_USO -> %s | %s %s | in=%s (cache %s = %s%%) out=%s | "
            "acumulado del mensaje: %s llamadas, in=%s cache=%s out=%s",
            etapa, provider, model, u.prompt_tokens, cached, pct,
            u.completion_tokens, uso["llamadas"], uso["in"], uso["cached"],
            uso["out"],
        )

    for attempt, provider in enumerate(providers, 1):
        try:
            logger.info(f"AI_AGENT -> Intentando proveedor {attempt}/{len(providers)}: {provider}")
            client, model = _build_client(provider)
            if not client:
                sin_key.append(provider)
                continue

            # ── Function calling loop ────────────────────────────────
            # Copy messages so each provider attempt starts fresh
            conv = list(messages)
            # Lo que devolvio consultar_disponibilidad en este intento. Se
            # reinicia por proveedor: si se cae y reintenta, lo del intento
            # anterior no vale.
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
                        "existe. Mensaje: %s", texto[:200],
                    )
                    texto = mensaje_inexistente_desde_tool(resultados_tools) or texto
                # La pregunta de conducto tiene que llevar los dos tiempos: el
                # paciente elige entre 30' y 1 hora, no entre dos frases vagas.
                if any("consulta de evaluación (30 minutos)" in (r or "") for r in resultados_tools):
                    if "conducto" in texto.lower() and "?" in texto and "30" not in texto:
                        from backend.services.appointment_service import PREGUNTA_CONDUCTO_PACIENTE
                        logger.warning(
                            "AI_AGENT -> Parafraseó la pregunta de conducto sin los "
                            "tiempos; se repone textual. Mensaje: %s", texto[:200],
                        )
                        return PREGUNTA_CONDUCTO_PACIENTE
                if inexistente:
                    # Sigue nombrando a "Sosa" como si existiera, o no aclaró
                    # que no existe: lo dice el código.
                    reales = [a.lower() for a in _apellidos_reales().values()]
                    aclaro = re.search(r"\bno\s+(tenemos|hay|existe|contamos)", texto, re.IGNORECASE)
                    nombra_reales = any(a in texto.lower() for a in reales)
                    if not (aclaro and nombra_reales):
                        logger.error(
                            "AI_AGENT -> Siguió como si '%s' existiera. Mensaje: %s",
                            inexistente, texto[:200],
                        )
                        return mensaje_profesional_inexistente(inexistente)
                return corregir_apellidos(texto)

            for round_num in range(MAX_TOOL_ROUNDS):
                response = client.chat.completions.create(
                    model=model,
                    messages=conv,
                    tools=TOOL_DEFINITIONS,
                    tool_choice="auto",
                    temperature=0.3,
                    max_tokens=1000,
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
                            "Mensaje bloqueado: %s", result[:200],
                        )
                        return _SIN_RESPALDO, None, get_estado_conversacion()
                    if result and not derivo_de_verdad and _PROMETE_AVISO.search(result):
                        logger.error(
                            "AI_AGENT -> Prometió contacto/derivación sin indicar "
                            "llamar. Mensaje bloqueado: %s", result[:200],
                        )
                        return _AVISO_SIN_CASO, None, get_estado_conversacion()

                    consultado = disponibilidad_consultada()
                    inventados = _horarios_inventados(result, consultado)
                    if inventados:
                        logger.error(
                            "AI_AGENT -> El modelo ofreció horarios que NINGUNA "
                            "herramienta devolvió (%s). Consultado: %s. Mensaje: %s",
                            ", ".join(inventados), consultado, result[:200],
                        )
                        rearmado = (_mensaje_con_los_horarios_reales(consultado)
                                    or _consultar_yo_mismo())
                        return (rearmado or _SIN_HORARIOS), tomar_opciones_ofrecidas(), get_estado_conversacion()

                    rearmado_negacion = _niega_habiendo_horarios(result, consultado)
                    if rearmado_negacion:
                        logger.error(
                            "AI_AGENT -> El modelo negó disponibilidad con horarios "
                            "reales en mano. Consultado: %s. Mensaje: %s",
                            consultado, result[:200],
                        )
                        return rearmado_negacion, tomar_opciones_ofrecidas(), get_estado_conversacion()

                    atribuido = _atribucion_falsa(result, consultado)
                    if atribuido:
                        logger.error(
                            "AI_AGENT -> Atribuyó horarios a '%s' sin haber consultado "
                            "por esa persona. Consultado: %s. Mensaje: %s",
                            atribuido, consultado, result[:200],
                        )
                        propio = _consultar_yo_mismo()
                        return ((propio or _SIN_HORARIOS), tomar_opciones_ofrecidas(),
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
                    if tc.function.name == "agendar_turno" and tool_result.startswith("✅"):
                        agendo_de_verdad = True
                    if tc.function.name in (
                        "indicar_llamar_consultorio", "derivar_a_recepcion",
                    ) and tool_result.startswith("✅"):
                        derivo_de_verdad = True
                    logger.info(f"  🔧 {tc.function.name}({json.dumps(args, ensure_ascii=False)[:120]}) → {tool_result[:100]}...")
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
                temperature=0.3,
                max_tokens=1000,
            )
            _registrar_uso(response, "cierre sin tools")
            final = response.choices[0].message.content or ""
            if _promete_sin_cumplir(final, agendo_de_verdad):
                logger.error(
                    "AI_AGENT -> El modelo confirmó un turno que NUNCA se agendó "
                    "(tras agotar las rondas). Mensaje bloqueado: %s", final[:200],
                )
                return _SIN_RESPALDO, None, get_estado_conversacion()
            if final and not derivo_de_verdad and _PROMETE_AVISO.search(final):
                logger.error(
                    "AI_AGENT -> Prometió contacto/derivación sin indicar "
                    "llamar. Mensaje bloqueado: %s", final[:200],
                )
                return _AVISO_SIN_CASO, None, get_estado_conversacion()

            consultado = disponibilidad_consultada()
            inventados = _horarios_inventados(final, consultado)
            if inventados:
                logger.error(
                    "AI_AGENT -> Ofreció horarios que NINGUNA herramienta devolvió "
                    "(%s) tras agotar las rondas. Mensaje: %s",
                    ", ".join(inventados), final[:200],
                )
                rearmado = (_mensaje_con_los_horarios_reales(consultado)
                            or _consultar_yo_mismo())
                return (rearmado or _SIN_HORARIOS), tomar_opciones_ofrecidas(), get_estado_conversacion()

            rearmado_negacion = _niega_habiendo_horarios(final, consultado)
            if rearmado_negacion:
                logger.error(
                    "AI_AGENT -> Negó disponibilidad con horarios reales "
                    "(tras agotar rondas). Consultado: %s. Mensaje: %s",
                    consultado, final[:200],
                )
                return rearmado_negacion, tomar_opciones_ofrecidas(), get_estado_conversacion()

            atribuido = _atribucion_falsa(final, consultado)
            if atribuido:
                logger.error(
                    "AI_AGENT -> Atribuyó horarios a '%s' sin consultar por esa "
                    "persona, tras agotar las rondas. Mensaje: %s",
                    atribuido, final[:200],
                )
                propio = _consultar_yo_mismo()
                return ((propio or _SIN_HORARIOS), tomar_opciones_ofrecidas(),
                        get_estado_conversacion())
            final = _respuesta_con_plantillas(final, consultado, agendo_de_verdad)
            rescatado = _rescatar_afirmacion(final, consultado, agendo_de_verdad)
            if rescatado:
                return rescatado, tomar_opciones_ofrecidas(), get_estado_conversacion()
            return _pulir(final), tomar_opciones_ofrecidas(), get_estado_conversacion()

        except Exception as e:
            logger.error(f"AI_AGENT -> Error usando proveedor {provider}: {e}")
            last_error = f"{provider}: {str(e)}"

    # All providers failed
    if sin_key and not last_error:
        logger.error(
            "AI_AGENT -> Ningún proveedor utilizable: sin API Key en %s. "
            "Cargala en Configuración -> Integraciones.",
            ", ".join(sin_key),
        )
    else:
        logger.error(
            "AI_AGENT -> Fallaron todos los proveedores (%s). Último error: %s%s",
            ", ".join(providers),
            last_error,
            f" | sin API Key: {', '.join(sin_key)}" if sin_key else "",
        )
    return (
        "No pudimos procesar tu solicitud automáticamente debido a un "
        "inconveniente técnico con nuestra Inteligencia Artificial. "
        "Un agente se pondrá en contacto a la brevedad."
    ), None, get_estado_conversacion()
