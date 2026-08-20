# AgentCore Gateway — Guía de Configuración de Tools MCP

## Agente Comercial IA · CIME Power Systems

---

## Resumen

Este documento describe cómo registrar y configurar las 5 tools MCP del Agente Comercial IA en Amazon Bedrock AgentCore Gateway. Las tools permiten al agente interactuar con sistemas externos (Pipefy, SES, Tesorería, Slack) de forma segura y con trazabilidad completa.

**Archivo de configuración:** `infra/agentcore_gateway_tools.yaml`

---

## Prerrequisitos

1. **Cuenta AWS** con acceso a Amazon Bedrock AgentCore (región `us-east-1`)
2. **AWS Secrets Manager** con los 4 secretos ya creados:
   - `cime/pipefy/api-token` — Token Bearer para Pipefy GraphQL API
   - `cime/ses/smtp-credentials` — Credenciales de Amazon SES
   - `cime/tesoreria/endpoint-key` — API key del endpoint interno de Tesorería
   - `cime/comercial/slack-webhook` — URL del webhook de Slack para escalamientos
3. **Amazon SES** configurado con dominio verificado (DKIM + SPF)
4. **Pipefy** con el pipe operativo creado y el token con permisos de lectura/escritura
5. **Endpoint de Tesorería** accesible vía HTTPS desde la VPC del agente
6. **Slack App** con webhook configurado para el canal del Equipo Comercial

---

## Tools Registradas

| # | Tool | Descripción | Secret | Scope |
|---|------|-------------|--------|-------|
| 1 | `consultar_pipefy` | Consulta estado de póliza en Pipefy | `cime/pipefy/api-token` | `pipefy:read` |
| 2 | `actualizar_pipefy` | Actualiza estado con trazabilidad | `cime/pipefy/api-token` | `pipefy:write` |
| 3 | `enviar_correo` | Envía correo vía Amazon SES | `cime/ses/smtp-credentials` | `ses:send` |
| 4 | `notificar_tesoreria` | Notifica comprobante a Tesorería | `cime/tesoreria/endpoint-key` | `tesoreria:notify` |
| 5 | `escalar_humano` | Escala caso al Equipo Comercial | `cime/comercial/slack-webhook` | `escalation:notify` |

---

## Paso 1: Configurar Variables de Entorno

Antes de desplegar la configuración, establece las siguientes variables:

```bash
export AWS_ACCOUNT_ID="123456789012"        # Tu Account ID de AWS
export ENVIRONMENT="dev"                     # dev | staging | prod
export TESORERIA_ENDPOINT_URL="https://internal.cimepower.com/api/tesoreria/notificacion-pago"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."
```

---

## Paso 2: Registrar Tools en AgentCore Gateway

### Opción A: Vía AWS CLI (recomendado para CI/CD)

```bash
# Registrar configuración de Gateway tools
aws bedrock-agent create-agent-action-group \
  --agent-id <AGENT_ID> \
  --agent-version DRAFT \
  --action-group-name "cime-tools-mcp" \
  --action-group-executor '{"customControl": "RETURN_CONTROL"}' \
  --function-schema '{"functions": [...]}' \
  --region us-east-1
```

### Opción B: Vía consola de AgentCore

1. Navegar a **Amazon Bedrock → AgentCore → Agents → cime-agente-comercial**
2. En la pestaña **Gateway**, seleccionar **"Register MCP Target"**
3. Para cada tool, ingresar:
   - **Name:** nombre de la tool (ej: `consultar_pipefy`)
   - **Input Schema:** copiar del archivo `agentcore_gateway_tools.yaml`
   - **Output Schema:** copiar del archivo `agentcore_gateway_tools.yaml`
   - **Authorization:** seleccionar el secreto correspondiente de Secrets Manager
   - **Scope:** asignar el scope exclusivo de la tool

---

## Paso 3: Configurar AgentCore Identity (Autorización por Scope)

