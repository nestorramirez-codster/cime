# Setup en una Cuenta / Consola AWS Nueva — Agente Comercial IA · CIME Power Systems

Guía autocontenida para desplegar el proyecto **desde cero** en una cuenta AWS limpia
(nueva consola). Cubre desde el acceso inicial hasta el webhook operativo y las tareas
manuales posteriores.

> Región de trabajo: **us-east-1** (alternativa soportada: us-west-2).
> Modelo fundacional: **Claude Sonnet 4** (`anthropic.claude-sonnet-4-20250514-v1:0`).
> Todos los comandos son de **PowerShell** (Windows). El backtick `` ` `` continúa la línea.

---

## 0. Resumen del despliegue

Se despliegan **dos stacks CloudFormation** + **un stack SAM**, en este orden:

```
[1] infra/base_infrastructure.yaml       → DynamoDB, S3, IAM, SES, Secrets, Logs
[2] infra/agentcore_runtime_config.yaml  → Bedrock Agent + Alias (reglas embebidas)
[3] template.yaml (SAM)                   → Lambda webhook + API Gateway + tool enviar_correo
[4] Configurar Zapier con la URL del webhook
```

Componentes que **NO** se despliegan en el MVP:
- `infra/kb_cloudformation.yaml` — la Knowledge Base fue descartada. Las reglas comerciales,
  plantillas y criterios de escalamiento están embebidos en el campo `Instruction` del Bedrock Agent.
- `infra/agentcore_gateway_tools.yaml` y `infra/agentcore_identity_config.yaml` — son documentos
  de referencia (formato AgentCore), no templates de CloudFormation desplegables. La tool
  `enviar_correo` se despliega como Action Group Lambda vía SAM.

---

## 1. Prerrequisitos de la máquina

Instalar y verificar:

| Herramienta | Verificación | Instalación |
|---|---|---|
| AWS CLI v2 | `aws --version` | https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html |
| AWS SAM CLI | `sam --version` | https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html |
| Python 3.12 | `python --version` | https://www.python.org/downloads/ |

> El `template.yaml` fija `Runtime: python3.12`. Si tu máquina tiene otra versión, instala 3.12
> o ajusta el runtime en `Globals.Function.Runtime`.

---

## 2. Acceso a la cuenta AWS nueva

### 2.1 Configurar credenciales

Con un usuario/rol que tenga permisos administrativos (o al menos IAM, CloudFormation, Lambda,
API Gateway, S3, DynamoDB, SES, Secrets Manager y Bedrock):

```powershell
# Opción A: credenciales de acceso (Access Key)
aws configure

# Opción B: AWS IAM Identity Center (SSO) — recomendado
aws configure sso
```

### 2.2 Verificar identidad y cuenta

```powershell
aws sts get-caller-identity
```

Anota el **Account ID** que devuelve. Lo vas a necesitar (los nombres de bucket lo incluyen y
`samconfig.toml` referencia IDs específicos de la cuenta).

```powershell
# Guardar el account id en una variable para el resto de la sesión
$ACCOUNT = (aws sts get-caller-identity --query Account --output text)
$ACCOUNT
```

---

## 3. Habilitar acceso al modelo en Bedrock

Amazon Bedrock requiere habilitar explícitamente cada modelo por cuenta y región.

1. Consola AWS → **Amazon Bedrock** → región **us-east-1**.
2. Menú izquierdo → **Model access** → **Manage model access** (o **Enable specific models**).
3. Habilitar **Anthropic · Claude Sonnet 4**.
4. Guardar y esperar a que el estado pase a **Access granted** (suele ser inmediato; puede tardar
   unos minutos).

Verificación por CLI (el modelo debe aparecer en la lista):

```powershell
aws bedrock list-foundation-models --region us-east-1 `
  --query "modelSummaries[?contains(modelId, 'claude-sonnet-4')].modelId" --output table
```

> Si tu cuenta no tiene acceso a Claude Sonnet 4, ajusta el parámetro `FoundationModelId` del
> stack del paso 5 a un modelo que sí tengas habilitado.

