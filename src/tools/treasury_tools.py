"""
Tool para notificación al equipo de Tesorería.

Envía un HTTP POST al endpoint interno de Tesorería cuando se recibe
un comprobante de pago, permitiendo la validación del depósito.

Requisitos: 5.3, 5.4, 5.5
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from src.models.constants import (
    RETRY_BACKOFF_CORREO_SEGUNDOS,
    RETRY_MAX_INTENTOS_TESORERIA,
    TIMEOUT_NOTIFICAR_TESORERIA_SEGUNDOS,
)
from src.models.data_models import DatosPago
from src.observability.tracer import registrar_error, registrar_tool_call

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------


class NotificationError(Exception):
    """Error técnico al notificar a Tesorería tras agotar reintentos."""

    pass


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

_SECRETS_CACHE: dict[str, Any] = {}


def _get_treasury_secret() -> dict[str, str]:
    """Obtiene URL y API key de Tesorería desde AWS Secrets Manager.

    El secreto esperado es un JSON con las claves:
        - url: endpoint HTTP del servicio de Tesorería
        - api_key: clave de autenticación

    Returns:
        Dict con 'url' y 'api_key'.

    Raises:
        RuntimeError: Si no se puede obtener el secreto.
    """
    secret_name = "cime/tesoreria/endpoint-key"

    if secret_name in _SECRETS_CACHE:
        return _SECRETS_CACHE[secret_name]

    try:
        import boto3

        client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
        secret_data = json.loads(response["SecretString"])
        _SECRETS_CACHE[secret_name] = secret_data
        return secret_data
    except Exception as e:
        raise RuntimeError(
            f"No se pudo obtener el secreto '{secret_name}' de Secrets Manager: {e}"
        ) from e


def _serialize_datos_pago(datos_pago: DatosPago) -> bytes:
    """Serializa DatosPago a JSON bytes para el cuerpo del POST."""
    payload = {
        "cliente_nombre": datos_pago.cliente_nombre,
        "poliza_id": datos_pago.poliza_id,
        "monto": datos_pago.monto,
        "timestamp_recepcion": datos_pago.timestamp_recepcion.isoformat(),
        "referencia_adjunto": datos_pago.referencia_adjunto,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _post_to_treasury(url: str, api_key: str, body: bytes) -> bool:
    """Ejecuta HTTP POST al endpoint de Tesorería con timeout configurado.

    Args:
        url: URL del endpoint de Tesorería.
        api_key: API key para el header de autenticación.
        body: JSON serializado como bytes.

    Returns:
        True si recibe respuesta HTTP 2xx.

    Raises:
        TimeoutError: Si el endpoint no responde en el tiempo configurado.
        NotificationError: Si recibe un error HTTP (4xx/5xx) u otro error técnico.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    req = urllib.request.Request(
        url, data=body, headers=headers, method="POST"
    )

    try:
        with urllib.request.urlopen(
            req, timeout=TIMEOUT_NOTIFICAR_TESORERIA_SEGUNDOS
        ) as response:
            status_code = response.getcode()
            if 200 <= status_code < 300:
                return True
            raise NotificationError(
                f"Tesorería respondió con código HTTP {status_code}"
            )
    except urllib.error.URLError as e:
        if isinstance(e.reason, OSError) and "timed out" in str(e.reason):
            raise TimeoutError(
                f"Timeout de {TIMEOUT_NOTIFICAR_TESORERIA_SEGUNDOS}s "
                f"al contactar endpoint de Tesorería"
            ) from e
        raise NotificationError(
            f"Error de conexión al endpoint de Tesorería: {e}"
        ) from e
    except TimeoutError:
        raise
    except Exception as e:
        if "timed out" in str(e).lower():
            raise TimeoutError(
                f"Timeout de {TIMEOUT_NOTIFICAR_TESORERIA_SEGUNDOS}s "
                f"al contactar endpoint de Tesorería"
            ) from e
        raise NotificationError(
            f"Error técnico al notificar Tesorería: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Tool principal
# ---------------------------------------------------------------------------


def notificar_tesoreria(datos_pago: DatosPago) -> bool:
    """Notifica al equipo de Tesorería sobre un comprobante de pago recibido.

    Envía un HTTP POST al endpoint interno de Tesorería con los datos del
    comprobante. Implementa timeout de 60 segundos y 1 reintento tras 60s
    en caso de fallo técnico.

    Args:
        datos_pago: DatosPago con cliente_nombre, poliza_id, monto,
                    timestamp_recepcion, referencia_adjunto.

    Returns:
        True si la notificación fue entregada exitosamente.

    Raises:
        TimeoutError: Si no responde en 60 segundos (Req 5.5).
        NotificationError: Error técnico tras agotar reintentos.
    """
    _start_time = time.time()

    # Mock mode para desarrollo local
    mock_mode = os.environ.get("CIME_MOCK_MODE", "").lower() == "true"
    if mock_mode:
        logger.info(
            "[MOCK] notificar_tesoreria invocada — "
            f"poliza_id={datos_pago.poliza_id}, monto={datos_pago.monto}"
        )
        _duration_ms = (time.time() - _start_time) * 1000
        registrar_tool_call(
            tool_name="notificar_tesoreria",
            params_enmascarados={
                "cliente_nombre": datos_pago.cliente_nombre,
                "poliza_id": datos_pago.poliza_id,
                "monto": datos_pago.monto,
                "referencia_adjunto": datos_pago.referencia_adjunto,
            },
            resultado={"success": True},
            duracion_ms=_duration_ms,
        )
        return True

    # Obtener credenciales
    secret = _get_treasury_secret()
    url = secret["url"]
    api_key = secret["api_key"]

    # Serializar payload
    body = _serialize_datos_pago(datos_pago)

    # Log de inicio de invocación (Observability)
    logger.info(
        "notificar_tesoreria: inicio — "
        f"poliza_id={datos_pago.poliza_id}, "
        f"monto={datos_pago.monto}, "
        f"timestamp_recepcion={datos_pago.timestamp_recepcion.isoformat()}"
    )

    start_time = time.time()
    attempts = 0
    max_retries = RETRY_MAX_INTENTOS_TESORERIA  # 1 reintento
    last_error: Exception | None = None

    while attempts <= max_retries:
        try:
            result = _post_to_treasury(url, api_key, body)
            duration_ms = int((time.time() - start_time) * 1000)

            # Log de éxito (Observability)
            logger.info(
                "notificar_tesoreria: éxito — "
                f"poliza_id={datos_pago.poliza_id}, "
                f"intento={attempts + 1}, "
                f"duracion_ms={duration_ms}"
            )
            registrar_tool_call(
                tool_name="notificar_tesoreria",
                params_enmascarados={
                    "cliente_nombre": datos_pago.cliente_nombre,
                    "poliza_id": datos_pago.poliza_id,
                    "monto": datos_pago.monto,
                    "referencia_adjunto": datos_pago.referencia_adjunto,
                },
                resultado={"success": True},
                duracion_ms=duration_ms,
            )
            return result

        except (TimeoutError, NotificationError) as e:
            last_error = e
            attempts += 1
            duration_ms = int((time.time() - start_time) * 1000)

            logger.warning(
                "notificar_tesoreria: fallo — "
                f"poliza_id={datos_pago.poliza_id}, "
                f"intento={attempts}, "
                f"tipo_error={type(e).__name__}, "
                f"mensaje={str(e)}, "
                f"duracion_ms={duration_ms}"
            )
            registrar_error(
                tipo_error=type(e).__name__,
                componente="tesoreria",
                mensaje_error=str(e),
                num_reintento=attempts,
                accion_mitigacion="retry" if attempts <= max_retries else "escalar_humano",
            )

            if attempts <= max_retries:
                # Esperar backoff antes de reintentar
                logger.info(
                    f"notificar_tesoreria: reintentando en "
                    f"{RETRY_BACKOFF_CORREO_SEGUNDOS}s — "
                    f"poliza_id={datos_pago.poliza_id}"
                )
                time.sleep(RETRY_BACKOFF_CORREO_SEGUNDOS)

    # Reintentos agotados — propagar el error para que el agente escale
    duration_ms = int((time.time() - start_time) * 1000)
    logger.error(
        "notificar_tesoreria: reintentos agotados — "
        f"poliza_id={datos_pago.poliza_id}, "
        f"intentos_totales={attempts}, "
        f"duracion_ms={duration_ms}, "
        f"ultimo_error={str(last_error)}"
    )
    registrar_tool_call(
        tool_name="notificar_tesoreria",
        params_enmascarados={
            "cliente_nombre": datos_pago.cliente_nombre,
            "poliza_id": datos_pago.poliza_id,
            "monto": datos_pago.monto,
            "referencia_adjunto": datos_pago.referencia_adjunto,
        },
        resultado={"success": False, "error": str(last_error)},
        duracion_ms=duration_ms,
    )

    if isinstance(last_error, TimeoutError):
        raise last_error
    raise NotificationError(
        f"Notificación a Tesorería fallida tras {attempts} intentos: "
        f"{last_error}"
    ) from last_error