El sistema de autorización garantiza que cada tool solo acepta tokens con su scope exclusivo (Req 12.2, 12.8).

### Matriz de scopes exclusivos

```
consultar_pipefy   → pipefy:read
actualizar_pipefy  → pipefy:write
enviar_correo      → ses:send
notificar_tesoreria → tesoreria:notify
escalar_humano     → escalation:notify
```

### Configurar enforcement de scopes

En AgentCore Identity, habilitar:

```yaml
scopeEnforcement:
  enabled: true
  rejectOnMismatch: true
```

Esto asegura que si un token emitido para `pipefy:read` intenta invocar `enviar_correo` (que requiere `ses:send`), el Gateway responde con:

```json
{
  "error": "authorization_scope_mismatch",
  "message": "Token scope 'pipefy:read' no autorizado para tool 'enviar_correo'"
}
```

---

## Paso 4: Configurar Timeouts y Retry

| Tool | Timeout | Max Retry | Backoff |
|------|---------|-----------|---------|
| `consultar_pipefy` | 30s | 0 (sin retry) | — |
| `actualizar_pipefy` | 30s | 2 | 30s → 60s (exponencial) |
| `enviar_correo` | 60s | 1 | 60s fijo |
| `notificar_tesoreria` | 60s | 1 | 60s fijo |
| `escalar_humano` | 30s | 0 (fallback a logs) | — |

**Nota:** `escalar_humano` no tiene retry porque actúa como circuit breaker final. Si Slack falla, el payload se registra en CloudWatch Logs grupo `/agentcore/cime/escalamientos-fallback`.

---

## Paso 5: Verificar el Registro

### Test 1: Verificar que cada tool responde con token válido

```bash
# Obtener token con scope pipefy:read
TOKEN=$(aws bedrock-agent get-tool-token \
  --agent-id <AGENT_ID> \
  --tool-name consultar_pipefy \
  --output text --query 'token')

# Invocar tool con token válido — debe retornar 200
curl -X POST https://gateway.agentcore.us-east-1.amazonaws.com/tools/consultar_pipefy \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"poliza_id": "POL-2024-TEST-001"}'
```

### Test 2: Verificar rechazo con scope incorrecto (Req 12.8)

```bash
# Obtener token con scope pipefy:read
TOKEN_PIPEFY=$(aws bedrock-agent get-tool-token \
  --agent-id <AGENT_ID> \
  --tool-name consultar_pipefy \
  --output text --query 'token')

# Intentar invocar enviar_correo con token de pipefy — debe retornar 403
curl -X POST https://gateway.agentcore.us-east-1.amazonaws.com/tools/enviar_correo \
  -H "Authorization: Bearer $TOKEN_PIPEFY" \
  -H "Content-Type: application/json" \
  -d '{"destinatario": "test@example.com", "asunto": "Test", "cuerpo": "Hola"}' \
  --write-out "\nHTTP Status: %{http_code}\n"

# Respuesta esperada: HTTP 403
# {
#   "error": "authorization_scope_mismatch",
#   "message": "Token scope 'pipefy:read' no autorizado para tool 'enviar_correo'"
# }
```

### Test 3: Verificar todas las combinaciones de scope cruzado

```bash
#!/bin/bash
# Script de verificación exhaustiva de aislamiento de credenciales

TOOLS=("consultar_pipefy" "actualizar_pipefy" "enviar_correo" "notificar_tesoreria" "escalar_humano")
AGENT_ID="<AGENT_ID>"

echo "=== Verificación de aislamiento de scopes (Req 12.8) ==="

for SOURCE_TOOL in "${TOOLS[@]}"; do
  TOKEN=$(aws bedrock-agent get-tool-token \
    --agent-id $AGENT_ID \
    --tool-name $SOURCE_TOOL \
    --output text --query 'token' 2>/dev/null)

  for TARGET_TOOL in "${TOOLS[@]}"; do
    if [ "$SOURCE_TOOL" != "$TARGET_TOOL" ]; then
      HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "https://gateway.agentcore.us-east-1.amazonaws.com/tools/$TARGET_TOOL" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{}')

      if [ "$HTTP_CODE" == "403" ]; then
        echo "  ✓ $SOURCE_TOOL → $TARGET_TOOL: RECHAZADO (403)"
      else
        echo "  ✗ $SOURCE_TOOL → $TARGET_TOOL: PROBLEMA (HTTP $HTTP_CODE)"
      fi
    fi
  done
done

echo ""
echo "=== Fin de verificación ==="
```

