# Guía Paso a Paso: Configurar Amazon SES desde la Terminal

## ¿Qué es SES?

Amazon SES (Simple Email Service) es el servicio de AWS que permite enviar correos electrónicos. El agente lo usará para contactar a los clientes de CIME.

---

## Requisitos previos

Antes de empezar necesitas:

- [ ] Windows 10 o superior
- [ ] Conexión a internet
- [ ] Tus credenciales AWS (Access Key ID y Secret Access Key) — si no las tienes, sigue primero la `guia-credenciales-aws.md`
- [ ] Saber el dominio de correo de CIME (ej: `cime.com.mx`)

---

## PARTE 1: Instalar AWS CLI

### Paso 1.1 — Descargar el instalador

1. Abre tu navegador
2. Ve a esta dirección: https://awscli.amazonaws.com/AWSCLIV2.msi
3. Se descargará un archivo llamado `AWSCLIV2.msi`

### Paso 1.2 — Instalar

1. Ve a tu carpeta de Descargas
2. Haz **doble click** en `AWSCLIV2.msi`
3. Se abre un asistente de instalación:
   - Click en **Next**
   - Acepta los términos → **Next**
   - Deja la ruta por defecto → **Next**
   - Click en **Install**
   - Espera a que termine → Click en **Finish**

### Paso 1.3 — Verificar que se instaló

1. **Cierra** cualquier terminal o CMD que tengas abierta
2. Abre una **nueva** ventana de CMD:
   - Presiona la tecla `Windows`
   - Escribe `cmd`
   - Presiona Enter
3. Escribe lo siguiente y presiona Enter:

```cmd
aws --version
```

4. Deberías ver algo como:

```
aws-cli/2.17.x Python/3.11.x Windows/10 exe/AMD64
```

✅ Si ves eso, AWS CLI está instalado correctamente.

❌ Si dice "no se reconoce como un comando", cierra la terminal, ábrela de nuevo e intenta otra vez. Si sigue fallando, reinicia tu computadora.

---

## PARTE 2: Configurar tus credenciales AWS

### Paso 2.1 — Ejecutar el comando de configuración

En la misma terminal CMD, escribe:

```cmd
aws configure --profile cime-dev
```

Presiona Enter. Te pedirá 4 datos uno por uno:

### Paso 2.2 — Ingresar cada dato

```
AWS Access Key ID [None]: 
```
👉 Pega tu Access Key ID (el que te dio el administrador) y presiona Enter.

```
AWS Secret Access Key [None]: 
```
👉 Pega tu Secret Access Key y presiona Enter. **No verás los caracteres mientras pegas, es normal.**

```
Default region name [None]: 
```
👉 Escribe `us-east-1` y presiona Enter.

```
Default output format [None]: 
```
👉 Escribe `json` y presiona Enter.

### Paso 2.3 — Verificar que funciona

Escribe:

```cmd
aws sts get-caller-identity --profile cime-dev
```

Deberías ver algo como:

```json
{
    "UserId": "AIDAXXXXXXXXXXXXXXXXX",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/cime-developer"
}
```

✅ Si ves eso, estás conectado a AWS.

❌ Si ves un error, revisa la sección de problemas frecuentes en `guia-credenciales-aws.md`.

### Paso 2.4 — Activar el perfil para no repetir `--profile` cada vez

Escribe:

```cmd
set AWS_PROFILE=cime-dev
```

A partir de ahora, todos los comandos en esta terminal usarán tus credenciales automáticamente. **Si cierras la terminal y abres otra, debes ejecutar este comando de nuevo.**

---

## PARTE 3: Verificar una dirección de correo (Modo Sandbox — para desarrollo)

En el modo sandbox de SES solo puedes enviar correos **a direcciones que hayas verificado manualmente**. Esto es suficiente para desarrollo y pruebas.

### Paso 3.1 — Verificar tu propio correo (para poder recibir pruebas)

Escribe (reemplaza con tu email real):

```cmd
aws ses verify-email-identity --email-address tu-email@ejemplo.com
```

### Paso 3.2 — Revisar tu bandeja de entrada

1. Ve a tu correo electrónico
2. Busca un email de `no-reply-aws@amazon.com` con asunto "Amazon Web Services – Email Address Verification Request"
3. Haz click en el enlace del email

✅ Eso es todo. Tu dirección está verificada.

### Paso 3.3 — Verificar el correo del remitente (desde el que enviará el agente)

Si CIME ya te dio una dirección de envío (ej: `renovaciones@cime.com.mx`), verifícala también:

```cmd
aws ses verify-email-identity --email-address renovaciones@cime.com.mx
```

Alguien con acceso a esa bandeja debe hacer click en el link de verificación.

### Paso 3.4 — Confirmar qué direcciones están verificadas

```cmd
aws ses list-identities --identity-type EmailAddress
```

Verás algo como:

```json
{
    "Identities": [
        "tu-email@ejemplo.com",
        "renovaciones@cime.com.mx"
    ]
}
```

---

## PARTE 4: Verificar el dominio de CIME (necesario para producción)

Esto genera los registros DNS que debes pasarle al administrador del dominio.

### Paso 4.1 — Iniciar verificación del dominio

Escribe (reemplaza con el dominio real de CIME):

```cmd
aws ses verify-domain-identity --domain cime.com.mx
```

Respuesta:

```json
{
    "VerificationToken": "abc123XYZdef456..."
}
```

**Guarda ese token.** El admin del dominio necesita agregar este registro TXT:

```
Tipo:   TXT
Nombre: _amazonses.cime.com.mx
Valor:  abc123XYZdef456...
```

### Paso 4.2 — Generar registros DKIM

DKIM es lo que evita que los correos caigan en spam.

```cmd
aws ses verify-domain-dkim --domain cime.com.mx
```

Respuesta:

```json
{
    "DkimTokens": [
        "token1abc",
        "token2def",
        "token3ghi"
    ]
}
```

### Paso 4.3 — Preparar los registros DNS para el admin del dominio

Con los tokens del paso anterior, los registros a agregar son:

```
Tipo:   CNAME
Nombre: token1abc._domainkey.cime.com.mx
Valor:  token1abc.dkim.amazonses.com

Tipo:   CNAME
Nombre: token2def._domainkey.cime.com.mx
Valor:  token2def.dkim.amazonses.com

Tipo:   CNAME
Nombre: token3ghi._domainkey.cime.com.mx
Valor:  token3ghi.dkim.amazonses.com
```

### Paso 4.4 — Enviar los registros al admin del dominio

Copia y envíale algo como:

> "Necesito que agregues estos registros en el DNS de cime.com.mx para verificar el dominio en AWS:
>
> **1 registro TXT:**
> - Nombre: `_amazonses.cime.com.mx`
> - Valor: `[el token del paso 4.1]`
>
> **3 registros CNAME:**
> - `token1abc._domainkey.cime.com.mx` → `token1abc.dkim.amazonses.com`
> - `token2def._domainkey.cime.com.mx` → `token2def.dkim.amazonses.com`
> - `token3ghi._domainkey.cime.com.mx` → `token3ghi.dkim.amazonses.com`
>
> Son para que AWS autorice el envío de correos desde nuestro dominio sin caer en spam."

### Paso 4.5 — Esperar y verificar estado

La propagación DNS tarda entre 15 minutos y 72 horas (normalmente 1–2 horas).

Para verificar el estado:

```cmd
aws ses get-identity-verification-attributes --identities cime.com.mx
```

Cuando el admin haya agregado los registros y se propaguen, verás:

```json
{
    "VerificationAttributes": {
        "cime.com.mx": {
            "VerificationStatus": "Success",
            "VerificationToken": "abc123XYZdef456..."
        }
    }
}
```

Si dice `"Pending"`, los registros DNS aún no se propagan. Espera y vuelve a intentar.

Para ver el estado de DKIM:

```cmd
aws ses get-identity-dkim-attributes --identities cime.com.mx
```

Cuando funcione:

```json
{
    "DkimAttributes": {
        "cime.com.mx": {
            "DkimEnabled": true,
            "DkimVerificationStatus": "Success",
            "DkimTokens": ["token1abc", "token2def", "token3ghi"]
        }
    }
}
```

---

## PARTE 5: Crear un Configuration Set (para rastrear entregas)

Un configuration set permite rastrear si los correos se entregaron, rebotaron, etc.

### Paso 5.1 — Crear el configuration set

```cmd
aws ses create-configuration-set --configuration-set Name=cime-agent-tracking
```

Si no hay error, se creó correctamente. No da respuesta visible.

### Paso 5.2 — Verificar que existe

```cmd
aws ses describe-configuration-set --configuration-set-name cime-agent-tracking
```

Verás:

```json
{
    "ConfigurationSet": {
        "Name": "cime-agent-tracking"
    }
}
```

✅ Configuration set listo.

---

