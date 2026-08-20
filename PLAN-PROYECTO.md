# Plan de Proyecto — Agente Comercial IA para Renovación de Pólizas

## Cliente: CIME Power Systems
## Plataforma: Amazon Bedrock AgentCore + Amazon Bedrock
## Fecha: Julio 2026

---

## 1. Contexto del Proyecto

CIME Power Systems opera en la industria de energía y soluciones industriales (plantas de luz, UPS, mantenimiento). Actualmente gestiona ~30 pólizas de mantenimiento al mes con una tasa de renovación estimada del 20% (6 de 30 pólizas). Hasta 24 pólizas mensuales no se renuevan — no por falta de interés del cliente, sino por falta de contacto oportuno y persistente.

### Oportunidad Comercial

| Métrica | Valor |
|---------|-------|
| Pólizas gestionadas/mes | 30 |
| Ticket promedio por póliza | $25,000 MXN |
| Tasa actual de renovación | ~20% (6 de 30) |
| Revenue potencial no capturado | Hasta $7,200,000 MXN/año |
| Break-even del proyecto | 1.2 pólizas adicionales/mes |

---

## 2. Objetivo

Implementar un **Agente Comercial IA** sobre Amazon Bedrock AgentCore que automatice el seguimiento comercial de renovaciones de pólizas de mantenimiento. El agente:

1. Detecta automáticamente pólizas próximas a vencer o vencidas (vía Pipefy + Zapier)
2. Contacta al cliente (correo en MVP, WhatsApp en producción)
3. Da seguimiento con reglas comerciales aprobadas por CIME
4. Solicita el depósito cuando el cliente confirma interés
5. Recibe el comprobante de pago
6. Notifica a tesorería para validación humana
7. Actualiza estado en Pipefy
8. Escala casos que requieren intervención humana

---

## 3. Arquitectura de la Solución

```
Pipefy (fuente de datos: pólizas, clientes, fechas, precios)
    │
    ▼
Zapier (activador: detecta pólizas próximas a vencer / vencidas)
    │
    ▼
Amazon Bedrock AgentCore — Orquestador y Plataforma del Agente
    ├── AgentCore Runtime: Entorno serverless para ejecutar el agente
    ├── AgentCore Gateway: Punto de entrada seguro MCP para herramientas (Pipefy, correo, WA)
    ├── AgentCore Memory: Contexto conversacional multi-turno y persistencia entre sesiones
    ├── AgentCore Observability: Trazabilidad, debugging y monitoreo del agente en producción
    ├── AgentCore Policy: Guardrails determinísticos (qué puede/no puede hacer el agente)
    ├── AgentCore Identity: Gestión de permisos y autenticación hacia herramientas externas
    │
    ▼
Amazon Bedrock (Modelo Fundacional: Claude / Amazon Nova)
    │
    ▼
Canales de Contacto
    ├── Canal MVP: Correo electrónico
    ├── Canal Producción: WhatsApp Business
    │
    ▼
Base de Conocimiento (Amazon Bedrock Knowledge Bases + S3 Vectors)
    ├── ⚠️ IMPORTANTE: Usar S3 como vector store para evitar costos altos (NO OpenSearch, NO Aurora)
    ├── Reglas comerciales, catálogo de precios, FAQs
    ├── Reglas de escalamiento: negociación, facturación, duda técnica, inconsistencia
    └── Registro: actualiza estado en Pipefy + notificación a tesorería
```

### Servicios por Capa