---

## 4. Paso 1 — Infraestructura base

Crea DynamoDB, buckets S3, rol IAM del agente, SES Configuration Set, 4 secretos y log groups.

```powershell
aws cloudformation deploy `
  --template-file infra/base_infrastructure.yaml `
  --stack-name cime-base-infra-dev `
  --parameter-overrides Environment=dev `
  --capabilities CAPABILITY_NAMED_IAM `
  --region us-east-1
```

### Recursos creados

| Recurso | Nombre |
|---|---|
| DynamoDB | `cime-agent-sessions-dev` |
| S3 memoria largo plazo | `cime-agent-memory-<ACCOUNT_ID>` |
| S3 documentos KB | `cime-kb-docs-<ACCOUNT_ID>` |
| IAM Role del agente | `cime-agent-execution-role-dev` |
| SES Configuration Set | `cime-agent-tracking-dev` |
| Secret Pipefy | `cime/pipefy/api-token` |
| Secret SES | `cime/ses/smtp-credentials` |
| Secret Tesorería | `cime/tesoreria/endpoint-key` |
| Secret Slack | `cime/comercial/slack-webhook` |

Ver outputs:

```powershell
aws cloudformation describe-stacks --stack-name cime-base-infra-dev `
  --query "Stacks[0].Outputs" --output table --region us-east-1
```

> Los 4 secretos se crean con valores **PLACEHOLDER**. Se actualizan con valores reales en el
> paso 8. El template ya no incluye `RotationSchedule` (requiere Lambda de rotación aparte),
> ni `TrackingOptions` de SES (requiere dominio verificado primero).

---

## 5. Paso 2 — Bedrock Agent + Alias

Crea el Bedrock Agent con todas las reglas comerciales embebidas y su alias `live-dev`.

```powershell
aws cloudformation deploy `
  --template-file infra/agentcore_runtime_config.yaml `
  --stack-name cime-runtime-dev `
  --parameter-overrides Environment=dev `
  --capabilities CAPABILITY_NAMED_IAM `
  --region us-east-1
```

### Obtener el Agent ID y Alias ID (¡importantes!)

En una cuenta nueva estos IDs son **distintos** a los de cualquier despliegue anterior. Cópialos:

```powershell
aws cloudformation describe-stacks --stack-name cime-runtime-dev `
  --query "Stacks[0].Outputs" --output table --region us-east-1
```

Busca los outputs `AgentId` y `AgentAliasId`.

> **Nota de dependencia:** el stack del runtime declara un `AWS::Lambda::Permission` que apunta a
> la función `cime-tool-enviar-correo-dev`, que aún no existe (se crea en el paso 6 vía SAM).
> Si el despliegue de este stack falla por ese permiso, primero despliega el SAM (paso 6) y luego
> reintenta este stack, o crea el permiso manualmente después. El Agent y su Alias se crean
> independientemente del permiso.

---

## 6. Paso 3 — Actualizar `samconfig.toml` y desplegar el webhook

### 6.1 Reemplazar los IDs de la cuenta anterior

`samconfig.toml` viene con los IDs del despliegue previo. **Edítalo** y reemplaza, en el bloque
`[dev.deploy.parameters]`, los valores de `AgentCoreAgentId` y `AgentCoreAgentAliasId` por los
que obtuviste en el paso 5:

```toml
parameter_overrides = [
    "Environment=dev",
    "AgentCoreAgentId=<TU_AGENT_ID>",
    "AgentCoreAgentAliasId=<TU_ALIAS_ID>",
    "PrimaryRegion=us-east-1",
    "LogRetentionDays=7"
]
```

### 6.2 Desplegar

Con el script incluido (valida prerrequisitos, credenciales, template, build y deploy):

```powershell
.\deploy.ps1 -Env dev
```

O manualmente:

```powershell
sam build
sam deploy --config-env dev
```

Esto crea la función webhook, el API Gateway HTTP, la función `test_email` y la función tool
`cime-tool-enviar-correo-dev`.

### 6.3 Copiar la URL del webhook

