# Propuesta de recorte y unificación del prompt

> Análisis del 11/09/2026. **Nada de esto está aplicado.** Es una propuesta
> para decidir, no un cambio hecho.

## De dónde salen los números

Cada llamada al modelo manda, fijo, antes del historial:

| | tokens |
|---|---|
| `SYSTEM_PROMPT` (21.286 caracteres) | ~6.450 |
| `TOOL_DEFINITIONS` (11 herramientas, 9.228 caracteres serializados) | ~2.800 |
| **Total fijo por llamada** | **~9.250** |

Eso se reenvía en cada ronda de tool calling, hasta `MAX_TOOL_ROUNDS = 8` por
mensaje del paciente. Una reserva de turno completa ronda las 20 llamadas.

El problema no es solo la plata. Son ~9.250 tokens de reglas que un modelo
chico tiene que sostener mientras elige entre 11 herramientas, y esa es la
sospecha anotada como causa de los descarríos: no llama la herramienta, inventa
parámetros, obedece instrucciones viejas al pie de la letra.

---

## 1. La sección de herramientas del prompt está duplicada (705 tokens, 11%)

**El hallazgo más grande y el más seguro de arreglar.**

La sección `# 🛠️ HERRAMIENTAS DISPONIBLES` re-documenta las 11 herramientas:
qué hacen, campos obligatorios, cuándo llamarlas. Todo eso YA viaja en el mismo
request, en el parámetro `tools`. Se está pagando dos veces.

Y no es una duplicación conceptual, es **literal**:

| | prompt | `TOOL_DEFINITIONS` |
|---|---|---|
| `quien_me_escribe` | "LLAMALA SIEMPRE al principio de una conversación nueva antes de pedir información." | "LLAMALA SIEMPRE al principio de una conversación nueva, …" |
| `preguntar_cobertura` | "Llamala ANTES de mostrar ninguna lista, apenas haya que hablar de cobertura." | "USALA ANTES de mostrar ninguna lista de obras sociales, apenas haya que hablar de cobertura." |
| `consultar_disponibilidad` | "No vuelvas a llamarla cuando el paciente simplemente esté seleccionando una opción que ya fue ofrecida." | "NO llamar si el paciente ya está eligiendo un horario de los que le ofreciste." |

**Propuesta:** borrar la sección entera del prompt. Donde una instrucción del
prompt sea más precisa que la descripción de la herramienta, mover ese texto a
la descripción en `TOOL_DEFINITIONS` (que es donde el modelo lo lee en el
momento de decidir si la llama) en vez de dejarlo en los dos lados.

**Ahorro:** ~705 tokens por llamada, ~14.000 por conversación.
**Riesgo:** bajo. La información no se pierde, deja de estar repetida.

---

## 2. Hay una contradicción sobre el DNI (97 tokens, y confunde)

Dos secciones seguidas dicen lo opuesto:

- `# 👤 IDENTIFICACIÓN DEL PACIENTE`:
  > 🚫 PROHIBIDO pedirle el DNI, el teléfono, la fecha de nacimiento o cualquier
  > otro dato administrativo.

- `# 🪪 DNI` (la sección inmediatamente siguiente):
  > Si necesitás pedir DNI: normalmente tiene 7 u 8 dígitos. Si el paciente da
  > 10 dígitos y parece un teléfono, decile: "Ese parece un teléfono 😊 ¿Me
  > pasás tu DNI?"

Para un modelo chico esto es veneno: una prohibición tajante y, cuatro líneas
después, el guion para hacer exactamente lo prohibido.

**Propuesta:** dejar la prohibición, y de la sección `DNI` conservar solamente
el caso que sí puede pasar sin violarla — que el paciente ofrezca un DNI por su
cuenta y haya que guardarlo. El guion para pedirlo se va.

**Riesgo:** bajo. Resuelve un conflicto, no saca una capacidad.

---

## 3. El principio "no preguntes lo que ya sabés" está dicho siete veces

Aparece, con distintas palabras, en:

`🧠 PRINCIPIO CENTRAL` · `⚡ MÍNIMA FRICCIÓN` · `📌 ESTADO DE LA CONVERSACIÓN` ·
`🧠 CAPTURA DE DATOS FUERA DE ORDEN` · `🦷 MOTIVO DE CONSULTA` ·
`💬 CÓMO PREGUNTAR CUANDO FALTAN DATOS` · `🎯 CRITERIO FINAL DE DECISIÓN`

Suman ~1.100 tokens para sostener una sola idea.

**Propuesta:** una sección con el principio y los ejemplos que valen la pena;
las otras seis se borran o quedan en una línea. Conservar los ejemplos
concretos (son los que enseñan) y sacar las reformulaciones abstractas.

**Ahorro estimado:** ~600-700 tokens.
**Riesgo:** medio. Requiere leer con cuidado cuál de las siete versiones es la
que mejor explica, porque no dicen exactamente lo mismo.

---

## 4. Las tres herramientas de obra social (candidato a unificar)

`preguntar_cobertura()` · `listar_obras_sociales(busqueda)` ·
`verificar_obra_social(obra_social)`

Son tres de las once, ~876 caracteres de descripciones, y el flujo que las
encadena ocupa otros 551 tokens en `# 🏥 OBRA SOCIAL` — la segunda sección más
grande del prompt.

**No recomiendo unificarlas todavía.** Cada una produce una interacción distinta
en WhatsApp (botones / lista tocable / verificación silenciosa), y fusionarlas
cambia lo que ve el paciente. Es el cambio de mayor riesgo de esta lista y el
único que necesita probarse en conversaciones reales antes de decidirse.

Lo que sí se puede hacer ya: sacar del prompt la explicación del flujo que está
duplicada en las descripciones de las tres herramientas (punto 1).

---

## Orden sugerido

1. **Punto 1** (sección de herramientas duplicada) — ~705 tokens, riesgo bajo.
2. **Punto 2** (contradicción del DNI) — poco ahorro, pero saca un conflicto.
3. **Punto 3** (principio repetido) — ~650 tokens, riesgo medio.
4. **Punto 4** (unificar obra social) — solo con conversaciones reales andando.

Los puntos 1 a 3 llevarían el prompt de ~6.450 a ~5.100 tokens: **un 20% menos**
en cada una de las ~20 llamadas de cada conversación.

## Antes de aplicar cualquiera de estos

Falta lo de siempre: **no hay una conversación completa verificada**. Recortar
el prompt sin poder recorrer un diálogo entero es cambiar y cruzar los dedos,
que es justo el vicio que veníamos sacando. Los 520 tests cubren las barreras de
código, no si el bot conversa bien con menos instrucciones.

El orden sano sigue siendo: subir el modelo → ver qué mejora → recortar con esa
información → intentar volver al modelo barato.