| Capa | Herramienta/Servicio |
|------|---------------------|
| Datos | Pipefy (registros de pólizas, clientes, fechas, precios, estados) |
| Automatización | Zapier (triggers, activaciones, webhooks entre sistemas) |
| Orquestación y Ejecución IA | **Amazon Bedrock AgentCore** (Runtime, Gateway, Memory, Observability, Policy, Identity) |
| Modelo fundacional | Amazon Bedrock (Claude / Amazon Nova — según disponibilidad) |
| Base de conocimiento | Amazon Bedrock Knowledge Bases con **S3 como vector store** (para evitar costos elevados de OpenSearch/Aurora). Documentos en S3, embeddings almacenados en S3 Vectors. |
| Canales | Correo electrónico (MVP) · WhatsApp Business (producción) |
| Notificaciones | Agente → Email/WhatsApp a Tesorería CIME |
| Registro | Pipefy (actualización de estado de póliza) |

### Rol de Amazon Bedrock AgentCore en la Solución

| Servicio AgentCore | Función en este proyecto |
|-------------------|--------------------------|
| **Runtime** | Entorno serverless seguro donde se ejecuta el agente. Escalado automático, cold starts rápidos, aislamiento por sesión. Sin gestión de infraestructura. |
| **Gateway** | Punto de entrada MCP unificado que conecta al agente con las herramientas: APIs de Pipefy, webhooks de Zapier, servicio de correo, WhatsApp. Seguridad y control centralizado. |
| **Memory** | Memoria de corto plazo (conversación multi-turno con el cliente) y largo plazo (historial de interacciones previas, preferencias del cliente). |
| **Observability** | Trazas de cada paso del agente (OpenTelemetry), debugging de flujos fallidos, métricas de rendimiento en producción. |
| **Policy** | Reglas determinísticas que limitan al agente: solo descuentos aprobados, solo datos bancarios cuando hay confirmación explícita, escalamiento obligatorio en casos definidos. |
| **Identity** | Gestión de identidad y permisos del agente para acceder a herramientas externas de forma segura. |

---

## 4. Flujo Operativo del MVP

### Diagrama de Flujo (Renovación de Póliza)

```
┌─────────────────────────────────┐
│ AGENTE IA monitorea pólizas     │
│ en Pipefy (vía Zapier)         │
└──────────────┬──────────────────┘
               ▼
       ┌───────────────┐
       │ ¿Póliza próxima│    No
       │ a vencer o sin ├────────► (Sin acción)
       │ renovar?       │
       └───────┬───────┘
               │ Sí
               ▼
┌─────────────────────────────────┐
│ IA pregunta al cliente sobre    │
│ renovación                      │
└──────────────┬──────────────────┘
               ▼
       ┌───────────────┐
       │ ¿Cliente      │    Sí
       │ interesado?   ├────────► Agente genera cotización
       └───────┬───────┘              │
               │ No                    ▼
               ▼               Cotización enviada al cliente
     IA manda descuento                │
               │                       ▼
               ▼               ┌───────────────┐
       ┌───────────────┐      │ ¿Acepta       │
       │ ¿Acepta       │      │ cotización?   │
       │ descuento?    │      └───┬───────┬───┘
       └───┬───────┬───┘          │ Sí    │ No
           │ Sí    │ No           ▼       ▼
           ▼       ▼       IA solicita  Seguimiento IA
    Genera  IA manda       el pago      + Descuento IA
  cotización encuesta          │             │
               │               ▼             ▼
               ▼        Recibe pago    Asesor contacta
         (Cierre sin    (correo/WA)    al cliente
          renovación)        │         (escalamiento)
                             ▼
                    Confirma pago al cliente
                             │
                             ▼
                    Asesor da seguimiento
                    y cierra renovación
                             │
                             ▼
                    Póliza registrada y
                    activa en Pipefy
```

### Outputs por Etapa

