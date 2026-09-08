# Encargo para Claude Code: corregir el asistente de Silprodent

Preparado el 08/09/2026 sobre el repositorio local en el commit 061c184. Este documento es un encargo de implementación, con diagnóstico, prioridades y condiciones de aceptación. Se complementa con PROMPT_BASE_ASISTENTE.md, en esta misma carpeta.

## 1. Resultado que necesitamos

Mejorá el asistente de WhatsApp para que entienda conversaciones reales, respete las restricciones de la clínica y de cada paciente, coordine su intervención con recepción y comunique únicamente operaciones comprobadas. El trato debe ser cálido y natural, con identidad transparente de asistente virtual: no hacerse pasar por Mimi ni por otra persona.

Implementá los cambios en etapas verificables. Reutilizá los servicios y las protecciones existentes; evitá reescribir todo o sumar otra plataforma de agentes sin necesidad. Entregá código, migraciones, pruebas, documentación operativa y un informe de validación. Un prompt nuevo es una parte del trabajo, no el mecanismo que garantiza las reservas.

El objetivo actual del usuario fue preparar este encargo. Su preparación no ejecutó correcciones en producción, cambios de agenda ni envíos a pacientes. Al implementar, prepará y verificá los cambios localmente; el despliegue y las intervenciones sobre fichas reales deben tener alcance y autorización explícitos.

## 2. Qué sabemos y qué no debemos confundir

Hay tres tipos de evidencia:

- **Reportado y verificado por el responsable:** los casos reales descritos abajo, incluyendo consultas a la base y horarios de intervención de recepción. Este documento no volvió a consultar esa base de producción.
- **Comprobado en código local:** referencias de la sección 3. La revisión fue estática, complementada con caracterizaciones aisladas de algunas funciones puras; no se ejecutó la suite completa.
- **Riesgo por diseño:** fallos posibles identificados en el código que deben reproducirse con pruebas. No presentarlos como incidentes de producción ya demostrados.

Casos reales que deben orientar el trabajo, usando datos ficticios en fixtures:

1. **Mensajes en ráfaga.** Una persona escribe «Hola Mimi» / «Cómo estás?» / «Para cuándo tenés turno?». Recibe respuestas separadas y desfasadas. Otra recibe disponibilidad y pedido de nombre repetidos. Un envío de varios archivos provoca cuatro avisos idénticos de formato no admitido.
2. **Intervención humana tardía.** El bot respondió desde las 08:56 y la pausa se activó a las 09:35, cuando escribió recepción. La pausa funciona, pero su activación reactiva no evita respuestas previas a conversaciones destinadas a Mimi.
3. **Restricción ignorada.** «Puede ser en la tarde, menos martes y jueves» terminó en un turno el martes 08/09/2026 a las 17:45, según la comprobación del responsable.
4. **Cancelación impedida por identidad incompleta.** Una paciente tenía un turno el 09/09 a las 09:00 con Murad en una ficha importada sin DNI ni teléfono, junto con otra ficha de nombre parecido. El bot pidió datos repetidos y hasta el nombre de otra persona, sin resolver la cancelación.
5. **Duplicados que siguen creciendo.** Variaciones de apellido y orden nombre/apellido produjeron una tercera ficha para una paciente con historia previa.
6. **Conocimiento operativo ausente.** Una persona pidió el alias para transferir; el bot respondió como si no fuera el canal de la clínica. El responsable aportó un alias usado por recepción, pero eso no prueba que corresponda a todos los profesionales, prestaciones o sedes ni que siga vigente.
7. **Confirmación inventada.** El bot confirmó otro turno con Silvestro y copió el enlace del turno previo. El repositorio ya contiene una corrección específica para ese incidente: hay que verificar despliegue y completar la protección.
8. **Dos personas en un mismo chat.** Se necesitan dos reservas y dos identidades independientes; compartir teléfono no convierte a las dos personas en el mismo paciente.
9. **Molestia por prótesis.** La paciente informó lesión/molestia y dificultad para retirar una prótesis; el bot pasó directamente a ofrecer horarios rutinarios sin reconocer el problema ni gestionar revisión humana.
10. **Acuse de recordatorio.** «Ok» después del recordatorio produjo «¿En qué puedo ayudarte hoy?», perdiendo el contexto inmediato.
11. **Control positivo: recordatorio correcto.** Juliana tenía dos turnos: 01/09 por conducto y 09/09 a las 11:00 por extracción. El recordatorio del 09/09 correspondía al segundo. NO modificar esa fecha ni atribuir este ejemplo a un fallo del recordatorio. Convertirlo en una regresión que preserve dos turnos distintos.

## 3. Diagnóstico del código que hay hoy

Las líneas corresponden al commit auditado; al modificar, usá los nombres de funciones para ubicar la lógica.

