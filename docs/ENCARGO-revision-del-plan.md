# Revisión del plan de QA, contra el código y la base real

Rama `encargo/asistente-etapas`. Nada desplegado.

El plan pide distinguir lo verificado de lo supuesto. Esto es el resultado de
verificarlo.

## 1. Lo que el plan dice bien (comprobado)

| Afirmación del plan | Verificación |
| --- | --- |
| `conftest.py` con `setdefault` puede apuntar a una base real | **Peor de lo descrito.** Reproducido: la suite borró la tabla `patients` de una base descartable e informó *11 passed*. |
| La pausa se chequea al entrar pero no antes de enviar | Confirmado en `evolution_router.py`. La llamada al modelo tarda segundos y ahí entra recepción. |
| El fallback duplica mensajes | Confirmado. `_enviar_interactivo` mandaba el texto y devolvía `False`; `_responder` lo mandaba otra vez. Dos mensajes idénticos. |
| Se reutiliza el DNI de la ficha del teléfono aunque venga otro nombre | Confirmado. El alta busca por DNI, así que el turno del familiar caía en la ficha del titular. |
| Estar en Alembic head no prueba que exista la restricción | Confirmado en producción: head `c5d6e7f8a9b0`, restricción **ausente**, 107 pares solapados. |
| No hay agrupamiento de ráfagas | Confirmado: una tarea por mensaje. |

## 2. Donde el plan se pasa de rosca para este despliegue

- **C05 «mismo webhook a dos workers»**: el `CMD` es `uvicorn` sin `--workers`.
  Hay un solo proceso, y es deliberado (hay estado en memoria). La
  deduplicación entre workers no es un riesgo actual. La durabilidad sí importa
  —un reinicio pierde los `BackgroundTasks` en vuelo— pero es otra prioridad.
- **Ledgers, brokers y reconciliación de envíos**: con 18 turnos creados por el
  bot en total, esa maquinaria es más grande que el problema. Vale la pena el
  contrato de entrega (`accepted` ≠ `delivered`); no un sistema de mensajería.
- **El prompt no se instala todavía.** Lo dice su propia cabecera y es correcto:
  describe estado (`HUMAN_PENDING`, borradores, opciones vigentes) que no
  existe. Activarlo hoy sería pedirle al modelo que finja una infraestructura
  ausente, que es el error que el plan advierte.

## 3. Lo que al plan le falta, y hoy es la falla más grande

**La agenda está partida en dos por el nombre de la sede.** El plan no lo tiene:
su único punto sobre sedes es un P2 sobre `Professional.locations`.

La misma sede física está cargada con tres nombres:

```
Silprodent   153 turnos futuros    ← acá está casi toda la agenda
San Rafael    22 turnos futuros    ← el bot agenda siempre acá
Silproden      4 turnos futuros    ← con la 't' faltante
```

`get_day_appointments` filtraba `location = 'X'`, así que **el bot no ve el 87%
de los turnos futuros** y ofrece como libres horarios ya tomados. No es
hipotético: el 01/09 a las 11:00 agendó un conducto de 60 minutos encima de un
turno de 10:30 a 11:30 cargado como "Silprodent", misma profesional, un sillón.

Es, además, el único solapamiento que creó el bot en toda la base. La regla de
que los sobreturnos son solo del panel **está bien implementada**; lo que falló
fue que el bot miraba media agenda.

### Qué se puede arreglar por código y qué no

Se arregló la comparación: mayúsculas, acentos, espacios y espacios dobles ya no
crean agendas paralelas. **Pero "San Rafael" y "Silprodent" no son variantes de
escritura, son dos cadenas distintas**, y ningún normalizador puede adivinar que
son el mismo lugar. Eso es una decisión de datos, no de código. Hay un test que
fija ese límite para que no se confunda con un arreglo hecho.

## 4. Otro hallazgo del plan que se quedó corto

El plan dice que faltan datos de identidad. La medida real: **380 de 446 fichas
activas (85%) no tienen DNI ni teléfono.** No es un caso raro, es la norma: 8 de
cada 10 pacientes no pueden identificarse solos ante el bot. Eso sube el peso de
la Etapa 3 por encima de donde el plan la pone.

Y: **el bot está apagado** (`BOT_IS_ACTIVE = false`) desde el 08/09 16:57. El
plan asume que está funcionando. No hay daño nuevo en curso.

## 5. Entregado en esta tanda

| Arreglo | Prioridad | Tests |
| --- | --- | --- |
| Comparación de sede normalizada | falta en el plan, P0 real | `test_sede_partida.py` (12) |
| Un solo envío por respuesta lógica | P0 (C09) | `test_un_solo_envio.py` (5) |
| Pausa revalidada antes de guardar y enviar | P0 (H02) | cubierto por los de pausa |
| El familiar no hereda el DNI del titular | P0 (I01) | `test_turno_para_un_familiar.py` (9) |
| Con varios en el teléfono y nombre dado, no pregunta | P0 (I05) | idem |

368 tests verdes.

## 6. Orden que propongo seguir

1. **Decidir los nombres de sede.** Sin eso, cualquier mejora de disponibilidad
   sigue calculando sobre media agenda. Es una decisión de la clínica.
2. **Agrupar ráfagas** (C01-C08). Es lo que más ruido saca de las
   conversaciones reales.
3. **Restricciones estructuradas** (R01-R15), incluidos los días excluidos.
4. **Identidad y revisión por recepción** (I02-I09), que con el 85% sin
   contacto es lo que decide si el bot sirve para consultar y cancelar.
5. Catálogo operativo y ruta clínica (K, S).
6. Recordatorios trazables (N).
