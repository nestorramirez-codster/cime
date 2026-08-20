# Implementation Plan: Agente Comercial IA — Renovación de Pólizas

## Overview

Implementación del Agente Comercial IA sobre Amazon Bedrock AgentCore Runtime usando Strands Agents (Python) y Claude Sonnet 3.5. El agente automatiza el ciclo completo de renovación de pólizas: detección vía Zapier, contacto inicial por correo, seguimiento multi-etapa, generación de cotización, recepción de comprobante y notificación a Tesorería.

**Stack:** Python 3.11+ · Strands Agents SDK · Amazon Bedrock AgentCore · S3 Vectors · DynamoDB · Amazon SES · hypothesis==6.112.0

---

## Tareas

## Tasks

- [x] 1. Configurar estructura del proyecto y modelos de datos
  - Crear estructura de directorios del proyecto: `src/`, `src/agent/`, `src/tools/`, `src/models/`, `src/config/`, `src/observability/`, `tests/unit/`, `tests/property/`, `tests/integration/`
  - Implementar dataclasses en `src/models/data_models.py`: `ActivationPayload`, `SessionState`, `Mensaje`, `EscalationPayload`, `DatosPago`, `DatosPoliza`, `PipelineCard`, `EmailResult`
  - Definir el conjunto `ESTADOS_VALIDOS_PIPEFY` (10 estados) y la enumeración de tipos de mensaje en `src/models/constants.py`
  - Implementar función `es_payload_valido(payload: ActivationPayload) -> bool` con todas las reglas de validación del Requisito 1.2 (RFC 5321, ISO 8601, precio > 0, campos no vacíos)
  - Crear `requirements.txt` con dependencias pinneadas: `strands-agents`, `boto3`, `hypothesis==6.112.0`, `pytest`, `pytest-asyncio`, `pydantic`
  - _Requisitos: 1.2, 1.3, 7.1, 12.4_

  - [x] 1.1 Implementar modelos de datos y validación de payload
    - Crear `src/models/data_models.py` con todas las dataclasses del diseño
    - Crear `src/models/constants.py` con `ESTADOS_VALIDOS_PIPEFY` y tipos
    - Implementar `src/models/validators.py` con `es_payload_valido()`
    - _Requisitos: 1.2, 1.3_

  - [x] 1.2 Escribir property test — Propiedad 1: Validación exhaustiva de payload
    - **Property 1: Validación exhaustiva de payload de activación**
    - Usar `hypothesis` con estrategias `builds(ActivationPayload, ...)` generando campos válidos e inválidos
    - Verificar: payload inválido → `sesion_iniciada == False` y `correo_enviado == False`
    - Verificar: payload válido → `sesion_iniciada == True`
    - Archivo: `tests/unit/test_payload_validation.py`
    - **Valida: Requisitos 1.2, 1.3**

- [x] 2. Configurar infraestructura AWS base (IaC con AWS CDK o CloudFormation)
  - Crear stack de infraestructura en `infra/` con los siguientes recursos:
  - **DynamoDB:** tabla `cime-agent-sessions` con PK `session_id` (String), TTL en atributo `expiry_time`, billing mode PAY_PER_REQUEST
  - **S3 bucket memoria:** `cime-agent-memory-{account_id}` con prefix `memoria/{poliza_id}/historial.json`, versioning habilitado
  - **S3 bucket KB:** `cime-kb-documentos-{account_id}` con acceso restringido a rol del agente, versioning habilitado
  - **IAM roles:** rol de ejecución del agente con políticas mínimas para DynamoDB, S3, Bedrock, SES, CloudWatch, Secrets Manager
  - **Amazon SES:** verificar dominio o dirección de envío CIME, configurar DKIM/SPF, crear configuration set para tracking
  - **Secrets Manager:** crear los 4 secretos (`cime/pipefy/api-token`, `cime/ses/smtp-credentials`, `cime/tesoreria/endpoint-key`, `cime/comercial/slack-webhook`) con rotación automática de 90 días habilitada
  - _Requisitos: 12.1, 12.3, 5.3, 2.1, 10.1_

  - [x] 2.1 Crear tabla DynamoDB para memoria de corto plazo
    - Definir tabla con PK `session_id`, TTL de 24 horas, índices GSI si se necesitan
    - Configurar política IAM para lectura/escritura desde el rol del agente
    - _Requisitos: 8.1, 12.7_
    - _(Diferido: se desplegará en AWS al final. Código local usa mocks.)_

  - [x] 2.2 Crear buckets S3 para memoria de largo plazo y documentos KB
    - Bucket `cime-agent-memory-{account_id}` para historial por póliza
    - Bucket `cime-kb-documentos-{account_id}` para documentos de Knowledge Base
    - Configurar políticas de bucket y cifrado SSE-S3
    - _Requisitos: 8.3, 11.3_
    - _(Diferido: se desplegará en AWS al final. Código local usa mocks.)_

  - [x] 2.3 Configurar Secrets Manager con los 4 secretos del agente
    - Crear secretos con rotación automática de 90 días
    - Configurar políticas IAM para que solo el rol del agente acceda a cada secreto
    - Verificar que ningún valor de credencial aparece en variables de entorno o logs
    - _Requisitos: 12.3, 9.3_
    - _(Diferido: se desplegará en AWS al final. Código local usa mocks.)_

  - [x] 2.4 Configurar Amazon SES para envío de correos
    - Verificar dominio de envío de CIME y configurar registros DNS (DKIM, SPF, DMARC)
    - Crear configuration set con tracking de bounces y complaints
    - Solicitar salida de sandbox SES si el entorno es producción
    - _Requisitos: 2.1, 2.6, 2.7_
    - _(Diferido: se desplegará en AWS al final. Código local usa mocks.)_