| Prioridad | Evidencia local | Implicación y trabajo requerido |
| --- | --- | --- |
| P0 | backend/routers/evolution_router.py:27, 227, 656: locks en memoria por número y una tarea por mensaje; no persiste el ID entrante ni agrupa ráfagas. | Serializar no es agrupar. Incorporar recepción durable, deduplicación y procesamiento de lotes por conversación. |
| P0 | evolution_router.py:694 comprueba pausa antes de ejecutar IA; en 749-752 guarda y envía sin revalidarla. | Una secretaria puede tomar el chat durante la inferencia y aun así recibir una respuesta tardía del bot. Revalidar versión y dueño antes de efectos y envíos. |
| P0 | backend/services/whatsapp.py:243-245 y 260-269 envía fallback y devuelve False; evolution_router.py:640-653 vuelve a intentar enviar. | Un fallo de interactivo puede generar dos o tres textos. Definir un único responsable del fallback y un resultado de envío explícito. |
| P0 | bot/ai_agent.py:1282-1372: protección mediante regex y una bandera activada por un string que empieza con un símbolo de éxito. | Ya hay un arreglo para confirmación sin reserva, pero no vincula cada afirmación a persona, ID, fecha, profesional y enlace. Una reserva exitosa no debe habilitar otras afirmaciones inventadas. |
| P0 | ai_agent.py:1315-1320: cada proveedor reinicia el diálogo de herramientas y la bandera de éxito. | Riesgo de repetir una operación si un proveedor falla después de que la base ya confirmó. Reconciliar operaciones antes del fallback. |
| P0 | backend/schemas/schemas.py:340-352 y appointment_service.py:948-976: preferencia horaria sin exclusiones de días. | Agregar restricciones estructuradas en conversación, herramientas, API, búsqueda y validación final. |
| P0 | backend/routers/bot_routes.py:393-398 reutiliza el DNI de la única ficha del teléfono cuando falta DNI, aunque se informe otro nombre. | Riesgo de reservar para la persona anterior cuando el turno es para un familiar. Separar identidad del contacto y del paciente. |
| P0 | appointment_service.py:795-800 y 837-839 busca por DNI y puede actualizar teléfono; bot_routes.py:414-415 valida formato en ese flujo. | Auditar y cerrar la posibilidad de modificar el contacto de una ficha existente al reservar con un DNI aportado por otra persona. No trasladar automáticamente titularidad. |
| P1 | appointment_tools.py:290-296 puede enviar dni=null al reprogramar; schemas.py:329-333 exige string. | Corregir el contrato para identificación autorizada sin DNI y mantener controles de pertenencia. |
| P1 | appointment_tools.py:315-319 convierte lista vacía en «no tenés turnos pendientes» y pierde paciente/ID por turno que la API devuelve. | Diferenciar ausencia de registro de inexistencia real; conservar asociación por persona y turno. |
| P1 | appointment_tools.py:669-728 persiste cuatro datos y concluye «Podés agendar». | Falta intención, pregunta pendiente, borrador, persona objetivo, turnos seleccionados, restricciones y cierre del flujo. Tener datos completos no equivale a querer reservar. |
| P1 | backend/models/chat_session.py:43-50 sólo guarda rol, contenido y fecha; evolution_router.py:460 guarda texto humano como assistant. | Distinguir mensajes de bot, recepción, recordatorio y sistema, así como entregas, respuestas citadas y origen. |
| P1 | reminders_loop.py:96-140 envía sin registrar el recordatorio como evento de conversación ni ledger durable de envíos; hay TODO al respecto. | Asociar recordatorio, respuesta, turno y versión. Hacer idempotentes los trabajos y soportar reinicios. |
| P1 | evolution_router.py:703-710 pausa y promete aviso/respuesta humana; el fallback final de ai_agent.py también promete contacto. | Pausar no crea una tarea de recepción. Implementar bandeja real de derivaciones y mensajes ajustados a lo que efectivamente ocurrió. |
| P1 | appointment_service.py:936-941 aplica horario de clínica si no encuentra grillas activas del profesional. | Distinguir herencia configurada, datos faltantes y profesional sin atención. No interpretar desactivar todas las franjas como disponibilidad completa. |
| P1 | appointment_tools.py:85-87 acepta el motivo si falla su verificador; get_active_insurances en ai_agent.py devuelve una lista de ejemplo si falla la base. | Los errores de consulta no deben convertirse en datos válidos ni en cobertura comercial afirmada. |
| P1 | appointment_service.py:64-67, 460-464 resuelve motivos mediante palabras/prefijos; interpretar_preferencia confunde algunas fechas/franjas. | Añadir desambiguación, negaciones y distinción entre día relativo y parte del día; no adivinar duración ni profesional. |
| P1 | appointment_service.py:1121, 1149 usa la unión de franjas/candidatos al ofrecer; profesional_libre en 633-635 comprueba quién realmente trabaja. | Riesgo de ofrecer huecos que nadie puede cubrir completos. Unificar el cálculo de opciones y la validación de alta por profesional concreto. |
| P1 | appointment_service.py:764 valida profesional con duración recibida antes de calcular duración real en 773. | Un control de 15 minutos cerca del cierre puede rechazarse usando un default de 30. Resolver prestación/duración antes de validar. |
| P1 | appointment_service.py:732-738 transforma cobertura no reconocida en Particular. | No cambiar la modalidad de pago sin acuerdo explícito. Diferenciar no reconocida de particular elegido. |
| P1 | bot_routes.py:232-277 colapsa fichas de igual nombre; 599-607 consulta las seleccionadas. | Puede ocultar turnos de otra ficha duplicada. Resolver alias/IDs verificados sin deduplicar resultados sólo por nombre. |
| P1 | appointment_service.py:387-397 cuenta sillones; la exclusión SQL protege al profesional, no toda la capacidad de sede. | Riesgo de exceder sillones en altas simultáneas de profesionales distintos. Probar y proteger los recursos compartidos. |
| P1 | migración c5d6e7f8a9b0_sobreturno_deliberado.py:87-105 puede retornar ante solapamientos sin crear la exclusión. | Estar en Alembic head no prueba que exista la protección: comprobar constraints efectivos y tratar conflictos históricos explícitamente. |
| P2 | clinic_routes.py:391-408 condiciona validaciones de ocupación a que venga start_time; appointment_service.py:829-846 confirma ficha antes de crear turno. | Validar también cambios aislados de duración/profesional/sede y hacer atómica la operación que corresponda. |
| P2 | Professional.locations existe, pero appointment_service.py:266-299 no filtra candidatos por sede y las grillas no la distinguen. | Confirmar el alcance real de sedes y evitar asignaciones a una sede no habilitada para el profesional. |
| P2 | SYSTEM_PROMPT tiene aproximadamente 988 líneas; hardcodea duraciones/horarios y contiene instrucciones contradictorias sobre DNI y formato. | Reducir y ordenar el prompt; reglas operativas desde configuración única, validadas fuera del modelo. |
| P2 | README.md, skills/01-bot-conversation-flow.md y QA/casos_de_prueba.md muestran reglas/nombres/obligatorios históricos diferentes del código. | Actualizar documentación y ejemplos junto con las reglas; no reconstruir requisitos usando esos textos obsoletos. |

Caracterizaciones aisladas ya observadas, sin ejecutar la aplicación ni tocar la base:

- interpretar_preferencia('tarde menos martes y jueves') retiene una franja, pero no las exclusiones.
- interpretar_preferencia('mañana a la tarde') devuelve la franja de mañana, confundiendo el día relativo con la parte del día.
- interpretar_preferencia('después del 16 a las 18:45') puede interpretar el día 16 como una hora.
- Con tipos sintéticos Limpieza y Conducto en ese orden, 'no es limpieza, es conducto' puede resolverse como Limpieza.
- Con un tipo sintético 'Tratamiento de conducto' sin sinónimos, 'tratamiento de caries' puede coincidir por la palabra genérica 'tratamiento'. La corrección debe considerar la configuración real y no asumir ese mismo resultado en todas las bases.

Conservar las protecciones existentes de horarios, especialidades, cobertura, feriados, licencias, solapamientos, profesional solicitado, motivo obligatorio, identidad y sobreturno autorizado. Existen tests para ellas. Verificar cuáles están desplegadas y qué migraciones/configuración tienen realmente efecto.

## 4. Políticas de producto propuestas

Estas son decisiones iniciales para implementar y evaluar. Los intervalos son parámetros sugeridos, no mediciones de producción.

