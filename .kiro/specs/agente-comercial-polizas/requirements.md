# Requirements Document

## Introduction

Este documento describe los requisitos funcionales y no funcionales del **Agente Comercial IA para la Renovación de Pólizas de Mantenimiento** de CIME Power Systems. El agente automatiza el ciclo completo de seguimiento comercial de renovaciones: detección de pólizas próximas a vencer o vencidas, contacto con el cliente, seguimiento basado en reglas comerciales aprobadas, recepción del comprobante de pago y notificación a tesorería, todo sobre la plataforma Amazon Bedrock AgentCore con un agente único y múltiples herramientas.

**Problema que resuelve:** De las ~30 pólizas gestionadas mensualmente, solo el 20% (~6) se renuevan. Las 24 pólizas restantes no se renuevan principalmente por falta de contacto oportuno y persistente, representando hasta $7,200,000 MXN anuales en revenue no capturado.

**Canal del MVP:** Correo electrónico. WhatsApp Business es el canal de producción posterior.

---

## Glossary

- **Agente**: El Agente Comercial IA implementado sobre Amazon Bedrock AgentCore Runtime que ejecuta el flujo de renovación.
- **AgentCore**: Plataforma Amazon Bedrock AgentCore que provee Runtime, Gateway, Memory, Observability, Policy e Identity para la ejecución del agente.
- **Gateway**: Componente AgentCore Gateway que expone las herramientas externas como targets MCP al agente.
- **Memory**: Componente AgentCore Memory que mantiene contexto conversacional de corto plazo (sesión activa) y de largo plazo (historial por cliente).
- **Policy**: Componente AgentCore Policy que aplica guardrails determinísticos sobre las acciones del agente antes de ejecutar cada tool call.
- **Pipefy**: Plataforma de gestión de procesos que actúa como fuente operativa de datos de pólizas, clientes, fechas de vencimiento y estados de seguimiento.
- **Póliza**: Contrato de mantenimiento suscrito entre CIME Power Systems y un cliente, que tiene fecha de inicio, fecha de vencimiento, precio y equipo cubierto.
- **Cliente**: Empresa o persona que tiene una póliza de mantenimiento vigente o vencida con CIME Power Systems.
- **Zapier**: Plataforma de automatización que monitorea condiciones en Pipefy y activa al Agente mediante webhook cuando se detecta una póliza que requiere acción comercial.
- **Ventana_Comercial**: Período de tiempo previo al vencimiento de una póliza durante el cual el Agente inicia el proceso de renovación (configurable por CIME, valor inicial: 30 días antes del vencimiento).
- **Cotización**: Documento generado por el Agente con el precio de renovación de la póliza, vigencia, condiciones y datos de pago.
- **Comprobante**: Archivo o imagen enviado por el Cliente como evidencia del depósito bancario para la renovación de su póliza.
- **Tesorería**: Equipo interno de CIME Power Systems responsable de validar los comprobantes de pago recibidos.
- **Equipo_Comercial**: Equipo humano de CIME Power Systems que atiende los casos escalados por el Agente.
- **Tool**: Herramienta expuesta vía AgentCore Gateway que el Agente puede invocar para interactuar con sistemas externos.
- **Knowledge_Base**: Base de conocimiento implementada sobre Amazon Bedrock Knowledge Bases con S3 Vectors, que contiene reglas comerciales, catálogo de precios, mensajes aprobados y criterios de escalamiento.
- **Estado_Pipefy**: Estado del registro de seguimiento de una póliza dentro del tablero operativo de Pipefy.
- **Descuento_Pre_Vencimiento**: Descuento del 5% aplicable únicamente cuando el Cliente confirma interés de renovar antes de la fecha de vencimiento de su póliza.
- **Modelo_Fundacional**: Modelo de lenguaje de Amazon Bedrock (Claude Sonnet o Amazon Nova) utilizado por el Agente para razonamiento y generación de respuestas.

---

## Requirements

---

### Requisito 1: Activación del Agente por Detección de Póliza

**User Story:** Como responsable operativo de CIME, quiero que el Agente se active automáticamente cuando Zapier detecta una póliza dentro de la Ventana_Comercial o vencida, para que ninguna oportunidad de renovación quede sin atención por falta de contacto oportuno.

#### Criterios de Aceptación

1. WHEN Zapier envía un webhook al AgentCore con el payload de activación, THE Agente SHALL iniciar una sesión de seguimiento comercial para la póliza indicada.
2. WHEN el Agente recibe el payload de activación, THE Agente SHALL validar que los campos obligatorios estén presentes, no sean strings vacíos ni nulos, y tengan formato válido: identificador de póliza (no vacío), nombre del cliente (no vacío), correo electrónico del cliente (formato RFC 5321 válido), fecha de vencimiento (fecha calendario válida en formato ISO 8601), precio de renovación (valor numérico mayor a 0) y nombre del equipo cubierto (no vacío).
3. IF el payload de activación contiene uno o más campos ausentes, vacíos, nulos o con formato inválido, THEN THE Agente SHALL registrar el error en AgentCore Observability, actualizar el Estado_Pipefy a "No renovada / sin respuesta" con una nota que identifique los campos específicos que fallaron, y terminar la sesión sin enviar comunicación al Cliente.
4. WHEN el Agente valida correctamente el payload, THE Agente SHALL invocar la tool `consultar_pipefy` para obtener el Estado_Pipefy actual de la póliza antes de iniciar cualquier contacto.
5. IF la tool `consultar_pipefy` retorna error o no responde en un plazo máximo de 30 segundos, THEN THE Agente SHALL registrar el error en AgentCore Observability, terminar la sesión sin enviar comunicación al Cliente y sin modificar el Estado_Pipefy.
6. IF el Estado_Pipefy consultado indica que la póliza ya se encuentra en estado "Renovación confirmada" o "Escalado a humano", THEN THE Agente SHALL terminar la sesión sin ejecutar acciones adicionales y registrar el motivo en AgentCore Observability.
7. WHEN el Agente completa la verificación del Estado_Pipefy y confirma que no bloquea la sesión, THE Agente SHALL invocar la tool `actualizar_pipefy` para registrar el Estado_Pipefy como "Póliza detectada".