- [x] 3. Configurar Knowledge Base con Amazon Bedrock KB + S3 Vectors
  - Crear y configurar la Knowledge Base en Amazon Bedrock con vector store S3 Vectors (NO OpenSearch ni Aurora)
  - Subir los 4 documentos al bucket S3 KB: `reglas_comerciales.md`, `catalogo_precios.json`, `plantillas_mensajes.md`, `criterios_escalamiento.md`
  - Configurar parámetros de KB: modelo de embeddings Titan Embeddings v2, chunk size 1,000 tokens, chunk overlap 200 tokens, Top-K=5, score mínimo 0.70
  - Implementar job de sincronización y verificar que tras sync las consultas retornan score ≥ 0.70
  - _Requisitos: 11.1, 11.2, 11.3, 11.4, 11.5_

  - [x] 3.1 Crear documentos de Knowledge Base y cargarlos en S3
    - Crear `docs/kb/reglas_comerciales.md` con reglas de negocio, ventana comercial (30 días), condiciones del Descuento_Pre_Vencimiento (5%)
    - Crear `docs/kb/catalogo_precios.json` con precios por tipo de equipo y plan de mantenimiento
    - Crear `docs/kb/plantillas_mensajes.md` con todas las plantillas aprobadas (6 tipos: pre-vencimiento, post-vencimiento, descuento, encuesta, escalamiento, confirmación)
    - Crear `docs/kb/criterios_escalamiento.md` con condiciones de activación de `escalar_humano`
    - Subir los 4 documentos al bucket S3 KB
    - _Requisitos: 11.1, 2.2, 2.3, 2.4, 3.3, 3.6_

  - [x] 3.2 Crear y configurar Knowledge Base en Amazon Bedrock con S3 Vectors
    - Crear Knowledge Base en Bedrock console/API apuntando al bucket S3 KB
    - Configurar vector store como S3 Vectors (verificar disponibilidad regional)
    - Configurar Amazon Titan Embeddings v2, chunk_size=1000, chunk_overlap=200, top_k=5
    - Ejecutar ingestion job inicial y verificar que los 4 documentos están indexados
    - _Requisitos: 11.1, 11.3, 11.4_

  - [x] 3.3 Escribir smoke test de KB: verificar score >= 0.70 para cada documento
    - Para cada documento cargado, consultar con sus términos clave y verificar que top score >= 0.70
    - Archivo: `tests/integration/test_kb_sync_score.py`
    - _Requisitos: 11.4_

- [x] 4. Implementar las 5 tools MCP del AgentCore Gateway

  - [x] 4.1 Implementar tool `consultar_pipefy`
    - Crear `src/tools/pipefy_tools.py` con función `consultar_pipefy(poliza_id: str) -> PipelineCard`
    - Integrar con Pipefy REST API (autenticación con token de Secrets Manager)
    - Implementar timeout de 30 segundos (Req 1.5) y manejo de errores HTTP 4xx/5xx
    - Mapear campos de respuesta Pipefy a dataclass `PipelineCard`
    - _Requisitos: 1.4, 1.5, 7.3_

  - [x] 4.2 Implementar tool `actualizar_pipefy`
    - En `src/tools/pipefy_tools.py`, implementar `actualizar_pipefy(poliza_id, estado, nota, session_id) -> bool`
    - Validar que `estado ∈ ESTADOS_VALIDOS_PIPEFY` antes de invocar la API (lanzar `InvalidStateTransitionError` si no)
    - Incluir `session_id`, `timestamp` UTC y `nota` (máx 200 chars) en el payload de actualización
    - Implementar política de retry: 2 reintentos con backoff 30s → 60s (Req 7.4)
    - _Requisitos: 7.1, 7.2, 7.3, 7.4, 9.4_

  - [x] 4.3 Implementar tool `enviar_correo`
    - Crear `src/tools/email_tools.py` con función `enviar_correo(destinatario, asunto, cuerpo, adjuntos=None) -> EmailResult`
    - Integrar con Amazon SES (boto3 `send_email` o `send_raw_email` para adjuntos)
    - Distinguir errores: `InvalidEmailError` (no reintento → escalar inmediato) vs `SESError` (1 reintento tras 60s)
    - Retornar `EmailResult` con `success`, `message_id`, `timestamp`, `error_code`, `error_type`
    - _Requisitos: 2.1, 2.6, 2.7, 4.5, 4.8_

  - [x] 4.4 Implementar tool `notificar_tesoreria`
    - Crear `src/tools/treasury_tools.py` con función `notificar_tesoreria(datos_pago: DatosPago) -> bool`
    - POST al endpoint interno de Tesorería (URL y API key desde Secrets Manager)
    - Implementar timeout de 60 segundos y 1 reintento tras 60s en caso de fallo técnico
    - Registrar en Observability la invocación y su resultado
    - _Requisitos: 5.3, 5.4, 5.5_

  - [x] 4.5 Implementar tool `escalar_humano`
    - Crear `src/tools/escalation_tools.py` con función `escalar_humano(motivo, historial, estado_pipefy, datos_poliza) -> bool`
    - Validar que `motivo != ""` y `estado_pipefy ∈ ESTADOS_VALIDOS_PIPEFY` antes de enviar
    - Notificar al Equipo Comercial vía Slack webhook (desde Secrets Manager)
    - Construir payload `EscalationPayload` completo incluyendo `session_id` y `timestamp` UTC
    - Actuar como circuit breaker final: nunca fallar silenciosamente; registrar fallback en CloudWatch Logs si falla
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

  - [x] 4.6 Escribir unit tests para manejo de errores y retry en las 5 tools
    - Fallo único con reintento exitoso para `actualizar_pipefy`, `enviar_correo`, `notificar_tesoreria`
    - Dos fallos consecutivos → activación de `escalar_humano` como circuit breaker
    - `enviar_correo` con email inválido → escalamiento inmediato sin reintento
    - `consultar_pipefy` con timeout de 30s → terminar sesión
    - Archivo: `tests/unit/test_retry_policy.py`
    - _Requisitos: 1.5, 2.6, 2.7, 5.5, 7.4_

