# Calculadora de Costos AWS — Agente Comercial IA CIME Power Systems

## Fecha: Agosto 2026
## Region: us-east-1 (N. Virginia)
## Moneda: USD (con conversiones a MXN al final)

---

## 1. Supuestos del Escenario

Basado en el plan del proyecto:

| Parametro | Valor |
|-----------|-------|
| Polizas gestionadas/mes | 30 |
| Clientes contactados/mes | ~30 |
| Mensajes promedio por poliza (ida y vuelta) | 6 (3 del agente + 3 del cliente) |
| Tokens promedio por interaccion del agente (input) | ~2,000 |
| Tokens promedio por respuesta del agente (output) | ~500 |
| Tool calls promedio por sesion de renovacion | 5 (consultar_pipefy, enviar_correo, actualizar_pipefy, notificar_tesoreria, escalar_humano) |
| Consultas a Knowledge Base por sesion | 2 |
| Documentos en Knowledge Base | ~20 documentos (reglas comerciales, catalogo, FAQs, mensajes) |
| Tamano estimado de documentos KB | ~500 KB (~0.5 MB de raw data) |

---

## 2. Modelos de Precios Considerados

### Opcion A: Amazon Nova Lite (RECOMENDADA para MVP - Costo minimo)

| Concepto | Precio |
|----------|--------|
| Input tokens | $0.06 / 1M tokens |
| Output tokens | $0.24 / 1M tokens |

### Opcion B: Claude Sonnet 4.6 (Mayor calidad de respuesta)

| Concepto | Precio |
|----------|--------|
| Input tokens | $3.00 / 1M tokens |
| Output tokens | $15.00 / 1M tokens |

### Opcion C: Claude Sonnet 5 (Precio introductorio hasta Ago 2026)

| Concepto | Precio |
|----------|--------|
| Input tokens | $2.00 / 1M tokens (despues $3.00) |
| Output tokens | $10.00 / 1M tokens (despues $15.00) |

---

## 3. Calculo Detallado — Escenario Base (30 polizas/mes)

### 3.1 Amazon Bedrock — Modelo Fundacional

**Tokens por sesion de renovacion completa:**
- 3 interacciones del agente x 2,000 tokens input = 6,000 tokens input
- 3 respuestas del agente x 500 tokens output = 1,500 tokens output
- Overhead de system prompt + contexto KB = ~3,000 tokens input adicionales
- **Total por sesion: ~9,000 input tokens + 1,500 output tokens**

**Volumen mensual (30 polizas):**
- Input: 30 x 9,000 = 270,000 tokens
- Output: 30 x 1,500 = 45,000 tokens

| Modelo | Costo Input | Costo Output | **Total/mes** |
|--------|-------------|--------------|---------------|
| Nova Lite | 270K/1M x $0.06 = $0.016 | 45K/1M x $0.24 = $0.011 | **$0.03** |
| Claude Sonnet 4.6 | 270K/1M x $3.00 = $0.81 | 45K/1M x $15.00 = $0.68 | **$1.49** |
| Claude Sonnet 5 (intro) | 270K/1M x $2.00 = $0.54 | 45K/1M x $10.00 = $0.45 | **$0.99** |

---

### 3.2 Amazon Bedrock AgentCore — Runtime (microVMs)

**Supuestos por sesion:**
- Duracion total de sesion: ~30 segundos
- I/O wait (esperando LLM, APIs): ~70% del tiempo = 21 seg inactivo
- Procesamiento activo CPU: ~9 segundos
- CPU utilizado: 1 vCPU
- Memoria peak: 512 MB (0.5 GB)

**Calculo por sesion:**
- CPU: 9 seg x 1 vCPU x ($0.0895/3600) = $0.000224
- Memoria: 30 seg x 0.5 GB x ($0.00945/3600) = $0.0000394
- **Total por sesion: $0.000263**

**Mensual (30 polizas x 3 interacciones = 90 sesiones):**
- **Total Runtime: $0.024**

---

