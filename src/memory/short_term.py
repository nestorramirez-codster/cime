"""
Capa de Memory de corto plazo (DynamoDB) para el Agente Comercial IA.

Almacena el estado de sesión activa con TTL de 24 horas.
Implementa purga de datos de comprobante tras 10 minutos de confirmación (Req 8.5).
Garantiza aislamiento: cada función opera exclusivamente sobre el session_id proporcionado.

Modo mock disponible para desarrollo local (env: CIME_MOCK_MODE=true).

Requisitos: 8.1, 8.5, 12.7
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from src.models.constants import (
    MEMORY_COMPROBANTE_TTL_MINUTOS,
    MEMORY_SHORT_TERM_TTL_HORAS,
)
from src.models.data_models import (
    DatosComprobanteTemp,
    Mensaje,
    SessionState,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_TABLE_NAME = os.environ.get("CIME_DYNAMODB_TABLE", "cime-agent-sessions")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_mock_mode() -> bool:
    """Determina si el módulo opera en modo mock para desarrollo local."""
    return os.environ.get("CIME_MOCK_MODE", "true").lower() == "true"


def _get_dynamodb_table():
    """Obtiene la referencia a la tabla DynamoDB.

    Returns:
        Recurso boto3 DynamoDB Table.

    Raises:
        RuntimeError: Si no se puede conectar a DynamoDB.
    """
    import boto3

    region = os.environ.get("CIME_AWS_REGION", "us-east-1")
    try:
        dynamodb = boto3.resource("dynamodb", region_name=region)
        return dynamodb.Table(_TABLE_NAME)
    except Exception as e:
        logger.error(f"Error conectando a DynamoDB tabla '{_TABLE_NAME}': {e}")
        raise RuntimeError(
            f"No se pudo acceder a la tabla DynamoDB '{_TABLE_NAME}': {e}"
        ) from e


def _calcular_ttl_sesion() -> int:
    """Calcula el TTL de expiración para una sesión (24 horas desde ahora).

    Returns:
        Timestamp Unix (epoch seconds) para el atributo TTL de DynamoDB.
    """
    return int(time.time()) + (MEMORY_SHORT_TERM_TTL_HORAS * 3600)


def _calcular_ttl_comprobante() -> int:
    """Calcula el TTL de expiración para datos de comprobante (10 minutos).

    Returns:
        Timestamp Unix (epoch seconds) para purga del comprobante.
    """
    return int(time.time()) + (MEMORY_COMPROBANTE_TTL_MINUTOS * 60)


# ---------------------------------------------------------------------------
# Serialización / Deserialización
# ---------------------------------------------------------------------------


def _serializar_mensaje(mensaje: Mensaje) -> dict:
    """Serializa un Mensaje a diccionario para DynamoDB."""
    return {
        "timestamp": mensaje.timestamp.isoformat(),
        "remitente": mensaje.remitente,
        "contenido": mensaje.contenido,
        "tipo": mensaje.tipo,
    }


def _deserializar_mensaje(data: dict) -> Mensaje:
    """Deserializa un diccionario de DynamoDB a Mensaje."""
    return Mensaje(
        timestamp=datetime.fromisoformat(data["timestamp"]),
        remitente=data["remitente"],
        contenido=data["contenido"],
        tipo=data["tipo"],
    )


def _serializar_comprobante(comprobante: DatosComprobanteTemp) -> dict:
    """Serializa DatosComprobanteTemp a diccionario para DynamoDB."""
    return {
        "referencia_adjunto": comprobante.referencia_adjunto,
        "monto": str(comprobante.monto),  # DynamoDB usa Decimal, guardamos str
        "timestamp_recepcion": comprobante.timestamp_recepcion.isoformat(),
        "formato": comprobante.formato,
        "tamanio_bytes": comprobante.tamanio_bytes,
    }


def _deserializar_comprobante(data: dict) -> DatosComprobanteTemp:
    """Deserializa un diccionario de DynamoDB a DatosComprobanteTemp."""
    return DatosComprobanteTemp(
        referencia_adjunto=data["referencia_adjunto"],
        monto=float(data["monto"]),
        timestamp_recepcion=datetime.fromisoformat(data["timestamp_recepcion"]),
        formato=data["formato"],
        tamanio_bytes=int(data["tamanio_bytes"]),
    )


def _serializar_session_state(session_state: SessionState) -> dict:
    """Serializa un SessionState completo a item de DynamoDB.

    Args:
        session_state: Estado de sesión a persistir.

    Returns:
        Diccionario con todos los atributos para DynamoDB put_item.
    """
    item = {
        "session_id": session_state.session_id,
        "poliza_id": session_state.poliza_id,
        "estado_pipefy": session_state.estado_pipefy,
        "historial_mensajes": json.dumps(
            [_serializar_mensaje(m) for m in session_state.historial_mensajes]
        ),
        "timestamp_inicio": session_state.timestamp_inicio.isoformat(),
        "expiry_time": _calcular_ttl_sesion(),
    }

    if session_state.datos_comprobante is not None:
        item["datos_comprobante"] = json.dumps(
            _serializar_comprobante(session_state.datos_comprobante)
        )
        item["comprobante_expiry_time"] = _calcular_ttl_comprobante()

    return item


def _deserializar_session_state(item: dict) -> SessionState:
    """Deserializa un item de DynamoDB a SessionState.

    Args:
        item: Diccionario del item recuperado de DynamoDB.

    Returns:
        SessionState reconstruido.
    """
    historial_raw = json.loads(item.get("historial_mensajes", "[]"))
    historial = [_deserializar_mensaje(m) for m in historial_raw]

    datos_comprobante: Optional[DatosComprobanteTemp] = None
    if "datos_comprobante" in item and item["datos_comprobante"]:
        # Verificar si el comprobante ya expiró (purga por TTL de 10 min)
        comprobante_expiry = item.get("comprobante_expiry_time", 0)
        if isinstance(comprobante_expiry, (int, float)) and comprobante_expiry > 0:
            if time.time() < comprobante_expiry:
                datos_comprobante = _deserializar_comprobante(
                    json.loads(item["datos_comprobante"])
                )
            else:
                logger.info(
                    f"Datos de comprobante expirados para session "
                    f"'{item['session_id']}' (TTL de {MEMORY_COMPROBANTE_TTL_MINUTOS} min)"
                )
        else:
            # Sin TTL de comprobante definido, incluir datos
            datos_comprobante = _deserializar_comprobante(
                json.loads(item["datos_comprobante"])
            )

    return SessionState(
        session_id=item["session_id"],
        poliza_id=item["poliza_id"],
        estado_pipefy=item["estado_pipefy"],
        historial_mensajes=historial,
        timestamp_inicio=datetime.fromisoformat(item["timestamp_inicio"]),
        datos_comprobante=datos_comprobante,
    )


# ---------------------------------------------------------------------------
# Mock en memoria para desarrollo local
# ---------------------------------------------------------------------------

# Almacenamiento mock: session_id -> (item_dict, expiry_time)
_mock_store: dict[str, dict] = {}


def _mock_guardar_estado_sesion(session_state: SessionState) -> bool:
    """Guarda el estado de sesión en el store mock en memoria."""
    item = _serializar_session_state(session_state)
    _mock_store[session_state.session_id] = item
    logger.info(
        f"[MOCK] Sesión guardada: session_id={session_state.session_id}, "
        f"estado={session_state.estado_pipefy}"
    )
    return True


def _mock_obtener_estado_sesion(session_id: str) -> Optional[SessionState]:
    """Obtiene el estado de sesión del store mock en memoria."""
    item = _mock_store.get(session_id)
    if item is None:
        logger.info(f"[MOCK] Sesión no encontrada: session_id={session_id}")
        return None

    # Verificar TTL de sesión
    expiry = item.get("expiry_time", 0)
    if isinstance(expiry, (int, float)) and expiry > 0 and time.time() >= expiry:
        logger.info(
            f"[MOCK] Sesión expirada (TTL {MEMORY_SHORT_TERM_TTL_HORAS}h): "
            f"session_id={session_id}"
        )
        del _mock_store[session_id]
        return None

    logger.info(f"[MOCK] Sesión recuperada: session_id={session_id}")
    return _deserializar_session_state(item)


def _mock_eliminar_dato_comprobante(session_id: str) -> bool:
    """Elimina datos de comprobante del store mock."""
    item = _mock_store.get(session_id)
    if item is None:
        logger.warning(
            f"[MOCK] No se puede eliminar comprobante: sesión '{session_id}' no existe"
        )
        return False

    if "datos_comprobante" in item:
        del item["datos_comprobante"]
    if "comprobante_expiry_time" in item:
        del item["comprobante_expiry_time"]

    logger.info(
        f"[MOCK] Datos de comprobante eliminados: session_id={session_id}"
    )
    return True


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------


def guardar_estado_sesion(session_state: SessionState) -> bool:
    """Guarda o actualiza el estado completo de una sesión activa.

    Persiste todos los campos del SessionState en DynamoDB con TTL de 24 horas.
    Si el session_state incluye datos_comprobante, estos tendrán un TTL separado
    de 10 minutos para purga automática (Req 8.5).

    Aislamiento (Req 12.7): opera exclusivamente sobre el session_id contenido
    en el session_state proporcionado.

    Args:
        session_state: Estado completo de la sesión a persistir.

    Returns:
        True si el guardado fue exitoso.

    Raises:
        ValueError: Si session_state.session_id está vacío.
        RuntimeError: Si falla la conexión a DynamoDB (modo real).
    """
    if not session_state.session_id or not session_state.session_id.strip():
        raise ValueError("session_state.session_id no puede estar vacío")

    if _is_mock_mode():
        return _mock_guardar_estado_sesion(session_state)

    # Modo real: DynamoDB
    logger.info(
        f"Guardando sesión en DynamoDB: session_id={session_state.session_id}"
    )
    table = _get_dynamodb_table()
    item = _serializar_session_state(session_state)

    try:
        table.put_item(Item=item)
        logger.info(
            f"Sesión guardada exitosamente: session_id={session_state.session_id}"
        )
        return True
    except Exception as e:
        logger.error(
            f"Error guardando sesión '{session_state.session_id}' en DynamoDB: {e}"
        )
        raise RuntimeError(
            f"Error al guardar sesión en DynamoDB: {e}"
        ) from e


def obtener_estado_sesion(session_id: str) -> Optional[SessionState]:
    """Recupera el estado de una sesión activa por su session_id.

    Aislamiento (Req 12.7): SOLO retorna datos del session_id proporcionado.
    No existe forma de acceder a datos de otra sesión a través de esta función.

    Si los datos de comprobante han expirado (> 10 minutos desde confirmación),
    se retorna el SessionState sin datos_comprobante (Req 8.5).

    Args:
        session_id: Identificador único de la sesión (UUID generado por Runtime).

    Returns:
        SessionState si la sesión existe y no ha expirado, None en caso contrario.

    Raises:
        ValueError: Si session_id está vacío.
        RuntimeError: Si falla la conexión a DynamoDB (modo real).
    """
    if not session_id or not session_id.strip():
        raise ValueError("session_id no puede estar vacío")

    if _is_mock_mode():
        return _mock_obtener_estado_sesion(session_id)

    # Modo real: DynamoDB
    logger.info(f"Recuperando sesión de DynamoDB: session_id={session_id}")
    table = _get_dynamodb_table()

    try:
        response = table.get_item(Key={"session_id": session_id})
        item = response.get("Item")

        if item is None:
            logger.info(f"Sesión no encontrada en DynamoDB: session_id={session_id}")
            return None

        return _deserializar_session_state(item)

    except Exception as e:
        logger.error(
            f"Error recuperando sesión '{session_id}' de DynamoDB: {e}"
        )
        raise RuntimeError(
            f"Error al recuperar sesión de DynamoDB: {e}"
        ) from e


def eliminar_dato_comprobante(session_id: str) -> bool:
    """Elimina los datos temporales de comprobante de una sesión.

    Implementa la purga inmediata de datos sensibles de comprobante (Req 8.5).
    Esta función se invoca tras los 10 minutos de confirmación, o puede ser
    llamada manualmente para limpiar datos antes del TTL automático.

    Aislamiento (Req 12.7): SOLO modifica el session_id proporcionado.

    Args:
        session_id: Identificador único de la sesión activa.

    Returns:
        True si la eliminación fue exitosa (o no había datos de comprobante).

    Raises:
        ValueError: Si session_id está vacío.
        RuntimeError: Si falla la conexión a DynamoDB (modo real).
    """
    if not session_id or not session_id.strip():
        raise ValueError("session_id no puede estar vacío")

    if _is_mock_mode():
        return _mock_eliminar_dato_comprobante(session_id)

    # Modo real: DynamoDB - eliminar atributos de comprobante
    logger.info(
        f"Eliminando datos de comprobante de DynamoDB: session_id={session_id}"
    )
    table = _get_dynamodb_table()

    try:
        table.update_item(
            Key={"session_id": session_id},
            UpdateExpression=(
                "REMOVE datos_comprobante, comprobante_expiry_time"
            ),
            ConditionExpression="attribute_exists(session_id)",
        )
        logger.info(
            f"Datos de comprobante eliminados: session_id={session_id}"
        )
        return True
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        logger.warning(
            f"Sesión '{session_id}' no existe en DynamoDB al eliminar comprobante"
        )
        return False
    except Exception as e:
        logger.error(
            f"Error eliminando datos de comprobante para '{session_id}': {e}"
        )
        raise RuntimeError(
            f"Error al eliminar datos de comprobante en DynamoDB: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Utilidades para testing
# ---------------------------------------------------------------------------


def _reset_mock_store() -> None:
    """Limpia el store mock. Solo para uso en tests."""
    _mock_store.clear()
