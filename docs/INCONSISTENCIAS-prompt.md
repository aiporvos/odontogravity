# Inconsistencias del prompt — revisión completa

> 11/09/2026. **Nada aplicado.** Revisión una por una, ordenadas por gravedad.
>
> Esto es distinto del recorte (ver `PROPUESTA-recorte-prompt.md`). Recortar
> puede sacar prevención útil y hay que pensarlo. Una contradicción, en cambio,
> solo puede empeorar las cosas: el modelo recibe dos órdenes opuestas en el
> mismo request y elige una. Sacarla no tiene contraindicación.

---

## 1. 🔴 El prompt miente sobre la firma de `consultar_disponibilidad`

**La más grave, y probablemente la causa del caso Murad.**

El prompt enumera los parámetros de la herramienta en **dos lugares**:

- línea 917: `` `consultar_disponibilidad(motivo_confirmado_por_paciente, location, date, obra_social, preferencia_horaria)` ``
- sección `# 📅 DISPONIBILIDAD`: "La herramienta recibe: motivo_confirmado_por_paciente; location; date; obra_social; preferencia_horaria."

**Los dos omiten `profesional`**, que es el sexto parámetro real.

Ese parámetro se agregó en `4cfd6ab` — el commit de ayer, "Los horarios que salen tienen que ser los que devolvió el sistema", justamente para arreglar que el bot atribuyera a Murad los horarios de Silvestro. **El prompt nunca se actualizó.**

Así que el modelo lee, en el system prompt, dos veces, que esa herramienta no
recibe `profesional`; y en `TOOL_DEFINITIONS` lee que sí. La minuta de ayer dice
"agregar el parámetro `profesional` no alcanzó: era un pedido, no una garantía".
Puede que no alcanzara porque el prompt le estaba diciendo que no existía.

**Arreglo:** borrar las dos enumeraciones. La firma verdadera ya viaja en
`TOOL_DEFINITIONS`; mantener una copia a mano es lo que produjo el desfasaje.

---

## 2. 🔴 `derivar_a_recepcion` es invisible para el prompt

La herramienta existe, tiene bandeja propia y fue el trabajo central del
08-09/09 ("dejé la consulta ahora significa algo"). **El prompt no la nombra ni
una vez.**

- No está en `# 🤖 QUÉ PODÉS HACER` (que lista 6 capacidades).
- No está en `# 🛠️ HERRAMIENTAS DISPONIBLES` (que documenta las otras 10).
- La sección `# 🧯 FALLBACK` enseña a decir:
  > "Con esto prefiero que te ayude directamente una persona de la clínica para
  > no darte información incorrecta."

  …sin decirle que llame a nada.

O sea: el prompt le enseña a despedir al paciente hacia "una persona de la
clínica" **sin dejar registro de nada**. El paciente espera, y del otro lado no
hay ningún caso creado.