| Etapa | Output generado |
|-------|----------------|
| Monitoreo de pólizas en Pipefy | Alerta interna: póliza próxima a vencer o sin renovar |
| IA pregunta al cliente sobre renovación | Respuesta del cliente registrada |
| Si dice No: IA manda descuento | Oferta de descuento enviada al cliente |
| Descuento no aceptado: IA manda encuesta | Encuesta de motivo de no renovación enviada |
| Agente IA genera cotización de renovación | Cotización de renovación (documento) |
| Envío automático al cliente | Cotización enviada / registro de envío |
| Si acepta: IA solicita, recibe y confirma el pago | Solicitud, comprobante y confirmación de pago |
| Si acepta: seguimiento del asesor | Póliza registrada y activa en Pipefy |
| Si NO acepta: seguimiento IA + descuento IA | Oferta de descuento por parte de la IA |
| Si NO acepta: asesor contacta y cotiza renovación | Cotización de renovación ajustada (documento) |

---

## 5. Reglas Comerciales del MVP

| Momento | Regla |
|---------|-------|
| **Antes del vencimiento** | Descuento del 5% si el cliente paga antes de vencer |
| **Después del vencimiento** | Seguimiento durante periodo definido por CIME, condiciones estándar |
| **Campaña de recuperación** | Mensajes adicionales aprobados, incentivos solo con autorización de CIME |
| **Escalamiento humano** | Negociación especial, facturación, duda técnica, inconsistencia, inconformidad |

### Criterios de Escalamiento Humano

El agente escala al equipo de CIME cuando:
- El cliente solicita negociación especial
- El cliente requiere factura o condiciones administrativas específicas
- El cliente tiene una duda técnica no cubierta por la base de conocimiento
- El cliente solicita llamada con asesor
- Existe inconsistencia en precio, datos de póliza o información del cliente
- El cliente solicita cambios en el alcance de la póliza
- El comprobante de pago requiere validación con tesorería
- El cliente expresa inconformidad, rechazo o requiere atención personalizada

---

## 6. Alcance Funcional del MVP (Fase 1)

El agente comercial deberá:

1. Recibir tareas activadas desde Zapier con base en información de Pipefy
2. Identificar pólizas próximas a vencer, vencidas o dentro de una ventana comercial definida
3. Recibir datos mínimos del cliente, póliza, equipo, fecha de vencimiento y precio aplicable
4. Contactar al cliente mediante correo electrónico (MVP) y WhatsApp (producción)
5. Dar seguimiento conforme a reglas comerciales previamente aprobadas
6. Comunicar beneficios de renovación, incluyendo descuento autorizado cuando aplique
7. Solicitar el depósito correspondiente cuando el cliente confirme interés
8. Recibir o identificar el comprobante de pago enviado por el cliente
9. Registrar el avance dentro de Pipefy
10. Crear tarea/notificación para que el equipo valide el pago con tesorería
11. Escalar casos que requieran intervención humana
12. Mantener trazabilidad del seguimiento comercial

---

## 7. Tablero Operativo del Agente (Estados en Pipefy)

El agente opera sobre un pipe/tablero separado con los siguientes estados:

1. Póliza detectada
2. Contacto inicial enviado
3. Seguimiento en curso
4. Cliente interesado
5. Depósito solicitado
6. Comprobante recibido
7. En validación con tesorería
8. Renovación confirmada
9. Escalado a humano
10. No renovada / sin respuesta

---

## 8. Consumidores de la Solución

| Consumidor | Rol en el flujo |
|-----------|----------------|
| **Clientes de CIME** (empresas con plantas de luz / UPS) | Reciben el contacto del agente y responden por WhatsApp o correo |
| **Equipo comercial de CIME** | Recibe escalamientos cuando el caso requiere negociación, facturación o atención especial |
| **Tesorería de CIME** | Valida comprobantes de pago cuando el agente los recibe y genera la notificación |
| **Responsable operativo de CIME** | Revisa tablero en Pipefy y supervisa el avance del agente |

---

## 9. Integraciones

### Pipefy (Fuente de datos)
- Fuente operativa principal para consultar información de pólizas, clientes, fechas, estados
- Se trabaja inicialmente sobre un **pipe duplicado** o ambiente de pruebas
- Pipefy mantiene el control operativo; el agente funciona como capa comercial automatizada
- Conexión vía **AgentCore Gateway** como herramienta MCP

