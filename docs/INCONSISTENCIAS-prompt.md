# Inconsistencias del prompt — revisión verificada

> 11/09/2026. **Nada aplicado.**
>
> Segunda pasada. La primera versión de este documento marcaba como 🔴 dos cosas
> que no lo eran, y afirmaba que una podía ser la causa del caso Murad. Eso era
> especulación y estaba mal. Lo que sigue está contrastado contra el
> comportamiento real del bot, documentado en los encabezados de los tests, que
> citan conversaciones textuales de producción.

## Cómo se verificó cada una

Tres fuentes, en este orden de autoridad:

1. **Conversaciones reales de producción** citadas en `tests/test_*.py`
   (08/09, 10/09, 23/08). Es lo que el bot hizo de verdad.
2. **El código**: qué garantiza y qué deja en manos del modelo.
3. **El texto del prompt** comparado con `TOOL_DEFINITIONS`.

---

## Lo que corrijo de la primera versión

### ❌ "El prompt miente sobre la firma y por eso falló el caso Murad"

**Era falso, y en dos niveles.**

El hecho verificable sigue en pie: el prompt enumera los parámetros de
`consultar_disponibilidad` en dos lugares y omite `profesional`; con
`agendar_turno` lista 9 de 11. Eso es información desactualizada y conviene
sacarla.

Pero **no impide que el modelo mande el parámetro**. En function calling, el
schema JSON que viaja en `tools` es lo autoritativo: de ahí el modelo construye
la llamada. La prosa del prompt que repite la firma es redundante e informativa.
Una copia desactualizada confunde; no bloquea.

Y sobre todo: **la causa del caso Murad ya estaba identificada y verificada
ayer**, y era otra — el propio resultado de la herramienta terminaba con "NO
llames a esta herramienta de nuevo", y el modelo obedeció. Eso se reprodujo
contra una copia de producción. Yo puse una hipótesis nueva encima de una causa
ya probada, sin evidencia.

**Reclasificado: de 🔴 a 🟢** (limpieza, no bug).

---

## Las que sí aguantan

### 1. 🟡 Duraciones y horarios escritos a mano, cuando viven en la base

**La más sólida.** Verificado que ambos datos se usan desde la base y son
editables desde el panel:

| dato fijo en el prompt | dónde vive de verdad | quién lo usa |
|---|---|---|
| "Limpieza / Consulta / Control: 15 min · Extracción / Ortodoncia: 30 · Endodoncia: 60" | `tipos_consulta.duracion_minutos` | `backend/routers/bot_routes.py:724` |
| "Lunes a Viernes · 09:00-12:30 · 17:00-20:30 · Miércoles tarde CERRADO" | tabla `clinic_schedule` | `clinica_abierta_ahora()`, y el panel la edita en `clinic_routes.py:638` |

El panel **borra y recrea** los horarios (`clinic_routes.py:638-642`). O sea que
están pensados para cambiar. Cuando cambien, el prompt va a seguir diciendo los
viejos: el bot le promete al paciente una duración y el sistema agenda otra.

Es inconsistente incluso con el propio diseño del prompt, que ya inyecta
`{sedes}` y `{especialistas}` desde la base.

**Arreglo:** dos funciones equivalentes a `get_sedes_texto()`. No afecta el
caché: ese texto cambia solo cuando la clínica edita su configuración, no entre
llamadas.

### 2. 🟡 El FALLBACK no nombra `derivar_a_recepcion`

Verificado que la herramienta **no aparece nombrada ni una vez** en el prompt, y
que **el código no fuerza la derivación**: solo bloquea la promesa falsa
(`_PROMETE_AVISO` → `_AVISO_SIN_CASO`). Crear el caso depende enteramente de que
el modelo llame a la herramienta.

La sección `# 🧯 FALLBACK` enseña la frase para despedir al paciente hacia
recepción sin mencionar que hay que llamar a nada.

**Lo que modero de la primera versión:** dije que la herramienta era "invisible".
No lo es — su descripción en `TOOL_DEFINITIONS` es la más larga de las once (423
caracteres) y explica bien cuándo usarla. El modelo tiene la información. Lo que
falta es que la sección donde se decide derivar la nombre.