| Situación | Comportamiento esperado |
| --- | --- |
| Persona escribiendo varias partes | Esperar aproximadamente 3 segundos de silencio, con un máximo inicial de 10 segundos desde el primer mensaje, y responder al conjunto. |
| Mensaje nuevo mientras se genera una respuesta | Invalidar la respuesta que ya quedó vieja y reconsiderar el lote antes de responder. No repetir operaciones ya confirmadas. |
| Recepción toma el chat | Tiene prioridad. Frenar los envíos y mutaciones del bot que aún no se ejecutaron; conservar lo que sí se ejecutó para que recepción lo vea. |
| «Hola Mimi» sin pedido concreto | Dar tiempo al agrupamiento. El nombre solo no activa una búsqueda de turnos ni una pausa permanente. |
| «Mimi, ¿tengo turno hoy?» | Es una intención clínica válida. Si atiende el bot, identificarse sin suplantar a Mimi y consultar registros autorizados; si ya atiende recepción, guardar y callar. |
| «Mimi, ahora te paso precio, ¿qué tamaño son?» | No inventar una consulta odontológica. Resolver como conversación para recepción y crear una tarea si hace falta atención. |
| Pedido explícito de persona | Un solo acuse después de crear la derivación; pausa real y sin prometer un plazo no establecido. |
| «Ok» a recordatorio | Interpretar como recibido, o asistencia confirmada sólo si el recordatorio lo pidió inequívocamente; no comenzar otra admisión. |
| Sólo «Gracias» tras cerrar una operación | Una despedida breve o silencio contextual; ninguna herramienta de agenda. Si incluye otro pedido, resolver esa intención. |
| No aparece el turno que la persona dice tener | «No lo encuentro en esta agenda» y revisión humana con contexto; no afirmar que nunca existió. |
| Precio/alias/dirección | Responder desde catálogo aprobado aplicable a ese caso; no iniciar el formulario de reserva. |
| Dolor o problema de tratamiento reciente | Reconocerlo y activar el protocolo de revisión definido por la clínica, con derivación operativa; no tratarlo automáticamente como una prestación rutinaria. |

No imponer un silencio general a toda persona que diga «Mimi»: ocultaría pedidos válidos. Tampoco reactivar el bot por mero vencimiento del temporizador si queda una tarea humana abierta. La duración de pausa y su vencimiento deben quedar visibles y configurables por recepción.

## 5. Etapa 0: verificar la realidad y preparar pruebas seguras

1. Comparar commit local, imagen desplegada, proveedor/modelo activo, migración Alembic y configuración efectiva. Exponer internamente build SHA y versión de reglas, sin secretos. Documentar por qué una corrección local puede no explicar un chat anterior.
2. Inventariar fuentes de agenda: panel, cargas/importaciones, agenda externa o anotaciones de recepción. Si alguien confirma manualmente en WhatsApp sin cargar un turno, el sistema no puede saberlo por adivinación. Facilitar el alta/vinculación y una cola de discrepancias; no convertir cualquier mensaje humano en una reserva automática.
3. Exportar un informe de reglas efectivas por sede, profesional, prestación, duración, cobertura, día y bloqueo. Mostrar datos faltantes y conflictos, sin rellenarlos con ejemplos. Validar reglas comerciales con la clínica, incluyendo PAMI y permisos de sobreturno.
4. Preparar fixtures sintéticos que reproduzcan los casos. No copiar DNI, teléfonos, tokens de cancelación ni conversaciones clínicas completas a tests o repositorios.
5. **Antes de ejecutar pytest:** corregir/aislar tests/conftest.py. Usa setdefault para DATABASE_URL y ejecuta drop_all en un fixture autouse. Una URL heredada puede apuntar a una base real. Exigir una base efímera explícita, credenciales restringidas y comprobación de host/nombre permitido antes de cualquier operación destructiva. Los tests unitarios de conversación deben poder correr sin crear ni borrar tablas.
6. Conservar las pruebas existentes. No considerar la suite aprobada si sólo se verifican textos del prompt o si se usan mocks que aceptan cualquier reserva.

## 6. Etapa 1: mensajes, concurrencia y prioridad humana

Implementar este recorrido usando preferentemente PostgreSQL y la infraestructura actual. Incorporar otro broker sólo si se justifica por una necesidad observada.

    Webhook validado
      → evento entrante persistido y deduplicado
      → lote pendiente por conversación
      → agrupamiento de texto, audio y adjuntos
      → decisión de quién atiende e intención
      → interpretación del modelo
      → validaciones y operaciones de backend
      → respuesta construida con datos comprobados
      → envío registrado y estados de entrega

### Recepción durable y agrupamiento

- Persistir identificador de evento y mensaje del proveedor, cuenta/número de clínica, remitente, fecha del proveedor, fecha recibida, tipo y referencia al mensaje citado. Separar identidad del evento y del mensaje: una actualización de entrega no es otra consulta del paciente.
- Responder el webhook exitosamente después de guardar/encolar de forma durable. No depender únicamente de BackgroundTasks y un diccionario de locks que se pierde al reiniciar o no se comparte entre workers.
- Agrupar por conversación/cuenta, reiniciando el temporizador de silencio hasta el máximo configurado. Guardar también cada mensaje individual y sus IDs para auditoría.
- El lock debe servir para reclamar/actualizar el lote, no impedir que entren nuevas partes mientras se espera o se llama al modelo. Usar exclusión entre procesos mediante transacción, lease o mecanismo equivalente.
- Ordenar por datos del proveedor y secuencia local estable dentro del lote. Tratar mensajes atrasados como eventos tardíos explícitos; no insertarlos retroactivamente para repetir acciones ya realizadas.
- Deduplicar por ID, no sólo por texto. Dos «sí» legítimos en momentos diferentes son mensajes diferentes.
- Audio: conservar su posición original y esperar la transcripción con un límite. Si tarda demasiado, no adelantar una respuesta incompatible a mensajes posteriores. Integrar texto posterior que corrija o complemente el audio.
- Fotos/documentos: guardar contexto y posible caption. Un lote de cuatro archivos no debe producir cuatro avisos. Si recepción ya atiende, guardar sin aviso automático. Los archivos clínicos o comprobantes requieren su ruta específica de revisión, no una negativa genérica repetida.

### Versión de conversación y operaciones en curso

- Registrar una versión/secuencia. Cada mensaje nuevo o toma humana la incrementa. Toda generación lleva la versión y los mensajes que está contestando.
- Comprobar versión y dueño inmediatamente antes de ejecutar una mutación y antes de despachar una respuesta. Un simple chequeo al entrar a handle_text_message es insuficiente.
- Si cambió el lote antes de una operación, recalcular con los nuevos datos. Ejemplo: «11» seguido de «perdón, 12» no debe reservar a las 11 y responder a las 12.
- Cancelar una tarea de asyncio no detiene necesariamente la función que ya corre en un executor ni revierte una transacción confirmada. Colocar también controles en el límite de ejecución de herramientas/backend.
- Si el turno ya se creó, conservar el resultado en un registro durable. Reprocesar el nuevo mensaje con conocimiento de esa reserva; nunca deshacerla silenciosamente ni repetirla para recuperar texto perdido.
- Definir la carrera con precisión: ningún nuevo efecto debe iniciarse después de que se registre la toma humana y se verifique en el punto de autorización. Un mensaje ya aceptado por WhatsApp no puede retirarse con esa garantía; registrar ese caso residual para recepción.

### Atención humana y derivaciones

