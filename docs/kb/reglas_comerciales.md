# Reglas Comerciales — CIME Power Systems
## Renovación de Pólizas de Mantenimiento

---

## 1. Ventana Comercial

- **Definición:** Período de 30 días naturales antes de la fecha de vencimiento de la póliza.
- **Inicio:** 30 días antes de `fecha_vencimiento`.
- **Cierre:** Día de `fecha_vencimiento` (inclusive).
- Durante la Ventana Comercial, el Agente inicia contacto proactivo con el cliente para gestionar la renovación.
- Si la póliza ya venció (fecha actual > fecha_vencimiento), se aplica flujo de recuperación post-vencimiento.

---

## 2. Descuento Pre-Vencimiento

- **Porcentaje:** 5% de descuento sobre el precio base de renovación.
- **Condición:** El cliente confirma su interés de renovar ANTES de la fecha de vencimiento de su póliza.
- **Cálculo:** `precio_final = round(precio_base * 0.95, 2)`
- **Restricciones:**
  - El Agente NO puede ofrecer descuentos distintos al 5%.
  - El Agente NO puede negociar condiciones especiales, plazos diferidos ni extensiones de cobertura.
  - El Agente NO puede acumular descuentos ni aplicar promociones adicionales.
  - Cualquier solicitud de descuento diferente al 5% debe escalarse a un asesor humano.
- **Vigencia del descuento:** Desde el momento del primer contacto hasta las 23:59 hrs (hora CDMX) del día de vencimiento de la póliza.
- **Post-vencimiento:** El descuento del 5% NO aplica. El precio de renovación es el precio base completo sin descuento.

---

## 3. Estados Válidos de Pipefy

El seguimiento de cada póliza pasa por los siguientes estados (en orden lógico):

1. **Póliza detectada** — El Agente identificó la póliza dentro de la Ventana Comercial o vencida.
2. **Contacto inicial enviado** — Se envió el primer correo al cliente.
3. **Seguimiento en curso** — Se están enviando mensajes de seguimiento.
4. **Cliente interesado** — El cliente expresó interés en renovar.
5. **Depósito solicitado** — Se envió cotización con datos bancarios.
6. **Comprobante recibido** — El cliente envió comprobante de pago.
7. **En validación con tesorería** — Comprobante enviado a Tesorería para validación.
8. **Renovación confirmada** — Tesorería validó el pago exitosamente.
9. **Escalado a humano** — Caso derivado a un asesor comercial humano.
10. **No renovada / sin respuesta** — El cliente no renovó o no respondió.

---

## 4. Datos Bancarios

- Los datos bancarios para depósito SOLO se incluyen en correos cuando el Estado_Pipefy es:
  - "Cliente interesado"
  - "Depósito solicitado"
- En CUALQUIER otro estado, el correo NO debe contener datos bancarios.
- Datos bancarios de CIME Power Systems:
  - Banco: BBVA México
  - Beneficiario: CIME Power Systems S.A. de C.V.
  - CLABE: 012180015678901234
  - Referencia: Número de póliza del cliente

---

## 5. Formatos de Comprobante Aceptados

- **Extensiones válidas:** PDF, JPG, PNG, JPEG (case-insensitive)
- **Tamaño máximo:** 10 MB
- Si el comprobante no cumple con formato o tamaño, se solicita reenvío al cliente indicando los formatos aceptados.

---

## 6. Cotización de Renovación

- La cotización incluye obligatoriamente:
  - Nombre del cliente
  - Nombre del equipo cubierto
  - Periodo de cobertura: 12 meses
  - Precio base de renovación (sin descuento)
  - Precio final (con descuento si aplica)
  - Datos bancarios para depósito
  - Fecha de vigencia de la cotización
- La cotización SOLO se genera cuando el Estado_Pipefy es "Cliente interesado".
- Si no existe precio en el catálogo para el tipo de equipo, se escala a un asesor humano.

---

## 7. Restricciones Absolutas del Agente

1. NO ofrecer descuentos distintos al 5%.
2. NO negociar condiciones especiales.
3. NO incluir datos bancarios fuera de los estados permitidos.
4. NO ofrecer servicios fuera del alcance de la póliza de mantenimiento.
5. NO realizar validación bancaria de comprobantes (solo recepción y reenvío a Tesorería).
6. NO generar cotización si el Estado_Pipefy no es "Cliente interesado".
7. NO contactar al cliente si el Estado_Pipefy es "Renovación confirmada" o "Escalado a humano".
