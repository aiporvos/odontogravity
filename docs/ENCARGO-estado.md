# Estado del encargo

Rama `encargo/asistente-etapas`, sobre `061c184`. **Nada desplegado.**
449 tests verdes (eran 332 al empezar).

## Entregado

| # | Qué | Casos del plan | Tests |
| --- | --- | --- | --- |
| 1 | La suite ya no puede borrar producción | Etapa 0.5 | 10 |
| 2 | Verificación de la realidad desplegada | Etapa 0.1, 0.3 | script |
| 3 | Un solo envío por respuesta lógica | C09 | 5 |
| 4 | Pausa revalidada antes de guardar y enviar | H02 | — |
| 5 | El familiar no hereda el DNI del titular | I01, I05 | 9 |
| 6 | Una sola sede *(no estaba en el plan)* | — | 16 |
| 7 | Ráfagas agrupadas y versión de conversación | C01-C08, H02 | 12 |
| 8 | Días excluidos y parsers ambiguos | R01, R02, R03, R06 | 19 |
| 9 | Bandeja de derivaciones | H03, I02, S01 | 18 |
| 10 | El turno que no aparece se deriva, no se niega | I02 | — |
| 11 | El bot no reanuda con un caso abierto | H06 | 1 |
| 12 | «Gracias» y «Ok» cierran en vez de reabrir | N01-N03, N08 | 28 |

### Lo que cada uno arregla, en una línea

1. `pytest` con `DATABASE_URL` heredada borraba esa base y decía *11 passed*.
2. Alembic en head no probaba que la restricción existiera. No existe.
3. Un interactivo rechazado llegaba como dos mensajes idénticos.
4. Recepción tomaba el chat durante la inferencia y la respuesta salía igual.
5. El turno de un familiar caía en la ficha del dueño del teléfono.
6. La agenda estaba partida en tres nombres; el bot no veía el 87%.
7. Tres mensajes seguidos producían tres respuestas cruzadas entre sí.
8. «Menos martes y jueves» terminó en un turno el martes.
9. «Dejé la consulta para recepción» no dejaba nada en ningún lado.
10. «No tenés turnos» cuando en realidad no se lo podía identificar.
11. Vencía la pausa y volvía a ofrecer turnos con el caso sin resolver.
12. «Ok» a un recordatorio abría otra admisión desde cero.

## Lo que NO se hizo, y por qué

Por indicación explícita, no se implementa lo que el plan pide de más:

- **Deduplicación entre workers (C05)**: el `CMD` corre `uvicorn` con un solo
  proceso, a propósito, porque hay estado en memoria.
- **Ledgers y brokers de mensajería**: con 18 turnos creados por el bot en
  total, esa maquinaria es más grande que el problema.
- **Instalar el prompt**: lo desaconseja su propia cabecera. Describe estado
  (`HUMAN_PENDING`, borradores, opciones vigentes) que recién ahora empieza a
  existir. Cuando esté completo, se instala y se prueba.

## Pendiente, y qué necesita

| Qué falta | De quién depende |
| --- | --- |
| Crear la restricción `EXCLUDE` en producción | Resolver los 11 solapamientos futuros: decidir cuáles son error de carga y cuáles sobreturno real |
| Catálogo operativo (alias, precios, dirección) | Contenido de la clínica: qué alias, de quién, vigente desde cuándo |
| Protocolo clínico (dolor, prótesis) | Aprobación del equipo odontológico: qué preguntar y qué orientar |
| Instalar el prompt | Que el estado de conversación esté completo |
| Desplegar | Decisión de alcance y momento |

## Al desplegar

Corren tres migraciones nuevas. La de sedes **toca 583 turnos**: está probada
contra una base que reproduce el reparto exacto de producción y es idempotente,
pero conviene que sea un deploy mirado.

Después del deploy, `python scripts/verificar_realidad.py` dentro del contenedor
dice qué quedó realmente aplicado.

El bot está apagado (`BOT_IS_ACTIVE = false`) desde el 08/09. Conviene
encenderlo contra un número de prueba antes de volver a habilitarlo.