**Propiedades de Corrección (Property-Based Testing):**

- **Invariante de idempotencia de activación:** Para cualquier póliza con Estado_Pipefy "Renovación confirmada", activar el Agente con el mismo payload N veces no debe modificar el estado ni generar comunicaciones adicionales al Cliente. `f(activar_agente(póliza_confirmada)) = Estado_Pipefy_sin_cambio`
- **Propiedad de validación de campos:** Para todo payload con al menos un campo obligatorio ausente o vacío, el Agente SIEMPRE debe terminar sin enviar correo. El conjunto de payloads inválidos recibidos debe ser igual al conjunto de payloads que generan registro de error. `invalid_payloads == error_logged_payloads`

---

### Requisito 2: Contacto Inicial con el Cliente

**User Story:** Como equipo comercial de CIME, quiero que el Agente envíe automáticamente el correo de contacto inicial al Cliente cuando se detecta una póliza dentro de la Ventana_Comercial o vencida, para iniciar el proceso de renovación sin intervención manual.

#### Criterios de Aceptación

1. WHEN el Agente completa la validación del payload y verifica que el Estado_Pipefy no es ninguno de los estados bloqueantes ("Renovación confirmada", "Escalado a humano", "No renovada / sin respuesta", "En validación con tesorería"), THE Agente SHALL invocar la tool `enviar_correo` con un mensaje de contacto inicial personalizado que incluya: nombre del Cliente, nombre del equipo cubierto, fecha de vencimiento de la póliza y precio de renovación formateado con dos decimales y moneda MXN.
2. WHEN el Agente genera el contenido del correo de contacto inicial, THE Agente SHALL consultar la Knowledge_Base para obtener la plantilla aprobada por CIME correspondiente al contexto (pre-vencimiento o post-vencimiento).
3. WHILE la póliza se encuentra dentro de la Ventana_Comercial (antes de la fecha de vencimiento), THE Agente SHALL incluir en el mensaje de contacto inicial la mención del Descuento_Pre_Vencimiento del 5% disponible si el Cliente confirma antes de la fecha de vencimiento.
4. IF la póliza ya se encuentra vencida al momento del contacto inicial, THEN THE Agente SHALL omitir la mención del Descuento_Pre_Vencimiento y usar la plantilla de recuperación post-vencimiento de la Knowledge_Base.
5. WHEN el Agente invoca exitosamente la tool `enviar_correo`, THE Agente SHALL invocar la tool `actualizar_pipefy` para registrar el Estado_Pipefy como "Contacto inicial enviado" y guardar la fecha y hora del envío en formato UTC.
6. IF la tool `enviar_correo` retorna un error técnico (falla de conectividad, timeout de respuesta, error interno del servicio), THEN THE Agente SHALL registrar el error en AgentCore Observability, reintentar el envío una vez después de 60 segundos, y si el reintento falla, actualizar el Estado_Pipefy con nota de fallo técnico y escalar mediante la tool `escalar_humano`.
7. IF la tool `enviar_correo` retorna un rechazo por dirección de correo inválida, THEN THE Agente SHALL invocar inmediatamente la tool `escalar_humano` sin ejecutar reintento, registrar el error en AgentCore Observability y terminar la sesión sin enviar comunicación al Cliente.

**Propiedades de Corrección (Property-Based Testing):**

- **Propiedad de consistencia de contexto pre/post vencimiento:** Para cualquier póliza con fecha de vencimiento futura (pre-vencimiento), el correo generado SIEMPRE debe contener la cadena de descuento del 5%. Para cualquier póliza con fecha de vencimiento pasada (post-vencimiento), el correo generado NUNCA debe contener la cadena de descuento del 5%. Esta propiedad debe validarse con entradas de fechas generadas aleatoriamente en ambos rangos.
- **Invariante de trazabilidad:** Para cada invocación exitosa de `enviar_correo`, debe existir exactamente una entrada correspondiente en AgentCore Observability y exactamente un registro de actualización en Pipefy con el estado "Contacto inicial enviado". `count(correos_enviados) == count(observability_entries) == count(pipefy_updates)`

---

### Requisito 3: Seguimiento Comercial Multi-Etapa

**User Story:** Como equipo comercial de CIME, quiero que el Agente realice seguimiento persistente con el Cliente según reglas comerciales aprobadas, para maximizar la probabilidad de renovación sin intervención manual en cada paso.

#### Criterios de Aceptación

