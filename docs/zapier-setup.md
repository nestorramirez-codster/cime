# Configuración de Zapier — Integración Pipefy → Agente Comercial IA

## Resumen

Este documento describe la configuración paso a paso del Zap que conecta el tablero operativo de Pipefy con el Agente Comercial IA de CIME Power Systems. El Zap detecta pólizas que entran en la Ventana Comercial (30 días antes del vencimiento) o que vencen sin renovar, y activa al agente mediante un webhook HTTP POST.

**Requisitos cubiertos:** 1.1, 1.2

---

## Prerrequisitos

1. Cuenta activa en [Zapier](https://zapier.com) (plan Team o superior recomendado para multi-step Zaps)
2. Cuenta de Pipefy con acceso API habilitado y token de integración generado
3. Endpoint del webhook del agente desplegado y accesible:
   - **URL formato:** `https://<API_GATEWAY_URL>/webhook/activar`
   - Alternativamente: URL de función Lambda si se usa invocación directa
4. El tablero operativo de Pipefy debe tener la columna **"Dentro de Ventana Comercial"** configurada

---

## Paso 1: Crear el Zap

1. Ir a [zapier.com/app/zaps](https://zapier.com/app/zaps) → **Create Zap**
2. Nombrar el Zap: `CIME - Activación Agente Renovación Pólizas`

---

## Paso 2: Configurar el Trigger (Pipefy)

### Trigger A: Card entra en columna "Dentro de Ventana Comercial"

| Campo | Valor |
|-------|-------|
| **App** | Pipefy |
| **Trigger Event** | Card Moved to Phase |
| **Account** | (Seleccionar cuenta de CIME Power Systems) |
| **Pipe** | Tablero Operativo de Pólizas de Mantenimiento |
| **Phase (Destination)** | `Dentro de Ventana Comercial` |

### Trigger B: Card vence sin renovar (alternativo)

Para capturar pólizas que vencen sin haber sido renovadas, configurar un **segundo Zap** o usar un filtro adicional:

| Campo | Valor |
|-------|-------|
| **App** | Pipefy |
| **Trigger Event** | Card Field Updated |
| **Account** | (Seleccionar cuenta de CIME Power Systems) |
| **Pipe** | Tablero Operativo de Pólizas de Mantenimiento |
| **Field** | `Estado de Renovación` |
| **New Value** | `Vencida sin renovar` |

> **Nota:** Si Pipefy no soporta el trigger por cambio de campo específico, usar un Zap con trigger tipo "Schedule" (cada 24 horas) que consulte la API de Pipefy buscando cards con `fecha_vencimiento <= hoy` y estado distinto a "Renovación confirmada".

---

## Paso 3: Configurar la Action (Webhook HTTP POST)

| Campo | Valor |
|-------|-------|
| **App** | Webhooks by Zapier |
| **Action Event** | POST |
| **URL** | `https://<API_GATEWAY_URL>/webhook/activar` |
| **Payload Type** | `json` |
| **Content-Type** | `application/json` |

---

## Paso 4: Mapeo de Campos Pipefy → ActivationPayload

La siguiente tabla describe el mapeo exacto entre los campos del card de Pipefy y los campos del `ActivationPayload` que espera el webhook del agente:

| Campo Pipefy (Card Field) | Campo ActivationPayload | Tipo | Validación | Ejemplo |
|---|---|---|---|---|
| `Card ID` o `Número de Póliza` | `poliza_id` | `string` | No vacío | `"POL-2024-001"` |
| `Nombre del Cliente` | `cliente_nombre` | `string` | No vacío | `"Grupo Industrial Norte S.A. de C.V."` |
| `Correo Electrónico` | `cliente_email` | `string` | Formato RFC 5321 válido | `"contacto@ginorte.com.mx"` |
| `Fecha de Vencimiento` | `fecha_vencimiento` | `string` (ISO 8601) | Formato `YYYY-MM-DD`, fecha válida | `"2025-08-15"` |
| `Precio de Renovación` | `precio_renovacion` | `number` | Valor numérico > 0 | `45000.00` |
| `Equipo Cubierto` | `equipo_nombre` | `string` | No vacío | `"UPS Liebert GXT5 20kVA"` |

### Configuración del Body en Zapier

En la sección **Data** del webhook POST, configurar cada campo:

```json
{
  "poliza_id": "{{Card ID}}",
  "cliente_nombre": "{{Nombre del Cliente}}",
  "cliente_email": "{{Correo Electrónico}}",
  "fecha_vencimiento": "{{Fecha de Vencimiento}}",
  "precio_renovacion": {{Precio de Renovación}},
  "equipo_nombre": "{{Equipo Cubierto}}"
}
```

> **Importante:** El campo `precio_renovacion` NO debe tener comillas — debe enviarse como número, no como string. Verificar que el campo de Pipefy no incluya símbolo de moneda ($) ni separadores de miles.

### Formato de fecha

Pipefy puede retornar fechas en distintos formatos. Usar un paso intermedio de **Formatter by Zapier** si es necesario para convertir al formato ISO 8601 (`YYYY-MM-DD`):

1. Agregar step: **Formatter by Zapier** → **Date/Time** → **Format**
2. Input: `{{Fecha de Vencimiento}}`
3. To Format: `YYYY-MM-DD`
4. Usar el output formateado en el webhook POST

---

## Paso 5: Configurar Headers del Webhook

| Header | Valor | Descripción |
|--------|-------|-------------|
| `Content-Type` | `application/json` | Tipo de contenido del body |
| `X-Zapier-Source` | `cime-pipefy-renovacion` | Identificador del origen para logging |
| `Authorization` | `Bearer <API_KEY>` | (Opcional) API key si el endpoint requiere autenticación |

---

## Paso 6: Manejo de Errores del Zap

### Configuración de Retry automático

Zapier reintenta automáticamente las acciones que fallan con errores HTTP 5xx. Configurar el comportamiento de retry:

| Configuración | Valor | Descripción |
|---|---|---|
| **Auto-retry on 5xx** | ✅ Habilitado | Zapier reintentará automáticamente en errores del servidor |
| **Número de reintentos** | Hasta 5 (comportamiento por defecto de Zapier) | Reintentos con backoff exponencial |
| **Errores 4xx** | ❌ No reintentar | Errores de cliente indican payload inválido — no se reintenta |

### Configuración de alertas por error

1. Ir a **Settings** → **Advanced Settings** del Zap
2. Habilitar **Error notifications** → Email al administrador del sistema
3. Configurar **Autoreplay** para errores transitorios (5xx)

### Comportamiento esperado por código HTTP

| Código HTTP | Significado | Acción de Zapier |
|---|---|---|
| `200` | Sesión aceptada exitosamente | Zap completado ✅ |
| `400` | Payload inválido (campos faltantes o mal formateados) | Zap falla ❌ — revisar mapeo de campos |
| `401` / `403` | Error de autenticación | Zap falla ❌ — verificar API key |
| `429` | Rate limit excedido | Reintentar con backoff |
| `500` | Error interno del servidor | Reintentar automáticamente |
| `502` / `503` | Servicio no disponible | Reintentar automáticamente |
| `504` | Timeout del gateway | Reintentar automáticamente |

### Timeout

El endpoint del agente debe responder en **menos de 30 segundos** (Req 12.6). Si el Zap reporta timeouts frecuentes:
- Verificar el cold start de la Lambda/Runtime
- Considerar provisioned concurrency si hay muchas activaciones simultáneas

---

## Paso 7: Filtro Opcional (Evitar duplicados)

Para evitar activaciones duplicadas cuando un card ya fue procesado:

1. Agregar step: **Filter by Zapier** entre el Trigger y la Action
2. Condición: `Card Phase` → **does not equal** → `Renovación confirmada`
3. Condición adicional (AND): `Card Phase` → **does not equal** → `Escalado a humano`

Esto previene que el Zap se active para pólizas que ya están en estados terminales.

---

## Paso 8: Testing

### Prueba manual del Zap

1. En Zapier, hacer clic en **Test trigger** para obtener un card de ejemplo de Pipefy
2. Verificar que los campos se mapean correctamente en el preview del body JSON
3. Ejecutar **Test action** para enviar el POST al webhook
4. Verificar la respuesta esperada:

```json
{
  "status": "accepted",
  "session_id": "sess-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

### Prueba con cURL (validación directa del endpoint)

```bash
curl -X POST https://<API_GATEWAY_URL>/webhook/activar \
  -H "Content-Type: application/json" \
  -H "X-Zapier-Source: cime-pipefy-renovacion" \
  -d '{
    "poliza_id": "POL-TEST-001",
    "cliente_nombre": "Empresa de Prueba S.A.",
    "cliente_email": "test@empresa.com",
    "fecha_vencimiento": "2025-08-15",
    "precio_renovacion": 45000.00,
    "equipo_nombre": "UPS Liebert GXT5 20kVA"
  }'
```

**Respuesta esperada (200):**
```json
{
  "status": "accepted",
  "session_id": "sess-a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Respuesta de error (400) — payload inválido:**
```json
{
  "status": "error",
  "message": "Campos inválidos: cliente_email (formato no válido RFC 5321)"
}
```

### Verificación post-activación

Tras una activación exitosa, verificar en el tablero de Pipefy que:
1. El card cambió a estado **"Póliza detectada"**
2. La nota de la transición incluye el `session_id` y timestamp UTC

---

## Diagrama del Flujo Zapier

```
┌─────────────────────────────────────────────────────────────────┐
│                        ZAPIER ZAP                                │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │   TRIGGER    │───▶│   FILTER     │───▶│     ACTION        │  │
│  │              │    │  (Opcional)   │    │                   │  │
│  │ Pipefy:     │    │ Excluir:      │    │ Webhooks by       │  │
│  │ Card Moved  │    │ - Renovación  │    │ Zapier: POST      │  │
│  │ to Phase    │    │   confirmada  │    │                   │  │
│  │ "Dentro de  │    │ - Escalado a  │    │ URL: /webhook/    │  │
│  │  Ventana    │    │   humano      │    │       activar     │  │
│  │  Comercial" │    │               │    │                   │  │
│  └──────────────┘    └──────────────┘    │ Body: JSON con    │  │
│                                          │ ActivationPayload │  │
│                                          └───────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
                                          ┌───────────────────┐
                                          │  Agente Comercial │
                                          │  IA (Webhook)     │
                                          │                   │
                                          │  Respuesta:       │
                                          │  200 → Aceptado   │
                                          │  400 → Inválido   │
                                          │  5xx → Retry      │
                                          └───────────────────┘
```

---

## Notas de Mantenimiento

- **Cambio de URL del webhook:** Si se redesplega el endpoint (nueva Lambda o API Gateway), actualizar la URL en la Action del Zap
- **Nuevos campos en Pipefy:** Si se agregan campos al card de Pipefy, actualizar el mapeo en el body del webhook y la validación en `src/webhook/handler.py`
- **Rotación de API key:** Si el endpoint requiere autenticación, actualizar el header `Authorization` al rotar credenciales
- **Monitoreo:** Revisar el historial de ejecuciones del Zap semanalmente en [zapier.com/app/history](https://zapier.com/app/history) para detectar fallos recurrentes
