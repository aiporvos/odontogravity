# Estrategia de confiabilidad del bot

> 11/09/2026. Cómo hacer que este bot sea confiable para una clínica real.

## Primero, la meta bien formulada

"Que no falle" no es una meta alcanzable con un LLM, y prometerla sería mentir.
Un modelo de lenguaje va a producir salidas equivocadas: es estadístico, no
determinista. La meta correcta es otra, y sí es alcanzable:

> **Que ningún error del modelo llegue al paciente como información falsa, y que
> cuando el bot no pueda resolver algo, una persona se entere.**

Ese es el estándar de una clínica: un paciente que viaja a un turno que no
existe es un problema en el mostrador; un paciente al que el bot le dice "esto
lo ve una persona" y efectivamente lo ve, no lo es.

Este proyecto ya eligió ese camino —las barreras de código son exactamente
eso— pero está a mitad. Lo que sigue es cómo completarlo.

---

## Las seis capas

La confiabilidad no sale de una sola cosa bien hecha sino de capas donde el
error tiene que atravesarlas todas para llegar al paciente.

### Capa 1 — Que el modelo tenga menos chances de equivocarse
**Estado: es lo más flojo.**

- 6.450 tokens de prompt y 11 herramientas para un bot de turnos es mucha carga.
- El modelo actual (`gpt-4o-mini`) puede ser chico para esa carga. Sin medir.
- Hay ambigüedades documentadas en `INCONSISTENCIAS-prompt.md`.

**Qué hacer:** medir primero (ya se puede: ver capa 6), después recortar.

### Capa 2 — Que lo que el modelo afirma esté respaldado por datos reales
**Estado: es lo mejor que tiene el proyecto.**

`_horarios_inventados`, `_atribucion_falsa`, `_promete_sin_cumplir`,
`_PROMETE_AVISO`. Cada una nació de un caso real. Comparan lo que el modelo va a
decir contra lo que las herramientas devolvieron, y bloquean o reescriben.

**Qué hacer:** nada nuevo. Sostenerlo: cada error nuevo que aparezca, una
barrera y un test.

### Capa 3 — Que los datos operativos no los redacte el modelo
**Estado: existe en germen, es la mayor oportunidad.**

Hoy el modelo redacta libremente y el código intercepta si detecta invento. Eso
es tapar salidas de a una: se taparon tres (horarios, atribución, confirmación) y
no hay motivo para suponer que no hay una cuarta.

La inversión de control elimina la clase entera de error: **el modelo decide qué
hacer, el código arma el texto que contiene datos.** Cuando hay que ofrecer
horarios, confirmar un turno o dar una fecha, esa oración se construye desde una
plantilla con los valores que devolvió la herramienta. El modelo aporta el
envoltorio conversacional, no los números.

Ya existe `_mensaje_con_los_horarios_reales()`: hace exactamente esto, pero solo
como plan B cuando se detecta un invento. **La propuesta es que sea el camino
normal, no el de excepción.**

Es el cambio más grande de esta lista y el de mayor retorno: después de hacerlo,
"el bot inventó un horario" deja de ser posible por construcción, no por
vigilancia.

### Capa 4 — Que la base impida lo imposible
**Estado: hecho y sólido.**

Índice único parcial contra la doble reserva; `CHECK` que exige
`overbooking_autorizado_por`. Garantías que ningún prompt puede violar.

### Capa 5 — Que lo irresoluble se derive a una persona
**Estado: la herramienta existe, el prompt no la refuerza.**

`derivar_a_recepcion` funciona y tiene bandeja. Pero la sección FALLBACK del
prompt enseña a despedir al paciente hacia recepción sin nombrarla, y el código
no fuerza la derivación: solo bloquea la promesa falsa.

**Qué hacer:** que el FALLBACK nombre la herramienta. Y evaluar que, cuando el
bot da vueltas (dos preguntas sin avanzar), el código derive por su cuenta en
vez de esperar que el modelo lo decida.

### Capa 6 — Que un error se detecte en minutos, no cuando se queja el paciente
**Estado: recién ahora es posible.**

Dos piezas nuevas de hoy:

- **El arnés de conversaciones** (`tests/test_conversaciones_completas.py`):
  cinco charlas enteras contra el modelo real, con invariantes verificadas
  después de cada respuesta. Convierte "probar el bot" de un día de WhatsApp a
  unos minutos.
- **El registro de consumo** (`AI_AGENT_USO`): tokens y caché por llamada.

**Lo que falta, y es importante:** las barreras de la capa 2 escriben
`logger.error` cuando intervienen, y nadie mira ese log. Hoy no se sabe **cuántas
veces por día el bot intentó inventar un horario y fue frenado**. Ese número es
el termómetro real de la calidad: si las barreras intervienen cincuenta veces
por día, el bot está fallando constantemente aunque ningún paciente reciba datos
falsos. Un contador y una alerta sobre esos eventos vale más que cualquier
opinión sobre el prompt.

---

## El orden de trabajo

1. **Correr el arnés con una API key.** Es lo primero porque todo lo demás se
   mide con él. Sin esto seguimos opinando.
2. **Contar las intervenciones de las barreras en producción.** El termómetro.
3. **Comparar modelos con la misma batería.** `gpt-4o-mini` contra uno mayor,
   mismos cinco guiones, resultados objetivos. Recién ahí se decide pagar más.
4. **Recortar prompt y ambigüedades**, verificando con el arnés que no se rompe
   nada.
5. **Invertir el control de los datos operativos** (capa 3). El cambio grande.
6. **Recién con todo eso verde: abrir a pacientes.**

## Lo que NO haría

- **Tocar el prompt hoy sin el arnés corriendo.** Es lo que se hizo tres veces y
  costó tres días.
- **Subir el modelo como solución de fondo.** Es un experimento para saber qué
  falla, no un arreglo. Un modelo mejor sobre un prompt ambiguo sigue siendo un
  prompt ambiguo, y cuesta cinco veces más por mes.
- **Abrir a pacientes antes del punto 6.** El costo de un error acá no se mide
  en tokens.