1. WHEN el Cliente responde al correo de contacto inicial con una expresión de interés observable (afirmación explícita de querer renovar, solicitud de información sobre el proceso de renovación, o pregunta sobre condiciones o precio), THE Agente SHALL invocar la tool `actualizar_pipefy` para registrar el Estado_Pipefy como "Cliente interesado".
2. WHEN el Estado_Pipefy ha sido actualizado a "Cliente interesado", THE Agente SHALL proceder a generar la cotización de renovación conforme al Requisito 4.
3. IF el Cliente responde al correo de contacto inicial con rechazo o falta de interés observable (negación explícita, indicación de que no desea renovar, falta de respuesta dentro del plazo de seguimiento, o respuesta no relacionada con la renovación) y IF la póliza se encuentra dentro de la Ventana_Comercial, THEN THE Agente SHALL consultar la Knowledge_Base para obtener la plantilla de oferta de Descuento_Pre_Vencimiento y enviar la oferta al Cliente mediante la tool `enviar_correo`.
4. IF la póliza se encuentra vencida y el Cliente responde con falta de interés, THEN THE Agente SHALL invocar la tool `escalar_humano` con el contexto completo de la interacción: historial de mensajes intercambiados, Estado_Pipefy actual, fecha de vencimiento de la póliza y motivo expresado de rechazo por el Cliente.
5. WHEN el Agente envía la oferta de Descuento_Pre_Vencimiento y el Cliente no responde en 48 horas contadas desde el timestamp de envío del correo, THE Agente SHALL enviar un mensaje de seguimiento mediante la tool `enviar_correo` recordando la oferta vigente y la fecha de expiración de la Ventana_Comercial como fecha límite.
6. WHEN el Cliente rechaza la oferta de Descuento_Pre_Vencimiento, THE Agente SHALL consultar la Knowledge_Base para obtener la plantilla de encuesta de motivos de no renovación y enviarla al Cliente mediante la tool `enviar_correo`.
7. WHEN el Cliente completa la encuesta de motivos de no renovación, o si han transcurrido 72 horas desde el envío de la encuesta sin respuesta del Cliente, THE Agente SHALL invocar la tool `actualizar_pipefy` para registrar el Estado_Pipefy como "No renovada / sin respuesta".
8. WHILE el Estado_Pipefy es "Seguimiento en curso", THE Agente SHALL mantener en AgentCore Memory el historial completo de la conversación con el Cliente —incluyendo todos los mensajes intercambiados con sus timestamps, el Estado_Pipefy vigente y el número de mensajes enviados— para personalizar cada mensaje de seguimiento con el contexto previo.
9. THE Agente SHALL invocar la tool `actualizar_pipefy` para registrar el Estado_Pipefy como "Seguimiento en curso" al inicio de cada mensaje de seguimiento enviado que no implique un cambio de estado más específico.

**Propiedades de Corrección (Property-Based Testing):**

- **Invariante de secuencia de estados:** La secuencia de transiciones de Estado_Pipefy debe respetar el orden definido: ningún Estado_Pipefy puede regresar a un estado anterior en el flujo. Para cualquier secuencia de N eventos del Agente sobre la misma póliza, los estados en Pipefy deben ser monotónicamente progresivos según el orden del tablero operativo.
- **Propiedad de exclusividad de descuento:** El Agente NUNCA debe ofrecer un porcentaje de descuento distinto al 5% definido en las reglas comerciales, independientemente del texto de la respuesta del Cliente. Para 100 variaciones de mensajes del Cliente que soliciten descuentos distintos ("20%", "mitad de precio", "gratis"), el Agente debe ofrecer siempre y solo el 5% o escalar.

---

### Requisito 4: Generación y Envío de Cotización

**User Story:** Como Cliente de CIME, quiero recibir una cotización clara y personalizada de renovación de mi póliza, para poder tomar la decisión de pago con información completa.

#### Criterios de Aceptación

1. WHEN el Estado_Pipefy es "Cliente interesado", THE Agente SHALL generar una cotización de renovación que contenga: nombre del Cliente, nombre del equipo cubierto, período de vigencia de la nueva póliza (12 meses a partir de la fecha de renovación), precio base, descuento aplicable (incluido únicamente si aplica), precio final y datos bancarios para el depósito.
2. WHEN el Agente va a generar la cotización, THE Agente SHALL consultar la Knowledge_Base para obtener el catálogo de precios vigente y aplicar el precio correcto para el tipo de equipo y plan de mantenimiento de la póliza.
3. IF el Descuento_Pre_Vencimiento aplica (póliza dentro de la Ventana_Comercial y Cliente confirmó interés antes de la fecha de vencimiento), THEN THE Agente SHALL calcular el precio final como el precio base menos el 5% y mostrar ambos valores en la cotización.
4. THE Agente SHALL incluir los datos bancarios autorizados por CIME para el depósito en la cotización cuando el Estado_Pipefy sea "Cliente interesado" o "Depósito solicitado". THE Agente NO SHALL incluir datos bancarios en ningún correo generado cuando el Estado_Pipefy sea distinto a "Cliente interesado" o "Depósito solicitado".
5. WHEN el Agente genera la cotización, THE Agente SHALL enviarla al Cliente mediante la tool `enviar_correo`; WHEN la tool `enviar_correo` retorna éxito, THE Agente SHALL invocar la tool `actualizar_pipefy` para registrar el Estado_Pipefy como "Depósito solicitado" y guardar el monto de la cotización enviada; IF la tool `actualizar_pipefy` retorna error, THE Agente SHALL reintentar una vez y, si el reintento falla, invocar la tool `escalar_humano`.
6. WHEN el Cliente solicita modificaciones en el alcance de la póliza, precio especial o condiciones no definidas en el catálogo de la Knowledge_Base, THE Agente SHALL invocar la tool `escalar_humano` con el detalle de la solicitud y registrar el Estado_Pipefy como "Escalado a humano".
7. IF el catálogo de la Knowledge_Base no contiene precio para el tipo de equipo de la póliza, THEN THE Agente SHALL detener la generación de la cotización e invocar la tool `escalar_humano` con el identificador de póliza y el tipo de equipo no encontrado.
8. IF la tool `enviar_correo` retorna error al intentar enviar la cotización, THEN THE Agente SHALL reintentar el envío una vez; si el reintento falla, THE Agente SHALL invocar la tool `escalar_humano` y NO SHALL actualizar el Estado_Pipefy a "Depósito solicitado" hasta confirmar la entrega exitosa del correo.