- [x] 5. Checkpoint — Verificar tools MCP
  - Ejecutar unit tests de las 5 tools: `pytest tests/unit/ -v`
  - Verificar que cada tool lee credenciales desde Secrets Manager y no de variables de entorno
  - Confirmar que los modelos de datos `PipelineCard` y `EmailResult` se serializan correctamente
  - Preguntar al usuario si hay ajustes antes de continuar con el agente.

- [x] 6. Implementar el agente principal con Strands Agents

  - [x] 6.1 Configurar agente Strands con system prompt y registro de tools
    - Crear `src/agent/agent.py` con la instancia del agente Strands Agents
    - Definir el system prompt completo (Español mexicano formal, restricciones absolutas, flujo general) tal como está en el diseño
    - Registrar las 5 tools MCP como herramientas disponibles del agente
    - Configurar Claude Sonnet 3.5 como modelo fundacional (parámetros: región `us-east-1`, modelo ID de Bedrock)
    - _Requisitos: 12.4, 12.5, 9.1, 9.2, 9.3_

  - [x] 6.2 Implementar lógica de validación y arranque de sesión
    - Crear `src/agent/session.py` con función `iniciar_sesion(payload: ActivationPayload, session_id: str)`
    - Llamar `es_payload_valido()` y manejar path de error (registrar en Observability, actualizar Pipefy a "No renovada / sin respuesta", terminar)
    - Invocar `consultar_pipefy` y verificar estado bloqueante (Req 1.6): si es bloqueante, terminar sin acción
    - Si el Estado_Pipefy presenta discrepancias vs. payload (precio >1%, nombre, fecha), invocar `escalar_humano` inmediatamente (Req 6.7)
    - Invocar `actualizar_pipefy("Póliza detectada")` para registrar inicio de sesión
    - _Requisitos: 1.1, 1.4, 1.6, 1.7, 6.7_

  - [x] 6.3 Implementar flujo de contacto inicial (correo pre/post vencimiento)
    - En `src/agent/flows/contacto_inicial.py`, implementar `enviar_contacto_inicial(session_state: SessionState)`
    - Determinar si la póliza es pre-vencimiento (`fecha_vencimiento > date.today()`) o post-vencimiento
    - Consultar KB con query de contexto correspondiente (pre o post) y verificar score ≥ 0.70
    - Si score < 0.70: invocar `escalar_humano` (Req 11.2)
    - Generar correo personalizado con `cliente_nombre`, `equipo_nombre`, `fecha_vencimiento`, `precio_renovacion` formateado con 2 decimales y "MXN"
    - Incluir mención del 5% SOLO si es pre-vencimiento (Req 2.3); omitirla si es post-vencimiento (Req 2.4)
    - Invocar `enviar_correo` y en éxito invocar `actualizar_pipefy("Contacto inicial enviado")` con timestamp UTC
    - _Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 6.4 Escribir property test — Propiedad 3: Consistencia pre/post vencimiento
    - **Property 3: Consistencia de contenido pre/post vencimiento (metamórfica)**
    - Generar fechas aleatorias: futuras (pre-vencimiento) y pasadas (post-vencimiento)
    - Verificar: fecha futura → cuerpo del correo contiene mención de descuento 5%
    - Verificar: fecha pasada → cuerpo del correo NO contiene mención de descuento 5%
    - Archivo: `tests/unit/test_discount_calculation.py`
    - **Valida: Requisitos 2.3, 2.4**

  - [x]* 6.5 Escribir property test — Propiedad 5: Personalización del correo con datos del payload
    - **Property 5: Personalización del correo con datos del payload**
    - Para 100 payloads válidos generados aleatoriamente, verificar que el cuerpo del correo contiene los valores exactos de `cliente_nombre`, `equipo_nombre`, `fecha_vencimiento` y `precio_renovacion` (con 2 decimales y "MXN")
    - Archivo: `tests/property/test_email_personalization.py`
    - **Valida: Requisito 2.1**

  - [x] 6.6 Implementar flujo de seguimiento multi-etapa
    - Crear `src/agent/flows/seguimiento.py` con la máquina de estados del Requisito 3
    - Manejar respuesta del cliente: interés explícito → actualizar Pipefy a "Cliente interesado" → continuar a cotización
    - Manejar rechazo pre-vencimiento → consultar KB para plantilla de descuento → enviar oferta
    - Manejar rechazo post-vencimiento → invocar `escalar_humano` con contexto completo
    - Implementar timer de 48h para seguimiento de oferta no respondida (Req 3.5)
    - Manejar rechazo de oferta → enviar encuesta de motivos de no renovación (Req 3.6)
    - Después de 72h sin respuesta a encuesta → actualizar Pipefy a "No renovada / sin respuesta" (Req 3.7)
    - Actualizar Pipefy a "Seguimiento en curso" al inicio de cada mensaje de seguimiento (Req 3.9)
    - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [x] 6.7 Implementar flujo de generación y envío de cotización
    - Crear `src/agent/flows/cotizacion.py` con función `generar_cotizacion(session_state: SessionState)`
    - Consultar KB para obtener precio del catálogo por tipo de equipo y plan (Req 4.2)
    - Si no hay precio en catálogo → invocar `escalar_humano` (Req 4.7)
    - Calcular `precio_final = round(precio_base * 0.95, 2)` si aplica Descuento_Pre_Vencimiento (Req 4.3)
    - Generar cotización con todos los campos obligatorios: nombre cliente, equipo, periodo (12 meses), precio_base, precio_final, datos_bancarios
    - Enviar cotización solo si Estado_Pipefy es "Cliente interesado" (Req 4.4)
    - En éxito de `enviar_correo` → actualizar Pipefy a "Depósito solicitado" con monto guardado
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_

  - [x] 6.8 Escribir property test — Propiedad 7: Cálculo aritmético del precio con descuento
    - **Property 7: Cálculo aritmético exacto del precio con descuento**
    - Generar 100 valores aleatorios de precio base en rango $1,000–$500,000 MXN
    - Verificar: `precio_final == round(precio_base * 0.95, 2)` para cada valor
    - Archivo: `tests/unit/test_discount_calculation.py`
    - **Valida: Requisito 4.3**

  - [x] 6.9 Escribir property test — Propiedad 9: Completitud de campos en cotización
    - **Property 9: Completitud de campos en la cotización**
    - Para 100 instancias de `SessionState` con Estado_Pipefy "Cliente interesado" y datos válidos
    - Verificar que la cotización generada contiene todos los campos obligatorios definidos en Req 4.1
    - Archivo: `tests/property/test_quote_fields.py`
    - **Valida: Requisito 4.1**

  - [x] 6.10 Implementar flujo de recepción y procesamiento de comprobante
    - Crear `src/agent/flows/comprobante.py` con función `procesar_comprobante(adjunto, session_state)`
    - Validar formato del adjunto: extensión ∈ {PDF, JPG, PNG, JPEG} (case-insensitive) y tamaño ≤ 10 MB
    - Si formato/tamaño inválido → enviar correo de reenvío con formatos aceptados (Req 5.6)
    - Si válido → actualizar Pipefy a "Comprobante recibido" → enviar confirmación al cliente (Req 5.2)
    - Invocar `notificar_tesoreria` DESPUÉS de confirmar recepción al cliente (garantizar orden temporal Req 5.3)
    - En éxito → actualizar Pipefy a "En validación con tesorería" en máximo 5 segundos (Req 5.4)
    - NO realizar ninguna validación bancaria del comprobante (Req 5.7)
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_

  - [x] 6.11 Escribir property test — Propiedad 11: Validación de formato de comprobante
    - **Property 11: Validación de formato de comprobante**
    - Generar combinaciones aleatorias de extensiones y tamaños de archivo
    - Verificar: `acepta(adjunto) == (extension_valida(adjunto) AND tamaño_valido(adjunto))`
    - Archivo: `tests/unit/test_attachment_validation.py`
    - **Valida: Requisitos 5.1, 5.6**

  - [x] 6.12 Escribir property test — Propiedad 12: Orden temporal de notificación de comprobante
    - **Property 12: Orden temporal de notificación de comprobante**
    - Para N eventos de recepción de comprobante, verificar que `timestamp(confirmacion_cliente) < timestamp(notificacion_tesoreria)`
    - Archivo: `tests/property/test_notification_order.py`
    - **Valida: Requisito 5.3**

  - [x] 6.13 Implementar lógica de escalamiento desde el agente
    - Crear `src/agent/flows/escalamiento.py` con la lógica de todos los triggers de escalamiento (Req 6.1–6.9)
    - Solicitud explícita de asesor humano → `escalar_humano` INMEDIATO en el mismo turno (Req 6.1)
    - Negociación especial (descuento ≠ 5%, plazos diferidos, extensión de cobertura) → escalar (Req 6.3)
    - Solicitud de facturación, datos fiscales, condiciones administrativas → escalar (Req 6.4)
    - Inconformidad, queja o solicitud de atención personalizada → escalar (Req 6.5)
    - Duda técnica no respondida en KB → escalar (Req 6.6)
    - IF Memory no disponible: incluir todos los datos del ActivationPayload + sesión actual en el payload de escalamiento (Req 6.8)
    - Confirmar al cliente por correo que un asesor lo contactará en máx 24 horas hábiles (Req 6.2)
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 6.9_

