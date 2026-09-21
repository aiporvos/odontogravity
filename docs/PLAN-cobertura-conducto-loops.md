# Plan — cobertura, conducto 30'/60', profesionales y loops

Origen: charla real de Claudio del 21/09/2026 (reset → «quiero turno» → nunca
llegó a un horario). Revisión completa en la sesión del 21/09.

Base: `main` @ `77ce6b2` (ya incluye: motivo ≠ obra social, forzar listado tras
«tengo obra social», bloqueo de agenda sin cobertura, siembra de la ficha,
fuzzy «Silvestre», y la regla de conducto en su primera versión).

---

## Principio rector

**El código decide, el modelo redacta.** Cada vez que una decisión quedó en
manos del modelo (registrar la obra social, elegir la duración, buscar
horarios cuando el paciente dijo «sí»), apareció un loop. Cada etapa de este
plan mueve una de esas decisiones al código y deja al modelo solo la
redacción. Ningún prompt nuevo sin su barrera en código.

Método por etapa, siempre igual:

1. **Spec** (Gherkin) en este documento.
2. **Tests primero** (rojos) que fijan la spec.
3. Implementación mínima que los pone verdes.
4. Suite completa verde (`TEST_DATABASE_URL=... .venv/bin/pytest -q`).
5. Commit por etapa, mensaje en castellano, sin secretos en el diff.

Deploy: `main` tiene auto-deploy. Se deploya al cerrar E1+E2 (críticas) y
otra vez al cerrar E3–E7. Verificación post-deploy: `/api/health` con
`codigo` del día + charla real por WhatsApp (guion en E8).

---

## E1 — La cobertura la registra el código

### Problema
`verificar_obra_social` (CUBIERTA) y `listar_obras_sociales` (una sola
coincidencia) le **piden al modelo** que llame `recordar_dato`. Si no lo hace,
`_exigir_cobertura` bloquea horarios y el bot vuelve a preguntar la cobertura
aunque el paciente acabe de escribir «Avalian». Tocar la obra social en la
lista dispara otra vez «¿es Avalian?».

### Spec
```gherkin
Feature: La cobertura queda registrada sin depender del modelo

  Scenario: El paciente escribe el nombre exacto de una obra social atendida
    Given la clínica atiende "Avalian"
    And el estado no tiene obra_social
    When el paciente escribe "Avalian"
    Then el estado queda con obra_social="Avalian"
    And la herramienta responde "✅ Cobertura registrada: Avalian. Seguí con el turno"
    And no se le vuelve a preguntar la cobertura

  Scenario: El paciente toca una obra social de la lista tocable
    Given se le mostró la lista de obras sociales
    When llega el texto exacto de una fila (ej. "OSDE")
    Then el estado queda con obra_social="OSDE" sin pedir confirmación

  Scenario: verificar_obra_social confirma una cobertura
    When verificar_obra_social("osde") devuelve CUBIERTA con nombre "OSDE"
    Then el estado queda con obra_social="OSDE"

  Scenario: Búsqueda con una sola coincidencia NO exacta
    Given la clínica atiende "OSPELSYM" y el paciente escribe "ospeysin"
    Then se le muestran botones "OSPELSYM" / "No es esa"
    And al tocar "OSPELSYM" el estado queda registrado (escenario 2)

  Scenario: Búsqueda sin coincidencias
    When el paciente escribe "banelco"
    Then se le muestra la lista de las atendidas + "Particular"
    And NO se registra nada

  Scenario: La barrera reconoce que el paciente ya nombró su cobertura
    Given el estado no tiene obra_social
    And el último mensaje del paciente parece un nombre de obra social
    When el modelo llama consultar_disponibilidad
    Then la herramienta resuelve la cobertura contra el backend ella misma
    And si es exacta la registra y sigue; si no, ordena listar_obras_sociales(busqueda)
    And NUNCA ordena preguntar_cobertura() de nuevo
```

### Tests primero
- `tests/test_cobertura_por_codigo.py` (nuevo): los 6 escenarios. Las tools
  hablan por HTTP con `API_BASE`; usar el mismo patrón de mock de
  `tests/test_busqueda_sin_cooperacion.py`.
- Ajustar `tests/test_cobertura_obligatoria.py::test_no_consulta_horarios_sin_cobertura`
  para el nuevo mensaje de la barrera.

### Implementación mínima
- `backend/routers/bot_routes.py` `GET /api/bot/obras-sociales`: devolver
  además `exacta: str|null` (nombre canónico si `q` coincide exacto sin
  acentos/mayúsculas).