**Propiedades de Corrección (Property-Based Testing):**

- **Propiedad de cálculo de descuento (round-trip aritmético):** Para cualquier precio base `P` y Descuento_Pre_Vencimiento aplicable, el precio final calculado debe satisfacer `precio_final == P * 0.95` con precisión de dos decimales. Para 100 valores aleatorios de `P` en el rango de precios de pólizas, el cálculo debe ser exacto.
- **Invariante de datos bancarios:** Los datos bancarios SOLO deben aparecer en correos generados cuando el Estado_Pipefy de la póliza es "Cliente interesado" o "Depósito solicitado". Para cualquier Estado_Pipefy distinto, la cadena de datos bancarios no debe estar presente en el contenido del correo generado.
- **Propiedad de consistencia precio-catálogo:** Para cualquier combinación de tipo de equipo y plan de mantenimiento definida en el catálogo, el precio base en la cotización generada debe ser igual al precio en la Knowledge_Base. `cotizacion.precio_base == knowledge_base.precio(tipo_equipo, plan)`

---

### Requisito 5: Recepción y Procesamiento del Comprobante de Pago

**User Story:** Como Tesorería de CIME, quiero que el Agente reciba automáticamente el comprobante de pago enviado por el Cliente y me notifique con el detalle completo, para validar el depósito sin necesidad de buscar correos manualmente.

#### Criterios de Aceptación

1. WHEN el Cliente responde al correo de solicitud de depósito con un archivo adjunto en uno de los formatos aceptados (PDF, JPG, PNG o JPEG) con tamaño máximo de 10 MB, THE Agente SHALL registrar la recepción del comprobante y actualizar el Estado_Pipefy a "Comprobante recibido" mediante la tool `actualizar_pipefy`.
2. WHEN el Agente registra la recepción del comprobante, THE Agente SHALL enviar al Cliente una confirmación de recepción mediante la tool `enviar_correo` indicando que el comprobante fue recibido y que el equipo de Tesorería lo validará en un plazo de 24 horas hábiles.
3. WHEN el Agente confirma la recepción del comprobante al Cliente, THE Agente SHALL invocar la tool `notificar_tesoreria` con los datos completos: nombre del Cliente, número de póliza, monto de la cotización enviada, fecha y hora de recepción del comprobante y referencia al archivo adjunto.
4. WHEN la tool `notificar_tesoreria` retorna éxito, THE Agente SHALL actualizar el Estado_Pipefy a "En validación con tesorería" mediante la tool `actualizar_pipefy` en un plazo máximo de 5 segundos.
5. IF la tool `notificar_tesoreria` retorna un error técnico o no responde en 60 segundos, THEN THE Agente SHALL registrar el error en AgentCore Observability incluyendo el identificador del comprobante, reintentar la notificación una vez después de 60 segundos, y si el reintento falla, invocar la tool `escalar_humano` con el contexto del comprobante recibido para garantizar que Tesorería sea notificada.
6. IF el Cliente responde sin adjunto o con un archivo en formato no soportado (distinto de PDF, JPG, PNG, JPEG) o que excede los 10 MB, THEN THE Agente SHALL enviar un correo al Cliente solicitando el reenvío del comprobante e indicando los formatos aceptados y el tamaño máximo permitido.
7. THE Agente NO SHALL realizar ninguna validación bancaria sobre el comprobante recibido, ni determinar si el monto depositado es correcto — esta responsabilidad es exclusiva de Tesorería.

**Propiedades de Corrección (Property-Based Testing):**

- **Invariante de notificación obligatoria:** Para cada comprobante recibido (N comprobantes), la tool `notificar_tesoreria` debe haber sido invocada exactamente N veces (una por comprobante) o, en caso de fallo técnico confirmado, la tool `escalar_humano` debe haberse invocado. `count(comprobantes_recibidos) == count(notificaciones_tesoreria) + count(escalamientos_por_fallo_notificacion)`
- **Propiedad de secuencia de confirmaciones:** La confirmación al Cliente siempre debe preceder en el tiempo a la notificación a Tesorería. Para cualquier evento de recepción de comprobante, `timestamp(confirmacion_cliente) < timestamp(notificacion_tesoreria)`.

---

### Requisito 6: Escalamiento a Intervención Humana

**User Story:** Como equipo comercial de CIME, quiero que el Agente escale automáticamente los casos que requieren negociación, atención técnica o decisiones fuera de su alcance, para que ningún cliente quede sin respuesta en situaciones complejas.

#### Criterios de Aceptación

