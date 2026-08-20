# Criterios de Escalamiento — CIME Power Systems
## Condiciones de Activación de `escalar_humano`

---

## Descripción General

El Agente Comercial IA debe invocar la tool `escalar_humano` de forma inmediata cuando se cumple cualquiera de las siguientes condiciones. El escalamiento transfiere el caso a un asesor comercial humano del Equipo Comercial de CIME Power Systems.

Tras escalar, el Agente DEBE:
1. Actualizar el Estado_Pipefy a "Escalado a humano".
2. Enviar al cliente la plantilla de confirmación de escalamiento (asesor lo contactará en máx. 24 horas hábiles).
3. Registrar en Observability el motivo del escalamiento y los datos del caso.

---

## Condiciones de Escalamiento

### 1. Solicitud Explícita de Asesor Humano (Req 6.1)

**Trigger:** El cliente solicita explícitamente hablar con un asesor, representante o persona humana.

**Ejemplos de frases detectables:**
- "Quiero hablar con una persona"
- "Prefiero que me atienda un asesor"
- "Comunícame con alguien de ventas"
- "No quiero hablar con un bot"
- "Necesito atención personalizada"

**Acción:** Invocar `escalar_humano` de forma INMEDIATA en el mismo turno conversacional. No intentar retener al cliente.

---

### 2. Negociación de Condiciones Especiales (Req 6.3)

**Trigger:** El cliente solicita cualquier condición que esté fuera de la autoridad del Agente.

**Condiciones que activan escalamiento:**
- Descuento diferente al 5% estándar (mayor o menor)
- Pagos diferidos, meses sin intereses o parcialidades
- Extensión del periodo de cobertura más allá de 12 meses
- Inclusión de equipos adicionales no cubiertos por la póliza original
- Modificación del alcance del servicio (agregar servicios no incluidos en el plan)
- Congelamiento de precio para renovaciones futuras

**Ejemplos:**
- "¿Me pueden dar un 10% de descuento?"
- "¿Puedo pagar en 3 mensualidades?"
- "¿Pueden extender la cobertura a 18 meses?"
- "Quiero incluir otro equipo en la misma póliza"

---

### 3. Solicitudes de Facturación, Datos Fiscales o Administrativas (Req 6.4)

**Trigger:** El cliente solicita información o acciones relacionadas con facturación, datos fiscales o trámites administrativos.

**Condiciones que activan escalamiento:**
- Solicitud de factura (CFDI)
- Consulta sobre datos fiscales de CIME
- Cambio de razón social o datos fiscales del cliente
- Solicitud de nota de crédito
- Consultas sobre IVA o desglose fiscal
- Solicitud de orden de compra o requisición

**Ejemplos:**
- "Necesito la factura de la renovación"
- "¿Cuál es su RFC?"
- "Necesito que la factura salga a otra razón social"
- "¿Pueden facturar sin IVA?"

---

### 4. Inconformidades, Quejas o Atención Personalizada (Req 6.5)

**Trigger:** El cliente expresa insatisfacción con el servicio, presenta una queja formal, o solicita atención especial.

**Condiciones que activan escalamiento:**
- Queja sobre servicio de mantenimiento recibido
- Inconformidad con tiempos de respuesta
- Reclamo por falla no resuelta
- Solicitud de compensación por mal servicio
- Tono agresivo o frustrado sostenido del cliente
- Solicitud explícita de atención personalizada o VIP

**Ejemplos:**
- "No estoy conforme con el servicio que recibí"
- "El técnico no resolvió mi problema"
- "Quiero poner una queja"
- "Exijo hablar con un gerente"
- "Su servicio es pésimo"

---

### 5. Dudas Técnicas No Respondidas por Knowledge Base (Req 6.6)

**Trigger:** El cliente hace una pregunta técnica que la Knowledge Base no puede responder con un score de confianza adecuado.

**Condición técnica:**
- La consulta a la Knowledge Base retorna un score < 0.70 para la mejor coincidencia.
- El Agente NO debe inventar ni inferir respuestas técnicas que no estén respaldadas por la KB.

**Ejemplos:**
- "¿El UPS soporta conexión con generador de gas?"
- "¿Pueden hacer mantenimiento a equipos que no son de su marca?"
- "¿Cuál es la vida útil de las baterías de mi equipo?"
- "¿El plan cubre daños por inundación?"

**Acción:** Informar al cliente que su consulta será atendida por un especialista técnico y escalar.

---

### 6. Discrepancia de Datos entre Payload y Pipefy (Req 6.7)

**Trigger:** Los datos recibidos en el payload de activación (de Zapier) no coinciden con los datos actuales en Pipefy.

**Condiciones específicas:**
- Precio de renovación difiere en más del 1% entre payload y Pipefy
- Nombre del cliente no coincide
- Fecha de vencimiento no coincide
- Equipo cubierto no coincide

**Acción:** Invocar `escalar_humano` INMEDIATAMENTE sin contactar al cliente, indicando la discrepancia específica encontrada para que el Equipo Comercial verifique los datos correctos.

---

### 7. Agotamiento de Reintentos (Circuit Breaker) (Req 6.9)

**Trigger:** Una tool del Agente ha agotado todos sus reintentos configurados sin éxito.

**Condiciones específicas:**
- `enviar_correo`: Fallo técnico en envío inicial + 1 reintento fallido (2 fallos totales)
- `actualizar_pipefy`: 2 reintentos con backoff 30s → 60s agotados (3 fallos totales)
- `notificar_tesoreria`: Fallo técnico en envío inicial + 1 reintento fallido (2 fallos totales)
- `consultar_pipefy`: Timeout de 30 segundos (1 fallo, sin reintento — terminar sesión)

**Acción:** Invocar `escalar_humano` como última acción antes de cerrar la sesión. Incluir en el payload:
- Tool que falló
- Número de reintentos ejecutados
- Último código de error recibido
- Contexto completo de la sesión activa

---

## Payload de Escalamiento

Al invocar `escalar_humano`, el Agente DEBE incluir la siguiente información:

```json
{
  "motivo": "Descripción del motivo de escalamiento",
  "categoria": "solicitud_humano | negociacion_especial | facturacion | queja | duda_tecnica | discrepancia_datos | circuit_breaker",
  "session_id": "ID de la sesión activa",
  "poliza_id": "ID de la póliza",
  "cliente_nombre": "Nombre del cliente",
  "cliente_email": "Correo del cliente",
  "estado_pipefy": "Estado actual en Pipefy",
  "historial_mensajes": ["Lista de mensajes intercambiados"],
  "datos_adicionales": "Contexto específico según el motivo",
  "timestamp": "Fecha y hora UTC del escalamiento"
}
```

---

## Prioridad de Escalamiento

Si se detectan múltiples condiciones de escalamiento simultáneamente, se reportan TODAS en el mismo payload de escalamiento. No se priorizan — el Equipo Comercial evalúa el caso completo.

---

## Restricción Importante

El `escalar_humano` es la tool de último recurso y circuit breaker del sistema. Si la propia invocación de `escalar_humano` falla:
1. Registrar el fallo en CloudWatch Logs directamente (fallback de Observability).
2. NO fallar silenciosamente — siempre dejar registro.
3. Terminar la sesión con estado "Escalado a humano" en Pipefy (mejor esfuerzo).