- [x] 7. Checkpoint — Verificar flujos del agente
  - Ejecutar suite completa de unit tests: `pytest tests/unit/ -v`
  - Verificar con un payload de prueba que el flujo happy path genera los logs esperados
  - Confirmar que ningún descuento distinto al 5% aparece en ningún output del agente
  - Preguntar al usuario si hay ajustes en los flujos antes de continuar.

- [x] 8. Configurar AgentCore Memory (short-term DynamoDB + long-term S3)

  - [x] 8.1 Implementar capa de Memory de corto plazo (DynamoDB)
    - Crear `src/memory/short_term.py` con funciones `guardar_estado_sesion(session_state)`, `obtener_estado_sesion(session_id)`, `eliminar_dato_comprobante(session_id)`
    - Usar `session_id` como PK de DynamoDB; configurar TTL de 24h en el item
    - Implementar purga de datos de comprobante tras 10 minutos de confirmación (Req 8.5): usar TTL separado o Lambda trigger
    - Asegurar aislamiento: las funciones SOLO aceptan el `session_id` propio de la sesión activa
    - _Requisitos: 8.1, 8.5, 12.7_

  - [x] 8.2 Implementar capa de Memory de largo plazo (S3 JSON)
    - Crear `src/memory/long_term.py` con funciones `persistir_historial(poliza_id, sesion_completada)` y `recuperar_historial(poliza_id)`
    - Usar prefix S3 `memoria/{poliza_id}/historial.json`
    - Implementar serialización/deserialización de `list[Mensaje]` a JSON con timestamps ISO 8601
    - En cierre de sesión: persistir dentro de 30 segundos los campos requeridos (Req 8.3)
    - En inicio de nueva sesión: recuperar historial previo en máx 5 segundos y usarlo para personalizar primer mensaje (Req 8.2)
    - _Requisitos: 8.2, 8.3, 8.4_

  - [x] 8.3 Escribir property test — Propiedad 17: Round-trip de serialización del historial
    - **Property 17: Round-trip de serialización del historial de memoria**
    - Para cualquier lista de N mensajes `list[Mensaje]`, verificar que `deserializar(serializar(historial)) == historial`
    - Generar historiales aleatorios con timestamps, remitentes y tipos de mensaje variados
    - Archivo: `tests/unit/test_memory_serialization.py`
    - **Valida: Requisito 8.1**

  - [x] 8.4 Escribir smoke test: TTL de comprobante y aislamiento de sesión
    - Verificar que los datos de comprobante son eliminados de DynamoDB tras 10 minutos (simular con TTL corto en test)
    - Verificar que leer Memory con `session_id_A` no retorna datos de `session_id_B`
    - Archivo: `tests/unit/test_memory_serialization.py`
    - _Requisitos: 8.5, 12.7_