1. WHEN el Cliente solicita explícitamente hablar con un asesor o una persona humana, THE Agente SHALL invocar la tool `escalar_humano` de forma inmediata en el mismo turno de conversación donde el Cliente realiza la solicitud, sin intentar retener al Cliente.
2. WHEN el Agente ha invocado exitosamente la tool `escalar_humano` por solicitud del Cliente de hablar con un asesor, THE Agente SHALL confirmar al Cliente por correo que un asesor lo contactará en un plazo máximo de 24 horas hábiles.
3. WHEN el Cliente expresa requerimientos de negociación especial (descuentos distintos al 5%, condiciones de pago diferidas, extensiones de cobertura), THE Agente SHALL invocar la tool `escalar_humano` con el detalle de la solicitud, registrar el Estado_Pipefy como "Escalado a humano" y confirmar al Cliente que un asesor lo contactará en un plazo máximo de 24 horas hábiles.
4. WHEN el Cliente solicita información de facturación, datos fiscales, condiciones administrativas especiales o modificaciones al alcance técnico de la póliza, THE Agente SHALL invocar la tool `escalar_humano` con el contexto de la solicitud y registrar el Estado_Pipefy como "Escalado a humano".
5. WHEN el Cliente expresa inconformidad, rechazo explícito, queja o solicita atención personalizada, THE Agente SHALL invocar la tool `escalar_humano` con los siguientes campos observables: resumen de la interacción (texto de los últimos mensajes relevantes), Estado_Pipefy actual y tipo de inconformidad expresada por el Cliente, y registrar el Estado_Pipefy como "Escalado a humano".
6. WHEN el Cliente expresa una duda técnica sobre el funcionamiento, mantenimiento o diagnóstico del equipo cubierto que no está respondida en la Knowledge_Base, THE Agente SHALL invocar la tool `escalar_humano` con el resumen de la duda y registrar el Estado_Pipefy como "Escalado a humano".
7. IF existe cualquier discrepancia entre los datos del payload de activación y los datos obtenidos de la tool `consultar_pipefy` en los campos precio, nombre del Cliente o fecha de vencimiento, THEN THE Agente SHALL invocar la tool `escalar_humano` con el detalle de la discrepancia y NO enviar ninguna comunicación al Cliente hasta que el Equipo_Comercial resuelva la inconsistencia.
8. IF AgentCore Memory no está disponible al momento del escalamiento, THEN THE Agente SHALL incluir en el payload de la tool `escalar_humano` todos los datos del payload de activación original más todos los mensajes disponibles en la sesión actual.
9. THE Agente SHALL incluir en cada invocación de la tool `escalar_humano` el historial completo de la conversación con el Cliente recuperado de AgentCore Memory, el Estado_Pipefy actual y el motivo específico del escalamiento.

**Propiedades de Corrección (Property-Based Testing):**

- **Propiedad de escalamiento por inconsistencia de datos:** Para cualquier par (payload_activacion, datos_pipefy) donde exista al menos un campo que difiera en más de un umbral permitido (ej: precio difiere más del 1%, nombre de cliente difiere, fecha de vencimiento difiere), el Agente debe SIEMPRE escalar y NUNCA enviar correo al Cliente. Esta propiedad debe validarse con 100 pares generados aleatoriamente con discrepancias en distintos campos.
- **Invariante de contexto en escalamiento:** Para cada invocación de `escalar_humano`, el payload debe contener los campos: historial_conversacion (no vacío si hubo interacción previa), estado_pipefy_actual, motivo_escalamiento. `ALL escalamientos: len(payload.historial) >= 0 AND payload.motivo_escalamiento != ""`

---

### Requisito 7: Actualización de Estados en Pipefy

**User Story:** Como responsable operativo de CIME, quiero que el tablero de Pipefy refleje en todo momento el estado real del proceso de renovación de cada póliza, para supervisar el avance del Agente sin necesidad de revisar logs técnicos.

#### Criterios de Aceptación

1. WHEN el Agente ejecuta una transición de Estado_Pipefy, THE Agente SHALL invocar la tool `actualizar_pipefy` utilizando exactamente los nombres de estado definidos en el Glosario de este documento.
2. WHEN el Agente actualiza un Estado_Pipefy, THE Agente SHALL incluir en el registro de Pipefy: el nuevo estado, la fecha y hora de la transición (UTC), el identificador de sesión de AgentCore y una descripción breve de la acción que generó el cambio (máximo 200 caracteres).
3. WHEN el Agente va a invocar la tool `actualizar_pipefy`, THE Agente SHALL invocar primero la tool `consultar_pipefy` para verificar que el estado actual no sea incompatible con la transición que se intenta registrar; IF el Estado_Pipefy actual en Pipefy es incompatible con la transición intentada, THEN THE Agente SHALL registrar el conflicto en AgentCore Observability y escalar mediante la tool `escalar_humano` sin ejecutar la actualización.
4. IF la tool `actualizar_pipefy` retorna un error técnico, THEN THE Agente SHALL registrar el error en AgentCore Observability con todos los datos de la transición intentada, reintentar la actualización con un backoff de 30 segundos entre reintentos hasta un máximo de 2 reintentos; si ambos reintentos fallan, THE Agente SHALL invocar la tool `escalar_humano` y continuar el flujo de la conversación con el Cliente para no interrumpir la experiencia.
5. THE Agente SHALL mantener en AgentCore Memory el último Estado_Pipefy registrado exitosamente para cada sesión activa, de modo que los fallos transitorios de actualización no pierdan el contexto del flujo.

**Propiedades de Corrección (Property-Based Testing):**

- **Invariante de estados válidos:** Para cualquier secuencia de eventos generada en el flujo de renovación, los estados registrados en Pipefy deben ser exclusivamente alguno de los 10 estados definidos en el tablero operativo. Ninguna secuencia de N eventos debe producir un estado fuera del conjunto definido.
- **Propiedad de consistencia Memory-Pipefy:** El Estado_Pipefy almacenado en AgentCore Memory debe ser siempre igual al último estado registrado exitosamente en Pipefy. `memory.ultimo_estado == pipefy.estado_actual` para cualquier número de transiciones ejecutadas.

---

### Requisito 8: Gestión de Memoria Conversacional

**User Story:** Como Cliente de CIME, quiero que el Agente recuerde el contexto de nuestras conversaciones previas, para no tener que repetir información en cada contacto y recibir una atención personalizada.

#### Criterios de Aceptación

