"""
Capa de Memory de largo plazo (S3 JSON) para el Agente Comercial IA.

Persiste y recupera el historial de sesiones por póliza usando S3 como
almacenamiento de largo plazo. Cada póliza tiene un archivo JSON en
`memoria/{poliza_id}/historial.json` que acumula las sesiones completadas.

Modo mock disponible para desarrollo local (env: CIME_MOCK_MODE=true)
con almacenamiento en-memoria.

Requisitos: 8.2, 8.3, 8.4
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from src.models.constants import MEMORY_LONG_TERM_WRITE_TIMEOUT_SEGUNDOS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_S3_BUCKET = os.environ.get("CIME_S3_MEMORY_BUCKET", "cime-agent-memory-000000000000")
_S3_PREFIX = "memoria"

# Resultados válidos para una sesión completada
_RESULTADOS_VALIDOS = frozenset({"interesado", "rechazó", "no respondió", "escalado"})


# ---------------------------------------------------------------------------
# Almacenamiento mock en memoria
# ---------------------------------------------------------------------------

_mock_memory_store: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_mock_mode() -> bool:
    """Determina si el módulo opera en modo mock para desarrollo local."""
    return os.environ.get("CIME_MOCK_MODE", "true").lower() == "true"


def _build_s3_key(poliza_id: str) -> str:
    """Construye la key S3 para el historial de una póliza.

    Args:
        poliza_id: Identificador único de la póliza.

    Returns:
        Key S3 con formato `memoria/{poliza_id}/historial.json`.
    """
    return f"{_S3_PREFIX}/{poliza_id}/historial.json"


def _validar_sesion_completada(sesion_completada: dict[str, Any]) -> None:
    """Valida que el dict de sesión completada tenga los campos requeridos.

    Args:
        sesion_completada: Dict con datos de la sesión finalizada.

    Raises:
        ValueError: Si faltan campos obligatorios o tienen formato inválido.
    """
    campos_requeridos = {
        "session_id",
        "timestamp_inicio",
        "timestamp_cierre",
        "estado_final",
        "resultado",
        "mensajes_enviados",
    }

    faltantes = campos_requeridos - set(sesion_completada.keys())
    if faltantes:
        raise ValueError(
            f"Campos obligatorios faltantes en sesion_completada: {sorted(faltantes)}"
        )

    resultado = sesion_completada["resultado"]
    if resultado not in _RESULTADOS_VALIDOS:
        raise ValueError(
            f"Resultado '{resultado}' no es válido. "
            f"Valores permitidos: {sorted(_RESULTADOS_VALIDOS)}"
        )

    mensajes = sesion_completada["mensajes_enviados"]
    if not isinstance(mensajes, int) or mensajes < 0:
        raise ValueError(
            f"mensajes_enviados debe ser un entero >= 0, recibido: {mensajes}"
        )


def _serializar_historial(historial: dict[str, Any]) -> str:
    """Serializa el historial a JSON con timestamps ISO 8601.

    Args:
        historial: Dict con estructura completa del historial.

    Returns:
        String JSON con indentación para legibilidad.
    """
    return json.dumps(historial, ensure_ascii=False, indent=2, default=str)


def _deserializar_historial(json_str: str) -> dict[str, Any]:
    """Deserializa un JSON string a dict de historial.

    Args:
        json_str: String JSON del historial.

    Returns:
        Dict con la estructura del historial.

    Raises:
        json.JSONDecodeError: Si el JSON es inválido.
    """
    return json.loads(json_str)


def _crear_historial_vacio(poliza_id: str) -> dict[str, Any]:
    """Crea la estructura base de un historial vacío.

    Args:
        poliza_id: Identificador de la póliza.

    Returns:
        Dict con la estructura base del historial.
    """
    return {
        "poliza_id": poliza_id,
        "sesiones": [],
    }


def _normalizar_timestamps(sesion: dict[str, Any]) -> dict[str, Any]:
    """Normaliza los timestamps de una sesión a formato ISO 8601 UTC.

    Si los timestamps son objetos datetime, los convierte a string ISO 8601.
    Si ya son strings, los deja como están.

    Args:
        sesion: Dict de la sesión con timestamps.

    Returns:
        Dict de la sesión con timestamps normalizados como strings ISO 8601.
    """
    sesion_normalizada = dict(sesion)

    for campo in ("timestamp_inicio", "timestamp_cierre"):
        valor = sesion_normalizada.get(campo)
        if isinstance(valor, datetime):
            # Asegurar timezone UTC y formatear ISO 8601
            if valor.tzinfo is None:
                valor = valor.replace(tzinfo=timezone.utc)
            sesion_normalizada[campo] = valor.strftime("%Y-%m-%dT%H:%M:%SZ")

    return sesion_normalizada


# ---------------------------------------------------------------------------
# Funciones mock
# ---------------------------------------------------------------------------


def _mock_persistir(poliza_id: str, sesion_completada: dict[str, Any]) -> bool:
    """Persiste historial en almacenamiento in-memory (modo mock).

    Args:
        poliza_id: Identificador de la póliza.
        sesion_completada: Dict con datos de la sesión finalizada.

    Returns:
        True si la operación fue exitosa.
    """
    if poliza_id not in _mock_memory_store:
        _mock_memory_store[poliza_id] = _crear_historial_vacio(poliza_id)

    sesion_normalizada = _normalizar_timestamps(sesion_completada)
    _mock_memory_store[poliza_id]["sesiones"].append(sesion_normalizada)

    logger.info(
        f"[MOCK] Historial persistido para poliza={poliza_id}, "
        f"session={sesion_completada.get('session_id')}, "
        f"total_sesiones={len(_mock_memory_store[poliza_id]['sesiones'])}"
    )
    return True


def _mock_recuperar(poliza_id: str) -> Optional[dict[str, Any]]:
    """Recupera historial desde almacenamiento in-memory (modo mock).

    Args:
        poliza_id: Identificador de la póliza.

    Returns:
        Dict con historial completo o None si no existe.
    """
    historial = _mock_memory_store.get(poliza_id)
    if historial:
        logger.info(
            f"[MOCK] Historial recuperado para poliza={poliza_id}, "
            f"sesiones={len(historial['sesiones'])}"
        )
    else:
        logger.info(f"[MOCK] No hay historial previo para poliza={poliza_id}")
    return historial


# ---------------------------------------------------------------------------
# Funciones S3 reales
# ---------------------------------------------------------------------------


def _s3_persistir(poliza_id: str, sesion_completada: dict[str, Any]) -> bool:
    """Persiste historial en S3 (modo real).

    Lee el historial existente (si lo hay), agrega la nueva sesión y
    escribe de vuelta a S3. Opera dentro del timeout de 30 segundos (Req 8.3).

    Args:
        poliza_id: Identificador de la póliza.
        sesion_completada: Dict con datos de la sesión finalizada.

    Returns:
        True si la operación fue exitosa.

    Raises:
        TimeoutError: Si la operación excede los 30 segundos.
        RuntimeError: Si hay un error de escritura en S3.
    """
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    region = os.environ.get("CIME_AWS_REGION", "us-east-1")
    config = Config(
        read_timeout=MEMORY_LONG_TERM_WRITE_TIMEOUT_SEGUNDOS,
        connect_timeout=10,
        retries={"max_attempts": 1},
    )
    s3_client = boto3.client("s3", region_name=region, config=config)
    s3_key = _build_s3_key(poliza_id)

    # Leer historial existente
    historial: dict[str, Any]
    try:
        response = s3_client.get_object(Bucket=_S3_BUCKET, Key=s3_key)
        body = response["Body"].read().decode("utf-8")
        historial = _deserializar_historial(body)
        logger.info(f"Historial existente recuperado de S3: {s3_key}")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "NoSuchKey":
            historial = _crear_historial_vacio(poliza_id)
            logger.info(f"No hay historial previo en S3, creando nuevo: {s3_key}")
        else:
            logger.error(f"Error leyendo historial de S3: {e}")
            raise RuntimeError(f"Error leyendo historial de S3: {e}") from e

    # Agregar nueva sesión
    sesion_normalizada = _normalizar_timestamps(sesion_completada)
    historial["sesiones"].append(sesion_normalizada)

    # Escribir historial actualizado
    try:
        json_body = _serializar_historial(historial)
        s3_client.put_object(
            Bucket=_S3_BUCKET,
            Key=s3_key,
            Body=json_body.encode("utf-8"),
            ContentType="application/json",
        )
        logger.info(
            f"Historial persistido en S3: {s3_key}, "
            f"total_sesiones={len(historial['sesiones'])}"
        )
        return True
    except ClientError as e:
        logger.error(f"Error escribiendo historial en S3: {e}")
        raise RuntimeError(f"Error escribiendo historial en S3: {e}") from e


def _s3_recuperar(poliza_id: str) -> Optional[dict[str, Any]]:
    """Recupera historial desde S3 (modo real).

    Opera con timeout de 5 segundos para cumplir Req 8.2.

    Args:
        poliza_id: Identificador de la póliza.

    Returns:
        Dict con historial completo o None si no existe.

    Raises:
        TimeoutError: Si la lectura excede los 5 segundos.
    """
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    region = os.environ.get("CIME_AWS_REGION", "us-east-1")
    config = Config(
        read_timeout=5,
        connect_timeout=3,
        retries={"max_attempts": 1},
    )
    s3_client = boto3.client("s3", region_name=region, config=config)
    s3_key = _build_s3_key(poliza_id)

    try:
        response = s3_client.get_object(Bucket=_S3_BUCKET, Key=s3_key)
        body = response["Body"].read().decode("utf-8")
        historial = _deserializar_historial(body)
        logger.info(
            f"Historial recuperado de S3: {s3_key}, "
            f"sesiones={len(historial.get('sesiones', []))}"
        )
        return historial
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "NoSuchKey":
            logger.info(f"No hay historial previo en S3 para poliza={poliza_id}")
            return None
        logger.error(f"Error recuperando historial de S3: {e}")
        raise RuntimeError(
            f"Error recuperando historial de S3 para poliza={poliza_id}: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Funciones públicas
# ---------------------------------------------------------------------------


def persistir_historial(poliza_id: str, sesion_completada: dict[str, Any]) -> bool:
    """Persiste el historial de una sesión completada en Memory de largo plazo.

    Al cierre de sesión, almacena los datos de la sesión en S3 dentro de los
    30 segundos posteriores al cierre (Req 8.3). Acumula sesiones por póliza.

    La estructura persistida es:
    ```json
    {
      "poliza_id": "POL-2024-001",
      "sesiones": [
        {
          "session_id": "sess-abc123",
          "timestamp_inicio": "2025-07-15T10:00:00Z",
          "timestamp_cierre": "2025-07-15T10:45:00Z",
          "estado_final": "En validación con tesorería",
          "resultado": "interesado",
          "mensajes_enviados": 3
        }
      ]
    }
    ```

    Args:
        poliza_id: Identificador único de la póliza (no vacío).
        sesion_completada: Dict con los campos requeridos:
            - session_id (str): ID de la sesión finalizada.
            - timestamp_inicio (str|datetime): Inicio de sesión ISO 8601.
            - timestamp_cierre (str|datetime): Cierre de sesión ISO 8601.
            - estado_final (str): Último Estado_Pipefy registrado.
            - resultado (str): Uno de "interesado", "rechazó",
              "no respondió", "escalado".
            - mensajes_enviados (int): Total de mensajes enviados >= 0.

    Returns:
        True si la persistencia fue exitosa.

    Raises:
        ValueError: Si poliza_id está vacío o sesion_completada tiene
            campos inválidos/faltantes.
        TimeoutError: Si la operación excede los 30 segundos.
        RuntimeError: Si hay un error de escritura en S3 (modo real).
    """
    # Validación de entrada
    if not poliza_id or not poliza_id.strip():
        raise ValueError("poliza_id no puede estar vacío")

    _validar_sesion_completada(sesion_completada)

    logger.info(
        f"Persistiendo historial para poliza={poliza_id}, "
        f"session={sesion_completada.get('session_id')}"
    )

    if _is_mock_mode():
        return _mock_persistir(poliza_id, sesion_completada)

    return _s3_persistir(poliza_id, sesion_completada)


def recuperar_historial(poliza_id: str) -> Optional[dict[str, Any]]:
    """Recupera el historial de sesiones previas de una póliza.

    Al inicio de una nueva sesión, recupera el historial en un plazo máximo
    de 5 segundos (Req 8.2) para personalizar el primer mensaje.

    Args:
        poliza_id: Identificador único de la póliza (no vacío).

    Returns:
        Dict con la estructura completa del historial:
        ```json
        {
          "poliza_id": "POL-2024-001",
          "sesiones": [...]
        }
        ```
        o None si no existe historial previo.

    Raises:
        ValueError: Si poliza_id está vacío.
        TimeoutError: Si la lectura excede los 5 segundos (modo real).
        RuntimeError: Si hay un error de lectura en S3 (modo real).
    """
    # Validación de entrada
    if not poliza_id or not poliza_id.strip():
        raise ValueError("poliza_id no puede estar vacío")

    logger.info(f"Recuperando historial para poliza={poliza_id}")

    if _is_mock_mode():
        return _mock_recuperar(poliza_id)

    return _s3_recuperar(poliza_id)