- [x] 9. Configurar AgentCore Policy (guardrails determinísticos)

  - [x] 9.1 Implementar guardrails de Policy en AgentCore
    - Configurar los 5 guardrails determinísticos en AgentCore Policy (consola o API):
      1. Bloquear tool call con descuento ≠ 5% (Req 9.1)
      2. Bloquear `enviar_correo` con datos bancarios cuando Estado_Pipefy ∉ {"Cliente interesado", "Depósito solicitado"} (Req 9.2)
      3. Bloquear tool calls que ofrezcan servicios fuera del alcance de póliza (Req 9.3)
      4. Bloquear `actualizar_pipefy` con estado fuera de `ESTADOS_VALIDOS_PIPEFY` (Req 9.4)
      5. Bloquear `enviar_correo` con condiciones comerciales no presentes en KB (Req 9.5)
    - Verificar que cada bloqueo registra en Observability los campos: `motivo_bloqueo`, `tool_call_intentado`, `session_id`, `estado_pipefy`, `timestamp` (Req 9.6)
    - Verificar que tras bloqueo el agente notifica al cliente y ofrece opciones disponibles o escala (Req 9.7)
    - _Requisitos: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [x]* 9.2 Escribir property test — Propiedad 6: Guardrail adversarial de descuento
    - **Property 6: Guardrail adversarial de descuento**
    - Generar mínimo 100 variaciones adversariales de mensajes de clientes que soliciten descuentos distintos al 5% (en español, inglés, con números, con porcentajes, con frases coloquiales)
    - Verificar que la Policy bloquea el tool call y el agente responde con oferta estándar 5% o escala
    - Archivo: `tests/property/test_adversarial_discount.py`
    - **Valida: Requisitos 3, 9.1**

  - [x]* 9.3 Escribir property test — Propiedad 8: Invariante de datos bancarios por estado
    - **Property 8: Invariante de datos bancarios por estado**
    - Para los 8 estados en los que NO aplica (todos excepto "Cliente interesado" y "Depósito solicitado")
    - Verificar que ningún correo generado contiene la cadena de datos bancarios
    - Archivo: `tests/unit/test_banking_data_guardrail.py`
    - **Valida: Requisitos 4.4, 9.2**

  - [x]* 9.4 Escribir property test — Propiedad 24: Completitud de registro de bloqueos
    - **Property 24: Completitud de registro de bloqueos por Policy**
    - Para N eventos de bloqueo por Policy, verificar que existen exactamente N entradas en Observability con todos los campos requeridos
    - Archivo: `tests/property/test_policy_blocks.py`
    - **Valida: Requisito 9.6**