1. WHILE el Agente tiene una sesión de seguimiento activa con un Cliente, THE Agente SHALL mantener en AgentCore Memory de corto plazo el contexto completo de esa sesión, incluyendo todos los mensajes intercambiados, el Estado_Pipefy vigente y los datos del comprobante confirmado si aplica.
2. WHEN el Agente inicia una nueva sesión de seguimiento para un Cliente que tiene historial de interacciones previas registradas en AgentCore Memory de largo plazo, THE Agente SHALL recuperar ese historial en un plazo máximo de 5 segundos y utilizarlo para personalizar el primer mensaje de la nueva sesión, referenciando al menos el último Estado_Pipefy registrado y la respuesta previa del Cliente.
3. WHEN una sesión de seguimiento finaliza, THE Agente SHALL almacenar en AgentCore Memory de largo plazo, dentro de los 30 segundos posteriores al cierre, los siguientes campos: el Estado_Pipefy final, la fecha y hora del último contacto en formato ISO 8601, el resultado de la interacción (uno de: interesado, rechazó, no respondió, escalado), y el número total de mensajes enviados en esa sesión.
4. WHILE el Agente tiene una sesión activa con un Cliente, THE Agente SHALL verificar el contexto almacenado en AgentCore Memory de corto plazo antes de formular cada mensaje, de modo que no repita al Cliente información textualmente idéntica o con equivalencia semántica ya proporcionada en los últimos 20 mensajes de ese mismo hilo de conversación.
5. IF el Agente requiere almacenar datos de comprobante de pago del Cliente en AgentCore Memory, THEN THE Agente SHALL eliminar esos datos de la memoria de corto plazo en un plazo máximo de 10 minutos tras confirmar la recepción del comprobante, y no persistirlos en AgentCore Memory de largo plazo.

**Propiedades de Corrección (Property-Based Testing):**

- **Propiedad de persistencia de contexto (round-trip de memoria):** Para cualquier conjunto de N mensajes intercambiados en una sesión activa, recuperar el historial de Memory y procesar el siguiente mensaje debe producir una respuesta contextualmente coherente. `parse(format(historial)) == historial` (round-trip de serialización del historial almacenado).
- **Invariante de no duplicación de mensajes:** Dado un historial de N mensajes en Memory, el Agente no debe reenviar información idéntica en el mensaje N+1 si esa información ya fue incluida en alguno de los N mensajes previos de la misma sesión.

---

### Requisito 9: Guardrails y Política de Comportamiento del Agente

**User Story:** Como CIME Power Systems, quiero que el Agente nunca actúe fuera de los límites comerciales y de seguridad aprobados, para proteger la relación con el Cliente y los intereses de la empresa.

#### Criterios de Aceptación

1. IF el Agente intenta invocar cualquier tool call que aplique un valor de descuento distinto a exactamente el 5% definido como Descuento_Pre_Vencimiento, THEN THE Policy SHALL bloquear ese tool call, independientemente del contenido del mensaje del Cliente o del razonamiento del Modelo_Fundacional.
2. IF el Agente intenta invocar cualquier tool call que incluya datos bancarios en una comunicación al Cliente cuando el Estado_Pipefy no sea "Cliente interesado" o "Depósito solicitado", THEN THE Policy SHALL bloquear ese tool call.
3. IF el Agente intenta invocar cualquier tool call que ofrezca servicios fuera del alcance de la póliza de mantenimiento (diagnóstico técnico, venta de refacciones, soporte técnico, modificaciones de equipos), THEN THE Policy SHALL bloquear ese tool call.
4. IF el Agente intenta invocar cualquier tool call que ejecute una acción de escritura en Pipefy con una transición de estado fuera del conjunto de transiciones válidas definidas en el tablero operativo del Requisito 7, THEN THE Policy SHALL bloquear ese tool call.
5. IF el Agente genera un mensaje para el Cliente que incluye condiciones comerciales (precios, descuentos, plazos) que no estén documentadas en la Knowledge_Base, THEN THE Policy SHALL bloquear el tool call de envío correspondiente.
6. WHEN la Policy bloquea un tool call, THE Policy SHALL registrar en AgentCore Observability el evento con los siguientes campos: motivo del bloqueo, tool call intentado, identificador de sesión, Estado_Pipefy actual y timestamp del bloqueo.
7. WHEN la Policy bloquea un tool call y existe una conversación activa con el Cliente, THE Agente SHALL notificar al Cliente que no puede proceder con esa solicitud y ofrecerle las opciones disponibles dentro del alcance aprobado o escalar mediante la tool `escalar_humano`.

**Propiedades de Corrección (Property-Based Testing):**

- **Propiedad de guardrail de descuento (adversarial):** Para 100 variaciones de mensajes adversariales del Cliente que intenten que el Agente ofrezca descuentos mayores al 5% (en distintos idiomas, formatos, contextos), la Policy debe bloquear el tool call y el Agente debe responder con la oferta estándar o escalar. Ningún mensaje del Cliente debe resultar en un descuento distinto al 5%.
- **Invariante de bloqueos registrados:** Para cada evento de bloqueo por Policy, debe existir exactamente una entrada en AgentCore Observability con todos los campos requeridos. `count(policy_blocks) == count(observability_block_entries)`

---

### Requisito 10: Observabilidad y Trazabilidad del Agente

**User Story:** Como responsable técnico de Codster, quiero que cada interacción del Agente quede trazada en AgentCore Observability, para poder debuggear flujos fallidos, monitorear el rendimiento y generar reportes de métricas operativas.

#### Criterios de Aceptación