Del output `WebhookEndpoint`, con formato:

```
https://<API_ID>.execute-api.us-east-1.amazonaws.com/dev/webhook/activar
```

```powershell
aws cloudformation describe-stacks --stack-name cime-webhook-dev `
  --query "Stacks[0].Outputs" --output table --region us-east-1
```

---

## 7. Paso 4 — Verificación de dominio y salida de sandbox en SES

Necesario para que el agente pueda enviar correos.

1. Consola → **Amazon SES** (us-east-1) → **Identities** → **Create identity** → tipo **Domain** →
   `cimepowersystems.com` (o el dominio que uses).
2. SES genera registros **DKIM (CNAME)**; agrégalos en el DNS del dominio. Añade también **SPF** y
   **DMARC** recomendados. Espera a que la identidad quede **Verified**.
3. **Salir del sandbox:** por defecto SES solo envía a direcciones verificadas. Solicita acceso a
   producción en **Account dashboard** → **Request production access**.
4. (Opcional) Verifica una dirección de correo individual para pruebas mientras sigues en sandbox.

> El `SESVerifiedDomain` por defecto del template es `cimepowersystems.com`. Si usas otro dominio,
> pásalo en el paso 4 con `--parameter-overrides Environment=dev SESVerifiedDomain=tu-dominio.com`.

---

## 8. Paso 5 — Cargar valores reales en los secretos

Los 4 secretos se crearon con PLACEHOLDER. Actualízalos con valores reales:

```powershell
# Pipefy
aws secretsmanager put-secret-value --secret-id "cime/pipefy/api-token" `
  --secret-string '{"token":"TOKEN_REAL_PIPEFY"}' --region us-east-1

# SES SMTP + remitente
aws secretsmanager put-secret-value --secret-id "cime/ses/smtp-credentials" `
  --secret-string '{"smtp_username":"...","smtp_password":"...","sender_email":"renovaciones@cimepowersystems.com"}' `
  --region us-east-1

# Tesorería
aws secretsmanager put-secret-value --secret-id "cime/tesoreria/endpoint-key" `
  --secret-string '{"url":"https://.../v1/notificaciones","api_key":"API_KEY_REAL"}' --region us-east-1

# Slack (escalamientos)
aws secretsmanager put-secret-value --secret-id "cime/comercial/slack-webhook" `
  --secret-string '{"webhook_url":"https://hooks.slack.com/services/XXX/YYY/ZZZ"}' --region us-east-1
```

> Trata estos valores como sensibles: no los pegues en tickets, chats ni logs.

---

## 9. Paso 6 — Configurar Zapier

1. En Zapier, crea un Zap con **Trigger** sobre Pipefy (póliza dentro de ventana comercial:
   ≤30 días para vencer, o ya vencida).
2. **Action:** Webhooks by Zapier → **POST** a la URL `WebhookEndpoint` del paso 6.3.
3. Cuerpo (JSON) con el `ActivationPayload`:

```json
{
  "poliza_id": "POL-2024-001",
  "cliente_nombre": "Empresa Ejemplo SA",
  "cliente_email": "contacto@empresa.com",
  "fecha_vencimiento": "2026-10-15",
  "precio_renovacion": 25000.00,
  "equipo_nombre": "UPS 10kVA"
}
```

Detalle completo del mapeo de campos en `docs/zapier-setup.md`.

---

## 10. Prueba de humo (sin Zapier)

### Health check

```powershell
curl.exe https://<API_ID>.execute-api.us-east-1.amazonaws.com/dev/health
```

### Envío de correo de prueba (endpoint `/test/email`)

```powershell
curl.exe -X POST https://<API_ID>.execute-api.us-east-1.amazonaws.com/dev/test/email `
  -H "Content-Type: application/json" `
  -d '{"destinatario":"tu-correo-verificado@dominio.com","cliente_nombre":"Prueba","equipo_nombre":"UPS 10kVA","fecha_vencimiento":"2026-10-15","precio_renovacion":25000}'
```

> Mientras SES esté en sandbox, el destinatario debe estar verificado.

