# Etapa 0 — Verificar la realidad y preparar pruebas seguras

Rama `encargo/asistente-etapas`, sobre `061c184`. **Nada de esto se desplegó**:
el encargo pide preparar y verificar localmente, y `main` tiene auto-deploy, así
que el trabajo va en rama.

Todo lo que sigue son lecturas. No se modificó ninguna ficha, turno ni
configuración de producción.

---

## 1. Riesgo cerrado: la suite podía borrar producción

`tests/conftest.py` resolvía la base así:

```python
os.environ.setdefault("DATABASE_URL", os.getenv("TEST_DATABASE_URL", "...dentibot_test"))
```

`setdefault` no pisa una variable que ya exista. En una terminal donde alguien
hubiera exportado `DATABASE_URL` —apuntando a producción, por ejemplo— la sesión
de tests se conectaba **ahí**, y el fixture `esquema` corría `drop_all()`.

**Verificado**, no supuesto. Sobre una base descartable con una tabla `patients`
y una fila:

```
ANTES:  1 fila
$ DATABASE_URL=...finge_produccion TEST_DATABASE_URL=...dentibot_test pytest
  11 passed
DESPUES: ERROR: relation "patients" does not exist
```

La suite informó **verde mientras borraba la tabla de pacientes**.

### Qué se hizo

- `TEST_DATABASE_URL` manda siempre; se asigna con `os.environ[...] = ...`, no
  con `setdefault`. Una `DATABASE_URL` heredada ya no puede ganar.
- Antes de importar nada del backend, `_exigir_base_de_pruebas()` **aborta la
  sesión** si la base no se reconoce como descartable: el nombre tiene que
  contener `test` o `prueba`, **y** el host tiene que estar en la lista
  (`localhost`, `127.0.0.1`, `::1`, `postgres`, `db`, ampliable con
  `TEST_DB_ALLOWED_HOSTS` para un runner de CI). Las dos condiciones, no una.
- El fixture `esquema` dejó de ser `autouse`. Los tests que no piden `db`
  —conversación, parsers, formato— ya no crean ni borran tablas.

### Verificación

| Caso | Antes | Ahora |
| --- | --- | --- |
| `DATABASE_URL` heredada a otra base | borró la tabla, 11 passed | la tabla sobrevive, 11 passed |
| `TEST_DATABASE_URL` a una base sin `test` en el nombre | habría borrado | aborta: *"no parece de pruebas: el nombre de la base ('finge_produccion') no contiene 'test' ni 'prueba'"* |
| `TEST_DATABASE_URL` al host del VPS | habría borrado | aborta: *"el host ('72.60.0.249') no está permitido"* |
| Tests de conversación sin base disponible | fallaban al crear el esquema | 15 passed |

10 tests nuevos en `tests/test_base_de_pruebas_segura.py` fijan la defensa.

---

## 2. Qué está realmente corriendo en producción

`scripts/verificar_realidad.py` (solo lectura) contra el contenedor productivo:

### El bot está APAGADO

```
BOT_IS_ACTIVE = false
```

Coincide con el chat del 08/09 a las 16:57: *"desestima los turnos de antes, no
da bien los turnos el asistente virtual"*. Recepción lo apagó. **No se está
generando daño nuevo**, y también significa que la corrección de `061c184`
(confirmación sin respaldo) todavía no se ejercitó con pacientes.

### La agenda no tiene protección en la base

```
alembic_version                   : c5d6e7f8a9b0        ← head
no_solapar_turnos_por_profesional : ⚠️ AUSENTE
Pares de turnos vivos superpuestos: 107
```

Exactamente lo que el encargo advierte: **estar en head no prueba que la
protección exista**. La migración detecta los solapamientos previos, avisa por
log y se saltea a sí misma. Hoy solo valida el código de la aplicación.

Los solapamientos **crecieron de 89 a 107** entre el 04/09 y el 08/09.

### La identidad está rota para la mayoría

```
Fichas sin DNI ni teléfono: 380 de 446   (85%)
```

Esto convierte el caso de la paciente que no pudo cancelar en algo **sistémico,
no anecdótico**: 8 de cada 10 pacientes no pueden identificarse solos ante el
bot, porque la búsqueda es por teléfono o DNI y sus fichas no tienen ninguno de
los dos. Vienen de la agenda de papel.

### Duplicados: resueltos

```
Nombres de paciente repetidos: 1        (eran 61 el 04/09)
Pacientes activos: 446                  (eran 475)
```

El script de unificación se corrió. Queda 1 grupo por revisar.

### Modelos configurados

```
AI_PROVIDER   = openai / gpt-4o-mini
AI_PROVIDER_2 = none
AI_PROVIDER_3 = none
GROQ_MODEL    = llama-3.1-70b-versatile
```

Dos observaciones, ninguna reemplaza los arreglos de código:

- No hay cascada configurada: si OpenAI falla, no hay a dónde caer.
- `llama-3.1-70b-versatile` está dado de baja en Groq, así que ese respaldo no
  funcionaría si se activara.

### Reglas cargadas

| | |
| --- | --- |
| Profesionales activos | 2, ambos con grilla propia |
| Franjas de clínica activas | 9 |
| Tipos de consulta | 9 |
| Obras sociales activas | 52 |
| Sedes | 5 |
| Feriados | 6 |

Sin profesionales sin grilla, así que hoy no se está aplicando la herencia
silenciosa del horario de clínica que el encargo marca como riesgo (P1,
`appointment_service.py:936-941`). Sigue siendo un riesgo latente.

---

## 3. Lo que esto cambia para las etapas siguientes

1. **La identidad (Etapa 3) pesa más de lo que parecía.** Con 85% de fichas sin
   contacto verificable, no alcanza con "buscar mejor": hace falta la vía de
   revisión por recepción que pide el encargo, o la mayoría de los pacientes
   seguirá sin poder consultar ni cancelar.
2. **La restricción ausente es una precondición, no un detalle.** Cualquier
   trabajo sobre concurrencia de reservas (A07, A08, R13) se apoya en una
   barrera que hoy no existe. Hay que decidir qué hacer con los 107
   solapamientos antes de poder crearla.
3. **El bot apagado da margen.** Se puede trabajar sin presión de daño en curso,
   y habilitar por etapas con un número de prueba.

## 4. Estado del encargo

| Punto de Etapa 0 | Estado |
| --- | --- |
| 0.1 Verificar commit/imagen/modelo/migración/config | Hecho |
| 0.3 Informe de reglas efectivas, con huecos expuestos | Hecho |
| 0.5 Aislar y corregir `conftest.py` | Hecho y verificado |
| 0.6 Conservar pruebas existentes | 332 verdes, ninguna quitada |
| 0.2 Inventario de fuentes de agenda | Pendiente — necesita a recepción |
| 0.4 Fixtures sintéticos de los casos | Se arman con cada etapa |

Puerta de aceptación de la Entrega 0 —*"ninguna prueba puede tocar una base
real"*— **cumplida y verificada**.

## 5. Lo que sigue

Etapa 1: fallback único de envío, recepción durable, agrupamiento de ráfagas,
versión de conversación y prioridad de recepción (C01-C10, H01-H06).