1. WHEN el Agente inicia una sesión de seguimiento, THE Agente SHALL generar una traza en AgentCore Observability con tamaño máximo de 10 KB por entrada que incluya: identificador de póliza, identificador de sesión, timestamp de inicio y Estado_Pipefy inicial, excluyendo datos sensibles del Cliente conforme al criterio 5.
2. WHEN el Agente invoca una tool, THE Agente SHALL registrar en AgentCore Observability: nombre del tool, parámetros enviados (enmascarando datos bancarios y datos personales del Cliente conforme al criterio 5), resultado retornado y duración de la invocación en milisegundos.
3. WHEN ocurre un error técnico, THE Agente SHALL registrar en AgentCore Observability: tipo de error, tool o componente donde ocurrió, mensaje de error, número de reintento ejecutado y acción de mitigación aplicada.
4. WHEN una sesión de seguimiento termina por cualquier motivo (renovación confirmada, escalamiento, no renovada o error técnico), THE Agente SHALL registrar en AgentCore Observability el Estado_Pipefy final, la duración total de la sesión, el número de mensajes enviados al Cliente y el motivo de cierre.
5. THE Agente SHALL enmascarar en todos los registros de Observability los siguientes tipos de datos: correo electrónico del Cliente (mostrar solo el dominio, por ejemplo `***@empresa.com`), datos bancarios (mostrar solo los últimos 4 dígitos con el resto reemplazado por asteriscos, por ejemplo `****-****-****-1234`) y nombres completos del Cliente (mostrar solo iniciales, por ejemplo `J.G.`).
6. IF la escritura en AgentCore Observability falla, THEN THE Agente SHALL continuar el flujo principal sin interrupciones y registrar el fallo de observabilidad en un log de fallback interno.

**Propiedades de Corrección (Property-Based Testing):**

- **Invariante de completitud de traza:** Para cualquier sesión completada (independientemente del Estado_Pipefy final), debe existir exactamente una traza de inicio de sesión y exactamente una traza de cierre de sesión en Observability. `count(trazas_inicio) == count(trazas_cierre) == count(sesiones)`
- **Propiedad de enmascaramiento de datos sensibles:** Para cualquier registro generado en Observability, la expresión regular de detección de correos electrónicos completos (`[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`) no debe encontrar coincidencias en los campos de parámetros y resultados de tools. Esta propiedad debe validarse con 100 registros generados aleatoriamente con distintos datos de Cliente.

---

### Requisito 11: Integración con Amazon Bedrock Knowledge Base

**User Story:** Como equipo de CIME, quiero que el Agente consulte únicamente información autorizada y actualizada de la base de conocimiento, para garantizar que los mensajes, precios y reglas comerciales que comunica al Cliente sean siempre correctos y aprobados.

#### Criterios de Aceptación

1. WHEN el Agente necesita formular una respuesta al Cliente o ejecutar una acción basada en reglas comerciales, THE Agente SHALL consultar la Knowledge_Base implementada sobre Amazon Bedrock Knowledge Bases con S3 Vectors para obtener: plantillas de mensajes aprobadas, catálogo de precios vigente, reglas comerciales y criterios de escalamiento, recuperando un máximo de 5 resultados ordenados por score descendente.
2. IF ningún resultado de la consulta a la Knowledge_Base tiene score mayor o igual a 0.7, THEN THE Agente SHALL invocar la tool `escalar_humano` en lugar de generar una respuesta basada únicamente en el razonamiento del Modelo_Fundacional.
3. THE Agente SHALL usar exclusivamente Amazon Bedrock Knowledge Bases con S3 Vectors como vector store para la Knowledge_Base — NO se debe utilizar Amazon OpenSearch Service ni Amazon Aurora como vector store, para mantener los costos de operación dentro del presupuesto del proyecto.
4. WHEN el proceso de sincronización de embeddings en S3 Vectors completa exitosamente tras una actualización de documentos en S3, THE Knowledge_Base SHALL retornar contenido actualizado con score mayor o igual a 0.7 al consultar con los términos clave del documento actualizado.
5. WHEN el Agente ejecuta una consulta a la Knowledge_Base, THE Agente SHALL registrar en AgentCore Observability: la query utilizada, el número de resultados retornados y el score de relevancia del resultado más alto, expresado en el rango de 0.0 a 1.0.

**Propiedades de Corrección (Property-Based Testing):**

- **Propiedad de cobertura de catálogo:** Para cada tipo de equipo y plan de mantenimiento definido en el catálogo de precios cargado en S3, la Knowledge_Base debe retornar al menos un resultado con score de relevancia mayor a 0.7 cuando se consulta con el nombre exacto del equipo y plan. `ALL (equipo, plan) in catalogo: knowledge_base.query(equipo + plan).top_score >= 0.7`
- **Propiedad de round-trip de documentos:** Para cualquier documento de plantilla de mensajes o regla comercial cargado en S3 y sincronizado en la Knowledge_Base, una consulta con los términos clave del documento debe retornar ese documento como resultado relevante. `parse(format(documento)) == documento` (el documento recuperado debe ser semánticamente equivalente al cargado).

---

### Requisito 12: Configuración y Despliegue del Agente en AgentCore

**User Story:** Como responsable técnico de Codster, quiero que el Agente esté desplegado sobre Amazon Bedrock AgentCore Runtime con todos los componentes correctamente configurados, para tener un entorno serverless seguro, escalable y sin gestión de infraestructura.

#### Criterios de Aceptación

