"""
Flujo de Contacto Inicial — Agente Comercial IA de CIME Power Systems.

Envía el primer correo de renovación al cliente. El contenido varía según
si la póliza está dentro de la ventana comercial (pre-vencimiento) o ya
venció (post-vencimiento).

- Pre-vencimiento: incluye mención del 5% de descuento por renovar antes
  de la fecha de vencimiento (Req 2.3).
- Post-vencimiento: omite la mención del descuento (Req 2.4).

Requisitos: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict

from src.config.kb_client import KBClient
from src.models.constants import (
    DESCUENTO_PRE_VENCIMIENTO,
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


def _formatear_precio(precio: float) -> str:
    """Formatea un precio con agrupación de miles, 2 decimales y moneda MXN.

    Ejemplo: 45000.0 → "45,000.00 MXN"
    """
    return f"{precio:,.2f} MXN"


def _es_pre_vencimiento(fecha_vencimiento: date) -> bool:
    """Determina si la póliza aún no ha vencido (fecha_vencimiento > hoy)."""
    return fecha_vencimiento > date.today()


def enviar_contacto_inicial(
    session_state: SessionState,
    payload: ActivationPayload,
    kb_client: KBClient | None = None,
) -> Dict[str, Any]:
    """Ejecuta el flujo de contacto inicial con el cliente.

    Determina si la póliza es pre o post-vencimiento, consulta la Knowledge
    Base para obtener la plantilla adecuada, genera el correo personalizado
    y lo envía. Si la KB no tiene resultados con score suficiente, escala
    a intervención humana.

    Args:
        session_state: Estado actual de la sesión del agente.
        payload: Datos de activación con información del cliente y la póliza.
        kb_client: Cliente de Knowledge Base (inyectable para testing).

    Returns:
        Dict con:
            - success: bool indicando si el correo fue enviado.
            - motivo: str con descripción del resultado.
            - pre_vencimiento: bool indicando el tipo de contacto.
    """
    if kb_client is None:
        kb_client = KBClient()

    pre_vencimiento = _es_pre_vencimiento(payload.fecha_vencimiento)

    # 1. Consultar KB con query de contexto apropiado
    if pre_vencimiento:
        query_text = (
            "plantilla mensaje correo contacto inicial pre-vencimiento "
            "renovación póliza descuento"
        )
    else:
        query_text = (
            "plantilla mensaje correo contacto inicial post-vencimiento "
            "recuperación póliza vencida"
        )

    logger.info(
        f"Contacto inicial para poliza {payload.poliza_id}: "
        f"{'pre' if pre_vencimiento else 'post'}-vencimiento. "
        f"Consultando KB..."
    )

    kb_response = kb_client.query(query_text)

    # 2. Verificar score ≥ 0.70
    if kb_response.top_score < KB_SCORE_MINIMO:
        logger.warning(
            f"KB score insuficiente ({kb_response.top_score:.2f} < {KB_SCORE_MINIMO}) "
            f"para poliza {payload.poliza_id}. Escalando a humano."
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
                f"Knowledge Base sin resultado relevante (score={kb_response.top_score:.2f}) "
                f"para contacto inicial {'pre' if pre_vencimiento else 'post'}-vencimiento"
            ),
            historial=session_state.historial_mensajes,
            estado_pipefy=session_state.estado_pipefy,
            datos_poliza=datos_poliza,
            session_id=session_state.session_id,
        )
        return {
            "success": False,
            "motivo": "KB score insuficiente, escalado a humano",
            "pre_vencimiento": pre_vencimiento,
        }

    # 3. Generar correo personalizado
    precio_formateado = _formatear_precio(payload.precio_renovacion)

    if pre_vencimiento:
        descuento_texto = (
            f"\n\nComo beneficio por renovar antes de la fecha de vencimiento, "
            f"le ofrecemos un {int(DESCUENTO_PRE_VENCIMIENTO * 100)}% de descuento "
            f"sobre el precio de renovación."
        )
    else:
        descuento_texto = ""

    asunto = (
        f"Renovación de póliza de mantenimiento - {payload.equipo_nombre}"
    )

    cuerpo = (
        f"Estimado/a {payload.cliente_nombre},\n\n"
        f"Le contactamos respecto a la póliza de mantenimiento de su equipo "
        f"{payload.equipo_nombre}.\n\n"
        f"Fecha de vencimiento: {payload.fecha_vencimiento.isoformat()}\n"
        f"Precio de renovación: {precio_formateado}\n"
        f"{descuento_texto}\n\n"
        f"Quedamos a sus órdenes para cualquier duda sobre el proceso de renovación.\n\n"
        f"Atentamente,\nCIME Power Systems"
    )

    # 4. Enviar correo
    logger.info(
        f"Enviando correo de contacto inicial a {payload.cliente_email} "
        f"para poliza {payload.poliza_id}"
    )

    email_result = enviar_correo(
        destinatario=payload.cliente_email,
        asunto=asunto,
        cuerpo=cuerpo,
    )

    if not email_result.success:
        logger.error(
            f"Fallo al enviar correo de contacto inicial para poliza "
            f"{payload.poliza_id}: {email_result.error_code}"
        )
        return {
            "success": False,
            "motivo": f"Error al enviar correo: {email_result.error_code}",
            "pre_vencimiento": pre_vencimiento,
        }

    # 5. Actualizar Pipefy con timestamp UTC
    timestamp_utc = datetime.now(timezone.utc)
    nota = (
        f"Contacto inicial enviado ({('pre' if pre_vencimiento else 'post')}-vencimiento) "
        f"a {payload.cliente_email} el {timestamp_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )

    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="Contacto inicial enviado",
        nota=nota,
        session_id=session_state.session_id,
    )

    logger.info(
        f"Contacto inicial completado exitosamente para poliza {payload.poliza_id}. "
        f"Pipefy actualizado a 'Contacto inicial enviado'."
    )

    return {
        "success": True,
        "motivo": "Contacto inicial enviado exitosamente",
        "pre_vencimiento": pre_vencimiento,
        "message_id": email_result.message_id,
        "timestamp": timestamp_utc.isoformat(),
    }