- [x] 10. Configurar AgentCore Observability (OpenTelemetry → CloudWatch)

  - [x] 10.1 Implementar capa de observabilidad con enmascaramiento de datos sensibles
    - Crear `src/observability/tracer.py` con funciones para registrar los 5 tipos de trazas definidas en el diseño
    - Implementar función `enmascarar_datos_sensibles(data: dict) -> dict` que aplica:
      - Email → `***@dominio.com` (solo dominio visible)
      - Datos bancarios → `****-****-****-1234` (últimos 4 dígitos)
      - Nombre completo → `J.G.` (solo iniciales)
    - Llamar enmascaramiento ANTES de registrar cualquier parámetro de tool en Observability
    - Implementar fallback: si falla escritura en OTel/CloudWatch, registrar en CloudWatch Logs directo sin interrumpir flujo (Req 10.6)
    - Limitar tamaño máximo de cada entrada a 10 KB (Req 10.1)
    - _Requisitos: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 10.2 Instrumentar el agente con trazas de inicio/cierre de sesión e invocaciones de tools
    - Agregar llamadas a `tracer.registrar_inicio_sesion()` al inicio de `iniciar_sesion()`
    - Agregar llamadas a `tracer.registrar_tool_call()` en cada invocación de las 5 tools (con parámetros enmascarados)
    - Agregar llamadas a `tracer.registrar_error()` en cada catch de error técnico
    - Agregar llamadas a `tracer.registrar_cierre_sesion()` en todos los paths de cierre
    - _Requisitos: 10.1, 10.2, 10.3, 10.4_

  - [x]* 10.3 Escribir property test — Propiedad 20: Enmascaramiento de datos sensibles
    - **Property 20: Enmascaramiento de datos sensibles en Observability**
    - Para 100 registros generados con distintos datos de clientes (emails, nombres, datos bancarios)
    - Verificar que la regex `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` NO encuentra coincidencias en campos `params_enmascarados` y `resultado`
    - Archivo: `tests/unit/test_observability_masking.py`
    - **Valida: Requisito 10.5**

  - [x]* 10.4 Escribir property test — Propiedad 19: Completitud de trazas de sesión
    - **Property 19: Completitud de trazas de sesión en Observability**
    - Para N sesiones completadas (por cualquier motivo), verificar `count(trazas_inicio) == count(trazas_cierre) == N`
    - Archivo: `tests/property/test_notification_count.py`
    - **Valida: Requisitos 10.1, 10.4**

- [x] 11. Checkpoint — Verificar Observability y Policy
  - Ejecutar: `pytest tests/unit/test_observability_masking.py tests/unit/test_banking_data_guardrail.py -v`
  - Verificar en CloudWatch que las trazas de inicio y cierre de sesión se registran correctamente
  - Confirmar que ningún email completo ni dato bancario aparece en los registros de Observability
  - Preguntar al usuario si hay ajustes antes de continuar con la integración.

- [x] 12. Configurar AgentCore Runtime y Gateway (despliegue)

  - [x] 12.1 Configurar AgentCore Runtime en AWS
    - Configurar AgentCore Runtime en región `us-east-1` (o `us-west-2` según disponibilidad)
    - Definir timeout de sesión: 900 segundos (15 minutos)
    - Configurar auto-scaling y concurrencia gestionada por AgentCore
    - Asociar el rol IAM creado en la tarea 2 al Runtime
    - _Requisitos: 12.1, 12.6, 12.7_

  - [x] 12.2 Registrar las 5 tools MCP en AgentCore Gateway
    - Registrar `consultar_pipefy`, `actualizar_pipefy`, `enviar_correo`, `notificar_tesoreria`, `escalar_humano` como targets MCP en Gateway
    - Configurar schemas de entrada/salida para cada tool según las firmas definidas en el diseño
    - Verificar que cada tool call incluye token de autorización emitido por AgentCore Identity (Req 12.2)
    - Verificar que una tool invocada con credenciales de otra tool es rechazada con error de autorización (Req 12.8)
    - _Requisitos: 12.2, 12.8_

  - [x] 12.3 Configurar AgentCore Identity con Secrets Manager
    - Mapear cada secreto de Secrets Manager a la tool correspondiente en AgentCore Identity:
      - `cime/pipefy/api-token` → `consultar_pipefy`, `actualizar_pipefy`
      - `cime/ses/smtp-credentials` → `enviar_correo`
      - `cime/tesoreria/endpoint-key` → `notificar_tesoreria`
      - `cime/comercial/slack-webhook` → `escalar_humano`
    - Verificar que ningún valor de credencial aparece en system prompt, historial de conversación ni payload de respuesta de tools (Req 12.3)
    - _Requisitos: 12.3_

  - [x]* 12.4 Escribir property test — Propiedad 22: Aislamiento de sesiones concurrentes
    - **Property 22: Aislamiento de sesiones concurrentes**
    - Simular N pares de sesiones concurrentes con datos de pólizas distintos
    - Verificar que `memory.get(session_id_A) ∩ memory.get(session_id_B) == ∅` para todo par A ≠ B
    - Archivo: `tests/property/test_session_isolation.py`
    - **Valida: Requisito 12.7**

  - [x]* 12.5 Escribir property test — Propiedad 23: Autenticación exclusiva de credenciales por tool
    - **Property 23: Autenticación exclusiva de credenciales por tool**
    - Para cada par de tools distintas (X, Y), verificar que invocar tool_X con credenciales de tool_Y retorna error de autorización
    - Archivo: `tests/property/test_tool_auth.py`
    - **Valida: Requisito 12.8**