Ese texto puntual no dispara la barrera `_PROMETE_AVISO` (el regex busca "dejé la
consulta", "te van a llamar", "quedó anotado", y esa frase no coincide), así que
pasa silenciosamente. Es peor que si fallara ruidosamente.

**Arreglo:** nombrar `derivar_a_recepcion` en la sección de capacidades y en el
fallback, dejando claro que la frase va DESPUÉS de que la herramienta devolvió ✅.

---

## 3. 🔴 La firma de `agendar_turno` también está incompleta

El prompt la enumera con 9 parámetros (dos veces, en `# ✅ AGENDAR` y en la
sección de herramientas). La firma real tiene **11**: omite `profesional` y
`preferencia_horaria`.

Mismo origen y mismo arreglo que el punto 1.

---

## 4. 🟡 Dos herramientas de obra social reclaman ser la primera

Las dos descripciones viajan en el mismo request, con la misma condición
disparadora, en mayúsculas, diciendo cosas incompatibles:

| herramienta | qué dice su descripción |
|---|---|
| `preguntar_cobertura` | "**USALA ANTES** de mostrar ninguna lista de obras sociales, **apenas haya que hablar de cobertura**" |
| `listar_obras_sociales` | "**USALA EN CUANTO** haya que hablar de cobertura, en lugar de pedirle que la escriba" |

El prompt, por su lado, respalda a la primera: "El flujo es de dos escalones. NO
empieces mostrando obras sociales. Primero llamá a `preguntar_cobertura()`".

La descripción de `listar_obras_sociales` quedó redactada de antes de que
existiera `preguntar_cobertura`, y nunca se ajustó.

**Arreglo:** reescribir la descripción de `listar_obras_sociales` para que diga
que es el **segundo** escalón — se llama cuando el paciente ya eligió "Tengo obra
social".

---

## 5. 🟡 La contradicción del DNI, que es doble

**En el texto:**

- `# 👤 IDENTIFICACIÓN DEL PACIENTE`: "🚫 PROHIBIDO pedirle el DNI, el teléfono,
  la fecha de nacimiento o cualquier otro dato administrativo."
- `# 🪪 DNI`, la sección **inmediatamente siguiente**: "Si necesitás pedir DNI…"
  y el guion textual: "Ese parece un teléfono 😊 ¿Me pasás tu DNI?"

**En la estructura**, que es lo que no se ve leyendo el prompt: `dni` es el
**primer parámetro** de `cancelar_turno(dni, appointment_id)` y el único de
`consultar_mis_turnos(dni)`. El modelo ve una firma que encabeza con `dni` y una
prohibición de pedirlo. Que no sea obligatorio no se nota tanto como que esté
primero.

**Arreglo:** conservar de la sección `DNI` solo el caso que no viola la
prohibición — que el paciente lo ofrezca por su cuenta y haya que guardarlo — y
borrar el guion para pedirlo. En las descripciones de las herramientas, aclarar
que `dni` es un fallback interno y que la identificación normal es por WhatsApp.

---

## 6. 🟡 Datos que viven en la base, escritos a mano en el prompt

El prompt inyecta dinámicamente `{sedes}` y `{especialistas}`. Pero deja fijos:

| dato en el prompt | dónde vive de verdad |
|---|---|
| "Limpieza / Consulta / Control: 15 minutos · Extracción / Ortodoncia: 30 · Endodoncia: 60" | tabla `tipos_consulta`, columna `duracion_minutos` (configurable desde el panel) |
| "Lunes a Viernes · Mañana 09:00-12:30 · Tarde 17:00-20:30 · Miércoles tarde CERRADO" | tabla `clinic_schedule` (la lee `clinica_abierta_ahora()`) |

Si la clínica cambia una duración o un horario desde el panel, **el bot sigue
diciendo el viejo**: le promete al paciente una cosa y el sistema agenda otra.

**Arreglo:** inyectarlos como `{sedes}` y `{especialistas}`, con dos funciones
equivalentes a `get_sedes_texto()`. Con una salvedad para el caché: el texto
cambia solo cuando la clínica edita su configuración, así que el prefijo sigue
siendo estable entre llamadas y conversaciones. No hay conflicto.

---

## 7. 🟢 La sección de herramientas duplicada (y por eso desactualizada)

Ya estaba en `PROPUESTA-recorte-prompt.md` como un tema de tokens. Esta revisión
le agrega el argumento definitivo: **la copia se desactualizó y ahora contradice
al original**. Los puntos 1, 3 y 4 son todos consecuencia de mantener a mano una
segunda copia de lo que ya viaja en `TOOL_DEFINITIONS`.

No es solo que se paguen 705 tokens de más. Es que esa copia es una fuente de
verdad paralela que nadie actualiza cuando cambia una herramienta.

---

## Resumen

| # | Qué | Gravedad | Riesgo de arreglarlo |
|---|---|---|---|
| 1 | Firma de `consultar_disponibilidad` sin `profesional` | 🔴 alta | bajo |
| 2 | `derivar_a_recepcion` invisible | 🔴 alta | bajo |
| 3 | Firma de `agendar_turno` incompleta | 🔴 alta | bajo |
| 4 | Dos herramientas de cobertura en conflicto | 🟡 media | bajo |
| 5 | DNI prohibido y pedido | 🟡 media | bajo |
| 6 | Duraciones y horarios hardcodeados | 🟡 media | medio |
| 7 | Sección de herramientas duplicada | 🟢 | bajo |

Los puntos 1, 2, 3 y 4 **no son cuestión de criterio: el prompt dice cosas que
son falsas**. Arreglarlos es corregir un error, no rediseñar.

Los puntos 5 y 6 tocan comportamiento y conviene mirarlos con una conversación
real andando.