### Zapier (Activador — herramienta existente de CIME)
- Revisa condiciones en Pipefy y activa al agente cuando hay tarea comercial
- Triggers: póliza por vencer, póliza vencida, sin respuesta, cambio de estado, confirmación de interés, comprobante recibido, necesidad de escalamiento
- Se conecta a AgentCore vía webhook/API

### Amazon Bedrock AgentCore (Orquestador y Plataforma del Agente)
- **Runtime**: Ejecuta el agente de forma serverless con aislamiento por sesión, sin gestión de infra
- **Gateway**: Expone herramientas (Pipefy API, correo, WhatsApp) como tools MCP al agente con autenticación centralizada
- **Memory**: Mantiene contexto de conversación (short-term) e historial del cliente (long-term)
- **Observability**: Traza cada interacción del agente para debugging y monitoreo
- **Policy**: Aplica guardrails determinísticos (descuentos permitidos, condiciones de escalamiento, restricciones de datos bancarios)
- **Identity**: Gestiona credenciales y permisos para acceder a herramientas externas

Configuración del agente:
- Rol comercial
- Reglas de conversación (system prompt)
- Mensajes base
- Políticas de descuento
- Reglas de escalamiento
- Validación de datos mínimos
- Registro de interacciones
- Criterios de cierre, abandono o escalamiento
- Base de conocimiento autorizada
- Reglas para recepción de comprobante y notificación a tesorería

### Amazon Bedrock (Modelo Fundacional)
- Modelo LLM para generación de respuestas y razonamiento del agente
- Opciones: Claude (Anthropic) o Amazon Nova según disponibilidad y costo
- Acceso gestionado vía Bedrock sin necesidad de infraestructura propia

---

## 10. Criterios de Éxito

| Criterio | Cómo se verifica |
|----------|-----------------|
| El agente detecta automáticamente una póliza vencida o próxima a vencer | Se activa el trigger de Zapier con un registro real de Pipefy |
| El agente contacta al cliente y da seguimiento según reglas comerciales | Se envía correo de prueba y se valida el contenido con CIME |
| El cliente confirma interés y el agente solicita el depósito | El flujo avanza al paso de solicitud de pago sin intervención manual |
| El agente recibe el comprobante y notifica a tesorería | Tesorería recibe la notificación automática con los datos del pago |
| El agente actualiza el estado de la póliza en Pipefy | El registro en Pipefy refleja el avance del flujo en tiempo real |
| Los casos de escalamiento se derivan correctamente | Escenarios de negociación/facturación generan notificación al equipo |

---

## 11. Métricas a Medir

### Métrica principal
**Incremento de ventas recurrentes mediante recuperación de renovaciones de pólizas.**

### Métricas operativas
- Número de pólizas próximas a vencer detectadas
- Número de clientes contactados
- Número de clientes con respuesta
- Número de clientes interesados
- Número de renovaciones confirmadas
- Número de depósitos solicitados
- Número de comprobantes recibidos
- Número de comprobantes enviados a validación con tesorería
- Número de casos escalados a vendedor humano
- Número de pólizas no renovadas
- Monto potencial de renovación detectado
- Monto recuperado por renovaciones confirmadas
- Tasa de renovación antes y después del agente
- Tiempo promedio de respuesta del cliente
- Conversión por canal

---

## 12. Plan de Trabajo — Día de Prototipado Intensivo (DPI)

Se ejecutará en un **solo día de prototipado intensivo** (~7-8 horas efectivas), con el objetivo de tener un MVP funcional y demo-ready al final de la jornada.

**Punto de partida: implementación desde cero.** No hay infraestructura previa en AWS ni agente configurado. Se parte de una cuenta AWS limpia con acceso a Bedrock habilitado.

### Decisión de Arquitectura: Agente Único (Sin Sub-agentes)

