"""
Flujo de Recepción y Procesamiento del Comprobante de Pago.

Procesa el comprobante enviado por el cliente, valida formato y tamaño,
envía confirmación de recepción al cliente y notifica a Tesorería.

Orden temporal obligatorio (Req 5.3):
  1. Validar adjunto → si inválido, solicitar reenvío (Req 5.6)
  2. Actualizar Pipefy a "Comprobante recibido" (Req 5.1)
  3. Enviar confirmación al cliente (Req 5.2)
  4. Invocar notificar_tesoreria DESPUÉS de confirmar al cliente (Req 5.3)
  5. Actualizar Pipefy a "En validación con tesorería" (Req 5.4)

NO se realiza validación bancaria del comprobante (Req 5.7).

Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from src.models.constants import (
    FORMATOS_COMPROBANTE_ACEPTADOS,
    TAMANIO_MAXIMO_COMPROBANTE_BYTES,
)
from src.models.data_models import (
    ActivationPayload,
    DatosPago,
    DatosPoliza,
    SessionState,
)
from src.tools.email_tools import enviar_correo
from src.tools.escalation_tools import escalar_humano
from src.tools.pipefy_tools import actualizar_pipefy
from src.tools.treasury_tools import NotificationError, notificar_tesoreria

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modelo de adjunto
# ---------------------------------------------------------------------------


@dataclass
class Adjunto:
    """Representa un archivo adjunto recibido del cliente.

    Attributes:
        nombre_archivo: Nombre del archivo (e.g., "comprobante.pdf").
        tamanio_bytes: Tamaño del archivo en bytes.
        s3_key: Referencia al archivo almacenado en S3.
    """

    nombre_archivo: str
    tamanio_bytes: int
    s3_key: str


# ---------------------------------------------------------------------------
# Funciones internas
# ---------------------------------------------------------------------------


def _validar_formato_adjunto(
    nombre_archivo: str, tamanio_bytes: int
) -> Tuple[bool, str]:
    """Valida formato y tamaño del adjunto recibido.

    Verifica que la extensión esté en FORMATOS_COMPROBANTE_ACEPTADOS
    (case-insensitive) y que el tamaño no exceda TAMANIO_MAXIMO_COMPROBANTE_BYTES.

    Args:
        nombre_archivo: Nombre del archivo con extensión.
        tamanio_bytes: Tamaño del archivo en bytes.

    Returns:
        Tupla (es_valido, motivo). Si es_valido es False, motivo describe
        la razón del rechazo.
    """
    # Extraer extensión
    if "." not in nombre_archivo:
        formatos_str = ", ".join(sorted(FORMATOS_COMPROBANTE_ACEPTADOS))
        return (
            False,
            f"El archivo '{nombre_archivo}' no tiene extensión reconocida. "
            f"Formatos aceptados: {formatos_str}.",
        )

    extension = nombre_archivo.rsplit(".", 1)[-1].upper()

    if extension not in FORMATOS_COMPROBANTE_ACEPTADOS:
        formatos_str = ", ".join(sorted(FORMATOS_COMPROBANTE_ACEPTADOS))
        return (
            False,
            f"El formato '{extension}' no es soportado. "
            f"Formatos aceptados: {formatos_str}.",
        )

    # Validar tamaño
    max_mb = TAMANIO_MAXIMO_COMPROBANTE_BYTES / (1024 * 1024)
    if tamanio_bytes > TAMANIO_MAXIMO_COMPROBANTE_BYTES:
        tamanio_mb = tamanio_bytes / (1024 * 1024)
        return (
            False,
            f"El archivo excede el tamaño máximo permitido "
            f"({tamanio_mb:.1f} MB > {max_mb:.0f} MB).",
        )

    return (True, "")


def _enviar_confirmacion_recepcion(
    session_state: SessionState, payload: ActivationPayload
) -> datetime:
    """Envía correo de confirmación de recepción al cliente (Req 5.2).

    El correo indica que el comprobante fue recibido y que Tesorería
    lo validará en un plazo de 24 horas hábiles.

    Args:
        session_state: Estado actual de la sesión.
        payload: Datos de activación con información del cliente.

    Returns:
        Timestamp UTC del momento de confirmación enviada.

    Raises:
        Propaga excepciones de enviar_correo si falla.
    """
    asunto = (
        f"Confirmación de recepción de comprobante - Póliza {payload.poliza_id}"
    )
    cuerpo = (
        f"Estimado/a {payload.cliente_nombre},\n\n"
        f"Confirmamos la recepción de su comprobante de pago para la "
        f"renovación de la póliza de mantenimiento del equipo "
        f"{payload.equipo_nombre}.\n\n"
        f"Nuestro equipo de Tesorería validará el comprobante en un plazo "
        f"máximo de 24 horas hábiles. Le notificaremos una vez que la "
        f"validación sea completada.\n\n"
        f"Atentamente,\nCIME Power Systems"
    )

    logger.info(
        f"Enviando confirmación de recepción de comprobante a "
        f"{payload.cliente_email} para poliza {payload.poliza_id}"
    )

    enviar_correo(
        destinatario=payload.cliente_email,
        asunto=asunto,
        cuerpo=cuerpo,
    )

    timestamp_confirmacion = datetime.now(timezone.utc)
    logger.info(
        f"Confirmación de recepción enviada al cliente "
        f"({timestamp_confirmacion.isoformat()})"
    )
    return timestamp_confirmacion


def _notificar_tesoreria_y_actualizar(
    session_state: SessionState,
    payload: ActivationPayload,
    adjunto: Adjunto,
    timestamp_recepcion: datetime,
) -> Dict[str, Any]:
    """Notifica a Tesorería y actualiza Pipefy a "En validación con tesorería".

    Si notificar_tesoreria falla tras retry → escala a humano (Req 5.5).
    Si tiene éxito → actualiza Pipefy en máximo 5 segundos (Req 5.4).

    Args:
        session_state: Estado actual de la sesión.
        payload: Datos de activación.
        adjunto: Datos del adjunto recibido.
        timestamp_recepcion: Momento de recepción del comprobante.

    Returns:
        Dict con resultado de la operación:
            - notificacion_exitosa: bool
            - escalado: bool (True si se escaló por fallo)
    """
    datos_pago = DatosPago(
        cliente_nombre=payload.cliente_nombre,
        poliza_id=payload.poliza_id,
        monto=payload.precio_renovacion,
        timestamp_recepcion=timestamp_recepcion,
        referencia_adjunto=adjunto.s3_key,
    )

    try:
        logger.info(
            f"Notificando a Tesorería — poliza={payload.poliza_id}, "
            f"monto={payload.precio_renovacion}"
        )
        notificar_tesoreria(datos_pago)

        # Éxito → actualizar Pipefy a "En validación con tesorería" (Req 5.4)
        nota = (
            f"Tesorería notificada. Comprobante: {adjunto.nombre_archivo}. "
            f"Recepción: {timestamp_recepcion.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        actualizar_pipefy(
            poliza_id=payload.poliza_id,
            estado="En validación con tesorería",
            nota=nota,
            session_id=session_state.session_id,
        )

        logger.info(
            f"Pipefy actualizado a 'En validación con tesorería' "
            f"para poliza {payload.poliza_id}"
        )
        return {"notificacion_exitosa": True, "escalado": False}

    except (TimeoutError, NotificationError) as e:
        # Fallo tras reintentos → escalar a humano (Req 5.5)
        logger.error(
            f"Fallo al notificar Tesorería para poliza {payload.poliza_id}: {e}. "
            f"Escalando a humano."
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
                f"Fallo al notificar Tesorería sobre comprobante recibido "
                f"(poliza {payload.poliza_id}). Error: {type(e).__name__}: {e}. "
                f"Comprobante: {adjunto.nombre_archivo} ({adjunto.s3_key})"
            ),
            historial=session_state.historial_mensajes,
            estado_pipefy=session_state.estado_pipefy,
            datos_poliza=datos_poliza,
            session_id=session_state.session_id,
        )

        return {"notificacion_exitosa": False, "escalado": True}


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------


def procesar_comprobante(
    adjunto: Adjunto,
    session_state: SessionState,
    payload: ActivationPayload,
) -> Dict[str, Any]:
    """Procesa un comprobante de pago enviado por el cliente.

    Flujo:
      1. Validar formato y tamaño del adjunto.
      2. Si inválido → enviar correo de reenvío (Req 5.6).
      3. Si válido → actualizar Pipefy a "Comprobante recibido" (Req 5.1).
      4. Enviar confirmación al cliente (Req 5.2).
      5. Notificar a Tesorería DESPUÉS de confirmar (Req 5.3).
      6. Actualizar Pipefy a "En validación con tesorería" (Req 5.4).

    NO se realiza validación bancaria del comprobante (Req 5.7).

    Args:
        adjunto: Datos del archivo adjunto recibido.
        session_state: Estado actual de la sesión del agente.
        payload: Datos de activación con información del cliente y póliza.

    Returns:
        Dict con:
            - success: bool indicando si el flujo completó exitosamente.
            - motivo: str con descripción del resultado.
            - formato_valido: bool indicando si el adjunto pasó validación.
            - timestamp_confirmacion: str ISO 8601 (si aplica).
            - notificacion_tesoreria: bool (si aplica).
            - escalado: bool (si se escaló por fallo en notificación).
    """
    logger.info(
        f"Procesando comprobante para poliza {payload.poliza_id}: "
        f"archivo='{adjunto.nombre_archivo}', "
        f"tamaño={adjunto.tamanio_bytes} bytes"
    )

    # --- Paso 1: Validar formato y tamaño (Req 5.1, 5.6) ---
    es_valido, motivo_rechazo = _validar_formato_adjunto(
        adjunto.nombre_archivo, adjunto.tamanio_bytes
    )

    if not es_valido:
        # Enviar correo de reenvío con formatos aceptados (Req 5.6)
        logger.info(
            f"Adjunto inválido para poliza {payload.poliza_id}: {motivo_rechazo}"
        )

        formatos_str = ", ".join(sorted(FORMATOS_COMPROBANTE_ACEPTADOS))
        max_mb = TAMANIO_MAXIMO_COMPROBANTE_BYTES / (1024 * 1024)

        asunto_reenvio = (
            f"Reenvío de comprobante solicitado - Póliza {payload.poliza_id}"
        )
        cuerpo_reenvio = (
            f"Estimado/a {payload.cliente_nombre},\n\n"
            f"Recibimos su archivo, pero no pudimos procesarlo por la "
            f"siguiente razón:\n\n"
            f"{motivo_rechazo}\n\n"
            f"Le solicitamos reenviar el comprobante de pago en alguno de los "
            f"siguientes formatos: {formatos_str}.\n"
            f"El tamaño máximo permitido es de {max_mb:.0f} MB.\n\n"
            f"Quedamos a sus órdenes.\n\n"
            f"Atentamente,\nCIME Power Systems"
        )

        enviar_correo(
            destinatario=payload.cliente_email,
            asunto=asunto_reenvio,
            cuerpo=cuerpo_reenvio,
        )

        return {
            "success": False,
            "motivo": f"Adjunto inválido: {motivo_rechazo}",
            "formato_valido": False,
        }

    # --- Paso 2: Actualizar Pipefy a "Comprobante recibido" (Req 5.1) ---
    timestamp_recepcion = datetime.now(timezone.utc)
    nota_recepcion = (
        f"Comprobante recibido: {adjunto.nombre_archivo} "
        f"({adjunto.tamanio_bytes} bytes). "
        f"Recepción: {timestamp_recepcion.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )

    actualizar_pipefy(
        poliza_id=payload.poliza_id,
        estado="Comprobante recibido",
        nota=nota_recepcion,
        session_id=session_state.session_id,
    )

    logger.info(
        f"Pipefy actualizado a 'Comprobante recibido' para poliza "
        f"{payload.poliza_id}"
    )

    # --- Paso 3: Enviar confirmación al cliente (Req 5.2) ---
    timestamp_confirmacion = _enviar_confirmacion_recepcion(
        session_state, payload
    )

    # --- Paso 4 y 5: Notificar Tesorería y actualizar Pipefy (Req 5.3, 5.4) ---
    # IMPORTANTE: notificar_tesoreria se invoca DESPUÉS de confirmar al cliente
    resultado_tesoreria = _notificar_tesoreria_y_actualizar(
        session_state=session_state,
        payload=payload,
        adjunto=adjunto,
        timestamp_recepcion=timestamp_recepcion,
    )

    if resultado_tesoreria["notificacion_exitosa"]:
        logger.info(
            f"Flujo de comprobante completado exitosamente para poliza "
            f"{payload.poliza_id}"
        )
        return {
            "success": True,
            "motivo": "Comprobante procesado y Tesorería notificada",
            "formato_valido": True,
            "timestamp_confirmacion": timestamp_confirmacion.isoformat(),
            "notificacion_tesoreria": True,
            "escalado": False,
        }
    else:
        logger.warning(
            f"Comprobante recibido pero notificación a Tesorería falló "
            f"para poliza {payload.poliza_id}. Escalado a humano."
        )
        return {
            "success": False,
            "motivo": "Comprobante recibido pero fallo al notificar Tesorería (escalado)",
            "formato_valido": True,
            "timestamp_confirmacion": timestamp_confirmacion.isoformat(),
            "notificacion_tesoreria": False,
            "escalado": True,
        }
