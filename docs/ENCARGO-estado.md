# Estado del encargo

**Desplegado el 09/09/2026** (`bf20f79`, alembic `a9b0c1d2e3f4`).
456 tests verdes (eran 332 al empezar).

Backup de producción tomado y **verificado restaurándolo** antes y después del
deploy. Backup diario automático instalado en el VPS (03:15, retiene 30 días).

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
| 13 | La barrera EXCLUDE de la base, por fin creada | R15, A07, A08 | ensayo |
| 14 | Backup diario verificado, en el VPS y en cron | Etapa 3 | ensayo |
| 15 | Un sobreturno exige una persona que lo autorice | — | 7 |

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
13. La agenda no tenía ninguna protección a nivel base. Ahora sí.
14. Perder el volumen de Postgres borraba todo sin recuperación.
15. Nada impedía a nivel base que un sobreturno saliera de otro lado que el panel.

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
| Catálogo operativo (alias, precios, dirección) | Contenido de la clínica: qué alias, de quién, vigente desde cuándo |
| Protocolo clínico (dolor, prótesis) | Aprobación del equipo odontológico: qué preguntar y qué orientar |
| Instalar el prompt | Que el estado de conversación esté completo |
| Desplegar | Decisión de alcance y momento |

## Verificado en producción después del deploy

```
alembic_version                    : a9b0c1d2e3f4
no_solapar_turnos_por_profesional  : PRESENTE, validada
solo_el_panel_marca_sobreturnos    : PRESENTE, NOT VALID (90 filas históricas)
Pares superpuestos                 : 107, todos marcados, 0 sin marcar
Turnos por sede                    : Silprodent 593  (era 382/195/16)
Sedes activas                      : 1
Tabla derivaciones                 : creada
```

Backups tomados y **verificados restaurándolos** antes del deploy, después, y al
cerrar. El diario corre en el VPS a las 03:15 y retiene 30 días.

Y comprobado sobre una copia restaurada: la restricción **rechaza** una doble
reserva nueva y **deja pasar** un sobreturno marcado.

## Al desplegar

Corren tres migraciones nuevas. La de sedes **toca 583 turnos**: está probada
contra una base que reproduce el reparto exacto de producción y es idempotente,
pero conviene que sea un deploy mirado.

Después del deploy, `python scripts/verificar_realidad.py` dentro del contenedor
dice qué quedó realmente aplicado.

**El bot sigue apagado** (`BOT_IS_ACTIVE = false`) desde que recepción lo
desactivó el 08/09 a las 16:57. Todo lo de arriba está desplegado pero no se
ejercitó con pacientes: conviene encenderlo primero contra un número de prueba.
