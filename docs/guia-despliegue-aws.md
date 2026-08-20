# Guía de Despliegue — Agente Comercial IA · CIME Power Systems

## Resumen

Esta guía documenta el proceso de despliegue del Agente Comercial IA en AWS, incluyendo los errores encontrados durante la implementación y sus soluciones.

**Fecha:** Agosto 2026  
**Stack desplegado:** base_infrastructure + agentcore_runtime (Bedrock Agent)  
**Pendiente:** webhook Lambda + API Gateway (SAM)

---

## Prerrequisitos

1. AWS CLI configurado con credenciales válidas (`aws configure` o SSO)
2. SAM CLI instalado: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html
3. Python 3.12 en PATH
4. Región: `us-east-1`
5. Acceso al modelo Claude Sonnet 4 habilitado en Amazon Bedrock (consola → Model access)

Verificar credenciales:
```powershell
aws sts get-caller-identity
```

---

## Orden de Despliegue

```
[1] infra/base_infrastructure.yaml  → DynamoDB, S3, IAM, SES, Secrets
[2] infra/agentcore_runtime_config.yaml → Bedrock Agent + Alias
[3] template.yaml (SAM)             → Lambda + API Gateway (webhook)
[4] Configurar Zapier con la URL del webhook
```

> **Nota:** La Knowledge Base (kb_cloudformation.yaml) fue descartada. Las reglas comerciales, plantillas y criterios de escalamiento están embebidos directamente en las instrucciones del Bedrock Agent.

---

## Paso 1: Infraestructura Base

```powershell
aws cloudformation deploy `
  --template-file infra/base_infrastructure.yaml `
  --stack-name cime-base-infra-dev `
  --parameter-overrides Environment=dev `
  --capabilities CAPABILITY_NAMED_IAM `
  --region us-east-1
```

### Recursos creados

| Recurso | Nombre/ARN |
|---------|------------|
| DynamoDB | `cime-agent-sessions-dev` |
| S3 Memoria | `cime-agent-memory-{account_id}` |
| S3 KB Docs | `cime-kb-docs-{account_id}` |
| IAM Role | `cime-agent-execution-role-dev` |
| SES Config Set | `cime-agent-tracking-dev` |
| Secret Pipefy | `cime/pipefy/api-token` |
| Secret SES | `cime/ses/smtp-credentials` |
| Secret Tesorería | `cime/tesoreria/endpoint-key` |
| Secret Slack | `cime/comercial/slack-webhook` |

### Errores encontrados y soluciones

#### Error 1: SES — Dominio no verificado

```
Domain <cimepowersystems.com> is not verified under this account.
```

**Causa:** El `TrackingOptions.CustomRedirectDomain` requiere que el dominio ya esté verificado en SES antes de crear el Configuration Set.

**Solución:** Se eliminó `TrackingOptions` del template. Se puede agregar después de verificar el dominio:
```yaml
# Descomentar cuando el dominio esté verificado:
# TrackingOptions:
#   CustomRedirectDomain: !Ref SESVerifiedDomain
```

#### Error 2: Secrets Manager — Caracteres inválidos en tags

```
Request rejected by the downstream tagging service. Please check that you're only using allowed characters.
```

**Causa:** El tag `Tool` tenía comas en el valor (`consultar_pipefy,actualizar_pipefy`). Secrets Manager no acepta comas en valores de tags.

**Solución:** Se eliminaron los tags `Tool` de todos los secretos. Solo se mantienen `Project` y `Environment`.

#### Error 3: RotationSchedule sin Lambda de rotación

Los recursos `AWS::SecretsManager::RotationSchedule` requieren una Lambda de rotación configurada para funcionar.

**Solución:** Se eliminaron todos los RotationSchedule del template. Se configurarán manualmente cuando se implemente la Lambda de rotación.

#### Error 4: Bucket Policy con Deny bloqueó todo acceso

```
User is not authorized to perform: s3:PutObject with an explicit deny in a resource-based policy
```

**Causa:** La bucket policy del bucket KB tenía un `Deny *` que solo excluía al rol del agente y al root. El usuario SSO no estaba en la lista de excepción, y la policy se bloqueó a sí misma — ni CloudFormation podía borrarla.

**Solución:**
1. Se eliminó la bucket policy restrictiva completamente del template
2. Se renombró el bucket a `cime-kb-docs-{account}` (el anterior quedó huérfano — borrar desde root)
3. El acceso al bucket se controla solo via IAM policies del rol del agente (suficiente y no se auto-bloquea)

**Lección aprendida:** Nunca usar `Deny *` en bucket policies sin incluir TODOS los principals que necesitan acceso (incluyendo el rol de CloudFormation y los roles SSO administrativos).

---

## Paso 2: Bedrock Agent

```powershell
aws cloudformation deploy `
  --template-file infra/agentcore_runtime_config.yaml `
  --stack-name cime-runtime-dev `
  --parameter-overrides Environment=dev `
  --capabilities CAPABILITY_NAMED_IAM `
  --region us-east-1
```

### Recursos creados

| Recurso | Valor |
|---------|-------|
| Agent ID | `4DXPKDJ3SI` |
| Agent Alias ID | `O8VXCQJHUY` |
| Modelo | Claude Sonnet 4 |
| Timeout sesión | 900s (15 min) |
| IAM Role | `cime-agentcore-runtime-role-dev` |

### Decisión: Knowledge Base eliminada

La Knowledge Base con S3 Vectors presentó problemas de compatibilidad con CloudFormation:
- `StorageConfiguration.Type: S3` no es válido (el tipo correcto es `S3_VECTORS`)
- `S3VectorsConfiguration` es requerido pero la creación del recurso seguía fallando por validaciones internas del servicio