---

## Paso 6: Monitoreo y Observabilidad

Cada invocación de tool a través del Gateway genera una traza en AgentCore Observability con:

- `tool_name`: nombre de la tool invocada
- `params_enmascarados`: parámetros con datos sensibles enmascarados
- `resultado`: éxito o error
- `duracion_ms`: duración de la invocación en milisegundos
- `session_id`: identificador de la sesión activa
- `scope_utilizado`: scope del token utilizado

Los campos sensibles se enmascaran antes de registrar:
- **Email:** `***@dominio.com`
- **Datos bancarios:** `****-****-****-1234`
- **Nombres:** `J.G.` (iniciales)

---

## Troubleshooting

### Error: `authorization_scope_mismatch` (HTTP 403)

**Causa:** El token presentado tiene un scope que no corresponde a la tool invocada.

**Solución:** Verificar que AgentCore Identity emite tokens con el scope correcto para cada tool. Revisar la configuración de `scopeEnforcement` en `agentcore_gateway_tools.yaml`.

### Error: `TimeoutError` en `consultar_pipefy`

**Causa:** La API de Pipefy no respondió en 30 segundos.

**Solución:** Verificar conectividad de red hacia `api.pipefy.com`. Revisar si hay throttling en la API de Pipefy (rate limits).

### Error: `NotificationError` en `notificar_tesoreria`

**Causa:** El endpoint de Tesorería no respondió o retornó error tras agotar el reintento.

**Solución:** El agente invocará `escalar_humano` automáticamente. Verificar disponibilidad del endpoint y validez de la API key en Secrets Manager.

### Error: Slack webhook falla en `escalar_humano`

**Causa:** El webhook de Slack no está accesible o retornó error.

**Solución:** El payload se registra automáticamente en CloudWatch Logs (`/agentcore/cime/escalamientos-fallback`). Verificar la URL del webhook en Secrets Manager y que el canal de Slack no fue archivado.

---

## Rotación de Credenciales

Los 4 secretos en Secrets Manager están configurados con **rotación automática cada 90 días**. Tras una rotación:

1. AgentCore Identity obtiene automáticamente el nuevo valor del secreto
2. Los tokens emitidos a partir de la rotación usan las nuevas credenciales
3. No se requiere intervención manual ni reinicio del agente

Para forzar una rotación manual:

```bash
aws secretsmanager rotate-secret --secret-id cime/pipefy/api-token
aws secretsmanager rotate-secret --secret-id cime/ses/smtp-credentials
aws secretsmanager rotate-secret --secret-id cime/tesoreria/endpoint-key
aws secretsmanager rotate-secret --secret-id cime/comercial/slack-webhook
```

---

## Referencias

- [Amazon Bedrock AgentCore Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore.html)
- [Secrets Manager — Rotación automática](https://docs.aws.amazon.com/secretsmanager/latest/userguide/rotating-secrets.html)
- [Pipefy GraphQL API](https://developers.pipefy.com/reference/graphql-api)
- [Amazon SES Developer Guide](https://docs.aws.amazon.com/ses/latest/dg/Welcome.html)
- Diseño del Agente: `.kiro/specs/agente-comercial-polizas/design.md`
- Requisitos: `.kiro/specs/agente-comercial-polizas/requirements.md`