1. THE Agente SHALL ejecutarse sobre Amazon Bedrock AgentCore Runtime en la región AWS us-east-1 o us-west-2 (según disponibilidad de AgentCore).
2. THE AgentCore Gateway SHALL exponer las cinco tools del Agente como targets MCP: `consultar_pipefy`, `actualizar_pipefy`, `enviar_correo`, `notificar_tesoreria` y `escalar_humano`; cada tool call SHALL incluir un token de autorización válido emitido por AgentCore Identity antes de ejecutarse.
3. THE AgentCore Identity SHALL gestionar las credenciales de acceso a Pipefy API, al servicio de correo electrónico y al endpoint de notificación de tesorería; ningún valor de credencial SHALL aparecer en el system prompt, en el historial de conversación ni en el payload de respuesta de ninguna tool.
4. THE Agente SHALL ser implementado usando el framework Strands Agents (nativo AWS) o LangGraph, según la evaluación técnica del equipo de Codster al inicio del Día de Prototipado Intensivo.
5. THE Agente SHALL utilizar Amazon Bedrock con Claude Sonnet o Amazon Nova como Modelo_Fundacional, según disponibilidad y evaluación de costo-rendimiento en la región de despliegue.
6. IF el AgentCore Runtime detecta un cold start en la invocación del Agente, THEN THE Agente SHALL emitir el primer token de respuesta al webhook de Zapier en un tiempo total menor a 30 segundos medido desde la recepción del webhook.
7. WHILE el Agente tiene N sesiones concurrentes activas, THE Agente SHALL aislar el contexto de AgentCore Memory de cada sesión de modo que ningún mensaje, dato de póliza ni dato de Cliente de la sesión A sea accesible desde la sesión B.
8. IF una tool es invocada con credenciales correspondientes a una tool diferente, THEN AgentCore Identity SHALL rechazar la invocación retornando un error de autorización y la tool NO SHALL ejecutarse.

**Propiedades de Corrección (Property-Based Testing):**

- **Invariante de aislamiento de sesión:** Para N invocaciones concurrentes del Agente (distintas pólizas, distintos Clientes), el contexto de Memory de la sesión A no debe ser accesible ni modificable por la sesión B. Para cualquier par de sesiones concurrentes generadas con datos distintos, los historiales de conversación deben ser mutuamente independientes.
- **Propiedad de autenticación de tools:** Para cada invocación de tool, AgentCore Identity debe proveer las credenciales correspondientes. Una invocación de tool con credenciales de otra tool debe ser rechazada. `tool_X.credenciales != tool_Y.credenciales` para cualquier par de tools distintas.

---

## Resumen de Propiedades de Corrección por Requisito

| Requisito | Tipo de Propiedad | Categoría PBT |
|-----------|-------------------|---------------|
| R1: Activación | Idempotencia de activación | Idempotencia |
| R1: Activación | Validación de campos | Error Conditions |
| R2: Contacto Inicial | Consistencia pre/post vencimiento | Metamórfica |
| R2: Contacto Inicial | Trazabilidad de envíos | Invariante |
| R3: Seguimiento | Secuencia monotónica de estados | Invariante |
| R3: Seguimiento | Exclusividad de descuento | Error Conditions (adversarial) |
| R4: Cotización | Cálculo de descuento 5% | Round-trip aritmético |
| R4: Cotización | Datos bancarios por estado | Invariante |
| R4: Cotización | Consistencia precio-catálogo | Model-Based Testing |
| R5: Comprobante | Notificación obligatoria | Invariante |
| R5: Comprobante | Secuencia de confirmaciones | Invariante de orden |
| R6: Escalamiento | Escalamiento por inconsistencia | Error Conditions |
| R6: Escalamiento | Contexto en escalamiento | Invariante |
| R7: Estados Pipefy | Estados dentro del conjunto válido | Invariante |
| R7: Estados Pipefy | Consistencia Memory-Pipefy | Invariante |
| R8: Memoria | Round-trip de serialización | Round-trip |
| R8: Memoria | No duplicación de mensajes | Idempotencia |
| R9: Guardrails | Guardrail de descuento adversarial | Error Conditions (adversarial) |
| R9: Guardrails | Bloqueos registrados | Invariante |
| R10: Observabilidad | Completitud de traza | Invariante |
| R10: Observabilidad | Enmascaramiento de datos sensibles | Invariante de seguridad |
| R11: Knowledge Base | Cobertura de catálogo | Model-Based Testing |
| R11: Knowledge Base | Round-trip de documentos | Round-trip |
| R12: Despliegue | Aislamiento de sesión | Invariante de aislamiento |
| R12: Despliegue | Autenticación de tools | Invariante de seguridad |

---

## Criterios de Éxito del MVP

| Criterio | Verificación |
|----------|--------------|
| El Agente recibe el webhook de Zapier y valida el payload | Traza en AgentCore Observability con sesión iniciada |
| El Agente envía el correo de contacto inicial con contenido correcto | Correo recibido con datos personalizados de la póliza |
| El flujo de interés → cotización → solicitud de depósito funciona sin intervención manual | El Estado_Pipefy avanza de "Contacto inicial enviado" a "Depósito solicitado" automáticamente |
| El Agente recibe el comprobante y notifica a Tesorería | Tesorería recibe notificación automática con datos del pago |
| El Agente actualiza el Estado_Pipefy en tiempo real | El tablero de Pipefy refleja el avance del flujo |
| Los escalamientos se derivan correctamente al Equipo_Comercial | Los casos de negociación especial generan notificación al equipo |
| Los guardrails bloquean descuentos no autorizados | Mensajes adversariales no producen descuentos distintos al 5% |
| La observabilidad permite trazar cada interacción | AgentCore Observability muestra la traza completa de una sesión de prueba |

---

*Documento generado para CIME Power Systems · Agente Comercial IA — Renovación de Pólizas*
*Plataforma: Amazon Bedrock AgentCore · Framework: Strands Agents / LangGraph*
*Versión: 1.0 · Julio 2026*