### Activación real del agente (endpoint `/webhook/activar`)

```powershell
curl.exe -X POST https://<API_ID>.execute-api.us-east-1.amazonaws.com/dev/webhook/activar `
  -H "Content-Type: application/json" `
  -d '{"poliza_id":"POL-TEST-001","cliente_nombre":"Empresa Prueba","cliente_email":"tu-correo@dominio.com","fecha_vencimiento":"2026-10-15","precio_renovacion":25000,"equipo_nombre":"UPS 10kVA"}'
```

Revisa la traza:

```powershell
aws logs tail /aws/lambda/cime-webhook-activar-dev --follow --region us-east-1
```

---

## 11. Checklist final

| Componente | Estado esperado |
|---|---|
| Acceso a Claude Sonnet 4 en Bedrock | Access granted |
| Stack `cime-base-infra-dev` | CREATE_COMPLETE |
| Stack `cime-runtime-dev` (Agent + Alias) | CREATE_COMPLETE |
| `samconfig.toml` con Agent ID / Alias ID de la cuenta nueva | Actualizado |
| Stack `cime-webhook-dev` (Lambda + API GW) | CREATE_COMPLETE |
| Dominio SES verificado + fuera de sandbox | Verified / Production |
| 4 secretos con valores reales | Actualizados |
| Zapier apuntando a `WebhookEndpoint` | Configurado |
| Pipefy: pipe con los 10 estados | Configurado |

---

## 12. Comandos útiles

```powershell
# Outputs de cualquier stack
aws cloudformation describe-stacks --stack-name <STACK> --query "Stacks[0].Outputs" --output table --region us-east-1

# Recursos que fallaron en un deploy
aws cloudformation describe-stack-events --stack-name <STACK> --region us-east-1 `
  --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" --output table

# Eliminar un stack
aws cloudformation delete-stack --stack-name <STACK> --region us-east-1

# Validar template SAM
sam validate --lint

# Logs del webhook en vivo
aws logs tail /aws/lambda/cime-webhook-activar-dev --follow --region us-east-1
```

---

## 13. Notas y errores conocidos (aprendidos en el primer despliegue)

- **SES dominio no verificado:** `TrackingOptions.CustomRedirectDomain` requiere dominio verificado.
  Ya está comentado en el template; descoméntalo tras verificar el dominio.
- **Secrets Manager y tags con comas:** los valores de tags no admiten comas. El template ya solo
  usa los tags `Project` y `Environment`.
- **Bucket KB:** el nombre real es `cime-kb-docs-<ACCOUNT_ID>`. Evita bucket policies con `Deny *`
  (se auto-bloquean incluso para CloudFormation y roles administrativos).
- **Runtime Python:** Lambda usa `python3.12`. La función webhook solo necesita `boto3` para invocar
  el Bedrock Agent Runtime; `strands-agents` NO va en `requirements.txt` (trae `pywin32`, que rompe
  el build para Lambda Linux). Dependencias de Lambda en `requirements.txt`, dependencias de
  desarrollo en `requirements-dev.txt`.

---

## 14. Despliegue en staging / prod

Repite los pasos 4–6 cambiando `-Env`/`Environment` y el `--config-env`:

```powershell
# base + runtime
aws cloudformation deploy --template-file infra/base_infrastructure.yaml --stack-name cime-base-infra-staging --parameter-overrides Environment=staging --capabilities CAPABILITY_NAMED_IAM --region us-east-1
aws cloudformation deploy --template-file infra/agentcore_runtime_config.yaml --stack-name cime-runtime-staging --parameter-overrides Environment=staging --capabilities CAPABILITY_NAMED_IAM --region us-east-1

# webhook (recuerda actualizar los IDs del bloque [staging.deploy.parameters] en samconfig.toml)
.\deploy.ps1 -Env staging
```

> `samconfig.toml` tiene bloques separados para `dev`, `staging` y `prod`. Actualiza `AgentCoreAgentId`
> y `AgentCoreAgentAliasId` en el bloque del entorno correspondiente antes de desplegar el webhook.
