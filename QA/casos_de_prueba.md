# Casos de Prueba - Bot Silprodent (WhatsApp)

Este documento detalla los casos de prueba (Test Cases) para validar el correcto funcionamiento del asistente virtual de Odontología (Silprodent). Cada caso incluye un ejemplo del diálogo exacto que se debe esperar.

---

## 1. Flujo de Agendamiento Básico (Happy Path)
**Objetivo:** Verificar que un paciente nuevo puede agendar un turno sin problemas.
- **Precondición:** El usuario no tiene turnos agendados previamente.

**Diálogo de Prueba:**
> **Paciente:** Hola
> **Bot:** ¡Hola! Soy DentiBot 🦷, el asistente virtual de Silprodent. Nuestro horario de atención es de Lunes a Viernes de 09:00 a 12:30 y de 17:00 a 20:30 (miércoles por la tarde cerrado). ¿En qué te puedo ayudar hoy?
> **Paciente:** Quiero agendar un turno
> **Bot:** ¡Claro! 😊 Para poder ayudarte, ¿podés decirme si la atención es particular o tenés alguna obra social? Si es una obra social, también necesito saber cuál es.
> **Paciente:** Es particular
> **Bot:** ¡Perfecto! ¿Me podrías indicar cuál es el motivo de la consulta? (por ejemplo: limpieza, extracción, revisión, etc.)
> **Paciente:** Necesito una limpieza
> **Bot:** ¡Genial! Para las limpiezas te va a atender la Dra. Helena Murad. Tengo disponibilidad para este jueves a la mañana a las 09:00 o 10:00, y a la tarde a las 17:00. ¿Alguna de estas opciones te queda cómoda?
> **Paciente:** El jueves a las 17
> **Bot:** Excelente elección. Para poder confirmar la reserva en el sistema, necesito que me pases por favor tus datos completos: Nombre, Apellido, DNI y Teléfono.
> **Paciente:** Juan Perez, DNI 12345678, Tel 2604123456
> **Bot:** ¡Perfecto, Juan! He agendado tu turno para la limpieza con la Dra. Helena Murad el jueves a las 17:00 en la sede principal. ¡Te esperamos!

---

## 2. Validación de Obra Social y Restricciones (PAMI)
**Objetivo:** Verificar la restricción de que los pacientes de PAMI solo pueden atenderse los días viernes.
- **Precondición:** Hoy NO es viernes, y hay turnos libres en la semana.

**Diálogo de Prueba:**
> **Paciente:** Hola, necesito un turno
> **Bot:** ¡Hola! Soy DentiBot 🦷... ¡Claro! 😊 Para poder ayudarte, ¿podés decirme si la atención es particular o tenés alguna obra social?
> **Paciente:** Tengo PAMI
> **Bot:** Entendido. Por favor, indicame para qué sería la consulta (extracción, limpieza, prótesis, etc.).
> **Paciente:** Para una extracción
> **Bot:** Perfecto, para las extracciones te va a atender el Dr. Martin Silvestro. Te comento que por PAMI solo atendemos los días viernes. Tengo disponibilidad para el próximo viernes a las 09:00 o a las 10:30. ¿Te sirve alguna?
> **Paciente:** El viernes a las 9 está bien
> **Bot:** ¡Bárbaro! Para confirmar, por favor pasame tu Nombre, Apellido, DNI y Teléfono.
> **Paciente:** María Gomez, DNI 8765432, 2604112233
> **Bot:** ¡Listo María! Tu turno con el Dr. Silvestro para el viernes a las 09:00 ha sido confirmado.

---

## 3. Asignación de Profesional según Motivo de Consulta
**Objetivo:** Verificar que el bot asigne al especialista correcto obligatoriamente.
- **Precondición:** Existen profesionales con distintas especialidades configuradas.

**Diálogo de Prueba:**
> **Paciente:** Buenas, quiero un turno particular para ponerme brackets
> **Bot:** ¡Hola! Soy DentiBot 🦷... Entendido, como es para ortodoncia (brackets), la especialista que te va a atender es la Dra. Helena Murad. Déjame buscar turnos disponibles con ella... Tengo para ofrecerte el lunes a las 18:00 o el martes a las 10:00. ¿Cuál preferís?
> **Paciente:** El lunes a las 18 hs
> **Bot:** Perfecto. Por favor pasame tu Nombre, Apellido, DNI y número de celular para terminar de agendar el turno.

---

## 4. Prevención de Doble Reserva (Double-Booking)
**Objetivo:** Garantizar que no se asigne el mismo turno a dos personas diferentes si uno lo gana primero.
- **Precondición:** Dos usuarios distintos intentan pedir el mismo turno al mismo tiempo.