Para este MVP se implementa **un solo agente** con múltiples herramientas (tools). No se requieren sub-agentes porque:
- El flujo es lineal y bien definido (detectar → contactar → seguir → cobrar → notificar)
- Las decisiones son basadas en reglas predefinidas, no en razonamiento especializado diferente
- Los escalamientos van a humanos, no a otro agente
- La base de conocimiento es acotada (precios, reglas comerciales, mensajes)

Sub-agentes se considerarán en fases futuras si se necesita coordinar dominios distintos (ej: agente técnico + agente comercial + agente de refacciones).

---

### Bloque 1 — Infraestructura y Setup desde Cero (3h)

**AWS — Configuración base:**
- Crear/validar cuenta AWS con acceso a Amazon Bedrock habilitado en la región seleccionada
- Habilitar modelo fundacional en Bedrock (Claude Sonnet o Amazon Nova)
- Crear bucket S3 para base de conocimiento (reglas comerciales, catálogo de precios, mensajes)
- Crear Amazon Bedrock Knowledge Base con S3 Vectors como vector store
- Subir documentos a S3 y ejecutar sync de la Knowledge Base

**AgentCore — Creación del agente:**
- Crear agente en Amazon Bedrock AgentCore con system prompt (rol comercial, reglas de conversación)
- Asociar Knowledge Base al agente
- Configurar AgentCore Gateway con targets MCP:
  - Tool: `consultar_pipefy` (lectura de datos de póliza/cliente)
  - Tool: `actualizar_pipefy` (escritura de estado en Pipefy)
  - Tool: `enviar_correo` (contacto al cliente vía email)
  - Tool: `notificar_tesoreria` (alerta de comprobante recibido)
  - Tool: `escalar_humano` (derivación a equipo comercial)

**Integraciones externas:**
- Verificar accesos: Pipefy (pipe duplicado), Zapier
- Mapear campos de Pipefy (nombre cliente, póliza, fecha vencimiento, precio, contacto)
- Configurar trigger en Zapier (pólizas ≤15 días para vencer + vencidas)
- Configurar webhook de Zapier → AgentCore (invocación del agente con payload)

### Bloque 2 — Lógica del Agente y Reglas (3h)

**System prompt y comportamiento:**
- Definir instrucciones del agente (tono, idioma, reglas de negocio, flujo de conversación)
- Configurar lógica de seguimiento multi-paso (contacto → seguimiento → cierre)
- Definir templates de mensajes por etapa (contacto inicial, recordatorio, solicitud de pago, confirmación)

**AgentCore Policy — Guardrails:**
- Configurar reglas en lenguaje natural o Cedar:
  - Solo descuento 5% pre-vencimiento (no más)
  - Datos bancarios solo si el cliente confirmó interés
  - Escalamiento obligatorio para negociación especial, facturación, dudas técnicas
  - Prohibir ofrecer servicios fuera de alcance (refacciones, diagnóstico, soporte)

**AgentCore Memory:**
- Configurar memoria de corto plazo (conversación activa con el cliente)
- Configurar memoria de largo plazo (historial de interacciones previas del cliente)

**Flujos de escalamiento:**
- Configurar tool `escalar_humano` con criterios de activación
- Definir notificación al equipo comercial (correo/webhook)

### Bloque 3 — Testing E2E y Demo (1.5h)

- Ejecutar 3-5 casos de prueba con datos reales/simulados:
  - Caso 1: Póliza próxima a vencer → contacto → cliente acepta → solicita pago
  - Caso 2: Póliza vencida → contacto → cliente no responde → seguimiento
  - Caso 3: Cliente solicita descuento especial → escalamiento a humano
  - Caso 4: Cliente envía comprobante → notificación a tesorería
  - Caso 5: Cliente tiene duda técnica → escalamiento
