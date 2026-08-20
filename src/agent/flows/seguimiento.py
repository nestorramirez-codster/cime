"""
Flujo de Seguimiento Comercial Multi-Etapa — Agente Comercial IA de CIME Power Systems.

Implementa la máquina de estados del seguimiento post-contacto inicial.
Procesa las respuestas del cliente y ejecuta las acciones correspondientes
según las reglas comerciales aprobadas.

Estados de respuesta manejados:
- "interes": Cliente muestra interés → actualizar Pipefy a "Cliente interesado"
- "rechazo": Cliente rechaza (pre o post vencimiento) → oferta descuento o escalar
- "sin_respuesta_48h": 48h sin respuesta a oferta → enviar recordatorio
- "rechazo_oferta": Cliente rechaza oferta de descuento → enviar encuesta
- "sin_respuesta_72h": 72h sin respuesta a encuesta → cerrar como no renovada

Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

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

# ---------------------------------------------------------------------------
# Tipos de respuesta válidos para la máquina de estados
# ---------------------------------------------------------------------------
TIPOS_RESPUESTA_VALIDOS = frozenset({
    "interes",
    "rechazo",
    "sin_respuesta_48h",
    "rechazo_oferta",
    "sin_respuesta_72h",
})


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _es_pre_vencimiento(fecha_vencimiento: date) -> bool:
    """Determina si la póliza aún no ha vencido (fecha_vencimiento > hoy)."""
    return fecha_vencimiento > date.today()


def _formatear_precio(precio: float) -> str:
    """Formatea un precio con agrupación de miles, 2 decimales y moneda MXN."""
    return f"{precio:,.2f} MXN"


def _construir_datos_poliza(payload: ActivationPayload) -> DatosPoliza:
    """Construye un DatosPoliza a partir del ActivationPayload."""
    return DatosPoliza(
        poliza_id=payload.poliza_id,
        cliente_nombre=payload.cliente_nombre,
        cliente_email=payload.cliente_email,
        fecha_vencimiento=payload.fecha_vencimiento,
        precio_renovacion=payload.precio_renovacion,
        equipo_nombre=payload.equipo_nombre,
    )


# ---------------------------------------------------------------------------
# Funciones de la máquina de estados
# ---------------------------------------------------------------------------


def _manejar_interes(
    session_state: SessionState,
    payload: ActivationPayload,
) -> Dict[str, Any]:
    """Maneja la expresión de interés del cliente (Req 3.1, 3.2).

    Actualiza Pipefy a "Cliente interesado" para que el flujo de cotización
    pueda proceder según el Requisito 4.

    Args:
        session_state: Estado actual de la sesión.
        payload: Datos de activación de la póliza.

    Returns:
        Dict con success, nuevo_estado y motivo.
    """
    logger.info(
        f"Cliente interesado para poliza {payload.poliza_id}. "
        f"Actualizando Pipefy a 'Cliente interesado'."
    )

    timestamp_utc = datetime.now(timezone.utc)
    nota = (
        f"Cliente expresó interés en renovar. "
        f"Timestamp: {timestamp_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )

    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="Cliente interesado",
        nota=nota,
        session_id=session_state.session_id,
    )

    return {
        "success": True,
        "nuevo_estado": "Cliente interesado",
        "motivo": "Cliente expresó interés, proceder a cotización",
        "siguiente_accion": "generar_cotizacion",
    }


def _manejar_rechazo_pre_vencimiento(
    session_state: SessionState,
    payload: ActivationPayload,
    kb_client: KBClient,
) -> Dict[str, Any]:
    """Maneja rechazo del cliente cuando la póliza está pre-vencimiento (Req 3.3).

    Consulta la KB para obtener la plantilla de oferta de descuento del 5%
    y envía la oferta al cliente.

    Args:
        session_state: Estado actual de la sesión.
        payload: Datos de activación de la póliza.
        kb_client: Cliente de Knowledge Base.

    Returns:
        Dict con success, motivo y detalles de la oferta enviada.
    """
    logger.info(
        f"Rechazo pre-vencimiento para poliza {payload.poliza_id}. "
        f"Consultando KB para plantilla de descuento."
    )

    # Actualizar Pipefy a "Seguimiento en curso" (Req 3.9)
    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="Seguimiento en curso",
        nota="Enviando oferta de descuento pre-vencimiento",
        session_id=session_state.session_id,
    )

    # Consultar KB para plantilla de oferta de descuento
    kb_response = kb_client.query(
        "plantilla mensaje oferta descuento pre-vencimiento renovación póliza"
    )

    if kb_response.top_score < KB_SCORE_MINIMO:
        logger.warning(
            f"KB score insuficiente ({kb_response.top_score:.2f}) "
            f"para plantilla de descuento. Usando plantilla por defecto."
        )

    # Calcular precio con descuento
    precio_original = payload.precio_renovacion
    descuento = precio_original * DESCUENTO_PRE_VENCIMIENTO
    precio_con_descuento = precio_original - descuento

    # Generar correo de oferta de descuento
    asunto = (
        f"Oferta especial de renovación - {payload.equipo_nombre}"
    )

    cuerpo = (
        f"Estimado/a {payload.cliente_nombre},\n\n"
        f"Entendemos que por el momento no desea renovar su póliza de "
        f"mantenimiento para el equipo {payload.equipo_nombre}.\n\n"
        f"Sin embargo, como su póliza aún no ha vencido, queremos ofrecerle "
        f"un beneficio exclusivo:\n\n"
        f"Descuento del {int(DESCUENTO_PRE_VENCIMIENTO * 100)}% por renovar "
        f"antes de la fecha de vencimiento ({payload.fecha_vencimiento.isoformat()}).\n\n"
        f"Precio original: {_formatear_precio(precio_original)}\n"
        f"Descuento: -{_formatear_precio(descuento)}\n"
        f"Precio con descuento: {_formatear_precio(precio_con_descuento)}\n\n"
        f"Esta oferta es válida únicamente hasta la fecha de vencimiento "
        f"de su póliza.\n\n"
        f"¿Le gustaría aprovechar este beneficio?\n\n"
        f"Atentamente,\nCIME Power Systems"
    )

    email_result = enviar_correo(
        destinatario=payload.cliente_email,
        asunto=asunto,
        cuerpo=cuerpo,
    )

    if not email_result.success:
        logger.error(
            f"Error enviando oferta de descuento para poliza {payload.poliza_id}: "
            f"{email_result.error_code}"
        )
        return {
            "success": False,
            "motivo": f"Error enviando oferta: {email_result.error_code}",
        }

    logger.info(
        f"Oferta de descuento enviada a {payload.cliente_email} "
        f"para poliza {payload.poliza_id}."
    )

    return {
        "success": True,
        "motivo": "Oferta de descuento pre-vencimiento enviada",
        "descuento_porcentaje": DESCUENTO_PRE_VENCIMIENTO,
        "precio_con_descuento": precio_con_descuento,
        "message_id": email_result.message_id,
        "timestamp_envio": datetime.now(timezone.utc).isoformat(),
    }


def _manejar_rechazo_post_vencimiento(
    session_state: SessionState,
    payload: ActivationPayload,
) -> Dict[str, Any]:
    """Maneja rechazo del cliente cuando la póliza está vencida (Req 3.4).

    Escala a intervención humana con el contexto completo de la interacción.

    Args:
        session_state: Estado actual de la sesión.
        payload: Datos de activación de la póliza.

    Returns:
        Dict con success y motivo del escalamiento.
    """
    logger.info(
        f"Rechazo post-vencimiento para poliza {payload.poliza_id}. "
        f"Escalando a intervención humana."
    )

    datos_poliza = _construir_datos_poliza(payload)

    escalar_humano(
        motivo=(
            f"Cliente rechazó renovación de póliza vencida "
            f"(vencimiento: {payload.fecha_vencimiento.isoformat()}). "
            f"Requiere intervención del equipo comercial."
        ),
        historial=session_state.historial_mensajes,
        estado_pipefy=session_state.estado_pipefy,
        datos_poliza=datos_poliza,
        session_id=session_state.session_id,
    )

    # Actualizar Pipefy a "Escalado a humano"
    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="Escalado a humano",
        nota="Rechazo post-vencimiento, escalado al equipo comercial",
        session_id=session_state.session_id,
    )

    return {
        "success": True,
        "motivo": "Rechazo post-vencimiento escalado a humano",
        "nuevo_estado": "Escalado a humano",
    }


def _enviar_seguimiento_48h(
    session_state: SessionState,
    payload: ActivationPayload,
) -> Dict[str, Any]:
    """Envía recordatorio tras 48h sin respuesta a la oferta (Req 3.5).

    Envía un mensaje recordando la oferta vigente y la fecha límite
    (fecha de vencimiento de la póliza como fecha de expiración de la ventana).

    Args:
        session_state: Estado actual de la sesión.
        payload: Datos de activación de la póliza.

    Returns:
        Dict con success y detalles del recordatorio enviado.
    """
    logger.info(
        f"48h sin respuesta para poliza {payload.poliza_id}. "
        f"Enviando recordatorio de oferta."
    )

    # Actualizar Pipefy a "Seguimiento en curso" (Req 3.9)
    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="Seguimiento en curso",
        nota="Recordatorio 48h: oferta sin respuesta",
        session_id=session_state.session_id,
    )

    # Calcular precio con descuento para el recordatorio
    precio_con_descuento = (
        payload.precio_renovacion * (1 - DESCUENTO_PRE_VENCIMIENTO)
    )

    asunto = (
        f"Recordatorio: oferta de renovación vigente - {payload.equipo_nombre}"
    )

    cuerpo = (
        f"Estimado/a {payload.cliente_nombre},\n\n"
        f"Le recordamos que tiene una oferta vigente para la renovación "
        f"de su póliza de mantenimiento del equipo {payload.equipo_nombre}.\n\n"
        f"Precio con descuento del {int(DESCUENTO_PRE_VENCIMIENTO * 100)}%: "
        f"{_formatear_precio(precio_con_descuento)}\n\n"
        f"Esta oferta es válida hasta el "
        f"{payload.fecha_vencimiento.isoformat()} (fecha de vencimiento "
        f"de su póliza).\n\n"
        f"Si desea aprovechar este beneficio, por favor responda a este "
        f"correo o contáctenos directamente.\n\n"
        f"Atentamente,\nCIME Power Systems"
    )

    email_result = enviar_correo(
        destinatario=payload.cliente_email,
        asunto=asunto,
        cuerpo=cuerpo,
    )

    if not email_result.success:
        logger.error(
            f"Error enviando recordatorio 48h para poliza {payload.poliza_id}: "
            f"{email_result.error_code}"
        )
        return {
            "success": False,
            "motivo": f"Error enviando recordatorio: {email_result.error_code}",
        }

    logger.info(
        f"Recordatorio 48h enviado a {payload.cliente_email} "
        f"para poliza {payload.poliza_id}."
    )

    return {
        "success": True,
        "motivo": "Recordatorio de oferta enviado (48h sin respuesta)",
        "message_id": email_result.message_id,
        "timestamp_envio": datetime.now(timezone.utc).isoformat(),
    }


def _enviar_encuesta_no_renovacion(
    session_state: SessionState,
    payload: ActivationPayload,
    kb_client: KBClient,
) -> Dict[str, Any]:
    """Envía encuesta de motivos de no renovación (Req 3.6).

    Consulta la KB para la plantilla de encuesta y la envía al cliente
    cuando rechaza la oferta de descuento.

    Args:
        session_state: Estado actual de la sesión.
        payload: Datos de activación de la póliza.
        kb_client: Cliente de Knowledge Base.

    Returns:
        Dict con success y detalles de la encuesta enviada.
    """
    logger.info(
        f"Rechazo de oferta para poliza {payload.poliza_id}. "
        f"Enviando encuesta de motivos de no renovación."
    )

    # Actualizar Pipefy a "Seguimiento en curso" (Req 3.9)
    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="Seguimiento en curso",
        nota="Enviando encuesta de motivos de no renovación",
        session_id=session_state.session_id,
    )

    # Consultar KB para plantilla de encuesta
    kb_response = kb_client.query(
        "plantilla encuesta motivos no renovación póliza mantenimiento"
    )

    if kb_response.top_score < KB_SCORE_MINIMO:
        logger.warning(
            f"KB score insuficiente ({kb_response.top_score:.2f}) "
            f"para plantilla de encuesta. Usando plantilla por defecto."
        )

    asunto = (
        f"Encuesta breve - Ayúdenos a mejorar nuestro servicio"
    )

    cuerpo = (
        f"Estimado/a {payload.cliente_nombre},\n\n"
        f"Lamentamos que haya decidido no renovar su póliza de mantenimiento "
        f"para el equipo {payload.equipo_nombre}.\n\n"
        f"Nos gustaría conocer sus motivos para poder mejorar nuestro servicio. "
        f"Por favor, indíquenos cuál de las siguientes razones aplica:\n\n"
        f"1. El precio no se ajusta a mi presupuesto\n"
        f"2. Ya no cuento con el equipo cubierto\n"
        f"3. Encontré un proveedor alternativo\n"
        f"4. No estoy satisfecho con el servicio de mantenimiento\n"
        f"5. Otro motivo (por favor especifique)\n\n"
        f"Su retroalimentación es muy valiosa para nosotros.\n\n"
        f"Atentamente,\nCIME Power Systems"
    )

    email_result = enviar_correo(
        destinatario=payload.cliente_email,
        asunto=asunto,
        cuerpo=cuerpo,
    )

    if not email_result.success:
        logger.error(
            f"Error enviando encuesta para poliza {payload.poliza_id}: "
            f"{email_result.error_code}"
        )
        return {
            "success": False,
            "motivo": f"Error enviando encuesta: {email_result.error_code}",
        }

    logger.info(
        f"Encuesta de no renovación enviada a {payload.cliente_email} "
        f"para poliza {payload.poliza_id}."
    )

    return {
        "success": True,
        "motivo": "Encuesta de motivos de no renovación enviada",
        "message_id": email_result.message_id,
        "timestamp_envio": datetime.now(timezone.utc).isoformat(),
    }


def _cerrar_sin_respuesta(
    session_state: SessionState,
    payload: ActivationPayload,
) -> Dict[str, Any]:
    """Cierra la póliza como no renovada tras 72h sin respuesta (Req 3.7).

    Actualiza Pipefy a "No renovada / sin respuesta" cuando han pasado
    72h desde el envío de la encuesta sin respuesta del cliente.

    Args:
        session_state: Estado actual de la sesión.
        payload: Datos de activación de la póliza.

    Returns:
        Dict con success y el nuevo estado registrado.
    """
    logger.info(
        f"72h sin respuesta a encuesta para poliza {payload.poliza_id}. "
        f"Cerrando como 'No renovada / sin respuesta'."
    )

    timestamp_utc = datetime.now(timezone.utc)
    nota = (
        f"72h sin respuesta a encuesta. Cerrada automáticamente el "
        f"{timestamp_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )

    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="No renovada / sin respuesta",
        nota=nota,
        session_id=session_state.session_id,
    )

    return {
        "success": True,
        "nuevo_estado": "No renovada / sin respuesta",
        "motivo": "Cerrada por 72h sin respuesta a encuesta",
        "timestamp_cierre": timestamp_utc.isoformat(),
    }


# ---------------------------------------------------------------------------
# Router principal de la máquina de estados
# ---------------------------------------------------------------------------


def procesar_respuesta_cliente(
    session_state: SessionState,
    payload: ActivationPayload,
    respuesta_tipo: str,
    mensaje_cliente: str = "",
    kb_client: Optional[KBClient] = None,
) -> Dict[str, Any]:
    """Router principal del flujo de seguimiento multi-etapa.

    Procesa la respuesta del cliente y ejecuta la acción correspondiente
    según el tipo de respuesta y el estado de la póliza.

    Args:
        session_state: Estado actual de la sesión del agente.
        payload: Datos de activación con información del cliente y la póliza.
        respuesta_tipo: Tipo de respuesta del cliente. Valores válidos:
            - "interes": Cliente muestra interés explícito
            - "rechazo": Cliente rechaza (se evalúa pre/post vencimiento)
            - "sin_respuesta_48h": Timer de 48h expirado sin respuesta
            - "rechazo_oferta": Cliente rechaza la oferta de descuento
            - "sin_respuesta_72h": Timer de 72h expirado sin respuesta a encuesta
        mensaje_cliente: Texto del mensaje del cliente (para contexto).
        kb_client: Cliente de Knowledge Base (inyectable para testing).

    Returns:
        Dict con:
            - success: bool indicando si la acción fue ejecutada.
            - motivo: str con descripción del resultado.
            - nuevo_estado: str (si aplica) con el nuevo estado de Pipefy.
            - Campos adicionales según la acción ejecutada.

    Raises:
        ValueError: Si respuesta_tipo no es un tipo válido.
    """
    if respuesta_tipo not in TIPOS_RESPUESTA_VALIDOS:
        raise ValueError(
            f"Tipo de respuesta '{respuesta_tipo}' no es válido. "
            f"Tipos permitidos: {sorted(TIPOS_RESPUESTA_VALIDOS)}"
        )

    if kb_client is None:
        kb_client = KBClient()

    logger.info(
        f"Procesando respuesta '{respuesta_tipo}' para poliza {payload.poliza_id}. "
        f"Estado actual: {session_state.estado_pipefy}."
    )

    # --- Router de la máquina de estados ---

    if respuesta_tipo == "interes":
        return _manejar_interes(session_state, payload)

    elif respuesta_tipo == "rechazo":
        # Evaluar si es pre o post vencimiento
        if _es_pre_vencimiento(payload.fecha_vencimiento):
            return _manejar_rechazo_pre_vencimiento(
                session_state, payload, kb_client
            )
        else:
            return _manejar_rechazo_post_vencimiento(session_state, payload)

    elif respuesta_tipo == "sin_respuesta_48h":
        return _enviar_seguimiento_48h(session_state, payload)

    elif respuesta_tipo == "rechazo_oferta":
        return _enviar_encuesta_no_renovacion(
            session_state, payload, kb_client
        )

    elif respuesta_tipo == "sin_respuesta_72h":
        return _cerrar_sin_respuesta(session_state, payload)

    # No debería llegar aquí (el raise anterior lo previene)
    return {"success": False, "motivo": "Tipo de respuesta no manejado"}
