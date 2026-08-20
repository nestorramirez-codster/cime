# Guía: Solicitar y Configurar Credenciales AWS — Proyecto CIME

## Índice

1. [Contexto — ¿Qué estamos pidiendo y por qué?](#1-contexto)
2. [Documento para enviar al dueño de la cuenta AWS](#2-documento-para-el-administrador)
3. [Recibir las credenciales de forma segura](#3-recibir-las-credenciales)
4. [Instalar AWS CLI en tu computadora](#4-instalar-aws-cli)
5. [Configurar las credenciales en tu máquina](#5-configurar-credenciales)
6. [Verificar que todo funciona](#6-verificar-conexion)
7. [Problemas frecuentes y soluciones](#7-problemas-frecuentes)

---

## 1. Contexto

### ¿Qué necesitamos?

Para desplegar la infraestructura del Agente Comercial (DynamoDB, S3, SES, Secrets Manager, IAM roles), necesitas **credenciales de acceso programático** a una cuenta AWS.

### ¿Qué es "mínimos privilegios"?

Significa que solo pedimos permisos para hacer exactamente lo que necesitamos — ni más, ni menos. Esto protege la cuenta AWS de errores accidentales o accesos no autorizados.

### ¿Qué vas a recibir?

Dos valores secretos que funcionan como tu "usuario y contraseña" para AWS desde la terminal:

- **Access Key ID** — parece algo como: `AKIAIOSFODNN7EXAMPLE`
- **Secret Access Key** — parece algo como: `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`

> ⚠️ **NUNCA** compartas estos valores en chat, email, o repositorios de código.

---

## 2. Documento para el Administrador

Copia desde aquí y envíalo al dueño de la cuenta AWS:

---

### 📋 INICIO DEL DOCUMENTO PARA EL ADMINISTRADOR 📋

---

**Asunto:** Solicitud de usuario IAM — Proyecto Agente Comercial CIME

**Hola [nombre del administrador],**

Necesito acceso programático a la cuenta AWS para desplegar la infraestructura del proyecto Agente Comercial IA. A continuación te detallo exactamente qué necesito y la política de permisos mínimos.

#### Lo que necesito que hagas:

1. **Crear un usuario IAM** llamado `cime-developer`
2. **Adjuntar la política de permisos** que incluyo abajo
3. **Generar una Access Key** (acceso programático)
4. **Enviarme las credenciales** de forma segura (ver opciones al final)

#### Política de permisos (copiar tal cual)

Ve a IAM → Policies → Create Policy → pestaña JSON, y pega esto:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DynamoDBSessionTable",
      "Effect": "Allow",
      "Action": [
        "dynamodb:CreateTable",
        "dynamodb:DescribeTable",
        "dynamodb:UpdateTable",
        "dynamodb:DeleteTable",
        "dynamodb:UpdateTimeToLive",
        "dynamodb:DescribeTimeToLive",
        "dynamodb:TagResource",
        "dynamodb:ListTagsOfResource"
      ],
      "Resource": "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/cime-agent-sessions"
    },
    {
      "Sid": "S3BucketsCreation",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:PutBucketVersioning",
        "s3:PutBucketEncryption",
        "s3:PutBucketPolicy",
        "s3:GetBucketPolicy",
        "s3:GetBucketVersioning",
        "s3:GetEncryptionConfiguration",
        "s3:PutBucketTagging",
        "s3:GetBucketTagging",
        "s3:ListBucket",
        "s3:DeleteBucket"
      ],
      "Resource": [
        "arn:aws:s3:::cime-agent-memory-ACCOUNT_ID",
        "arn:aws:s3:::cime-kb-documentos-ACCOUNT_ID"
      ]
    },
    {
      "Sid": "S3ObjectsManagement",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::cime-agent-memory-ACCOUNT_ID/*",
        "arn:aws:s3:::cime-kb-documentos-ACCOUNT_ID/*"
      ]
    },
    {
      "Sid": "SecretsManagerSetup",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:CreateSecret",
        "secretsmanager:DescribeSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:UpdateSecret",
        "secretsmanager:DeleteSecret",
        "secretsmanager:TagResource",
        "secretsmanager:PutResourcePolicy",
        "secretsmanager:GetResourcePolicy",
        "secretsmanager:RotateSecret"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:cime/pipefy/api-token*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:cime/ses/smtp-credentials*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:cime/tesoreria/endpoint-key*",
        "arn:aws:secretsmanager:us-east-1:ACCOUNT_ID:secret:cime/comercial/slack-webhook*"
      ]
    },
    {
      "Sid": "SESConfiguration",
      "Effect": "Allow",
      "Action": [
        "ses:VerifyDomainIdentity",
        "ses:VerifyDomainDkim",
        "ses:GetIdentityVerificationAttributes",
        "ses:GetIdentityDkimAttributes",
        "ses:CreateConfigurationSet",
        "ses:DescribeConfigurationSet",
        "ses:DeleteConfigurationSet",
        "ses:CreateConfigurationSetEventDestination",
        "ses:VerifyEmailIdentity",
        "ses:ListIdentities",
        "ses:GetAccountSendingEnabled"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        }
      }
    },
    {
      "Sid": "IAMRoleForAgent",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:TagRole",
        "iam:PassRole",
        "iam:CreatePolicy",
        "iam:DeletePolicy",
        "iam:GetPolicy",
        "iam:GetPolicyVersion",
        "iam:CreatePolicyVersion"
      ],
      "Resource": [
        "arn:aws:iam::ACCOUNT_ID:role/cime-agent-*",
        "arn:aws:iam::ACCOUNT_ID:policy/cime-agent-*"
      ]
    },
    {
      "Sid": "CloudFormationOrCDK",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateStack",
        "cloudformation:UpdateStack",
        "cloudformation:DeleteStack",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:GetTemplate",
        "cloudformation:ListStackResources",
        "cloudformation:CreateChangeSet",
        "cloudformation:ExecuteChangeSet",
        "cloudformation:DescribeChangeSet",
        "cloudformation:DeleteChangeSet"
      ],
      "Resource": "arn:aws:cloudformation:us-east-1:ACCOUNT_ID:stack/cime-*/*"
    },
    {
      "Sid": "CDKBootstrapBucket",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::cdk-*-assets-ACCOUNT_ID-us-east-1",
        "arn:aws:s3:::cdk-*-assets-ACCOUNT_ID-us-east-1/*"
      ]
    },
    {
      "Sid": "CDKSSMParameter",
      "Effect": "Allow",
      "Action": [
        "ssm:GetParameter",
        "ssm:PutParameter"
      ],
      "Resource": "arn:aws:ssm:us-east-1:ACCOUNT_ID:parameter/cdk-bootstrap/*"
    }
  ]
}
```

> ⚠️ **IMPORTANTE:** Reemplaza todas las apariciones de `ACCOUNT_ID` con el número de 12 dígitos de la cuenta AWS. Lo encuentras en la esquina superior derecha de la consola AWS.

#### Nombre de la política

Guárdala con el nombre: `cime-developer-policy`

#### Pasos en la consola AWS (resumidos)

1. **Crear la política:**
   - Ve a: IAM → Policies → Create policy
   - Selecciona la pestaña **JSON**
   - Pega el JSON de arriba (reemplazando ACCOUNT_ID)
   - Click "Next" → nombre: `cime-developer-policy` → Create policy

2. **Crear el usuario:**
   - Ve a: IAM → Users → Create user
   - Nombre: `cime-developer`
   - NO marques "Provide user access to the AWS Management Console" (a menos que quieras)
   - Click "Next"
   - Selecciona "Attach policies directly"
   - Busca `cime-developer-policy` y selecciónala
   - Click "Next" → Create user

3. **Generar Access Key:**
   - Click en el usuario `cime-developer` recién creado
   - Pestaña "Security credentials"
   - Sección "Access keys" → Click "Create access key"
   - Selecciona "Command Line Interface (CLI)"
   - Marca el checkbox de confirmación → Next → Create access key
   - **COPIA AMBOS VALORES** (Access Key ID y Secret Access Key)
   - ⚠️ El Secret Access Key solo se muestra UNA VEZ

#### Cómo enviarme las credenciales de forma segura

Elige UNA de estas opciones (de más segura a menos segura):

| Opción | Cómo |
|--------|------|
| 🟢 Mejor | Usa [onetimesecret.com](https://onetimesecret.com) — pega las credenciales, genera un enlace temporal que se destruye al leerlo |
| 🟡 Buena | Envía el Access Key ID por un canal (email) y el Secret por otro (WhatsApp/llamada) |
| 🔴 Nunca | No envíes ambas credenciales juntas en un email o chat sin cifrar |

#### ¿Qué NO puede hacer este usuario?

Para tu tranquilidad, este usuario NO puede:
- Crear/eliminar otros usuarios IAM
- Acceder a EC2, RDS, Lambda, ni otros servicios no listados
- Ver información de billing o costos
- Modificar recursos fuera del prefijo `cime-`
- Acceder a secretos que no empiecen con `cime/`

---

### 📋 FIN DEL DOCUMENTO PARA EL ADMINISTRADOR 📋

---

## 3. Recibir las Credenciales

Cuando el administrador te envíe las credenciales, tendrás dos valores:

```
Access Key ID:     AKIAXXXXXXXXXXXXXXXX
Secret Access Key: XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

**Guárdalos temporalmente** en un lugar seguro (un gestor de contraseñas como 1Password, Bitwarden, o un archivo local que borres después de configurar).

---

## 4. Instalar AWS CLI

AWS CLI es el programa que te permite hablar con AWS desde tu terminal.

### En Windows (tu sistema actual)

#### Opción A: Instalador oficial (recomendada)

1. Abre tu navegador
2. Ve a: https://awscli.amazonaws.com/AWSCLIV2.msi
3. Se descargará un archivo `.msi`
4. Haz doble click en el archivo descargado
5. Sigue el asistente: Next → Next → Install → Finish
6. **Cierra y vuelve a abrir** cualquier terminal/CMD que tengas abierta

#### Opción B: Desde PowerShell (si prefieres terminal)

Abre PowerShell **como Administrador** (click derecho → "Run as Administrator") y ejecuta:

```powershell
msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2.msi /quiet
```

Espera ~2 minutos. Cierra y vuelve a abrir la terminal.

### Verificar instalación

Abre una **nueva** ventana de CMD o PowerShell y escribe:

```cmd
aws --version
```

Deberías ver algo como:

```
aws-cli/2.x.x Python/3.x.x Windows/10 exe/AMD64
```

Si ves un error "aws no se reconoce como comando", cierra la terminal, ábrela de nuevo e intenta otra vez. Si persiste, reinicia tu computadora.

---

## 5. Configurar Credenciales

Ahora vas a guardar tus credenciales en tu máquina para que AWS CLI las use automáticamente.

### Paso a paso

1. Abre CMD o PowerShell (no necesita ser como Administrador)

2. Escribe este comando y presiona Enter:

```cmd
aws configure --profile cime-dev
```

3. Te pedirá 4 datos. Escribe cada uno y presiona Enter:

```
AWS Access Key ID [None]: AKIAXXXXXXXXXXXXXXXX
AWS Secret Access Key [None]: XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
Default region name [None]: us-east-1
Default output format [None]: json
```

   - En el primer campo, pega tu Access Key ID
   - En el segundo, pega tu Secret Access Key
   - En región, escribe `us-east-1`
   - En formato, escribe `json`

4. ¡Listo! Las credenciales se guardaron en tu carpeta de usuario.

### Configurar el perfil como predeterminado para el proyecto

Para no tener que escribir `--profile cime-dev` en cada comando, establece una variable de entorno.

**En CMD:**
```cmd
set AWS_PROFILE=cime-dev
```

**En PowerShell:**
```powershell
$env:AWS_PROFILE = "cime-dev"
```

> ⚠️ Esto solo dura mientras la terminal esté abierta. Si la cierras y abres otra, debes ejecutarlo de nuevo.

#### (Opcional) Hacer permanente la variable de entorno

**En PowerShell como Administrador:**
```powershell
[System.Environment]::SetEnvironmentVariable("AWS_PROFILE", "cime-dev", "User")
```

Esto persiste entre sesiones.

---

## 6. Verificar Conexión

Ejecuta este comando para confirmar que todo funciona:

```cmd
aws sts get-caller-identity --profile cime-dev
```

Si todo está bien, verás una respuesta como:

```json
{
    "UserId": "AIDAXXXXXXXXXXXXXXXXX",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/cime-developer"
}
```

### ¿Qué significa cada campo?

| Campo | Significado |
|-------|-------------|
| `UserId` | Identificador interno de tu usuario |
| `Account` | El número de 12 dígitos de la cuenta AWS |
| `Arn` | La "dirección" completa de tu usuario en AWS |

Si ves esta respuesta, **¡felicidades!** Ya estás conectado a AWS y listo para desplegar infraestructura.

---

## 7. Problemas Frecuentes

### "aws no se reconoce como un comando"

**Causa:** AWS CLI no se instaló correctamente o la terminal no se actualizó.

**Solución:**
1. Cierra TODAS las terminales
2. Abre una terminal nueva
3. Intenta `aws --version` de nuevo
4. Si sigue fallando, reinstala AWS CLI con el instalador .msi

---

### "An error occurred (InvalidClientTokenId)"

**Causa:** El Access Key ID está mal copiado o el usuario fue eliminado.

**Solución:**
1. Ejecuta `aws configure --profile cime-dev` de nuevo
2. Pega el Access Key ID con cuidado (sin espacios al inicio/final)
3. Verifica con el administrador que el usuario sigue activo

---

### "An error occurred (SignatureDoesNotMatch)"

**Causa:** El Secret Access Key está mal copiado.

**Solución:**
1. Ejecuta `aws configure --profile cime-dev` de nuevo
2. Pega el Secret Access Key con cuidado
3. Asegúrate de no haber incluido espacios extra

---

### "An error occurred (AccessDenied)"

**Causa:** El usuario no tiene permisos para la acción que intentas.

**Solución:**
1. Verifica que el administrador adjuntó la política `cime-developer-policy`
2. Verifica que `ACCOUNT_ID` fue reemplazado correctamente en la política
3. Si el error menciona un servicio específico, podría faltar un permiso — consulta con el administrador

---

### "Unable to locate credentials"

**Causa:** No configuraste las credenciales o no estás usando el perfil correcto.

**Solución:**
```cmd
aws configure --profile cime-dev
```
Y luego:
```cmd
set AWS_PROFILE=cime-dev
```

---

## Resumen de Comandos Clave

| Qué quieres hacer | Comando |
|-------------------|---------|
| Verificar que AWS CLI está instalado | `aws --version` |
| Configurar credenciales | `aws configure --profile cime-dev` |
| Activar el perfil en esta terminal | `set AWS_PROFILE=cime-dev` |
| Verificar conexión | `aws sts get-caller-identity --profile cime-dev` |
| Ver qué perfil estás usando | `aws configure list --profile cime-dev` |

---

## Próximos Pasos

Una vez que tengas la conexión verificada (sección 6), estarás listo para:

1. Ejecutar el código de infraestructura (CDK/CloudFormation) para crear los recursos de la Tarea 2
2. Desplegar DynamoDB, S3, Secrets Manager y configurar SES

¿Dudas? Pregúntame en cualquier momento.