- Verificar actualización de estados en Pipefy
- Verificar trazas en AgentCore Observability
- Identificar y corregir gaps
- Ajustes finales a mensajes y reglas
- **Demo funcional** con al menos un caso de renovación real recorriendo el flujo completo

### Resultado esperado al final del día
MVP funcional desde cero: infraestructura AWS desplegada, agente configurado en Bedrock AgentCore, integrado con Pipefy vía Zapier, capaz de detectar pólizas, contactar clientes por correo, dar seguimiento, solicitar depósito, recibir comprobante, notificar a tesorería y actualizar Pipefy — todo sin intervención manual.

---

## 13. Entregables

1. Configuración del agente comercial en Amazon Bedrock AgentCore
2. Diseño del flujo de renovación de pólizas
3. Integración inicial con Pipefy mediante Zapier + AgentCore Gateway
4. Validación de lectura de datos desde Pipefy
5. Configuración de reglas comerciales iniciales (system prompt + Policy)
6. Plantillas base de comunicación para correo y WhatsApp
7. Configuración de estados de oportunidad para seguimiento
8. Registro de avance de oportunidades en Pipefy
9. Flujo de recepción de comprobante de pago
10. Generación de actividad/notificación para validación con tesorería
11. Reglas de escalamiento a equipo humano (AgentCore Policy)
12. Pruebas controladas con casos simulados
13. Ajustes posteriores a validación del flujo
14. Documentación operativa básica
15. Sesión de transferencia al equipo de CIME
16. Reporte inicial de métricas (AgentCore Observability)

---

## 14. Información Requerida de CIME (Pre-requisitos)

| Pendiente | Responsable |
|-----------|------------|
| Confirmar Sponsor y Champion internos | CIME |
| Acceso a Pipefy (pipe duplicado o ambiente de pruebas) | CIME |
| Confirmar estructura de campos en Pipefy | CIME + Codster |
| Base de precios de pólizas vigente | CIME |
| Definición de reglas comerciales y descuentos | CIME |
| Mensajes aprobados para correo y WhatsApp | CIME |
| Definición del canal WhatsApp Business | CIME |
| Datos bancarios autorizados para compartir | CIME |
| Responsable de tesorería para validación | CIME |
| Criterios de cierre / abandono / escalamiento | CIME |
| Credenciales de Zapier y validación del plan | CIME |

### Pre-requisitos Técnicos (AWS — responsabilidad Codster)

| Pendiente | Detalle |
|-----------|---------|
| Cuenta AWS con Bedrock habilitado | Región con soporte para AgentCore (us-east-1 o us-west-2) |
| Acceso a modelos en Bedrock | Solicitar acceso a Claude Sonnet y/o Amazon Nova |
| Permisos IAM configurados | Roles para AgentCore, S3, Knowledge Bases |
| Bucket S3 creado | Para documentos de la base de conocimiento |
| Dominio/correo para envío | Cuenta de correo configurada para el agente (SES o servicio externo) |

---

## 15. Riesgos Identificados

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|-----------|
| WhatsApp Business sin cuenta activa/aprobada | Media | Alto | Iniciar con correo; activar WA en paralelo |
| Datos en Pipefy incompletos o de baja calidad | Alta | Alto | Discovery Semana 1 con validación exhaustiva |
| CIME no define reglas comerciales a tiempo | Media | Alto | Tener plantilla preconfigurada para validación rápida |
| Ausencia de champion interno = baja adopción | Alta | Medio | Identificar y formalizar champion en Kickoff |
| Scope creep hacia refacciones o diagnóstico técnico | Media | Medio | Documentar claramente el fuera de alcance |
| Límites del plan Zapier de CIME | Baja | Medio | Validar plan actual en Semana 1 |

---

## 16. Fuera de Alcance del MVP

