# Guía de Configuración: AgentCore Runtime

## Agente Comercial IA — CIME Power Systems

Esta guía describe los pasos para configurar el AgentCore Runtime en AWS para el Agente Comercial IA de renovación de pólizas.

---

## Prerrequisitos

1. **Cuenta AWS** con acceso a Amazon Bedrock y AgentCore
2. **Rol IAM del agente** creado previamente (tarea 2 del plan de implementación)
3. **Knowledge Base** configurada y sincronizada (tarea 3)
4. **AWS CLI** configurado con credenciales de un usuario con permisos de administrador de Bedrock
5. **Región habilitada**: verificar que `us-east-1` tiene AgentCore disponible; si no, usar `us-west-2`

---

## Parámetros de Configuración

| Parámetro | Valor | Justificación |
|-----------|-------|---------------|
| Región | `us-east-1` (preferida) / `us-west-2` (fallback) | Disponibilidad de AgentCore y Claude Sonnet 3.5 |
| Timeout de sesión | 900 segundos (15 minutos) | Tiempo suficiente para completar flujos multi-paso |
| Cold start máximo | 30 segundos | Req 12.6: responder al webhook de Zapier en tiempo |
| Modelo fundacional | Claude Sonnet 3.5 (`anthropic.claude-sonnet-3.5-v1`) | Capacidad de razonamiento + español |
| Auto-scaling | Gestionado por AgentCore | Sin configuración manual de concurrencia |
| Aislamiento de sesión | Por `session_id` (garantizado por Runtime) | Req 12.7 |

---

## Paso 1: Desplegar el Stack de CloudFormation

### Opción A: Despliegue via AWS CLI

```bash
aws cloudformation deploy \
  --template-file infra/agentcore_runtime_config.yaml \
  --stack-name cime-agentcore-runtime-dev \
  --parameter-overrides \
    Environment=dev \
    PrimaryRegion=us-east-1 \
    FoundationModelId=anthropic.claude-sonnet-3.5-v1 \
    KnowledgeBaseId=<ID_DE_LA_KB> \
    AgentRoleArn=<ARN_DEL_ROL_IAM> \
    SessionTimeoutSeconds=900 \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Opción B: Despliegue via consola AWS

1. Ir a **CloudFormation** > **Create Stack**
2. Subir `infra/agentcore_runtime_config.yaml`
3. Completar los parámetros requeridos
4. Marcar la casilla de capacidades IAM
5. Crear el stack

---

## Paso 2: Verificar el Despliegue

### 2.1 Verificar el agente en Bedrock

```bash
# Listar agentes en la región
aws bedrock-agent list-agents --region us-east-1

# Obtener detalles del agente
aws bedrock-agent get-agent \
  --agent-id <AGENT_ID> \
  --region us-east-1
```

### 2.2 Verificar el alias

```bash
aws bedrock-agent list-agent-aliases \
  --agent-id <AGENT_ID> \
  --region us-east-1
```

### 2.3 Verificar el rol IAM

```bash
aws iam get-role --role-name cime-agentcore-runtime-role-dev
```

---

## Paso 3: Configurar Auto-Scaling

AgentCore gestiona la concurrencia automáticamente. No se requiere configuración manual de auto-scaling para el MVP con ~30 pólizas/mes. El Runtime escala a cero cuando no hay invocaciones activas.

**Monitoreo recomendado:**
- Configurar alarma CloudWatch si la concurrencia supera 5 sesiones simultáneas
- Revisar métricas de cold start para confirmar < 30 segundos

```bash
# Crear alarma de concurrencia (opcional)
aws cloudwatch put-metric-alarm \
  --alarm-name "cime-agente-alta-concurrencia" \
  --metric-name "ConcurrentSessions" \
  --namespace "AWS/Bedrock" \
  --statistic Maximum \
  --period 60 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 3 \
  --alarm-actions <SNS_TOPIC_ARN> \
  --dimensions Name=AgentId,Value=<AGENT_ID> \
  --region us-east-1
```

---

## Paso 4: Asociar el Rol IAM al Runtime

El template de CloudFormation crea y asocia automáticamente el rol `cime-agentcore-runtime-role-dev` al agente. Este rol incluye permisos mínimos para:

- **Bedrock**: invocar modelo fundacional y consultar Knowledge Base
- **DynamoDB**: lectura/escritura en tabla de sesiones (memoria corto plazo)
- **S3**: lectura/escritura en bucket de memoria largo plazo
- **Secrets Manager**: lectura de credenciales de las 5 tools
- **SES**: envío de correos electrónicos
- **CloudWatch**: logs, métricas y trazas (observabilidad)

Si el rol fue creado manualmente en la tarea 2, se puede usar el parámetro `AgentRoleArn` para referenciarlo en lugar de crear uno nuevo.

---

## Paso 5: Probar Invocación del Agente

### Test básico con AWS CLI

```bash
# Invocar el agente con un payload de prueba
aws bedrock-agent-runtime invoke-agent \
  --agent-id <AGENT_ID> \
  --agent-alias-id <ALIAS_ID> \
  --session-id "test-session-001" \
  --input-text '{"poliza_id": "POL-TEST-001", "cliente_nombre": "Empresa Prueba SA", "cliente_email": "test@empresa.com", "fecha_vencimiento": "2025-08-15", "precio_renovacion": 45000.00, "equipo_nombre": "UPS APC Smart 3000VA"}' \
  --region us-east-1
```

### Verificar logs en CloudWatch

```bash
aws logs filter-log-events \
  --log-group-name "/aws/bedrock/agents/cime-agente-comercial-dev" \
  --filter-pattern "session_id" \
  --region us-east-1
```

---

## Paso 6: Configuración de Timeout y Sesiones

### Timeout de 900 segundos

El timeout está configurado como `IdleSessionTTLInSeconds: 900` en el template. Esto significa:

- La sesión se mantiene activa hasta 15 minutos desde el último mensaje
- Si el agente no recibe interacción en 15 minutos, la sesión se cierra automáticamente
- Al cierre, se persiste el historial en memoria de largo plazo (S3)

### Aislamiento de sesiones (Req 12.7)

- Cada invocación desde Zapier genera un `session_id` único
- La memoria DynamoDB particiona por `session_id`
- No existe path de código para leer el contexto de otra sesión
- El Runtime garantiza aislamiento a nivel de invocación

---

## Troubleshooting

| Problema | Causa probable | Solución |
|----------|---------------|----------|
| Cold start > 30s | Región congestionada | Probar us-west-2 como alternativa |
| Error de permisos en KB | Rol IAM no tiene acceso a la KB | Verificar policy `AccessKnowledgeBase` |
| Timeout en tool calls | Tools MCP no registradas en Gateway | Completar tarea 12.2 |
| Sesiones no se crean | Alias no apunta a versión preparada | Ejecutar `prepare-agent` antes de crear alias |

---

## Siguiente Paso

Una vez el Runtime esté operativo, continuar con:
- **Tarea 12.2**: Registrar las 5 tools MCP en AgentCore Gateway
- **Tarea 12.3**: Configurar AgentCore Identity con Secrets Manager
- **Tarea 13**: Integrar webhook de Zapier con el endpoint del agente

---

## Referencias

- [Amazon Bedrock Agents Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html)
- [CloudFormation AWS::Bedrock::Agent](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-bedrock-agent.html)
- Template IaC: `infra/agentcore_runtime_config.yaml`
