# Plantillas de Mensajes Aprobadas — CIME Power Systems
## Agente Comercial IA · Renovación de Pólizas

> **Nota:** Todas las plantillas están en español mexicano formal. Los placeholders entre llaves `{}` deben sustituirse con los datos reales del cliente y la póliza.

---

## 1. Plantilla Pre-Vencimiento (Contacto Inicial)

**Uso:** Primer correo cuando la póliza se encuentra dentro de la Ventana Comercial (antes de la fecha de vencimiento).

**Asunto:** Renovación de su póliza de mantenimiento — {equipo_nombre}

**Cuerpo:**

```
Estimado/a {cliente_nombre},

Le saludamos cordialmente de parte de CIME Power Systems.

Nos comunicamos con usted para informarle que su póliza de mantenimiento para el equipo {equipo_nombre} está próxima a vencer el {fecha_vencimiento}.

Para garantizar la continuidad de la cobertura de su equipo, le invitamos a renovar su póliza. El precio de renovación anual es de ${precio_renovacion} MXN.

Como beneficio por renovar antes de la fecha de vencimiento, le ofrecemos un descuento del 5% sobre el precio de renovación, lo que resulta en un precio preferencial de ${precio_con_descuento} MXN.

Este descuento está disponible únicamente si confirma su renovación antes del {fecha_vencimiento}.

¿Le gustaría proceder con la renovación? Quedo a sus órdenes para enviarle la cotización formal con los datos para realizar el depósito.

Atentamente,
Equipo Comercial
CIME Power Systems
```

---

## 2. Plantilla Post-Vencimiento (Contacto Inicial)

**Uso:** Primer correo cuando la póliza ya venció (después de la fecha de vencimiento).

**Asunto:** Su póliza de mantenimiento ha vencido — {equipo_nombre}

**Cuerpo:**

```
Estimado/a {cliente_nombre},

Le saludamos cordialmente de parte de CIME Power Systems.

Le informamos que su póliza de mantenimiento para el equipo {equipo_nombre} venció el {fecha_vencimiento}.

Para mantener su equipo protegido y con el respaldo técnico de nuestros especialistas, le invitamos a renovar su póliza. El precio de renovación anual es de ${precio_renovacion} MXN.

La renovación le garantiza:
- Mantenimiento preventivo programado
- Soporte técnico especializado
- Tiempo de respuesta prioritario ante fallas

¿Le gustaría proceder con la renovación? Con gusto le envío la cotización formal con todos los detalles.

Atentamente,
Equipo Comercial
CIME Power Systems
```

---

## 3. Plantilla de Oferta de Descuento Pre-Vencimiento

**Uso:** Cuando el cliente no mostró interés inmediato pero la póliza aún está dentro de la Ventana Comercial. Se envía como segundo intento con énfasis en el descuento.

**Asunto:** Oferta especial: 5% de descuento en su renovación — {equipo_nombre}

**Cuerpo:**

```
Estimado/a {cliente_nombre},

Entendemos que la decisión de renovar requiere consideración. Por ello, queremos recordarle que tiene disponible un descuento del 5% en la renovación de su póliza de mantenimiento para el equipo {equipo_nombre}.

Resumen de la oferta:
- Precio base de renovación: ${precio_renovacion} MXN
- Descuento pre-vencimiento: 5%
- Precio con descuento: ${precio_con_descuento} MXN
- Vigencia de la oferta: hasta el {fecha_vencimiento}

Este descuento es exclusivo para renovaciones confirmadas antes de la fecha de vencimiento de su póliza.

Si desea aprovechar esta oferta, solo indíquemelo y le enviaré la cotización formal con los datos de pago.

Quedo a sus órdenes.

Atentamente,
Equipo Comercial
CIME Power Systems
```

---

## 4. Plantilla de Encuesta de Motivos de No Renovación

**Uso:** Cuando el cliente rechaza la oferta de descuento. Se envía para recopilar información sobre los motivos.

**Asunto:** Su opinión nos importa — CIME Power Systems

**Cuerpo:**

```
Estimado/a {cliente_nombre},

Respetamos su decisión. Con el fin de mejorar nuestro servicio, nos gustaría conocer el motivo por el cual no desea renovar la póliza de mantenimiento de su equipo {equipo_nombre}.

¿Podría indicarnos cuál de las siguientes opciones describe mejor su situación?

1. El precio no se ajusta a mi presupuesto actual
2. Ya no cuento con el equipo / fue dado de baja
3. Contraté mantenimiento con otro proveedor
4. No estoy satisfecho con el servicio recibido
5. Otro motivo (por favor indíquelo)

Su respuesta nos ayuda a mejorar. Agradecemos su tiempo.

Atentamente,
Equipo Comercial
CIME Power Systems
```

---

## 5. Plantilla de Escalamiento a Asesor Humano

**Uso:** Cuando el caso es escalado a un asesor humano por cualquier motivo definido en los criterios de escalamiento.

**Asunto:** Un asesor especializado le contactará — CIME Power Systems

**Cuerpo:**

```
Estimado/a {cliente_nombre},

Agradezco su consulta. Para brindarle la mejor atención posible, he trasladado su caso a uno de nuestros asesores comerciales especializados.

Un asesor de CIME Power Systems se comunicará con usted en un plazo máximo de 24 horas hábiles para atender su solicitud de manera personalizada.

Si requiere atención urgente, puede comunicarse directamente con nuestro equipo comercial:
- Correo: comercial@cimepower.com
- Teléfono: (55) 1234-5678

Agradecemos su paciencia y preferencia.

Atentamente,
Equipo Comercial
CIME Power Systems
```

---

## 6. Plantilla de Confirmación de Recepción de Comprobante

**Uso:** Cuando el cliente envía un comprobante de pago válido (formato y tamaño correctos).

**Asunto:** Comprobante recibido — Renovación {equipo_nombre}

**Cuerpo:**

```
Estimado/a {cliente_nombre},

Confirmamos la recepción exitosa de su comprobante de pago para la renovación de la póliza de mantenimiento del equipo {equipo_nombre}.

Su comprobante ha sido enviado a nuestro equipo de Tesorería para validación. Una vez confirmado el depósito, recibirá la confirmación de renovación de su póliza.

El proceso de validación toma habitualmente de 1 a 3 días hábiles.

Agradecemos su confianza en CIME Power Systems.

Atentamente,
Equipo Comercial
CIME Power Systems
```

---

## Notas de Uso

- **Placeholders obligatorios:** `{cliente_nombre}`, `{equipo_nombre}`, `{fecha_vencimiento}`, `{precio_renovacion}`
- **Placeholder adicional (solo plantillas con descuento):** `{precio_con_descuento}` — Calcular como `round(precio_renovacion * 0.95, 2)`
- **Formato de precio:** Siempre con 2 decimales y sufijo "MXN". Ejemplo: `$15,000.00 MXN`
- **Formato de fecha:** dd/mm/aaaa. Ejemplo: `15/03/2025`
- **Tono:** Español mexicano formal, respetuoso, orientado al servicio.
- **Prohibiciones:** No incluir promesas fuera del alcance de la póliza, no mencionar descuentos en plantillas post-vencimiento, no incluir datos bancarios fuera de la cotización formal.