- ❌ Validación bancaria automática de depósitos
- ❌ Facturación y conciliación contable
- ❌ Diagnóstico técnico de equipos
- ❌ Venta de refacciones (Fase 4)
- ❌ Monitoreo remoto de plantas
- ❌ Atención de soporte técnico
- ❌ Modificación de procesos administrativos de CIME
- ❌ Generación formal de documentos de póliza
- ❌ Conciliación bancaria automática

---

## 17. Roadmap Posterior al MVP

| Fase | Caso de Uso |
|------|------------|
| **Fase 1 (MVP)** | Renovación de pólizas de mantenimiento |
| **Fase 2** | Venta de póliza / garantía extendida posterior a arranque exitoso |
| **Fase 3** | Seguimiento comercial de recomendaciones post-visita técnica (cambio de batería, etc.) |
| **Fase 4** | Activación comercial de refacciones (catálogo estructurado) |

---

## 18. Guardrails del Agente (implementados vía AgentCore Policy)

- El agente **solo aplica descuentos y condiciones aprobadas** por CIME → Policy rule en AgentCore
- Cualquier negociación fuera de las reglas predefinidas **escala al equipo comercial** → Policy rule de escalamiento automático
- Datos bancarios **solo se comparten** cuando el cliente ha confirmado interés explícito → Policy rule condicional
- Se trabaja sobre **pipe duplicado** en Pipefy para pruebas (no el productivo)
- Los mensajes deben ser **validados por CIME** antes de enviarlos a clientes reales
- AgentCore Policy intercepta cada tool call del agente antes de ejecutarse, validando que cumpla con las reglas definidas en lenguaje natural o Cedar

---

## 19. Notas para Generación del Spec

Al generar el spec en tu entorno local, considera:

1. **Implementación desde cero**: No hay infraestructura previa. Se parte de cuenta AWS limpia con Bedrock habilitado.
2. **Agente único**: Un solo agente con múltiples tools — NO sub-agentes para el MVP.
3. **Orquestador**: Amazon Bedrock AgentCore — Runtime, Gateway, Memory, Observability, Policy, Identity
4. **Modelo fundacional**: Amazon Bedrock (Claude Sonnet / Amazon Nova)
5. **Integraciones clave**: Pipefy → Zapier → AgentCore Gateway (MCP) → Agente → Pipefy (bidireccional)
6. **Canal MVP**: Correo electrónico (WhatsApp es canal productivo posterior)
7. **El agente NO sustituye** el proceso administrativo completo — automatiza hasta la confirmación del cliente y recepción de comprobante
8. **La validación bancaria queda fuera** — solo se registra que el comprobante fue recibido y se notifica a tesorería
9. **AgentCore Gateway** expone Pipefy, correo y WhatsApp como herramientas MCP al agente
10. **AgentCore Policy** implementa los guardrails determinísticos (descuentos, escalamiento, datos bancarios)
11. **AgentCore Memory** mantiene contexto entre turnos de conversación y entre sesiones del mismo cliente
12. **AgentCore Observability** permite trazar y debuggear cada interacción del agente
13. **Base de conocimiento**: Usar **Amazon Bedrock Knowledge Bases con S3 Vectors** como vector store — NO usar OpenSearch ni Aurora para mantener costos bajos. Los documentos (reglas comerciales, catálogo de precios, mensajes) se almacenan en S3 y los embeddings se indexan en S3 Vectors.
14. **Tools del agente** (definir en AgentCore Gateway como targets MCP):
    - `consultar_pipefy` — lectura de datos de póliza/cliente
    - `actualizar_pipefy` — escritura de estado en Pipefy
    - `enviar_correo` — contacto al cliente vía email
    - `notificar_tesoreria` — alerta de comprobante recibido
    - `escalar_humano` — derivación a equipo comercial
15. **Framework recomendado**: Strands Agents (nativo AWS) o LangGraph — compatible con AgentCore Runtime

---

*Documento preparado por Codster · Julio 2026*
*Confidencial — CIME Power Systems + Codster + AWS*