**Evidencia real a favor** (caso del 08/09, `test_derivaciones.py`): el bot
interrogó a una paciente tres veces sin derivar nunca, y su turno siguió en la
agenda. Ese caso motivó la bandeja de derivaciones.

### 3. 🟡 El DNI: ambigüedad de alcance, no contradicción

Acá también me corrijo. Leído entero, no es una contradicción pura:

- La prohibición está en el contexto de **reservar**: "Cuando corresponda
  reservar… 🚫 PROHIBIDO pedirle el DNI".
- En cancelar, el prompt dice "NO pidas DNI **inicialmente**", que implica que
  después puede.

El problema real es que la prohibición está **redactada en absoluto** ("el DNI,
el teléfono, la fecha de nacimiento o cualquier otro dato administrativo") sin
acotar a qué situación aplica, y cuatro líneas después viene el guion para
pedirlo. Es ambiguo, no contradictorio.

**Y la ambigüedad tiene consecuencias reales.** Conversación del 08/09:

    paciente: Escribo para cancelar mi turno de mañana, se me complica
    bot:      No encuentro turnos asociados a este número. ¿Me pasás tu DNI?
    paciente: 35878761
    bot:      No encuentro turnos asociados a ese DNI. ¿El nombre y apellido?

Su turno existía. Su ficha venía de la agenda de papel, sin DNI ni teléfono
—como 380 de 446 fichas activas—, así que el DNI no podía identificarla nunca.

**Arreglo:** acotar la prohibición al contexto de reservar y decir explícitamente
qué hacer cuando la identificación falla (derivar, no seguir pidiendo datos).
Se cruza con el punto 2.

### 4. 🟡 Las dos herramientas de cobertura: ambiguo, no contradictorio

También lo modero. Releídas completas:

- `preguntar_cobertura`: "USALA ANTES de mostrar ninguna lista de obras
  sociales, apenas haya que hablar de cobertura"
- `listar_obras_sociales`: "USALA EN CUANTO haya que hablar de cobertura, **en
  lugar de pedirle que la escriba**"

El contraste de la segunda es con *pedirle que escriba*, no con la primera. No
se contradicen frontalmente. Pero las dos abren con la misma condición ("apenas
/ en cuanto haya que hablar de cobertura") y en mayúsculas, y el prompt aclara
que el flujo es de dos escalones. La descripción de `listar_obras_sociales`
quedó redactada de antes de que existiera `preguntar_cobertura`.

**Arreglo:** que la segunda diga que es el segundo escalón.

### 5. 🟢 La sección de herramientas duplicada

Se mantiene, como tema de tokens (705, 11%) y de mantenimiento: es la copia
paralela que se desactualizó y produjo las firmas incompletas.

---

## Balance honesto

| # | Qué | Primera versión | Verificado |
|---|---|---|---|
| Firmas incompletas en el prompt | 🔴 "el prompt miente" | 🟢 limpieza |
| Duraciones y horarios hardcodeados | 🟡 | 🟡 **confirmada** |
| FALLBACK no nombra `derivar_a_recepcion` | 🔴 "invisible" | 🟡 confirmada, moderada |
| DNI | 🟡 "contradicción" | 🟡 ambigüedad, con daño real |
| Dos herramientas de cobertura | 🟡 "contradicción" | 🟡 ambigüedad |
| Sección duplicada | 🟢 | 🟢 |

**No hay ninguna contradicción dura en el prompt.** Hay una copia desactualizada
de las firmas, dos ambigüedades de alcance con consecuencias documentadas, y dos
datos hardcodeados que deberían venir de la base.

Eso cambia la recomendación que di antes. Dije que estas se podían arreglar sin
probar conversaciones completas porque "una contradicción solo puede empeorar
las cosas". Como no son contradicciones sino ambigüedades, ese argumento no
aplica: tocarlas **sí** cambia comportamiento y **sí** conviene tener una
conversación completa andando antes.

La única que se puede hacer con red hoy es la de duraciones y horarios: es
reemplazar texto fijo por el dato real de la base, y se puede cubrir con tests
como cualquier otra función de inyección.