- [x] 13. Integración con Zapier y configuración del webhook

  - [x] 13.1 Implementar endpoint webhook para recibir activaciones de Zapier
    - Crear `src/webhook/handler.py` con función Lambda o FastAPI handler que recibe el POST de Zapier
    - Parsear y validar el `ActivationPayload` del body del webhook
    - Invocar AgentCore Runtime con el payload parseado y el `session_id` generado
    - Retornar HTTP 200 con `{"status": "accepted", "session_id": "..."}` a Zapier en < 30 segundos (Req 12.6)
    - _Requisitos: 1.1, 12.6_

  - [x] 13.2 Configurar Zapier con triggers de Pipefy
    - Documentar en `docs/zapier-setup.md` la configuración del Zap:
      - Trigger: Pipefy card entra en columna "Dentro de Ventana Comercial" O card vence sin renovar
      - Action: POST HTTP al webhook endpoint del agente
      - Mapeo de campos Pipefy → `ActivationPayload` (poliza_id, cliente_nombre, cliente_email, fecha_vencimiento, precio_renovacion, equipo_nombre)
    - Configurar manejo de errores del Zap (retry en caso de HTTP 5xx)
    - _Requisitos: 1.1, 1.2_

  - [x]* 13.3 Escribir test de integración: webhook Zapier → sesión AgentCore
    - Verificar que un HTTP POST con payload válido crea una sesión en AgentCore con `session_id` retornado
    - Verificar que un POST con payload inválido retorna HTTP 400 sin crear sesión
    - Archivo: `tests/integration/test_webhook_to_session.py`
    - _Requisitos: 1.1, 1.2, 1.3_

- [x] 14. Implementar property-based tests restantes (propiedades no cubiertas en tareas previas)

  - [x] 14.1 Implementar tests de propiedades de idempotencia y secuencia de estados

    - [x]* 14.1.1 Escribir property test — Propiedad 2: Idempotencia de activación en estados bloqueantes
      - **Property 2: Idempotencia de activación en estados bloqueantes**
      - Para pólizas con Estado_Pipefy ∈ {"Renovación confirmada", "Escalado a humano"}, invocar el agente N veces debe producir estado sin cambio y cero correos enviados
      - Archivo: `tests/property/test_idempotence.py`
      - **Valida: Requisito 1.6**

    - [x]* 14.1.2 Escribir property test — Propiedad 16: Invariante de estados válidos en Pipefy
      - **Property 16: Invariante de estados válidos en Pipefy**
      - Para N secuencias de eventos generadas, verificar que TODOS los estados registrados pertenecen a `ESTADOS_VALIDOS_PIPEFY`
      - Archivo: `tests/unit/test_state_transitions.py`
      - **Valida: Requisitos 7.1, 9.4**

  - [x] 14.2 Implementar tests de propiedades de trazabilidad y conteo

    - [x]* 14.2.1 Escribir property test — Propiedad 4: Trazabilidad de envíos de correo
      - **Property 4: Trazabilidad de envíos de correo (invariante de conteo)**
      - Para N invocaciones exitosas de `enviar_correo`, verificar `count(envios) == count(observability_entries) == count(pipefy_updates)`
      - Archivo: `tests/property/test_notification_count.py`
      - **Valida: Requisito 2.5**

    - [x]* 14.2.2 Escribir property test — Propiedad 13: Invariante de notificación obligatoria de comprobante
      - **Property 13: Invariante de notificación obligatoria de comprobante**
      - Para N comprobantes aceptados, verificar `count(comprobantes) == count(notificaciones_tesoreria) + count(escalamientos_por_fallo)`
      - Archivo: `tests/property/test_notification_count.py`
      - **Valida: Requisito 5.5**

  - [x] 14.3 Implementar tests de propiedades de escalamiento y contexto

    - [x]* 14.3.1 Escribir property test — Propiedad 14: Escalamiento por discrepancia de datos
      - **Property 14: Escalamiento inmediato por discrepancia de datos**
      - Para 100 pares (payload_activacion, datos_pipefy) con discrepancias en precio >1%, nombre o fecha
      - Verificar: agente SIEMPRE invoca `escalar_humano` y NUNCA invoca `enviar_correo`
      - Archivo: `tests/property/test_data_discrepancy.py`
      - **Valida: Requisito 6.7**

    - [x]* 14.3.2 Escribir property test — Propiedad 15: Contexto mínimo en escalamiento
      - **Property 15: Contexto mínimo requerido en todo escalamiento**
      - Para cualquier invocación de `escalar_humano`, verificar: `motivo != ""` y `estado_pipefy ∈ ESTADOS_VALIDOS_PIPEFY`
      - Archivo: `tests/unit/test_escalation_context.py`
      - **Valida: Requisito 6.9**

  - [x] 14.4 Implementar tests de propiedades de Knowledge Base y catálogo

    - [x]* 14.4.1 Escribir property test — Propiedad 10: Consistencia precio-catálogo
      - **Property 10: Consistencia precio-catálogo (model-based testing)**
      - Para cada combinación (tipo_equipo, plan_mantenimiento) del catálogo, verificar `cotizacion.precio_base == knowledge_base.precio(tipo_equipo, plan)`
      - Archivo: `tests/property/test_price_catalog.py`
      - **Valida: Requisito 4.2**

    - [x]* 14.4.2 Escribir property test — Propiedad 21: Escalamiento por score insuficiente en KB
      - **Property 21: Escalamiento por score insuficiente en Knowledge Base**
      - Para consultas a KB que retornan score máximo < 0.70, verificar que el agente SIEMPRE invoca `escalar_humano`
      - Archivo: `tests/unit/test_payload_validation.py`
      - **Valida: Requisito 11.2**

  - [x] 14.5 Implementar tests de propiedades de no-duplicación de mensajes

    - [x]* 14.5.1 Escribir property test — Propiedad 18: No duplicación de información en mensajes consecutivos
      - **Property 18: No duplicación de información en mensajes consecutivos**
      - Generar historiales con información repetida y verificar que el mensaje N+1 no reitera textualmente lo ya dicho en los últimos 20 mensajes
      - Archivo: `tests/unit/test_memory_serialization.py`
      - **Valida: Requisito 8.4**