- `bot/tools/appointment_tools.py`:
  - helper `_registrar_cobertura(nombre)` (escribe estado, limpia
    `cobertura_preguntada`).
  - `listar_obras_sociales`: si `exacta` → registrar y devolver «✅ Cobertura
    registrada…». Si 1 coincidencia no exacta → botones (ya está).
  - `verificar_obra_social`: en CUBIERTA → registrar.
  - `_exigir_cobertura`: si `_texto_parece_busqueda(ultimo)` → consultar
    `/obras-sociales?q=` y resolver como arriba; nunca devolver «llamá
    preguntar_cobertura» en ese caso.
- `bot/ai_agent.py`: el bloque forzado de «primeras letras» pasa a decir
  «llamá listar_obras_sociales(busqueda=…)» solo si no quedó registrada por
  código (revisar el estado después de las tools, no antes).

### Archivos
`bot/tools/appointment_tools.py`, `backend/routers/bot_routes.py`,
`bot/ai_agent.py`, tests.

---

## E2 — Conducto: 30' o 60' de punta a punta

### Problema
Pedido del consultorio: «si piden tratamiento de conducto, preguntar si viene
derivado y es consulta (30') o ya para realizarse (1 h)». Hoy:
- la pregunta existe pero una respuesta corta («tratamiento», «una hora»,
  «30») sigue ambigua → se repregunta → loop;
- la duración del turno sale de `reason`, que **manda el modelo**; si escribe
  «tratamiento de conducto» aunque el estado diga «Consulta por conducto», el
  backend calcula 60'.

### Spec
```gherkin
Feature: Un conducto dura 30 o 60 minutos y lo decide el paciente

  Background:
    Given existen los tipos "Consulta por conducto" (30', Endodoncia)
    And "Conducto" (60', Endodoncia)
    And ambos los atiende solo la Dra. Murad

  Scenario: Pedido ambiguo dispara UNA pregunta con dos botones
    When el paciente dice "quiero un turno para tratamiento de conducto"
    Then el bot pregunta si viene derivado y si es consulta (30 min) o tratamiento (1 hora)
    And le muestra dos botones: "Consulta (30 min)" / "Tratamiento (1 hora)"
    And NO ofrece horarios todavía

  Scenario Outline: Respuestas cortas resuelven la ambigüedad
    Given el bot hizo la pregunta de conducto
    When el paciente responde "<respuesta>"
    Then el estado queda con motivo="<motivo>" y la duración es <min>

    Examples:
      | respuesta               | motivo                | min |
      | Tratamiento (1 hora)    | Conducto              | 60  |
      | tratamiento             | Conducto              | 60  |
      | una hora                | Conducto              | 60  |
      | ya para hacérmelo       | Conducto              | 60  |
      | Consulta (30 min)       | Consulta por conducto | 30  |
      | consulta                | Consulta por conducto | 30  |
      | vengo derivado          | Consulta por conducto | 30  |
      | 30                      | Consulta por conducto | 30  |

  Scenario: Frases que ya lo dicen no preguntan
    When el paciente dice "me tienen que matar el nervio"
    Then el motivo queda "Conducto" (60') sin pregunta intermedia

  Scenario: La duración la decide el estado, no el modelo
    Given el estado tiene motivo="Consulta por conducto"
    When el modelo llama consultar_disponibilidad(reason="tratamiento de conducto")
    Then el backend recibe reason="Consulta por conducto"
    And los huecos ofrecidos son de 30 minutos
    When el modelo llama agendar_turno(reason="conducto", duration_minutes=60)
    Then el turno se crea con reason="Consulta por conducto" y 30 minutos

  Scenario: Un turno de 60' bloquea el hueco entero
    Given un "Conducto" a las 10:00 con Murad
    Then a las 10:30 no hay disponibilidad con Murad

  Scenario: El panel puede cambiar las duraciones
    When en Configuración → Tipos de consulta se cambia "Conducto" a 45'
    Then la disponibilidad y el alta usan 45' sin tocar código
```

### Tests primero
- `tests/test_conducto_consulta_vs_tratamiento.py`: agregar el Outline de
  respuestas cortas y el caso de botones.
- `tests/test_el_paciente_manda.py` (o nuevo `test_motivo_manda_el_estado.py`):
  `consultar_disponibilidad` y `agendar_turno` pisan `reason` con el motivo
  del estado.
- `tests/test_reglas_de_turnos.py`: ya cubre 60' bloqueando 10:30; agregar el
  espejo con 30'.

### Implementación mínima
- `backend/services/appointment_service.py` `resolver_ambiguiedad_conducto`:
  si el **último** dicho tiene ≤ 4 palabras (es una respuesta a la pregunta),
  aceptar: `tratamiento|1 hora|una hora|60|hacerme|realizar` → 60;
  `consulta|evaluaci|derivad|30|media hora` → 30. Los textos de los botones
  entran por ahí sin regla especial.
- `bot/tools/appointment_tools.py`:
  - `recordar_dato('motivo', …)` cuando vuelve `razon == PREGUNTA_CONDUCTO`
    → `set_opciones_ofrecidas(["Consulta (30 min)", "Tratamiento (1 hora)"],
    siempre=True, tipo="botones")`.
  - `consultar_disponibilidad` y `agendar_turno`: `reason = estado["motivo"]`
    si está (el parámetro del modelo pasa a ser informativo). Quitar
    `duration_minutes` del schema de la tool: el backend ya lo ignora.
- `bot/ai_agent.py`: la sección «CONDUCTO — REGLA OBLIGATORIA» se reduce a
  dos líneas: «si la herramienta te devuelve la pregunta de conducto, hacela
  textual; hay botones». El resto lo garantiza el código.
- Post-deploy: confirmar en el panel que existe «Consulta por conducto»
  (30', Endodoncia, activo) — lo crea la migración `b0c1d2e3f4a5`.

### Archivos
`backend/services/appointment_service.py`, `bot/tools/appointment_tools.py`,
`bot/ai_agent.py`, tests.

---

## E3 — Profesional inexistente y typos

### Problema
«Dr. Sosa» no existe. El backend devuelve «no encuentro a ningún profesional
con ese nombre» y el modelo lo suaviza a «no está disponible». El paciente
cree que Sosa existe. Además el bot repite el typo («Dr. Silvestre») como si
fuera el apellido.

### Spec
```gherkin
Feature: Solo existen los profesionales cargados

  Scenario: Piden a alguien que no existe
    When el paciente pide turno "con el doctor Sosa"
    Then la herramienta devuelve "No hay ningún profesional llamado Sosa. Atienden: Dr. Martín Silvestro y Dra. Elena Murad"
    And el bot se lo dice así, sin decir "no está disponible"
    And le pregunta con quién quiere

  Scenario: Typo leve se resuelve al nombre real
    When el paciente escribe "Silvestre" o "el drama Silvestre"
    Then se resuelve a "Dr. Martín Silvestro"
    And el bot lo nombra con el nombre real, nunca con el typo

  Scenario: El profesional pedido no hace ese tratamiento
    When pide conducto con Silvestro
    Then el bot dice que eso lo hace la Dra. Murad y pregunta si quiere con ella
    (ya cubierto por test_dia_de_cada_profesional; no tocar)
```

### Tests primero
- `tests/test_profesional_pedido.py`: «Sosa» en disponibilidad y en alta →
  mensaje contiene ambos nombres reales; respuesta del bot no contiene
  «disponible» (test de prompt/rearmado en `test_horarios_inventados.py`).

### Implementación mínima
- `appointment_service.py` (dos sitios: `get_available_slots` y
  `create_appointment_logic`): mensaje con la lista de activos.
- `bot/ai_agent.py`: en el rearmado de mensajes, si el texto nombra un
  apellido con typo (fuzzy contra `_apellidos_activos()`), reemplazarlo por el
  nombre real. Barato: ya existe `_apellidos_activos()`.

---

## E4 — Detector de loop que detecte

### Problema
`es_repeticion` compara texto exacto o los primeros 60 caracteres, contra las
últimas 2 respuestas. «No, el Dr. Silvestre…» vs «El Dr. Silvestre…» se
escapó; «Te ofrezco…» repetido dos mensajes después también.

### Spec
```gherkin
Feature: El bot no repite lo mismo tres veces

  Scenario: Reformulación mínima cuenta como repetición
    Given el bot dijo "No, el Dr. X no hace conducto. La Dra. Y puede atenderte. ¿Busco el jueves con ella?"
    When está por decir "El Dr. X no hace conducto. La Dra. Y puede atenderte. ¿Busco el jueves con ella?"
    Then se considera repetición

  Scenario: Mira las últimas 4 respuestas, no 2
    Given dijo A, B, A
    When está por decir A otra vez
    Then se considera repetición

  Scenario: Progreso con opciones distintas no es loop
    (ya existe; mantener test_anti_loop)

  Scenario: Antes de derivar, un intento de rescate por código
    Given detectó repetición
    And al estado le falta motivo o cobertura
    Then responde con la pregunta determinística de lo que falta (con botones)
    And NO deriva todavía
    When se repite por segunda vez
    Then deriva a teléfono y pausa
```

### Tests primero
- `tests/test_anti_loop.py`: los 4 escenarios.

### Implementación mínima
- `evolution_router.py`:
  - `_normalizar`: quitar muletillas iniciales (`no,`, `sí,`, `bueno,`,
    `dale,`, `perfecto,`).
  - `es_repeticion`: `difflib.SequenceMatcher.ratio() >= 0.9` además del
    prefijo; `ultimas = [...][-4:]`.
  - `debe_derivar_por_loop` → devuelve `"rescate" | "derivar" | None`.
    Rescate = mensaje armado por código según `faltan` del estado
    (`preguntar_cobertura` / pregunta de motivo / pregunta de conducto), una
    sola vez por conversación (flag en estado).

---

## E5 — «Sí» ejecuta, no repregunta

### Problema
Raíz de los mensajes 11–14: el bot preguntó «¿te gustaría que busque
disponibilidad?» tres veces y ante «Sí» nunca llamó a
`consultar_disponibilidad`. Terminó ofreciendo «¿querés que lo agende?» sin
ningún horario.

### Spec
```gherkin
Feature: Una afirmación a una oferta del bot se ejecuta

  Scenario: El paciente acepta buscar horarios
    Given el bot preguntó "¿Te gustaría que busque disponibilidad para el jueves con la Dra. Murad?"
    And el estado tiene motivo y obra_social
    When el paciente responde "sí" / "dale" / "ok" / "bueno"
    Then la respuesta contiene horarios reales del sistema para ese día y profesional
    And no vuelve a preguntar permiso

  Scenario: Acepta pero falta un dato
    Given el estado NO tiene motivo
    When responde "sí"
    Then el bot pregunta el motivo (con botones si es conducto), una sola vez

  Scenario: Nunca ofrece agendar sin horario
    When la respuesta del modelo contiene "agende" / "agendar" / "reservar"
    And no hubo disponibilidad consultada en este turno
    Then se reemplaza por los horarios reales (_consultar_yo_mismo) o por la pregunta de lo que falta
```

### Tests primero
- `tests/test_no_confirmar_lo_que_no_se_hizo.py`: «¿querés que lo agende?»
  sin disponibilidad → reemplazado.
- `tests/test_conversacion.py` o nuevo `test_si_ejecuta.py`: mock del modelo
  que contesta sin tools; verificar que el código consulta por su cuenta.

### Implementación mínima
- `bot/ai_agent.py`:
  - detector `_es_afirmacion(user_message)` + `_ultima_oferta(history)`
    (regex sobre el último assistant: `busque|buscar disponibilidad|agend`).
  - Si afirmación + oferta + estado completo → bloque `[SISTEMA]` forzado:
    «OBLIGATORIO: llamá consultar_disponibilidad ahora» (mismo mecanismo que
    la cobertura) **y**, si igual no consulta, `_consultar_yo_mismo()` arma la
    respuesta (ya existe; hoy solo se usa para horarios inventados).
  - Regex `_OFRECE_AGENDAR_SIN_HORARIO` → mismo tratamiento que
    `_horarios_inventados`.

---

## E6 — Mensajes duplicados en el envío

### Problema
Dos veces en la charla el mismo texto llegó duplicado, sin mensaje del
paciente en medio, y ambas veces era un mensaje con botones/lista.
`_enviar_interactivo` usa `httpx.AsyncClient()` con timeout default (5 s): si
YCloud tarda, salta la excepción, se manda el texto de respaldo, y el
interactivo también llega.

### Spec
```gherkin
Feature: Un mensaje se entrega una vez

  Scenario: YCloud rechaza el interactivo (4xx)
    Then se manda el texto de respaldo (una vez)

  Scenario: YCloud tarda o corta (timeout / 5xx / excepción de red)
    Then NO se manda texto de respaldo
    And se loguea "POSIBLE_NO_ENTREGADO" con el id del intento
    And la función devuelve False

  Scenario: Timeout razonable
    Then el POST a YCloud espera hasta 20 s antes de darse por vencido
```

### Antes de tocar código
Confirmar la hipótesis en los logs de producción (panel de Dokploy →
backend → logs, no hay SSH desde esta máquina):
`grep -E "rechazó el interactivo|Error enviando interactivo"` alrededor de la
hora de la charla.

### Tests primero
- `tests/test_un_solo_envio.py`: monkeypatch de `httpx.AsyncClient.post` que
  lanza `httpx.ReadTimeout` → `send_whatsapp_message` no se llama.

### Implementación mínima
- `backend/services/whatsapp.py` `_enviar_interactivo`:
  `AsyncClient(timeout=20)`; fallback solo en `400 <= status < 500`.

---

## E7 — Hora local sin red

### Problema
«Buenas noches» a una hora que hay que confirmar con Claudio. `get_clinic_now`
consulta `http://worldtimeapi.org` (http, servicio intermitente) y cachea 10
minutos; si devuelve algo raro, el saludo y la fecha de los turnos se corren.

### Spec
```gherkin
Feature: La hora del consultorio es determinística

  Scenario: Sin red la hora es la de Argentina
    When se pide get_clinic_now()
    Then devuelve datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")) sin llamadas HTTP

  Scenario: Saludo según hora
    Given son las 07:30 → "buen día"
    Given son las 21:00 → "buenas noches"
```

### Implementación mínima
- `appointment_service.get_clinic_now`: `zoneinfo`, sin httpx, sin caché.
- Test en `tests/test_conversacion.py` o nuevo `test_hora_local.py`.

---

## E8 — Verificación de punta a punta

### Arnés
- Agregar a `tests/test_conversaciones_completas.py` la **charla 6 (Claudio
  21/09)** tal como ocurrió, con el resultado esperado por mensaje:

  ```
  Quiero turno                      → pregunta motivo (ficha Particular, no pregunta cobertura)
  Un turno con el doctor sosa       → "no hay ningún Dr. Sosa; atienden Silvestro y Murad"
  Tengo obra social                 → lista de obras sociales (sin repreguntar)
  Avalian                           → registrada; pregunta motivo
  Tratamiento de conducto           → pregunta consulta 30' / tratamiento 1 h (botones)
  Tratamiento (1 hora)              → motivo Conducto 60'; pide día
  El jueves con Silvestre           → "Silvestro no hace conducto; Murad sí, ¿jueves con ella?"
  Sí                                → horarios REALES del jueves con Murad (60')
  10:30                             → turno creado, 60', Avalian, Murad, link de cancelación
  ```
- Correr las 5 charlas existentes + la 6 dos veces seguidas (estabilidad).

### Post-deploy (checklist)
1. `curl https://odobot.aiporvos.com/api/health` → `codigo` del día.
2. Panel → Tipos de consulta: «Consulta por conducto» 30' Endodoncia activo.
3. WhatsApp real al 2604590071, guion de la charla 6. Capturar.
4. Panel → Agenda: el turno de prueba dura lo que dice el motivo. Borrarlo.
5. Logs: `AI_AGENT_USO` (caché), `🔁 Respuesta repetida`, `POSIBLE_NO_ENTREGADO`.

---

## Orden, dependencias y tamaño

| Etapa | Depende de | Tamaño | Deploy |
|---|---|---|---|
| E1 cobertura por código | — | M | ✔ junto con E2 |
| E2 conducto 30'/60' | E1 (misma barrera) | M | ✔ |
| E7 hora local | — | S | con E1+E2 (es trivial y saca una variable) |
| E3 profesional inexistente | — | S | ✔ segundo deploy |
| E4 detector de loop | — | S/M | ✔ |
| E5 «sí» ejecuta | E1, E2 (necesita estado completo) | M | ✔ |
| E6 duplicados | logs de prod | S | ✔ (o antes si los logs confirman) |
| E8 arnés + checklist | todo | S | — |

Dos commits/deploys, no ocho. Estimación total: una jornada de trabajo
enfocada (E1+E2+E7 ≈ media jornada; E3–E6+E8 ≈ media jornada).

## Fuera de alcance (a propósito)
- Recorte del prompt (`PROPUESTA-recorte-prompt.md`): recién con una semana de
  `AI_AGENT_USO`.
- Cambio de modelo.
- Datos de clínica (alias, precios, urgencias): los carga Martín; bloquean
  habilitar el bot solo con pacientes, no este plan.

## Riesgos
- **Sobre-bloquear.** Cada barrera nueva puede frenar un caso legítimo. Por
  eso E1 resuelve por código en vez de solo prohibir, y E4 rescata antes de
  derivar.
- **Tests que dependen del modelo** (charlas completas): son lentos y no
  determinísticos al 100 %. Se corren dos veces; el resto de la suite (530+)
  es determinística y es la que gatea el commit.
- **Migración en prod**: `b0c1d2e3f4a5` ya corrió con el deploy del 21/09;
  verificar en el panel antes de E2.