**Diálogo de Prueba (Usuario B):**
> **Paciente B:** Me sirve el jueves a las 15:00
> **Bot:** Excelente opción. Para confirmar la reserva, por favor decime tu Nombre, Apellido, DNI y Teléfono.
*(Nota: En este lapso, el Usuario A confirma el turno de las 15:00 en su propio chat)*
> **Paciente B:** Carlos Lopez, DNI 22334455, 2604998877
> **Bot:** Uy, Carlos, te pido mil disculpas pero mientras me pasabas los datos el turno del jueves a las 15:00 acaba de ser ocupado. ¿Te gustaría que te ofrezca otro horario el mismo jueves a las 16:00 o el viernes a la mañana?

---

## 5. Cancelación de Turno (Validación de DNI)
**Objetivo:** Verificar el flujo de cancelación exigiendo la validación de identidad.
- **Precondición:** El usuario tiene un turno agendado.

**Diálogo de Prueba:**
> **Paciente:** Hola, no voy a poder ir a mi turno, quiero cancelar
> **Bot:** ¡Hola! Lamento escuchar que no podés asistir. Para poder buscar tus turnos y cancelarlo, necesito que me digas tu número de DNI por favor.
> **Paciente:** 11223344
*(Asumiendo que el DNI es incorrecto)*
> **Bot:** No encontré ningún turno asociado a ese DNI. ¿Podrías verificarlo y decírmelo nuevamente?
> **Paciente:** ah perdón, 12345678
> **Bot:** ¡Gracias! Veo que tenés un turno agendado para limpieza con la Dra. Murad el jueves a las 17:00. ¿Es este el turno que deseás cancelar?
> **Paciente:** Sí, ese mismo
> **Bot:** ¡Listo! El turno ha sido cancelado exitosamente. Si más adelante querés reprogramarlo, no dudes en escribirme.

---

## 6. Sincronización de Zona Horaria (Hora Argentina)
**Objetivo:** Verificar que el bot entiende términos de tiempo relativos basados en la hora actual de Argentina.
- **Precondición:** Realizar la prueba cerca de la medianoche (ej. 23:30 ART).

**Diálogo de Prueba:**
> **Paciente:** Hola, necesito un turno urgente para mañana a la mañana
> **Bot:** ¡Hola! Soy DentiBot 🦷... Para poder buscar disponibilidad para mañana, necesito saber si es por obra social o particular, y cuál es el motivo de la urgencia.
> **Paciente:** Particular, me duele una muela y quiero extraerla
> **Bot:** Entendido. Para extracciones te atiende el Dr. Silvestro. Déjame revisar la agenda de mañana [Bot revisa el día siguiente a la fecha de hoy real]... Tengo un turno mañana mismo a las 09:30. ¿Te sirve?
> **Paciente:** Si!
> **Bot:** Perfecto, pasame tu Nombre, Apellido, DNI y Teléfono y te lo confirmo ya mismo.

---

## 7. Manejo de Interrupciones y Fuera de Contexto
**Objetivo:** Probar la resiliencia del bot ante entradas inesperadas sin perder el hilo.

**Diálogo de Prueba:**
> **Paciente:** Hola, quiero un turno
> **Bot:** ¡Hola! Soy DentiBot 🦷... ¿Podés decirme si la atención es particular o tenés alguna obra social?
> **Paciente:** ¿Qué clima hace hoy?
> **Bot:** Jaja, ¡no soy muy bueno prediciendo el clima! Soy DentiBot, el asistente dental virtual de Silprodent 🦷. Volviendo a tu turno, ¿me podrías confirmar si te atendés de forma particular o con alguna obra social?

---

## 8. Persistencia y Recuperación de Contexto
**Objetivo:** Verificar que el bot "recuerde" al usuario si la conversación se pausa largo tiempo.

**Diálogo de Prueba:**
> **Paciente:** Hola
> **Bot:** ¡Hola! Soy DentiBot 🦷... ¿En qué te puedo ayudar hoy?
> **Paciente:** Quiero un turno por obra social, tengo OSDE.
> **Bot:** ¡Perfecto! ¿Me podrías indicar cuál es el motivo de la consulta?
*(El usuario deja el celular y no responde por 3 horas)*
> **Paciente:** Perdón, estaba ocupado. Es para un tratamiento de conducto.
> **Bot:** ¡No hay problema! Entendido, tenés OSDE y es para un tratamiento de conducto. Para esto te va a atender la Dra. Helena Murad. Te ofrezco los siguientes horarios disponibles...
