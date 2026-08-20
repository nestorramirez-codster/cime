# AgentCore Identity — Guía de Configuración

## Resumen

AgentCore Identity gestiona las credenciales del Agente Comercial IA mediante AWS Secrets Manager. Cada tool del agente tiene acceso exclusivo a su(s) secreto(s) correspondiente(s), con rotación automática cada 90 días.

## Mapeo Secret → Tool

| Secreto (Secrets Manager) | Tools Autorizadas | Descripción |
|---|---|---|
| `cime/pipefy/api-token` | `consultar_pipefy`, `actualizar_pipefy` | Token Bearer para Pipefy GraphQL API |
| `cime/ses/smtp-credentials` | `enviar_correo` | Credenciales SMTP de Amazon SES |
| `cime/tesoreria/endpoint-key` | `notificar_tesoreria` | API key + URL del endpoint de Tesorería |
| `cime/comercial/slack-webhook` | `escalar_humano` | Webhook URL de Slack para escalamientos |

## Principios de Seguridad (Req 12.3)

### 1. Las credenciales NUNCA aparecen en:

- **System prompt**: El prompt del agente no contiene valores de credenciales. Las tools obtienen las credenciales en runtime desde Secrets Manager.
- **Historial de conversación**: Los mensajes intercambiados con el cliente no incluyen tokens, API keys ni URLs de webhooks.
- **Payload de respuesta de tools**: Las funciones `consultar_pipefy`, `actualizar_pipefy`, `enviar_correo`, `notificar_tesoreria` y `escalar_humano` retornan resultados (success/failure, IDs, timestamps) sin exponer credenciales.
- **Logs de Observability**: El módulo `src/observability/tracer.py` aplica enmascaramiento antes de registrar cualquier dato. Los patrones de credenciales son detectados y redactados.

### 2. Obtención de credenciales en runtime

Cada tool obtiene sus credenciales dinámicamente al momento de ejecución:

```python
# src/tools/pipefy_tools.py — _get_pipefy_token()
client = boto3.client("secretsmanager", region_name=region)
response = client.get_secret_value(SecretId="cime/pipefy/api-token")
secret_data = json.loads(response["SecretString"])
token = secret_data["token"]

# src/tools/treasury_tools.py — _get_treasury_secret()
response = client.get_secret_value(SecretId="cime/tesoreria/endpoint-key")
secret_data = json.loads(response["SecretString"])
url, api_key = secret_data["url"], secret_data["api_key"]

# src/tools/escalation_tools.py — _get_slack_webhook_url()
response = client.get_secret_value(SecretId="cime/comercial/slack-webhook")
secret = json.loads(response["SecretString"])
webhook_url = secret["webhook_url"]
```

### 3. Aislamiento de credenciales por tool (Req 12.8)

El IAM Role del agente limita el acceso a cada secreto mediante condiciones de recurso. Configurado en `infra/agentcore_identity_config.yaml`:

- `consultar_pipefy` / `actualizar_pipefy` solo acceden a `cime/pipefy/api-token`
- `enviar_correo` solo accede a `cime/ses/smtp-credentials`
- `notificar_tesoreria` solo accede a `cime/tesoreria/endpoint-key`
- `escalar_humano` solo accede a `cime/comercial/slack-webhook`

Invocar una tool con credenciales de otra tool genera un error de autorización IAM.

## Rotación Automática

- **Período**: 90 días
- **Mecanismo**: AWS Secrets Manager automatic rotation
- **Impacto**: Las tools leen el secreto en cada invocación (no cachean indefinidamente), por lo que la rotación es transparente
- **Notificación**: Se notifica al canal de Slack del Equipo Comercial cuando ocurre una rotación

## Modo de Desarrollo Local

En modo mock (`CIME_MOCK_MODE=true`), las tools retornan valores ficticios sin consultar Secrets Manager:

- `pipefy_tools.py`: retorna `"mock-pipefy-token-dev"`
- `treasury_tools.py`: no consulta Secrets Manager
- `escalation_tools.py`: retorna URL ficticia de Slack
- `email_tools.py`: simula envío sin conectar a SES

Esto permite desarrollo y testing local sin credenciales reales.

## Verificación

El test `tests/unit/test_credential_isolation.py` verifica automáticamente que:

1. El system prompt (`SYSTEM_PROMPT`) no contiene patrones de credenciales
2. Los payloads de respuesta de tools no exponen valores de secretos
3. Los logs enmascarados no contienen emails completos, tokens ni API keys
4. Las tools obtienen credenciales via `boto3.client("secretsmanager")`, no de variables de entorno ni valores hardcoded

## Archivos Relacionados

| Archivo | Propósito |
|---|---|
| `infra/agentcore_identity_config.yaml` | Configuración declarativa del mapeo secret→tool |
| `src/tools/pipefy_tools.py` | Tool Pipefy — lee `cime/pipefy/api-token` |
| `src/tools/email_tools.py` | Tool correo — usa SES (credenciales IAM role) |
| `src/tools/treasury_tools.py` | Tool tesorería — lee `cime/tesoreria/endpoint-key` |
| `src/tools/escalation_tools.py` | Tool escalamiento — lee `cime/comercial/slack-webhook` |
| `src/observability/tracer.py` | Enmascaramiento de datos sensibles en logs |
| `tests/unit/test_credential_isolation.py` | Test de verificación de aislamiento |