### 3.3 Amazon Bedrock AgentCore — Gateway

**Tool calls por poliza:** 5 calls promedio
**Mensual:** 30 polizas x 5 = 150 tool calls

| Concepto | Calculo | Costo |
|----------|---------|-------|
| InvokeTool | 150 calls x $5/1M = $0.00075 | $0.001 |
| SearchToolIndex | 5 tools x $0.02/100 = $0.001 | $0.001 |
| **Total Gateway/mes** | | **$0.002** |

---

### 3.4 Amazon Bedrock AgentCore — Memory

**Short-term memory (eventos por sesion):** 6 eventos por poliza (3 ida + 3 vuelta)
**Long-term memory:** 30 records almacenados (historial por cliente)
**Retrieval calls:** 30/mes (1 por poliza al iniciar)

| Concepto | Calculo | Costo |
|----------|---------|-------|
| Short-term events | 30 x 6 = 180 eventos x $0.25/1000 | $0.045 |
| Long-term storage | 30 records x $0.75/1000 | $0.023 |
| Long-term retrieval | 30 calls x $0.50/1000 | $0.015 |
| **Total Memory/mes** | | **$0.08** |

---

### 3.5 Amazon Bedrock AgentCore — Policy

**Authorization requests:** 1 por cada tool call = 150/mes

| Concepto | Calculo | Costo |
|----------|---------|-------|
| Auth requests | 150 x $0.025/1000 | $0.004 |
| **Total Policy/mes** | | **$0.004** |

---

### 3.6 Amazon Bedrock AgentCore — Identity

**Costo:** Incluido sin cargo adicional al usar AgentCore Runtime y Gateway.

| Concepto | Costo |
|----------|-------|
| **Total Identity/mes** | **$0.00** |

---

### 3.7 Amazon Bedrock AgentCore — Observability

**Supuestos:** ~90 sesiones generan ~5 spans c/u = 450 spans (~1 KB c/u = 0.45 MB)
**Logs:** ~0.3 MB de event logging

| Concepto | Calculo | Costo |
|----------|---------|-------|
| Span ingestion | 0.00045 GB x $0.35 | $0.0002 |
| Event logging | 0.0003 GB x $0.50 | $0.0002 |
| **Total Observability/mes** | | **$0.001** |

---

### 3.8 Amazon Bedrock — Managed Knowledge Base

**Configuracion:**
- Documentos: ~20 docs (reglas comerciales, catalogo, FAQs, mensajes base)
- Raw data indexado: ~0.5 MB (0.0005 GB)
- Retrieval queries/mes: 30 polizas x 2 consultas = 60 queries

| Concepto | Calculo | Costo |
|----------|---------|-------|
| Index Storage | 0.0005 GB x $5.00/GB | $0.003 |
| Multimodal Parsing | Incluido | $0.00 |
| Embeddings Generation | Incluido | $0.00 |
| Standard Retrieval | 60/1000 x $1.00 | $0.06 |
| Re-ranking | Incluido | $0.00 |
| **Total Knowledge Base/mes** | | **$0.06** |

> **NOTA IMPORTANTE:** Managed Knowledge Base con parser, embeddings y reranker incluidos tiene un minimo real de ~$5/GB. Con solo 0.5 MB de datos, el costo es practicamente nulo. Si se usa Self-Managed KB con S3 Vectors como vector store, los costos de storage son aun menores.

---

### 3.9 Amazon S3 — Almacenamiento de Documentos

| Concepto | Calculo | Costo |
|----------|---------|-------|
| Storage (documentos KB) | 0.001 GB x $0.023/GB | $0.00003 |
| PUT/GET requests | ~100 req x $0.005/1000 | $0.0005 |
| **Total S3/mes** | | **$0.001** |

---

### 3.10 Amazon SES — Envio de Correos

**Supuestos:**
- Correos enviados/mes: 30 polizas x 3 mensajes promedio = 90 correos
- Primer ano: 3,000 correos gratis/mes (Free Tier)