## PARTE 6: Enviar un correo de prueba

### Paso 6.1 — Enviar un correo simple

**Solo funciona entre direcciones verificadas** (modo sandbox).

```cmd
aws ses send-email --from renovaciones@cime.com.mx --destination ToAddresses=tu-email@ejemplo.com --message Subject={Data="Prueba SES"},Body={Text={Data="Este es un correo de prueba del agente CIME."}}
```

> ⚠️ Reemplaza `renovaciones@cime.com.mx` con la dirección verificada del remitente y `tu-email@ejemplo.com` con tu correo verificado.

Si todo funciona, verás:

```json
{
    "MessageId": "0100018a1234abcd-12345678-abcd-..."
}
```

### Paso 6.2 — Revisar tu bandeja

Ve a tu email. Deberías tener el correo de prueba. Revisa spam si no lo ves en la bandeja principal.

✅ **¡Felicidades! SES está configurado y funcionando.**

---

## PARTE 7: Solicitar salida de Sandbox (cuando estés listo para producción)

> ⚠️ NO hagas esto hasta que el agente esté probado y listo para enviar a clientes reales.

### Paso 7.1 — Abrir la solicitud

Esto se hace desde la **consola web** (no hay comando CLI para esto):

1. Ve a: https://console.aws.amazon.com/ses/home#/account
2. En "Account dashboard" verás un banner que dice "Your Amazon SES account is in the sandbox"
3. Click en **"Request production access"**

### Paso 7.2 — Llenar el formulario

| Campo | Qué poner |
|-------|-----------|
| Mail type | Transactional |
| Website URL | El sitio web de CIME (si tienen) |
| Use case description | "We send transactional emails for insurance policy renewals. Recipients are existing CIME customers whose policies are approaching expiration. Estimated volume: 50-200 emails per day. We handle bounces automatically and only send to customers who have an active policy with us." |
| Additional contacts | Tu email para recibir notificación de aprobación |
| Preferred contact language | English (responden más rápido) |

### Paso 7.3 — Esperar aprobación

AWS revisa manualmente. Tarda **24–48 horas hábiles**. Te notifican por email.

---

## Resumen de comandos

| Qué hace | Comando |
|----------|---------|
| Verificar correo individual | `aws ses verify-email-identity --email-address EMAIL` |
| Ver correos verificados | `aws ses list-identities --identity-type EmailAddress` |
| Verificar dominio | `aws ses verify-domain-identity --domain DOMINIO` |
| Generar DKIM | `aws ses verify-domain-dkim --domain DOMINIO` |
| Ver estado de verificación | `aws ses get-identity-verification-attributes --identities DOMINIO` |
| Ver estado DKIM | `aws ses get-identity-dkim-attributes --identities DOMINIO` |
| Crear configuration set | `aws ses create-configuration-set --configuration-set Name=NOMBRE` |
| Enviar correo de prueba | `aws ses send-email --from REMITENTE --destination ToAddresses=DESTINO --message Subject={Data="ASUNTO"},Body={Text={Data="CUERPO"}}` |

---

## ¿Qué hacer ahora?

| Situación | Acción |
|-----------|--------|
| Estás desarrollando (sin acceso real a AWS aún) | No hagas nada todavía. El código usa mocks. |
| Ya tienes credenciales AWS | Empieza por la Parte 3 (verificar tu email) para poder probar |
| El cliente ya te dio el dominio | Haz la Parte 4 y pasa los registros DNS |
| El agente ya funciona en pruebas | Haz la Parte 7 para salir de sandbox |

---

## Problemas frecuentes

### "An error occurred (AccessDenied) when calling the VerifyEmailIdentity operation"

Tu usuario IAM no tiene permisos de SES. Verifica con el admin que la política `cime-developer-policy` incluye el bloque de permisos SES.

### "Email address is not verified"

Estás en sandbox y la dirección destino no está verificada. Verifica primero la dirección con `verify-email-identity`.

### "MessageRejected: Email address not verified"

La dirección del **remitente** (from) no está verificada. Ejecuta `verify-email-identity` con esa dirección.

### El correo llega a spam

- Si estás usando solo dirección verificada (sin dominio): es normal en sandbox
- Si ya verificaste el dominio: espera a que DKIM esté en "Success"
- Verifica que SPF y DMARC también estén configurados (pregunta al admin DNS)

### "Throttling: Rate exceeded"

Estás en sandbox, el límite es 1 correo por segundo y 200 por día. No te preocupes, en producción el límite sube.