- [x] 15. Tests de integración y E2E

  - [x] 15.1 Implementar test E2E del happy path completo
    - Crear `tests/integration/test_e2e_happy_path.py` que ejecute el flujo completo en entorno staging:
      1. POST webhook con payload válido
      2. Verificar correo de contacto inicial enviado (SES sandbox o mock)
      3. Simular respuesta de interés del cliente
      4. Verificar cotización generada y enviada con datos bancarios correctos
      5. Simular envío de comprobante PDF
      6. Verificar notificación a Tesorería
      7. Verificar que Estado_Pipefy final es "En validación con tesorería"
    - _Requisitos: 1.1, 2.1, 3.1, 4.1, 5.1, 5.3, 7.1_

  - [x] 15.2 Implementar tests de casos de borde críticos
    - Crear `tests/integration/test_edge_cases.py` con escenarios:
      - Payload con correo inválido → escalamiento inmediato sin reintento
      - Estado_Pipefy bloqueante → sesión termina sin acción
      - KB con score < 0.70 → escalamiento inmediato
      - Discrepancia de datos entre payload y Pipefy → escalamiento sin enviar correo
      - Comprobante con formato no soportado (`.doc`) → solicitud de reenvío
      - Comprobante de 10 MB + 1 byte → solicitud de reenvío
    - _Requisitos: 1.5, 1.6, 2.7, 6.7, 11.2, 5.6_

  - [x]* 15.3 Implementar smoke tests de infraestructura
    - Verificar que la KB retorna Top-K=5 resultados ordenados por score
    - Verificar que los 4 secretos de Secrets Manager son accesibles desde el rol del agente
    - Verificar que DynamoDB tiene la tabla y partición `session_id` correctas
    - Verificar que S3 tiene los buckets y prefixes correctos
    - Archivo: `tests/integration/test_smoke.py`
    - _Requisitos: 11.1, 12.2, 12.3_

  - [x]* 15.4 Implementar test de performance: cold start < 30s
    - Medir tiempo desde recepción del webhook hasta primer token de respuesta del agente
    - Verificar que cold start total < 30 segundos (Req 12.6)
    - Archivo: `tests/integration/test_e2e_happy_path.py`
    - _Requisitos: 12.6_

- [x] 16. Checkpoint final — Verificar implementación completa
  - Ejecutar suite completa de tests: `pytest tests/ -v --tb=short`
  - Verificar que los 8 criterios de éxito del MVP se cumplen (referencia: sección "Criterios de Éxito del MVP" en requirements.md)
  - Verificar que ningún secreto aparece en logs, variables de entorno o respuestas de tools
  - Revisar que el tablero de Pipefy refleja estados correctos para cada escenario de prueba
  - Preguntar al usuario si hay ajustes finales antes de declarar el MVP listo.

---

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para acelerar el MVP. Los property-based tests son la principal categoría opcional.
- Cada tarea referencia requisitos específicos del `requirements.md` para trazabilidad completa.
- Los checkpoints (tareas 5, 7, 11, 16) aseguran validación incremental antes de avanzar al siguiente grupo.
- El lenguaje de implementación es **Python 3.11+** con Strands Agents SDK de AWS.
- La biblioteca PBT es `hypothesis==6.112.0` con configuración `settings(max_examples=100, deadline=5000)`.
- Para ejecutar los tests en modo single-run (no watch): `pytest tests/ --no-header -rN`
- Los property tests adversariales (Propiedad 6) requieren mocks del modelo fundacional para controlar las respuestas del agente en pruebas determinísticas.
- La integración con Zapier (tarea 13.2) requiere acceso a la cuenta de Zapier de CIME; documentar la configuración para que el equipo operativo pueda reproducirla.

---

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": ["1.1"]
    },
    {
      "id": 1,
      "tasks": ["1.2", "2.1", "2.2", "2.3", "2.4"]
    },
    {
      "id": 2,
      "tasks": ["3.1", "4.1", "4.2", "4.3", "4.4", "4.5"]
    },
    {
      "id": 3,
      "tasks": ["3.2", "4.6"]
    },
    {
      "id": 4,
      "tasks": ["3.3", "6.1", "8.1", "8.2"]
    },
    {
      "id": 5,
      "tasks": ["6.2", "6.3", "8.3", "8.4"]
    },
    {
      "id": 6,
      "tasks": ["6.4", "6.5", "6.6", "6.7", "6.10", "6.13"]
    },
    {
      "id": 7,
      "tasks": ["6.8", "6.9", "6.11", "6.12", "9.1", "10.1"]
    },
    {
      "id": 8,
      "tasks": ["9.2", "9.3", "9.4", "10.2"]
    },
    {
      "id": 9,
      "tasks": ["10.3", "10.4", "12.1", "12.2", "12.3"]
    },
    {
      "id": 10,
      "tasks": ["12.4", "12.5", "13.1"]
    },
    {
      "id": 11,
      "tasks": ["13.2", "13.3", "14.1.1", "14.1.2", "14.2.1", "14.2.2", "14.3.1", "14.3.2", "14.4.1", "14.4.2", "14.5.1"]
    },
    {
      "id": 12,
      "tasks": ["15.1", "15.2", "15.3", "15.4"]
    }
  ]
}
```