| Concepto | Calculo | Costo |
|----------|---------|-------|
| Emails enviados (Free Tier) | 90 correos (dentro de 3,000 gratis) | $0.00 |
| Emails enviados (sin Free Tier) | 90/1000 x $0.10 | $0.009 |
| **Total SES/mes** | | **$0.00 — $0.009** |

---

## 4. RESUMEN DE COSTOS — Escenario Base (30 polizas/mes)

### Con Amazon Nova Lite (RECOMENDADO para MVP)

| Servicio | Costo Mensual USD |
|----------|-------------------|
| Bedrock — Nova Lite (modelo) | $0.03 |
| AgentCore Runtime | $0.024 |
| AgentCore Gateway | $0.002 |
| AgentCore Memory | $0.08 |
| AgentCore Policy | $0.004 |
| AgentCore Identity | $0.00 |
| AgentCore Observability | $0.001 |
| Managed Knowledge Base | $0.06 |
| Amazon S3 | $0.001 |
| Amazon SES | $0.00 |
| **TOTAL MENSUAL** | **~$0.20 USD** |
| **TOTAL ANUAL** | **~$2.40 USD** |

### Con Claude Sonnet 4.6 (Mayor calidad)

| Servicio | Costo Mensual USD |
|----------|-------------------|
| Bedrock — Claude Sonnet 4.6 | $1.49 |
| AgentCore Runtime | $0.024 |
| AgentCore Gateway | $0.002 |
| AgentCore Memory | $0.08 |
| AgentCore Policy | $0.004 |
| AgentCore Identity | $0.00 |
| AgentCore Observability | $0.001 |
| Managed Knowledge Base | $0.06 |
| Amazon S3 | $0.001 |
| Amazon SES | $0.00 |
| **TOTAL MENSUAL** | **~$1.66 USD** |
| **TOTAL ANUAL** | **~$19.92 USD** |

---

## 5. Escenarios de Crecimiento

### Escenario Optimista: 100 polizas/mes

| Modelo | Costo Mensual USD |
|--------|-------------------|
| Nova Lite | ~$0.67 |
| Claude Sonnet 4.6 | ~$5.50 |

### Escenario Agresivo: 300 polizas/mes

| Modelo | Costo Mensual USD |
|--------|-------------------|
| Nova Lite | ~$2.00 |
| Claude Sonnet 4.6 | ~$16.50 |

### Escenario Maximo: 1,000 polizas/mes

| Modelo | Costo Mensual USD |
|--------|-------------------|
| Nova Lite | ~$6.70 |
| Claude Sonnet 4.6 | ~$55.00 |

---

## 6. Costos Adicionales a Considerar (No incluidos en calculo base)

| Concepto | Estimacion | Notas |
|----------|-----------|-------|
| Zapier (plan existente de CIME) | $0 adicional | Ya lo tiene CIME |
| Dominio de correo / SES Setup | $0 — $1/mes | Verificacion de dominio |
| CloudWatch (logs adicionales) | $0.50 — $5/mes | Depende del nivel de logging |
| Data Transfer (egress) | ~$0.09/GB | Minimo para este caso |
| AWS Free Tier credits ($200) | -$200 | Disponible para nuevas cuentas |

---

## 7. Conversion a Pesos Mexicanos (MXN)

**Tipo de cambio estimado: 1 USD = $19.50 MXN** (Agosto 2026)

| Escenario | USD/mes | MXN/mes | MXN/ano |
|-----------|---------|---------|---------|
| Base (30 polizas) — Nova Lite | $0.20 | $3.90 | $46.80 |
| Base (30 polizas) — Claude Sonnet | $1.66 | $32.37 | $388.44 |
| Crecimiento (100 polizas) — Nova Lite | $0.67 | $13.07 | $156.78 |
| Crecimiento (100 polizas) — Claude Sonnet | $5.50 | $107.25 | $1,287.00 |
| Agresivo (300 polizas) — Claude Sonnet | $16.50 | $321.75 | $3,861.00 |
| Maximo (1,000 polizas) — Claude Sonnet | $55.00 | $1,072.50 | $12,870.00 |