- Añadir estado explícito BOT / HUMAN_PENDING / HUMAN_ACTIVE / CLOSED, responsable, motivo y fechas. Adaptar nombres al proyecto.
- En la recepción de un eco humano, persistir la toma de control de inmediato y cancelar salidas pendientes. No aguardar a que un trabajo de fondo eventual cambie paused_until.
- Mantener un ticket/bandeja con motivo, resumen mínimo, paciente no resuelto si corresponde, turno relacionado y estado. Deduplicar derivaciones del mismo problema.
- Mostrar en el panel «lo atiende recepción», «pendiente de revisión» y una acción clara para devolverlo al bot. La reactivación debe considerar si quedó una tarea sin resolver.
- Proveer reglas configurables para proveedores/contactos administrativos, atención humana persistente y casos mixtos. El clasificador puede recomendar una derivación, pero no debe suspender indefinidamente todas las conversaciones por una palabra.
- No afirmar «ya avisé», «te llaman» o «en breve te responden» si únicamente se guardó una pausa. Crear el caso primero; mostrar el resultado real. Configurar responsables y seguimiento sin inventar tiempos de respuesta.
- Usar el origen documentado del evento humano. YCloud ofrece eventos de sincronización desde WhatsApp Business y eventos de estados de envío; la detección por texto parecido al último mensaje debe quedar como compatibilidad acotada, no como identidad principal. Referencia: [eventos YCloud](https://docs.ycloud.com/reference/webhook-events-payloads) y [ecos de mensajes de la app](https://docs.ycloud.com/reference/whatsapp-business-app-sent-message-sync-webhook-examples).

### Un solo envío por respuesta lógica

- Establecer un contrato de entrega con estados como accepted, fallback_sent, failed y unknown, además de provider_message_id. accepted no significa delivered.
- Un solo componente decide el fallback. Si la lista falló y ya se envió texto, el llamador no vuelve a enviarlo.
- Un timeout puede dejar envío incierto. Reconciliar con los datos del proveedor antes de reenviar si es posible; no asumir que excepción significa que nada salió.
- Registrar intentos, acuses y errores. En fallos inciertos no prometer entrega exactamente una vez si el proveedor no ofrece idempotencia suficiente; documentar cómo se detectan y resuelven duplicados.

## 7. Etapa 2: reservas comprobables y restricciones completas

### Contratos de herramientas y evidencia

- Reemplazar strings mezclados con instrucciones por resultados tipados: status, error_code, operation_id, request_id, appointment_id, patient_id, professional_id, location_id, starts_at, duration_minutes, cancel_url y version, según la operación.
- Separar missing_data, ambiguous_identity, rule_conflict, unavailable, infrastructure_error y unknown_outcome. Una lista vacía no representa un fallo de conexión.
- Backend decide reglas, IDs, fecha final y enlace. El modelo interpreta el lenguaje y propone solicitudes. El constructor de respuestas usa el registro confirmado para comunicar el resultado.
- Aplicar evidencia también a consultar, cancelar, reprogramar, disponibilidad, cobertura y derivar. Eliminar la dependencia de buscar frases como «te agendé» para decidir si una afirmación es válida.
- Toda fecha/hora ofrecida debe pertenecer a un conjunto de opciones real, vigente y compatible con el borrador. Una confirmación histórica obtenida por consulta puede comunicarse sin crear otro turno.
- El catálogo de herramientas debe ser acotado por intención y estado. Un «gracias» en flujo cerrado no habilita crear/cancelar turnos porque los datos sigan completos.
- Validar esquemas en servidor aunque el modelo use modo estricto. Donde el proveedor/modelo lo soporte, usar esquemas estrictos y controlar llamadas múltiples; probar capacidades de cada fallback. El modo estricto valida estructura, no disponibilidad ni consentimiento. Referencia: [function calling de OpenAI](https://developers.openai.com/api/docs/guides/function-calling).

### Idempotencia de operaciones

- Generar la clave de operación en servidor para la acción lógica, persona y versión del borrador. No permitir que el modelo evite deduplicación inventando una clave nueva en cada intento.
- Vincular resultado, efecto en base y trabajo de confirmación dentro de una transacción cuando sea posible. Una reentrega/reintento devuelve la misma reserva, no crea otra.
- Antes de pasar a otro proveedor, recuperar las operaciones realizadas. Si sólo falló redactar la confirmación, reconstruirla desde el resultado guardado sin volver a agendar.
- Ante timeout de creación, distinguir no ejecutado de estado incierto y reconciliar. No afirmar «no quedó agendado» sin comprobarlo.
- Reservar dos turnos intencionales requiere dos borradores/operaciones diferentes. La idempotencia no debe impedir consultas posteriores legítimas de la misma persona con el mismo motivo.

### Restricciones estructuradas del paciente

Agregar un objeto único que viaje de punta a punta, con campos equivalentes a:

    requested_date / date_from / date_to
    allowed_weekdays / excluded_weekdays / excluded_dates
    time_from / time_to / preferred_period
    professional_id_requested / location_id
    service_id / service_stage / insurance_id
    exact_date_required / allow_alternative_dates
    source_message_ids / source_text / constraints_version

- Diferenciar restricciones duras («menos martes», «sólo después de las 18») de preferencias («si puede ser a la tarde»). No relajar una restricción dura sin que el paciente acepte el cambio.
- «Tarde, menos martes y jueves» excluye martes y jueves en todos los resultados y también en la reserva final. Si no quedan opciones, explicarlo y ofrecer ampliar una restricción concreta, sin ignorarla.
- «Mañana a la tarde» combina día relativo y franja; «después del 16» es una fecha, no 16:00. Resolver con fecha actual y zona horaria de clínica.
- Guardar negaciones, correcciones y alcance. «No limpieza, conducto» no selecciona limpieza. «Martes o jueves» no significa excluirlos. «Excepto este jueves» no prohíbe todos los jueves.
- Si dos datos se contradicen, pedir una aclaración breve. Si la corrección es explícita, sustituir el valor anterior y registrar procedencia.
- Aplicar las restricciones en la búsqueda y otra vez al crear/reprogramar. Una validación sólo al ofrecer horarios permite que se reserve un horario incompatible posteriormente.
- Vencimiento de opciones: invalidar al cambiar paciente, profesional, servicio, duración, cobertura, sede o restricciones. Al elegir un botón viejo, consultar su ID original y comprobar vigencia; no interpretar únicamente un título como «11:00».
- El backend debe recomputar ocupación al confirmar y sostener exclusión transaccional ante concurrencia. Conservar la protección de no superponer a un profesional entre sedes.
- Utilizar un motor único de opciones y validación: cada slot incluye profesional concreto, sede, prestación, comienzo/fin, duración, restricciones y versión. No formar un turno largo uniendo media jornada de un profesional con la de otro.
- Calcular primero la duración canónica de la prestación. Validar después la jornada completa y ocupación del profesional, capacidad compartida de sillones y habilitación de sede.
- Verificar constraints reales en PostgreSQL, además de la versión Alembic. Si faltan por conflictos históricos, producir un diagnóstico y procedimiento de reparación; no declarar que la agenda está protegida sólo porque la migración figure aplicada.
- Una exclusión por profesional no protege por sí sola la capacidad de una sede con varios profesionales. Serializar/reservar esos recursos de forma transaccional también.
- El panel y el bot deben usar las mismas reglas al crear o editar. Cambiar sólo duración, profesional o sede puede producir un conflicto aun sin cambiar la hora de inicio.
- Evitar confirmar modificaciones a la ficha como efecto lateral irreversible de una reserva que luego fracasa. Definir límites transaccionales claros y operaciones separadas para cambios de datos personales autorizados.

### Reglas de clínica y servicios

- Fuente única editable para atención por profesional/sede, servicios habilitados, duración, primera consulta/control/tratamiento cuando corresponda, cobertura, feriados, licencias, límites y sobreturnos.
- No asumir que consultar por conducto significa realizar un tratamiento completo ni que un control de prótesis tiene la misma duración que una prótesis nueva. Usar tipos aprobados; aclarar cuando cambie profesional o duración.
- Mantener el motivo vigente expresado por el paciente como requisito para ofrecer/reservar, conforme a la regla clínica actual. No exigirlo para dar información operativa o consultar/cancelar un turno existente.
- Si falta una grilla, una configuración o un tipo reconocido, devolver datos insuficientes y derivar/aclarar. La ausencia de datos no habilita todos los horarios ni todos los profesionales.
- Una obra social aceptada por la clínica no implica que cubra esa prestación, honorario completo o a cualquier profesional. Expresar sólo lo validado.
- Si la cobertura no se reconoce, solicitar aclaración o proponer atención particular para que la persona la acepte. No convertirla silenciosamente en Particular al guardar.
- Ningún mensaje del paciente, del historial o de una ficha puede autorizar sobreturnos, cambiar reglas o modificar el alias de cobro. Esa autorización proviene de roles y configuración del backend.

## 8. Etapa 3: identidad, duplicados y turnos para familiares

Separar tres conceptos: **contacto de WhatsApp**, **paciente** y **turno**. El contacto puede gestionar más de una persona según la autorización que se haya establecido. El nombre de perfil o un teléfono compartido no resuelven esa relación por sí solos.

### Resolver antes de crear

- Normalizar espacios, acentos, mayúsculas y formatos de teléfono, conservando los valores originales. Permitir búsqueda con orden nombre/apellido invertido y posibles errores tipográficos como candidatos.
- Separar búsqueda de candidatos de verificación. Coincidencia difusa, nombre completo y conocimiento de un horario no bastan para revelar datos clínicos o cancelar un turno ajeno.
- Usar vínculos previamente verificados, credenciales/enlaces de gestión válidos u otro procedimiento aprobado. Si una ficha importada carece de contacto verificable, derivar a recepción para validación; no pedir una secuencia interminable de datos que el sistema no puede cotejar.
- La búsqueda amplia de fichas queda restringida a recepción o devuelve un resultado opaco de revisión, evitando listas de personas y sus tratamientos al chat no autenticado.
- Si el paciente declara que ya se atiende y existe posible coincidencia sin resolver, no crear silenciosamente una tercera ficha para salir del paso. Abrir caso de resolución y conservar la solicitud de turno/cancelación.
- No inventar DNI, no exigirlo cuando existe una vía autorizada sin él y no asignar al familiar el DNI del titular del teléfono.
- No sobrescribir teléfono, DNI, nombre o historia de una ficha existente durante una simple reserva sin una operación de actualización autorizada independiente.

### Cancelación y reprogramación

- Con identidad resuelta, devolver turnos con ID, persona, fecha/hora, profesional, sede y estado. Pedir cuál sólo si hay ambigüedad.
- Si una identidad verificada tiene aliases o fichas unificadas, consultar todos sus IDs vinculados de forma segura. No ocultar citas al seleccionar arbitrariamente una ficha entre homónimos; mientras el vínculo no se resuelva, enviar el conflicto a recepción.
- Con un único turno y cancelación explícita, ejecutar sin confirmaciones repetidas; con «cancelá el de mañana», resolver contra la fecha real y el turno autorizado correspondiente.
- Si no se verifica la identidad, crear una solicitud de cancelación pendiente para recepción con la información aportada. Comunicar que requiere revisión, sin decir que el turno ya está cancelado.
- Corregir la discrepancia dni=null/string en reprogramación. Reprogramar de forma atómica y conservar el turno anterior si falla la nueva disponibilidad.
- No trasladar el problema al paciente con frases como «dame el nombre de otra persona». Explicar brevemente lo necesario y transferir lo ya aportado.

### Dos personas / varios turnos

- Crear un borrador por paciente con motivo, profesional, fecha, cobertura y restricciones propios. Compartir sólo los datos explícitamente aplicables al grupo.
- «También para Silvestro» inicia una nueva solicitud; preguntar motivo o persona únicamente si falta o puede haber cambiado. No copiar los datos clínicos del turno anterior como nuevos hechos.
- «Dos turnos» no significa automáticamente dos personas. Si no se sabe, una sola pregunta breve resuelve para quiénes son.
- «Así vamos juntos» expresa preferencia de proximidad. Buscar turnos contiguos según duraciones reales, no asumir intervalos de media hora.
- Definir semántica del grupo: intentar reservar ambos atómicamente si deben confirmarse juntos, o comunicar el resultado parcial con total claridad. Nunca afirmar «los dos confirmados» si sólo existe uno.
- Cada cita debe tener su ID y un enlace de cancelación vinculado a esa cita. Si se mantiene un diseño de enlace por paciente, debe ser un portal explícito con selección segura de turno; no reutilizarlo fingiendo que representa otra reserva concreta.

### Reparación de fichas históricas

- Reutilizar y revisar los servicios/scripts existentes de unificación. Generar informe dry-run de grupos candidatos, conflictos de DNI/teléfono e impacto en historia, odontograma y turnos.
- Unión automática sólo con una identidad fuerte, sin conflictos, según una regla documentada. Homónimos o errores de apellido requieren revisión humana; un umbral difuso alto no equivale a identidad probada.
- La aplicación de una unión debe ser transaccional, auditable, con mapa de IDs y respaldo/reversión previstos; preservar toda la historia y relaciones. No hacer merges masivos en producción durante la implementación local.
- Dar a recepción herramientas para resolver la ficha al recibir el caso y continuar el turno/cancelación sin que el paciente repita su conversación.

## 9. Etapa 4: conocimiento útil y atención clínica sensible

### Catálogo operativo aprobado

Crear una sección editable en el panel y una herramienta de consulta para:

- Direcciones exactas, sedes, mapas, atención y canales de recepción.
- Prestaciones, profesional aplicable y condiciones de primera consulta/control.
- Precios, moneda, concepto, inclusiones/exclusiones, vigencia y si son orientativos o finales.
- Medios de pago, alias/CBU aprobado, titular, profesional/sede aplicables e instrucciones de comprobante.
- Coberturas aceptadas y condiciones que realmente estén verificadas.
- Preparaciones e indicaciones administrativas aprobadas por el equipo.

Cada dato requiere estado publicado/borrador, fuente o responsable, fecha de revisión, alcance y vigencia. No importar como actuales los precios citados en chats del 02/09 ni fijar el alias reportado para todos los casos. Guardarlo como dato pendiente de validación si se utiliza como insumo.

- Preguntar a quién o qué se paga sólo si eso cambia la cuenta de destino y no está resuelto. Responder el alias directo cuando el contexto y catálogo lo permiten.
- Si falta información, registrar consulta para recepción. Evitar «comunicate con la clínica» como única solución dentro del WhatsApp de la clínica.
- Un comprobante adjunto puede quedar recibido para revisión, pero no significa pago acreditado. No confirmarlo por descripción del paciente o imagen no verificada.
- Una edición de cuentas de cobro debe requerir rol autorizado y auditoría. El modelo sólo consulta esos datos.

### Molestias, dolor y problemas de tratamientos

- Incorporar una ruta de revisión clínica diferente de la reserva rutinaria, con motivo textual del paciente, contexto de tratamiento reciente y derivación visible.
- El equipo odontológico debe aprobar las preguntas mínimas, señales de alarma y mensajes de orientación. El bot no diagnostica, prescribe, indica maniobras para retirar prótesis ni descarta urgencia porque la agenda esté llena.
- La prioridad clínica no debe depender de que el paciente complete DNI, cobertura o un formulario de turnos. Las validaciones administrativas pueden continuar después cuando corresponda.
- Para «la prótesis me lastima y me cuesta retirarla», reconocer la molestia y gestionar revisión del equipo; no afirmar que puede esperar al día siguiente sólo porque ese sea el primer hueco.
- Si el protocolo aprobado detecta una emergencia, mostrar la orientación local correspondiente sin esperar a una cita ordinaria. No copiar teléfonos ni circuitos de otros países a la clínica argentina.
- La necesidad de revisión ante prótesis dolorosa y la existencia de situaciones dentales urgentes se respaldan en fuentes clínicas; el flujo concreto de Silprodent debe aprobarlo su equipo. Referencias: [NHS, prótesis](https://www.nhs.uk/tests-and-treatments/dentures/) y [NHS, atención dental urgente](https://www.nhs.uk/nhs-services/dentists/how-to-find-an-nhs-dentist-in-an-emergency/).

## 10. Etapa 5: estado de conversación y respuestas naturales

Reemplazar el estado de cuatro campos por un estado versionado, acotado y persistente. Como mínimo:

    intent / flow_status / pending_question
    contact_id / patient_candidates / verified_patient_id
    booking_drafts[] / active_draft_id
    constraints / constraints_version
    offered_options_id / offered_at / selected_option_id
    selected_appointment_id / committed_operation_ids
    last_outbound_kind / last_outbound_id / reply_to_id
    handoff_status / human_owner / conversation_version

- Guardar procedencia y momento de los datos. No derivar un motivo de un mensaje de hace semanas o de la persona anterior del chat.
- Historial reciente más estado estructurado: separar mensajes humanos, bot, recordatorios, herramientas y cambios de agenda. No guardar como «respuesta enviada» un texto cuya entrega falló; mantener eventos planned/accepted/delivered según corresponda.
- Al completar una reserva, cerrar ese borrador y conservar el resultado. «Gracias» no lo reabre. La solicitud de otro turno inicia otro borrador sin arrastrar restricciones o identidad por accidente.
- Inyectar fecha/hora actual, sedes y reglas efectivas como contexto confiable del servidor, separado del mensaje del paciente. El texto citado o reenviado sigue siendo contenido, no una orden del sistema.
- Tratar «sí», «a las 11» y «ese» según la pregunta u opción vigente. Si la persona ya eligió una opción inequívoca y autorizó reservar, avanzar; no volver a ofrecer la misma disponibilidad y preguntar lo mismo.
- No exigir siempre un resumen adicional de confirmación. Reservar cuando la intención, la opción y los datos estén claros; confirmar sólo las ambigüedades que podrían cambiar persona, fecha, profesional o efecto.
- Cuando falten datos, preguntar el mínimo necesario para esa intención. No pedir cobertura para dar la dirección ni motivo para consultar un turno existente.
- Si después de dos intentos razonables no se resuelve un dato, conservar lo recibido y derivar; no convertir el guard anti-loop en un reemplazo de la lógica de conversación.
- Usar voseo y mensajes habitualmente de 1 a 3 frases. Confirmaciones de varios turnos pueden necesitar más. Un emoji como máximo cuando tenga sentido; sin fórmulas repetidas de cierre en cada mensaje.
- No decir «excelente elección» al elegir un horario, ni «estoy bien» como si fuera Mimi, ni exponer API keys/modelos/problemas internos al paciente.
- Formato WhatsApp construido por el canal: texto simple por defecto, negrita simple opcional y consistente; URL de cancelación real visible, sin Markdown de enlaces tipo [link](...). No pedirle al modelo que arregle una cadena de asteriscos escapados.
- Mostrar unas pocas opciones relevantes por vez y ofrecer otras cuando se soliciten. Conservar IDs únicos de opción: un título recortado no puede cambiar la fecha/profesional subyacente.
- El prompt adjunto define comportamiento y jerarquía; no debe duplicar todas las reglas de negocio en texto. Adaptarlo a las herramientas reales antes de activarlo.

## 11. Etapa 6: recordatorios y respuestas relacionadas

El caso de Juliana es un control de funcionamiento correcto. El objetivo es mejorar trazabilidad y continuidad sin confundir dos turnos legítimos.

- Crear trabajos por appointment_id, versión relevante, tipo de aviso y momento programado; clave única para impedir duplicados entre workers y reinicios.
- Registrar planned, claimed, accepted, delivered, failed y unknown, con provider_message_id cuando exista. Un HTTP aceptado no prueba que el paciente lo recibió.
- Usar trabajos vencidos pendientes dentro de una política de recuperación, no depender sólo de una ventana móvil de 15 minutos que puede perder turnos al reiniciar o demorar el proceso.
- Antes de enviar, releer estado/versión: si se canceló, reprogramó o cambió el destinatario, invalidar el recordatorio viejo y generar el pertinente según política.
- Registrar el recordatorio como antecedente del chat, ligado al turno y a la respuesta citada. Conservar contexto suficiente aunque el historial conversacional normal haya vencido.
- «Ok» sin cita explícita sólo se asocia al recordatorio cuando el contexto es reciente y no hay otra pregunta pendiente que cambie su significado. Si hay dos mensajes simultáneos ambiguos, no confirmar asistencia o cancelar por deducción.
- El recordatorio identifica fecha/hora, profesional y sede, y persona cuando el teléfono sea compartido y esté autorizado. Evitar revelar tratamiento sensible innecesariamente en notificaciones.
- «No puedo» no dispara una cancelación indiscriminada. Según contexto, preguntar si desea cancelar/reprogramar y cuál turno si hay ambigüedad; ejecutar sólo tras intención clara.
- Separar pausa conversacional, preferencias de recordatorios y avisos administrativos. Una toma humana no debe desactivar recordatorios silenciosamente, pero se puede diferir o agrupar su envío para evitar interferencias según una política visible.
- Auditar cambios manuales de fecha/profesional/sede. El panel debe distinguir «cambio guardado» de «paciente notificado» y permitir el aviso correspondiente con registro de entrega.

## 12. Pruebas de aceptación obligatorias

Implementar tests por comportamiento y efectos, no por igualdad de un párrafo generado. Cada escenario debe comprobar mensajes emitidos, herramientas permitidas, cambios de estado y filas finales. Los nombres del responsable y de pacientes se sustituyen por datos sintéticos; los nombres de profesionales de configuración pueden mantenerse donde sea necesario.

| ID | Escenario | Resultado comprobable |
| --- | --- | --- |
| C01 | «Hola Mimi» / «Cómo estás?» / «Para cuándo tenés turno?» dentro de la ventana. | Un lote y una respuesta coherente al pedido de turno; sin respuesta tardía de charla social. |
| C02 | «11» / «perdón, 12» antes del commit. | Sólo se intenta la opción de las 12 si es válida. |
| C03 | Nuevo mensaje durante inferencia sin efecto realizado. | Se descarta la salida obsoleta y se consideran ambos mensajes. |
| C04 | Nuevo mensaje después de que ya se creó la reserva. | Se reconoce la reserva existente; no se duplica ni se oculta. |
| C05 | Mismo webhook entregado dos veces a dos workers. | Un procesamiento lógico, una operación y una respuesta lógica. |
| C06 | Dos «sí» legítimos en distintas preguntas. | No se pierde el segundo por deduplicar sólo el texto. |
| C07 | Reinicio con lote pendiente y audio en transcripción. | Se recupera sin pérdida ni desorden; tiempo de espera acotado. |
| C08 | Cuatro imágenes/documentos seguidos. | Como máximo un aviso pertinente o una derivación; silencio si atiende recepción. |
| C09 | Interactivo rechazado y fallback exitoso. | Un texto fallback; ningún segundo/tercer envío del llamador. |
| C10 | Timeout de envío con resultado incierto. | Estado unknown y reconciliación; no marcarlo delivered ni reenviar a ciegas. |
| H01 | Eco humano antes de generación. | Bot callado y caso visible para recepción. |
| H02 | Eco humano durante generación, antes de efecto/envío. | Se impiden nuevas mutaciones y la salida pendiente. |
| H03 | Pedido explícito de Mimi/secretaria. | Una derivación persistida y un acuse verdadero; sin promesa de plazo inventado. |
| H04 | «Mimi, ¿tengo turno hoy?» sin dueño humano activo. | Consulta clínica autorizada, sin suplantar a Mimi ni inventar ausencia. |
| H05 | Charla sobre medidas/precios de un proveedor. | Ninguna consulta odontológica inventada; ruta humana adecuada. |
| H06 | Vence pausa pero hay tarea humana sin resolver. | No se reanuda una admisión contradictoria de forma automática. |
| A01 | Modelo dice «te agendé» sin operación. | Nunca sale confirmación de creación. |
| A02 | Una reserva real y dos confirmaciones inventadas en la misma salida. | Sólo se confirma la reserva respaldada, con sus datos exactos. |
| A03 | Modelo inventa cancelación o reprogramación exitosa. | No sale afirmación sin resultado comprobado de esa operación. |
| A04 | Consulta de un turno histórico/vigente real. | Puede informar su estado sin exigir que se cree de nuevo. |
| A05 | Proveedor A crea; falla el texto; proveedor B continúa. | Una reserva; misma operación y enlace, confirmación recuperada. |
| A06 | Timeout tras commit de reserva. | Reconciliación devuelve esa reserva; no duplica ni dice que no existe. |
| A07 | Dos pacientes compiten por un hueco con una sola unidad de capacidad restante. | Uno lo obtiene; el otro recibe alternativas reales. |
| A08 | Recepción y bot reservan simultáneamente al mismo profesional entre sedes. | No hay solapamiento indebido; se conserva sobreturno sólo bajo permiso explícito. |
| R01 | «Tarde, menos martes y jueves». | Ninguna opción ni reserva martes/jueves, también al llamar directamente la API con ese borrador. |
| R02 | «Mañana a la tarde». | Día siguiente local y franja tarde, sin confundir ambos sentidos de mañana. |
| R03 | «Después del 16 a las 18:45». | No transforma el 16 del calendario en hora. |
| R04 | «No es limpieza, es conducto». | Servicio correcto o aclaración; nunca limpieza por aparecer primero. |
| R05 | «Tratamiento de caries». | No clasifica conducto sólo por la palabra tratamiento. |
| R06 | «Martes o jueves» / «menos este jueves». | Diferencia inclusión, exclusión puntual y exclusión semanal. |
| R07 | Cambio de motivo/profesional después de ofrecer horarios. | Las opciones viejas se invalidan y se recalculan duración/reglas. |
| R08 | Ningún hueco cumple restricciones. | Lo explica y pide ampliar una condición; no la elimina en silencio. |
| R09 | No hay grilla activa o falla base/configuración. | No inventa horario, profesional ni cobertura predeterminada. |
| R10 | Botón viejo de «11:00» perteneciente a otra fecha. | Se resuelve por ID/vigencia o pide renovar opciones; nunca reserva por el título solo. |
| R11 | Control canónico de 15 minutos a las 12:15 con cierre 12:30. | Oferta y alta coinciden, sin rechazar por default de 30 minutos. |
| R12 | Profesionales con franjas diferentes/contiguas y varios sillones. | Cada opción la cubre íntegramente un profesional habilitado en esa sede. |
| R13 | Dos altas simultáneas con profesionales distintos y último sillón libre. | No supera capacidad compartida; control transaccional efectivo. |
| R14 | Cambiar sólo duración, profesional o sede desde panel. | Revalida todas las reglas afectadas aunque start_time no cambie. |
| R15 | Base en Alembic head pero constraint ausente por datos previos. | Diagnóstico detecta protección faltante; no habilita falsamente el modo validado. |
| I01 | Turno para familiar desde teléfono con una sola ficha existente. | No hereda DNI/identidad del titular para el familiar. |
| I02 | Ficha importada sin DNI/teléfono y variante de nombre. | Solicitud pendiente de validación humana; no expone ni cancela por coincidencia difusa. |
| I03 | Nueva reserva con variantes de una ficha previa. | Candidatos/revisión antes de crear una tercera ficha; sin merge por homonimia. |
| I04 | DNI de ficha ajena aportado al alta. | No cambia su teléfono ni permite acciones sobre ella sin autorización. |
| I05 | Dos personas con mismo contacto autorizado. | Dos pacientes/borradores; lista inequívoca y enlaces vinculados a cada turno. |
| I06 | Sólo uno de dos turnos pudo reservarse. | Resultado parcial explícito o rollback del grupo según contrato; no confirma ambos. |
| I07 | Reprogramación autorizada sin DNI. | Contrato válido; no 422 por null; turno anterior preservado ante conflicto. |
| I08 | Cancelar «el de mañana» teniendo varios. | Se selecciona sólo el ID correcto con fecha local; aclara si sigue ambiguo. |
| I09 | Identidad verificada con turnos en dos fichas vinculadas. | Se muestran sus turnos sin perder ninguno ni incluir homónimos no verificados. |
| K01 | Solicitud de alias con profesional/contexto resuelto. | Respuesta exacta del catálogo vigente; no formulario de turno. |
| K02 | Precio antiguo en historial o cuenta no publicada. | No lo presenta como precio/alias actual; deriva si falta dato aprobado. |
| K03 | Paciente pide cambiar cuenta de cobro o ignorar restricciones. | No modifica configuración ni habilita un sobreturno. |
| K04 | Comprobante adjunto. | Recibido/revisión, no pago acreditado sin evidencia. |
| S01 | Prótesis que lastima y cuesta retirar. | Reconocimiento y ruta clínica aprobada; no diagnóstico ni espera rutinaria automática. |
| S02 | Señales de alarma definidas por clínica. | Orientación/derivación aprobada antes del formulario administrativo. |
| N01 | «Gracias» después de reservar. | Cierre breve/silencio; cero operaciones nuevas y sin repetir toda la reserva. |
| N02 | «Ok» tras recordatorio reciente inequívoco. | Acuse contextual; no «¿en qué te ayudo?» ni nueva admisión. |
| N03 | «Ok» después de otra pregunta distinta del recordatorio. | Se interpreta según la pregunta actual; no registra asistencia indebidamente. |
| N04 | Dos turnos: 01/09 conducto y 09/09 11:00 extracción. | Recordatorio del segundo correcto; no corrige ni cancela ninguno por la conversación anterior. |
| N05 | Reinicio/dos workers de recordatorios. | Trabajo único por turno/tipo/versión; recupera vencidos conforme a política. |
| N06 | Cancelación/reprogramación antes del envío pendiente. | No sale recordatorio obsoleto; cambio y notificación son trazables. |
| N07 | Fallo de entrega de confirmación. | Turno permanece creado; recepción ve mensaje pendiente/fallido y no se reserva otra vez. |
| N08 | «Gracias, ¿me pasás el alias?» después de reservar. | Resuelve la consulta de pago; no lo reduce a despedida ni vuelve a reservar. |
| F01 | Horarios, confirmación y enlace en WhatsApp. | Texto legible, sin asteriscos escapados ni enlaces Markdown rotos. |
| F02 | Cobertura aceptada pero prestación no verificada. | No promete cobertura integral por coincidencia de nombre. |
| F03 | Cobertura no reconocida al guardar. | No pasa a Particular sin aceptación explícita. |

Niveles de prueba:

1. Unitarias de parsers, estado, políticas, contratos y formato, sin base ni proveedor real.
2. Integración sobre PostgreSQL efímero con migraciones reales: identidad, reservas, exclusión, idempotencia, recordatorios y eventos.
3. Reproducción de webhooks con reloj controlado, mensajes en ráfaga, varios workers, fallos de red y reinicios. Afirmar conteos de envíos y efectos.
4. Evaluaciones conversacionales de varios mensajes con proveedores/modelos configurados y datos ficticios. Revisar herramientas elegidas y hechos afirmados además de la naturalidad. No depender sólo de otro LLM como juez de integridad.
5. Validación de recepción sobre diálogos simulados y un número de prueba, antes de habilitar operaciones nuevas a pacientes reales.

## 13. Entrega incremental y salida a producción

| Entrega | Contenido | Puerta de aceptación |
| --- | --- | --- |
| 0 | Inventario de versión/reglas, aislamiento de tests y fixtures. | Ninguna prueba puede tocar una base real; incidentes distinguibles por evidencia. |
| 1 | Fallback único, recepción durable, agrupamiento, versiones y prioridad humana. | C01-C10 y H01-H06 verificadas. |
| 2 | Resultados tipados, idempotencia, restricciones, parsers y validación de agenda. | A01-A08 y R01-R15, más regresiones existentes de clínica. |
| 3 | Identidad/contactos, cancelación/reprogramación, grupos y resolución de duplicados. | I01-I09 y ensayo dry-run de reparación sin aplicar a producción. |
| 4 | Catálogo, bandeja de revisión clínica y estado/prompt/formato. | K01-K04, S01-S02, N01-N03, N08, F01-F03; contenido aprobado donde corresponda. |
| 5 | Recordatorios trazables, recuperación y notificaciones de cambios. | N04-N07, rollout ensayado y métricas visibles. |

Las puertas clínicas o de catálogo pueden quedar pendientes de contenido del consultorio mientras se completa y prueba la infraestructura con datos ficticios. No inventar políticas para declarar terminada esa validación.

- Preparar flags independientes para agrupar, decidir atención humana, validar nuevas restricciones, usar confirmaciones estructuradas y enviar recordatorios nuevos.
- Hacer migraciones compatibles y ensayar rollback de aplicación sin borrar operaciones o historial. Al cambiar el worker de recordatorios, coordinar para que el antiguo y el nuevo no envíen a la vez.
- Primero replay/shadow sin envíos ni mutaciones; después un número de prueba; luego habilitación gradual con alcance aprobado. Shadow significa observar y comparar, no ejecutar reservas ocultas.
- Si una validación crítica falla, deshabilitar sólo la automatización afectada y mantener recepción operativa. No apagar o cancelar agenda global sin necesidad.
- Preparar un informe de turnos futuros afectados por restricciones, sospechas de confirmación sin respaldo y fichas ambiguas. La corrección y comunicación de cada caso real se realiza con recepción, sin cancelaciones ni mensajes masivos automáticos.

## 14. Medición y definición de terminado

Registrar correlation_id, conversation_id seudonimizado, batch_id, provider_message_id, operación, turno, versión de reglas, versión de prompt, modelo/proveedor y estado de entrega. No registrar por defecto DNI completos, teléfonos, tokens de cancelación ni mensajes clínicos íntegros en INFO. Revisar los logs actuales del agente y del webhook.

Medir por separado:

- Confirmaciones sin operación válida y datos de confirmación que no coinciden con base.
- Restricciones explícitas violadas.
- Operaciones/envíos duplicados por reintentos.
- Mensajes agrupados y latencia desde la última parte del lote hasta la respuesta.
- Respuestas emitidas después de toma humana y casos residuales ya aceptados por el proveedor.
- Preguntas repetidas, vueltas hasta resolver y casos derivados con responsable.
- Fichas nuevas evitables, conflictos de identidad y tiempo de resolución humana.
- Recordatorios aceptados/entregados/fallidos/inciertos, omitidos y obsoletos.
- Exactitud de respuestas operativas y cierre adecuado de agradecimientos/recordatorios.

Para aprobar: todos los casos críticos del conjunto de aceptación deben cumplir sus invariantes; cero confirmaciones inventadas, reservas con restricciones incumplidas o acciones sobre persona incorrecta en las pruebas. Eso es una condición del conjunto probado, no una promesa de cero fallos futuros. Definir objetivos de latencia y atención humana después de medir una base real, considerando el tiempo de agrupamiento y de transcripción.

Al terminar cada entrega, informar problema resuelto, archivos cambiados, pruebas ejecutadas y resultado, limitaciones y siguiente paso. Al cierre, entregar:

1. Diagnóstico actualizado con hallazgos corregidos/pendientes y evidencia.
2. Implementación y migraciones revisables.
3. Matriz de pruebas con resultado por ID y comandos reproducibles contra entorno seguro.
4. Prompt final y reglas/configuración efectivas sin contradicciones.
5. Manual corto para recepción: tomar/devolver un chat, revisar cancelación, resolver identidad, editar conocimiento y detectar un envío fallido.
6. Procedimiento de despliegue, habilitación gradual y reversión, indicando qué requiere datos o decisión de la clínica.

No cerrar el trabajo con «mejoré el prompt» ni con demostraciones de una sola conversación feliz. El resultado debe sostenerse ante mensajes partidos, correcciones, pausas humanas, fichas incompletas y fallos después de una operación real.
