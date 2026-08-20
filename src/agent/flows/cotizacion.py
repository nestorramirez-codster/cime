"""
Flujo de Generación y Envío de Cotización — Agente Comercial IA de CIME Power Systems.

Genera y envía una cotización de renovación al cliente cuando el Estado_Pipefy
es "Cliente interesado". Incluye consulta a Knowledge Base para precio del
catálogo, cálculo de descuento pre-vencimiento (5%) si aplica, y envío de
correo con datos bancarios.

- Si KB no tiene precio → escalar a humano (Req 4.7)
- Descuento: precio_final = round(precio_base * 0.95, 2) si aplica (Req 4.3)
- Datos bancarios solo si estado ∈ {"Cliente interesado", "Depósito solicitado"} (Req 4.4)
- En éxito de enviar_correo → actualizar Pipefy a "Depósito solicitado" (Req 4.5)

Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict

from src.config.kb_client import KBClient
from src.models.constants import (
    DESCUENTO_PRE_VENCIMIENTO,
    ESTADOS_CON_DATOS_BANCARIOS,
    KB_SCORE_MINIMO,
)
from src.models.data_models import (
    ActivationPayload,
    DatosPoliza,
    SessionState,
)
from src.tools.email_tools import enviar_correo
from src.tools.escalation_tools import escalar_humano
from src.tools.pipefy_tools import actualizar_pipefy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes del flujo de cotización
# ---------------------------------------------------------------------------

PERIODO_MESES: int = 12

DATOS_BANCARIOS: str = (
    "Banco: BBVA | Cuenta: 0115868165 | CLABE: 012180001158681657 "
    "| Beneficiario: PPE SYSTEMS SA DE CV | RFC: PSY2009023W0"
)


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------


def _formatear_precio(precio: float) -> str:
    """Formatea un precio con agrupación de miles, 2 decimales y moneda MXN.

    Ejemplo: 45000.0 → "45,000.00 MXN"
    """
    return f"{precio:,.2f} MXN"


def _es_pre_vencimiento(fecha_vencimiento: date) -> bool:
    """Determina si la póliza aún no ha vencido (fecha_vencimiento > hoy)."""
    return fecha_vencimiento > date.today()


def _calcular_precio_final(precio_base: float, aplica_descuento: bool) -> float:
    """Calcula el precio final aplicando descuento si corresponde.

    Args:
        precio_base: Precio base de renovación (> 0).
        aplica_descuento: True si aplica el 5% de descuento pre-vencimiento.

    Returns:
        Precio final redondeado a 2 decimales.
        Si aplica descuento: round(precio_base * 0.95, 2)
        Si no aplica: precio_base
    """
    if aplica_descuento:
        return round(precio_base * (1 - DESCUENTO_PRE_VENCIMIENTO), 2)
    return precio_base


def _construir_cuerpo_cotizacion(
    payload: ActivationPayload,
    precio_base: float,
    precio_final: float,
    aplica_descuento: bool,
    datos_bancarios: str | None,
) -> str:
    """Construye el cuerpo del correo de cotización.

    Args:
        payload: Datos de activación con información del cliente y la póliza.
        precio_base: Precio base de renovación obtenido del catálogo.
        precio_final: Precio final tras aplicar descuento (si corresponde).
        aplica_descuento: True si se aplicó descuento pre-vencimiento.
        datos_bancarios: Cadena con datos bancarios o None si no corresponde.

    Returns:
        Cuerpo del correo en texto plano con formato legible.
    """
    # Calcular período de vigencia: 12 meses desde fecha de renovación
    fecha_inicio = payload.fecha_vencimiento
    anio_fin = fecha_inicio.year + 1
    mes_fin = fecha_inicio.month
    dia_fin = fecha_inicio.day
    # Manejar caso de 29 feb
    try:
        fecha_fin = date(anio_fin, mes_fin, dia_fin)
    except ValueError:
        fecha_fin = date(anio_fin, mes_fin, dia_fin - 1)

    lineas = [
        f"Estimado/a {payload.cliente_nombre},",
        "",
        "A continuación le presentamos la cotización de renovación de su póliza "
        "de mantenimiento:",
        "",
        "=" * 50,
        "COTIZACIÓN DE RENOVACIÓN",
        "=" * 50,
        "",
        f"Cliente: {payload.cliente_nombre}",
        f"Equipo: {payload.equipo_nombre}",
        f"Período de vigencia: {PERIODO_MESES} meses "
        f"({fecha_inicio.isoformat()} a {fecha_fin.isoformat()})",
        f"Precio base: {_formatear_precio(precio_base)}",
    ]

    if aplica_descuento:
        porcentaje = int(DESCUENTO_PRE_VENCIMIENTO * 100)
        lineas.append(
            f"Descuento por renovación anticipada: {porcentaje}%"
        )
        lineas.append(f"Precio final: {_formatear_precio(precio_final)}")
    else:
        lineas.append(f"Precio final: {_formatear_precio(precio_final)}")

    lineas.append("")

    if datos_bancarios:
        lineas.extend([
            "-" * 50,
            "DATOS PARA DEPÓSITO:",
            datos_bancarios,
            "-" * 50,
            "",
        ])

    lineas.extend([
        "Una vez realizado el depósito, por favor envíe su comprobante de pago "
        "como respuesta a este correo.",
        "",
        "Quedamos a sus órdenes para cualquier duda.",
        "",
        "Atentamente,",
        "CIME Power Systems",
    ])

    return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Función principal: generar_cotizacion
# ---------------------------------------------------------------------------


def generar_cotizacion(
    session_state: SessionState,
    payload: ActivationPayload,
    kb_client: KBClient | None = None,
) -> Dict[str, Any]:
    """Ejecuta el flujo de generación y envío de cotización.

    Consulta la KB para obtener el precio del catálogo, calcula el descuento
    si aplica, genera la cotización con todos los campos obligatorios y la
    envía al cliente. Si el envío es exitoso, actualiza Pipefy a
    "Depósito solicitado".

    Args:
        session_state: Estado actual de la sesión del agente.
        payload: Datos de activación con información del cliente y la póliza.
        kb_client: Cliente de Knowledge Base (inyectable para testing).

    Returns:
        Dict con:
            - success: bool indicando si la cotización fue enviada.
            - motivo: str con descripción del resultado.
            - precio_base: float (si se obtuvo del catálogo).
            - precio_final: float (si se calculó).
            - aplica_descuento: bool.
    """
    if kb_client is None:
        kb_client = KBClient()

    # 1. Verificar que el estado sea "Cliente interesado" (Req 4.1)
    if session_state.estado_pipefy != "Cliente interesado":
        logger.warning(
            f"Cotización rechazada: Estado_Pipefy='{session_state.estado_pipefy}' "
            f"no es 'Cliente interesado'. Poliza: {payload.poliza_id}"
        )
        return {
            "success": False,
            "motivo": (
                f"Estado_Pipefy '{session_state.estado_pipefy}' no permite "
                f"generar cotización. Se requiere 'Cliente interesado'."
            ),
            "aplica_descuento": False,
        }

    # 2. Consultar KB para obtener precio del catálogo (Req 4.2)
    query_text = (
        f"precio catálogo equipo {payload.equipo_nombre} "
        f"plan mantenimiento cotización"
    )

    logger.info(
        f"Generando cotización para poliza {payload.poliza_id}: "
        f"consultando KB para precio de '{payload.equipo_nombre}'..."
    )

    kb_response = kb_client.query(query_text)

    # 3. Si KB score < 0.70 → no hay precio en catálogo → escalar (Req 4.7)
    if kb_response.top_score < KB_SCORE_MINIMO:
        logger.warning(
            f"KB score insuficiente ({kb_response.top_score:.2f} < {KB_SCORE_MINIMO}) "
            f"para precio de equipo '{payload.equipo_nombre}'. Escalando a humano."
        )
        datos_poliza = DatosPoliza(
            poliza_id=payload.poliza_id,
            cliente_nombre=payload.cliente_nombre,
            cliente_email=payload.cliente_email,
            fecha_vencimiento=payload.fecha_vencimiento,
            precio_renovacion=payload.precio_renovacion,
            equipo_nombre=payload.equipo_nombre,
        )
        escalar_humano(
            motivo=(
                f"Catálogo de precios sin resultado relevante "
                f"(score={kb_response.top_score:.2f}) para equipo "
                f"'{payload.equipo_nombre}'. No se puede generar cotización."
            ),
            historial=session_state.historial_mensajes,
            estado_pipefy=session_state.estado_pipefy,
            datos_poliza=datos_poliza,
            session_id=session_state.session_id,
        )
        return {
            "success": False,
            "motivo": "KB score insuficiente para precio, escalado a humano",
            "aplica_descuento": False,
        }

    # 4. Usar precio_renovacion del payload como precio_base
    precio_base = payload.precio_renovacion

    # 5. Determinar si aplica descuento pre-vencimiento (Req 4.3)
    aplica_descuento = _es_pre_vencimiento(payload.fecha_vencimiento)

    # 6. Calcular precio final
    precio_final = _calcular_precio_final(precio_base, aplica_descuento)

    # 7. Determinar si incluir datos bancarios (Req 4.4)
    if session_state.estado_pipefy in ESTADOS_CON_DATOS_BANCARIOS:
        datos_bancarios = DATOS_BANCARIOS
    else:
        datos_bancarios = None

    # 8. Construir cuerpo de cotización
    cuerpo = _construir_cuerpo_cotizacion(
        payload=payload,
        precio_base=precio_base,
        precio_final=precio_final,
        aplica_descuento=aplica_descuento,
        datos_bancarios=datos_bancarios,
    )

    asunto = (
        f"Cotización de renovación - Póliza {payload.equipo_nombre}"
    )

    # 9. Enviar cotización por correo (Req 4.5)
    logger.info(
        f"Enviando cotización a {payload.cliente_email} "
        f"para poliza {payload.poliza_id}. "
        f"Precio base: {_formatear_precio(precio_base)}, "
        f"Precio final: {_formatear_precio(precio_final)}"
    )

    email_result = enviar_correo(
        destinatario=payload.cliente_email,
        asunto=asunto,
        cuerpo=cuerpo,
    )

    if not email_result.success:
        logger.error(
            f"Fallo al enviar cotización para poliza {payload.poliza_id}: "
            f"{email_result.error_code}"
        )
        return {
            "success": False,
            "motivo": f"Error al enviar correo: {email_result.error_code}",
            "precio_base": precio_base,
            "precio_final": precio_final,
            "aplica_descuento": aplica_descuento,
        }

    # 10. Actualizar Pipefy a "Depósito solicitado" (Req 4.5)
    timestamp_utc = datetime.now(timezone.utc)
    nota = (
        f"Cotización enviada a {payload.cliente_email} el "
        f"{timestamp_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC. "
        f"Monto: {_formatear_precio(precio_final)}"
    )

    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="Depósito solicitado",
        nota=nota,
        session_id=session_state.session_id,
    )

    logger.info(
        f"Cotización completada para poliza {payload.poliza_id}. "
        f"Pipefy actualizado a 'Depósito solicitado'."
    )

    return {
        "success": True,
        "motivo": "Cotización generada y enviada exitosamente",
        "precio_base": precio_base,
        "precio_final": precio_final,
        "aplica_descuento": aplica_descuento,
        "message_id": email_result.message_id,
        "timestamp": timestamp_utc.isoformat(),
    }