---

## 8. Analisis ROI

### Caso Base: 30 polizas/mes con Claude Sonnet

| Concepto | Valor |
|----------|-------|
| Costo AWS mensual | ~$1.66 USD ($32 MXN) |
| Costo AWS anual | ~$19.92 USD ($389 MXN) |
| Revenue por 1 poliza adicional renovada | $25,000 MXN |
| **Break-even** | **<1 poliza adicional renovada por AÑO** |
| Si se recuperan 2 polizas adicionales/mes | $50,000 MXN/mes adicionales |
| Si se recuperan 5 polizas adicionales/mes | $125,000 MXN/mes adicionales |
| **ROI anual (conservador, 2 polizas/mes)** | **> 150,000% ROI** |

### Conclusion del ROI

El costo de infraestructura AWS para este caso de uso es **practicamente insignificante** comparado con el valor comercial de cada poliza renovada ($25,000 MXN). Incluso con el modelo mas caro (Claude Sonnet) y el escenario mas agresivo (1,000 polizas/mes), el costo anual no supera $13,000 MXN — equivalente a menos de una poliza renovada.

---

## 9. Recomendacion de Implementacion

### Para el MVP (Dia de Prototipado Intensivo):

1. **Modelo:** Iniciar con **Amazon Nova Lite** para el MVP
   - Costo negligible (~$0.20/mes)
   - Suficiente para validar el flujo completo
   - Si la calidad de respuesta no es satisfactoria, migrar a Claude Sonnet sin cambios de arquitectura

2. **Knowledge Base:** Usar **Managed Knowledge Base**
   - Parser, embeddings y reranker incluidos sin cargo extra
   - Storage minimo para 20 documentos = costo practicamente $0
   - Sin necesidad de gestionar infraestructura de vectores

3. **SES:** Aprovechar el **Free Tier** (3,000 emails/mes gratis por 12 meses)
   - 90 correos/mes esta muy por debajo del limite gratuito

4. **Free Tier Credits:** Si es cuenta nueva, aplicar los **$200 USD de creditos gratuitos**
   - Cubre mas de 100 anos de operacion con Nova Lite al volumen actual

### Para Produccion:

- Migrar a **Claude Sonnet** para mejor calidad conversacional con clientes reales
- Agregar **WhatsApp Business** (costo adicional de Meta, no de AWS)
- El costo total AWS seguira siendo < $20 USD/mes incluso con crecimiento 10x

---

## 10. Notas Importantes

1. **Los costos de AWS son extremadamente bajos** para este volumen (30 polizas/mes). El principal costo del proyecto NO es la infraestructura — es el desarrollo, configuracion y mantenimiento del agente.

2. **No se requiere OpenSearch ni Aurora** — Managed Knowledge Base con S3 incluye todo lo necesario, eliminando los costos de ~$345/mes que tendria OpenSearch Serverless.

3. **AgentCore es pay-per-use** — No hay cargos fijos mensuales. Si el agente no se usa, no se paga nada.

4. **El harness de AgentCore es gratuito** — Solo se paga por los recursos subyacentes consumidos.

5. **Precios sujetos a cambio** — Estos son precios publicados a Agosto 2026. Verificar siempre en https://aws.amazon.com/bedrock/pricing/ y https://aws.amazon.com/bedrock/agentcore/pricing/

---

## 11. Fuentes de Precios

- [Amazon Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/)
- [Amazon Bedrock AgentCore Pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- [Amazon SES Pricing](https://aws.amazon.com/ses/pricing/)
- [Amazon S3 Pricing](https://aws.amazon.com/s3/pricing/)
- [CloudZero - Amazon Bedrock Pricing 2026](https://www.cloudzero.com/blog/amazon-bedrock-pricing/)

*Content was rephrased for compliance with licensing restrictions*

---

*Documento preparado por Codster · Agosto 2026*
*Confidencial — CIME Power Systems + Codster + AWS*