**Solución adoptada:** Embeber todo el contenido de la KB (reglas comerciales, plantillas de mensajes, criterios de escalamiento) directamente en el campo `Instruction` del Bedrock Agent. Esto:
- Elimina una dependencia compleja
- Simplifica el despliegue
- Funciona correctamente porque el precio viene en el payload de Zapier (no se necesita buscar en catálogo)

---

## Paso 3: Webhook Lambda + API Gateway (SAM)

### Subir documentos KB al bucket (referencia futura)

```powershell
aws s3 cp docs/kb/ s3://cime-kb-docs-460572858036/ --recursive --region us-east-1
```

### Desplegar

```powershell
.\deploy.ps1 -Env dev
```

O manualmente:
```powershell
sam build
sam deploy --config-env dev
```

### Errores encontrados y soluciones

#### Error 5: Python 3.11 no encontrado

```
Binary validation failed for python... which did not satisfy constraints for runtime: python3.11
```

**Causa:** El template declaraba `Runtime: python3.11` pero la máquina solo tiene Python 3.12 y 3.14.

**Solución:** Cambiar el runtime a `python3.12` en `template.yaml`:
```yaml
Globals:
  Function:
    Runtime: python3.12
```

#### Error 6: pywin32 en resolución de dependencias

```
PythonPipBuilder:ResolveDependencies - {pywin32==312(wheel)}
```

**Causa:** `strands-agents` trae `pywin32` como dependencia transitiva. SAM resuelve dependencias en Windows pero Lambda corre en Linux donde `pywin32` no existe.

**Solución:**
1. Separar dependencias: `requirements.txt` (Lambda) vs `requirements-dev.txt` (desarrollo local)
2. Eliminar `strands-agents` de las dependencias Lambda — el webhook solo necesita `boto3` para invocar el Bedrock Agent Runtime
3. `requirements.txt` final para Lambda:
```
boto3==1.35.99
pydantic==2.10.3
python-dateutil==2.9.0.post0
```

**Lección aprendida:** La Lambda webhook solo invoca `bedrock-agent-runtime` via boto3. El framework `strands-agents` corre DENTRO del Bedrock Agent (gestionado por AWS), no en la Lambda.

---

## Paso 4: Configurar Zapier

Una vez desplegado el webhook, copiar la URL del output `WebhookEndpoint` y seguir `docs/zapier-setup.md`.

El formato de la URL será:
```
https://<API_ID>.execute-api.us-east-1.amazonaws.com/dev/webhook/activar
```

---

## Estado Actual del Despliegue

| Componente | Estado | Stack |
|-----------|--------|-------|
| DynamoDB, S3, IAM, SES, Secrets | ✅ Desplegado | `cime-base-infra-dev` |
| Bedrock Agent + Alias | ✅ Desplegado | `cime-runtime-dev` |
| Lambda + API Gateway | ⏳ Pendiente (sam build/deploy) | `cime-webhook-dev` |
| Zapier | ⏳ Pendiente | Manual |
| SES Dominio verificado | ⏳ Pendiente | Manual (DNS) |
| Secretos con valores reales | ⏳ Pendiente | Manual |

---

## Acciones Pendientes Post-Despliegue

1. **Ejecutar `.\deploy.ps1 -Env dev`** — despliega Lambda + API Gateway
2. **Verificar dominio SES** — registros DNS (DKIM, SPF, DMARC) para `cimepowersystems.com`
3. **Salir del sandbox SES** — para enviar correos a cualquier dirección
4. **Actualizar secretos** con valores reales:
   ```powershell
   aws secretsmanager put-secret-value --secret-id "cime/pipefy/api-token" `
     --secret-string '{"token":"TOKEN_REAL"}' --region us-east-1
   ```
5. **Configurar Zapier** con la URL del webhook
6. **Configurar Pipefy** — pipe duplicado con los 10 estados y columna "Dentro de Ventana Comercial"
7. **Borrar bucket huérfano** `cime-kb-documentos-460572858036` (requiere acceso root de la cuenta AWS por la policy Deny)

---

## Comandos Útiles

```powershell
# Ver outputs de un stack
aws cloudformation describe-stacks --stack-name cime-base-infra-dev --query "Stacks[0].Outputs" --output table --region us-east-1

# Ver errores de un despliegue fallido
aws cloudformation describe-stack-events --stack-name <STACK> --region us-east-1 --query "StackEvents[?ResourceStatus=='CREATE_FAILED'].[LogicalResourceId,ResourceStatusReason]" --output table

# Eliminar stack
aws cloudformation delete-stack --stack-name <STACK> --region us-east-1

# Forzar delete saltando recursos problemáticos
aws cloudformation delete-stack --stack-name <STACK> --retain-resources Recurso1 Recurso2 --region us-east-1

# Validar template SAM
sam validate --lint

# Build y deploy
sam build; sam deploy --config-env dev
```

---

## Arquitectura Final (Simplificada)

```
Zapier (trigger: póliza en ventana comercial)
  │
  ▼ HTTP POST
API Gateway (POST /webhook/activar)
  │
  ▼
Lambda (webhook_handler.py)
  │  - Valida payload
  │  - Genera session_id
  │  - Invoca Bedrock Agent (async)
  ▼
Amazon Bedrock Agent (Claude Sonnet 4)
  │  - Instrucciones con reglas/plantillas/escalamiento embebidas
  │  - 5 tools MCP (Pipefy, Email, Tesorería, Escalamiento)
  ▼
Pipefy ← actualiza estado
SES ← envía correos
Slack ← escalamientos
DynamoDB ← memoria de sesión
S3 ← historial por póliza
```
