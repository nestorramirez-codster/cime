"""
Tools de integración con Pipefy para el Agente Comercial IA de CIME Power Systems.

Provee funciones para:
- Consultar el estado actual de una póliza en el tablero operativo de Pipefy
- Actualizar el estado de una póliza con trazabilidad completa

Integración vía Pipefy GraphQL API con autenticación Bearer token
almacenada en AWS Secrets Manager (secret: cime/pipefy/api-token).

Modo mock disponible para desarrollo local (env: CIME_MOCK_MODE=true).

Requisitos: 1.4, 1.5, 7.1, 7.2, 7.3, 7.4, 9.4
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Any, Optional

from src.models.constants import (
    ESTADOS_VALIDOS_PIPEFY,
    RETRY_BACKOFF_BASE_SEGUNDOS,
    RETRY_MAX_INTENTOS_PIPEFY,
    TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS,
)
from src.models.data_models import PipelineCard
from src.observability.tracer import registrar_error, registrar_tool_call

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Excepciones personalizadas
# ---------------------------------------------------------------------------


class PipefyAPIError(Exception):
    """Error de la API de Pipefy (HTTP 4xx/5xx).

    Attributes:
        status_code: Código HTTP de la respuesta.
        message: Mensaje descriptivo del error.
    """

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Pipefy API error {status_code}: {message}")


class InvalidStateTransitionError(Exception):
    """Transición de estado inválida en el tablero de Pipefy.

    Attributes:
        estado_actual: Estado actual de la póliza.
        estado_destino: Estado al que se intentó transicionar.
        message: Descripción del conflicto.
    """

    def __init__(
        self, estado_actual: str, estado_destino: str, message: str = ""
    ) -> None:
        self.estado_actual = estado_actual
        self.estado_destino = estado_destino
        self.message = message or (
            f"Transición inválida: '{estado_actual}' -> '{estado_destino}'"
        )
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Configuración interna
# ---------------------------------------------------------------------------

_PIPEFY_API_URL = os.environ.get(
    "CIME_PIPEFY_API_URL", "https://api.pipefy.com/graphql"
)

_SECRET_NAME = "cime/pipefy/api-token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_mock_mode() -> bool:
    """Determina si el módulo opera en modo mock para desarrollo local."""
    return os.environ.get("CIME_MOCK_MODE", "true").lower() == "true"


def _get_pipefy_token() -> str:
    """Recupera el token de autenticación de Pipefy desde AWS Secrets Manager.

    En modo mock, retorna un token ficticio.
    En modo real, consulta Secrets Manager con el secreto 'cime/pipefy/api-token'.

    Returns:
        Token Bearer para la API de Pipefy.

    Raises:
        RuntimeError: Si no se puede obtener el secreto.
    """
    if _is_mock_mode():
        return "mock-pipefy-token-dev"

    import boto3

    region = os.environ.get("CIME_AWS_REGION", "us-east-1")

    try:
        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=_SECRET_NAME)
        secret_data = json.loads(response["SecretString"])
        return secret_data.get("token", response["SecretString"])
    except Exception as e:
        logger.error(f"Error obteniendo secreto '{_SECRET_NAME}': {e}")
        raise RuntimeError(
            f"No se pudo obtener el token de Pipefy desde Secrets Manager: {e}"
        ) from e


def _build_consultar_query(poliza_id: str) -> dict[str, Any]:
    """Construye el payload GraphQL para consultar una card por poliza_id.

    Args:
        poliza_id: Identificador único de la póliza.

    Returns:
        Dict con la query GraphQL y variables.
    """
    query = """
    query GetCardByPolizaId($polizaId: String!, $pipeId: ID!) {
        cards(pipe_id: $pipeId, search: {fieldId: "poliza_id", fieldValue: $polizaId}) {
            edges {
                node {
                    id
                    title
                    current_phase {
                        name
                    }
                    fields {
                        name
                        value
                    }
                    updated_at
                    comments {
                        text
                    }
                }
            }
        }
    }
    """
    pipe_id = os.environ.get("CIME_PIPEFY_PIPE_ID", "")
    return {
        "query": query,
        "variables": {"polizaId": poliza_id, "pipeId": pipe_id},
    }


def _parse_pipefy_response(poliza_id: str, data: dict[str, Any]) -> PipelineCard:
    """Mapea la respuesta de Pipefy GraphQL a un PipelineCard.

    Args:
        poliza_id: Identificador de la póliza consultada.
        data: Respuesta JSON parseada de la API.

    Returns:
        PipelineCard con los datos mapeados.

    Raises:
        PipefyAPIError: Si la respuesta no contiene datos válidos.
    """
    try:
        edges = data.get("data", {}).get("cards", {}).get("edges", [])
        if not edges:
            raise PipefyAPIError(
                404, f"No se encontro card para poliza '{poliza_id}'"
            )

        node = edges[0]["node"]
        fields = {f["name"]: f["value"] for f in node.get("fields", [])}

        estado_actual = node.get("current_phase", {}).get("name", "")
        if estado_actual not in ESTADOS_VALIDOS_PIPEFY:
            logger.warning(
                f"Estado '{estado_actual}' no esta en ESTADOS_VALIDOS_PIPEFY"
            )

        # Parsear fecha de vencimiento
        fecha_venc_str = fields.get("fecha_vencimiento", "")
        if fecha_venc_str:
            fecha_vencimiento = date.fromisoformat(fecha_venc_str)
        else:
            fecha_vencimiento = date.today()

        # Parsear timestamp de última actualización
        updated_at_str = node.get("updated_at", "")
        if updated_at_str:
            timestamp_ultima = datetime.fromisoformat(
                updated_at_str.replace("Z", "+00:00")
            )
        else:
            timestamp_ultima = datetime.now(timezone.utc)

        # Extraer notas de comentarios
        comments = node.get("comments", [])
        notas = [c["text"] for c in comments if c.get("text")]

        return PipelineCard(
            poliza_id=poliza_id,
            estado_actual=estado_actual,
            cliente_nombre=fields.get("cliente_nombre", ""),
            cliente_email=fields.get("cliente_email", ""),
            fecha_vencimiento=fecha_vencimiento,
            precio_renovacion=float(fields.get("precio_renovacion", 0.0)),
            equipo_nombre=fields.get("equipo_nombre", ""),
            timestamp_ultima_actualizacion=timestamp_ultima,
            notas=notas,
        )
    except PipefyAPIError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise PipefyAPIError(
            500, f"Error parseando respuesta de Pipefy: {e}"
        ) from e


# ---------------------------------------------------------------------------
# Mock para desarrollo local
# ---------------------------------------------------------------------------

# Almacenamiento mock en memoria para simular estados de pólizas
_mock_pipefy_states: dict[str, dict] = {}


def _mock_consultar_pipefy(poliza_id: str) -> PipelineCard:
    """Retorna datos mock de una póliza para desarrollo local.

    Args:
        poliza_id: Identificador de la póliza.

    Returns:
        PipelineCard con datos simulados.
    """
    logger.info(f"[MOCK] Consultando Pipefy para poliza: {poliza_id}")

    # Si hay un estado previamente guardado en mock, usarlo
    if poliza_id in _mock_pipefy_states:
        stored = _mock_pipefy_states[poliza_id]
        return PipelineCard(
            poliza_id=poliza_id,
            estado_actual=stored.get("estado", "Poliza detectada"),
            cliente_nombre="Empresa Mock S.A. de C.V.",
            cliente_email="contacto@empresa-mock.com",
            fecha_vencimiento=date(2025, 8, 15),
            precio_renovacion=45000.00,
            equipo_nombre="UPS Eaton 9PX 6kVA",
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[stored.get("nota", "")],
        )

    return PipelineCard(
        poliza_id=poliza_id,
        estado_actual="Poliza detectada",
        cliente_nombre="Empresa Mock S.A. de C.V.",
        cliente_email="contacto@empresa-mock.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=["Poliza detectada por sistema automatico"],
    )


def _mock_actualizar_pipefy(
    poliza_id: str,
    estado: str,
    nota: str,
    session_id: str,
) -> bool:
    """Simula la actualización de estado en Pipefy (modo local)."""
    _mock_pipefy_states[poliza_id] = {
        "estado": estado,
        "nota": nota[:200],
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        f"[MOCK] Pipefy actualizado: poliza={poliza_id}, "
        f"estado='{estado}', nota='{nota[:50]}...'"
    )
    return True


# ---------------------------------------------------------------------------
# Tool pública: consultar_pipefy
# ---------------------------------------------------------------------------


def consultar_pipefy(poliza_id: str) -> PipelineCard:
    """Consulta el estado actual de una póliza en el tablero operativo de Pipefy.

    Obtiene la card correspondiente a la póliza desde la API GraphQL de Pipefy,
    incluyendo su estado actual, datos del cliente y metadatos de seguimiento.

    Args:
        poliza_id: Identificador único de la póliza (no vacío).

    Returns:
        PipelineCard con estado actual, datos del cliente y metadatos.

    Raises:
        ValueError: Si poliza_id está vacío o es None.
        TimeoutError: Si la API no responde en 30 segundos (Req 1.5).
        PipefyAPIError: Si la API retorna error HTTP 4xx/5xx.
    """
    # Validación de entrada
    if not poliza_id or not poliza_id.strip():
        raise ValueError("poliza_id no puede estar vacio")

    _start_time = time.time()

    # Modo mock para desarrollo local
    if _is_mock_mode():
        result = _mock_consultar_pipefy(poliza_id)
        _duration_ms = (time.time() - _start_time) * 1000
        registrar_tool_call(
            tool_name="consultar_pipefy",
            params_enmascarados={"poliza_id": poliza_id},
            resultado={"estado_actual": result.estado_actual},
            duracion_ms=_duration_ms,
        )
        return result

    # Modo real: consultar API de Pipefy
    logger.info(f"Consultando Pipefy para poliza: {poliza_id}")

    token = _get_pipefy_token()
    payload = _build_consultar_query(poliza_id)
    request_body = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        _PIPEFY_API_URL,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            req, timeout=TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS
        ) as response:
            response_data = json.loads(response.read().decode("utf-8"))

            # Verificar errores GraphQL
            if "errors" in response_data:
                error_msg = response_data["errors"][0].get(
                    "message", "Error desconocido"
                )
                logger.error(f"Error GraphQL de Pipefy: {error_msg}")
                raise PipefyAPIError(400, error_msg)

            result = _parse_pipefy_response(poliza_id, response_data)
            _duration_ms = (time.time() - _start_time) * 1000
            registrar_tool_call(
                tool_name="consultar_pipefy",
                params_enmascarados={"poliza_id": poliza_id},
                resultado={"estado_actual": result.estado_actual},
                duracion_ms=_duration_ms,
            )
            return result

    except urllib.error.HTTPError as e:
        _duration_ms = (time.time() - _start_time) * 1000
        status_code = e.code
        try:
            error_body = e.read().decode("utf-8")
            error_detail = json.loads(error_body).get("message", error_body[:200])
        except Exception:
            error_detail = f"HTTP {status_code}"

        logger.error(
            f"Error HTTP {status_code} consultando Pipefy "
            f"para poliza '{poliza_id}': {error_detail}"
        )
        registrar_error(
            tipo_error="PipefyAPIError",
            componente="pipefy",
            mensaje_error=f"HTTP {status_code}: {error_detail}",
            num_reintento=0,
            accion_mitigacion="propagar_error",
        )
        raise PipefyAPIError(status_code, error_detail) from e

    except urllib.error.URLError as e:
        _duration_ms = (time.time() - _start_time) * 1000
        if "timed out" in str(e).lower() or isinstance(
            getattr(e, "reason", None), TimeoutError
        ):
            logger.error(
                f"Timeout consultando Pipefy para poliza '{poliza_id}' "
                f"(limite: {TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS}s)"
            )
            registrar_error(
                tipo_error="TimeoutError",
                componente="pipefy",
                mensaje_error=f"Timeout de {TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS}s",
                num_reintento=0,
                accion_mitigacion="terminar_sesion",
            )
            raise TimeoutError(
                f"La consulta a Pipefy excedio el timeout de "
                f"{TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS} segundos"
            ) from e
        logger.error(f"Error de red consultando Pipefy: {e}")
        registrar_error(
            tipo_error="PipefyAPIError",
            componente="pipefy",
            mensaje_error=f"Error de conectividad: {e}",
            num_reintento=0,
            accion_mitigacion="propagar_error",
        )
        raise PipefyAPIError(503, f"Error de conectividad: {e}") from e

    except TimeoutError:
        _duration_ms = (time.time() - _start_time) * 1000
        logger.error(
            f"Timeout consultando Pipefy para poliza '{poliza_id}' "
            f"(limite: {TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS}s)"
        )
        registrar_error(
            tipo_error="TimeoutError",
            componente="pipefy",
            mensaje_error=f"Timeout de {TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS}s",
            num_reintento=0,
            accion_mitigacion="terminar_sesion",
        )
        raise

    except json.JSONDecodeError as e:
        _duration_ms = (time.time() - _start_time) * 1000
        logger.error(f"Error parseando respuesta JSON de Pipefy: {e}")
        registrar_error(
            tipo_error="JSONDecodeError",
            componente="pipefy",
            mensaje_error=str(e),
            num_reintento=0,
            accion_mitigacion="propagar_error",
        )
        raise PipefyAPIError(
            500, "Respuesta de Pipefy no es JSON valido"
        ) from e


# ---------------------------------------------------------------------------
# Tool pública: actualizar_pipefy
# ---------------------------------------------------------------------------


def actualizar_pipefy(
    poliza_id: str,
    estado: str,
    nota: str,
    session_id: str,
) -> bool:
    """Actualiza el Estado_Pipefy de una póliza con trazabilidad completa.

    Valida el estado antes de invocar la API. Implementa política de retry
    con backoff exponencial (30s -> 60s) para un máximo de 2 reintentos.

    Args:
        poliza_id: Identificador único de la póliza.
        estado: Uno de los 10 estados válidos del tablero operativo.
        nota: Descripción de la acción (se trunca a 200 caracteres, Req 7.2).
        session_id: Identificador de sesión AgentCore para trazabilidad.

    Returns:
        True si la actualización fue exitosa.

    Raises:
        InvalidStateTransitionError: Si el estado no pertenece a
            ESTADOS_VALIDOS_PIPEFY (Req 7.3, 9.4).
        PipefyAPIError: Si la API retorna error tras agotar todos los
            reintentos (el agente invocará escalar_humano).
    """
    _start_time = time.time()

    # --- Validación de estado (Req 7.1, 7.3, 9.4) ---
    if estado not in ESTADOS_VALIDOS_PIPEFY:
        logger.warning(
            f"Estado invalido '{estado}' para poliza {poliza_id}. "
            f"Session: {session_id}"
        )
        raise InvalidStateTransitionError(
            estado_actual="",
            estado_destino=estado,
            message=f"Estado '{estado}' no es valido. "
            f"Estados permitidos: {sorted(ESTADOS_VALIDOS_PIPEFY)}",
        )

    # --- Truncar nota a 200 caracteres (Req 7.2) ---
    nota_truncada = nota[:200] if nota else ""

    # --- Modo mock para desarrollo local ---
    if _is_mock_mode():
        result = _mock_actualizar_pipefy(
            poliza_id, estado, nota_truncada, session_id
        )
        _duration_ms = (time.time() - _start_time) * 1000
        registrar_tool_call(
            tool_name="actualizar_pipefy",
            params_enmascarados={
                "poliza_id": poliza_id,
                "estado": estado,
                "nota": nota_truncada,
                "session_id": session_id,
            },
            resultado={"success": result},
            duracion_ms=_duration_ms,
        )
        return result

    # --- Modo real con retry (Req 7.4) ---
    token = _get_pipefy_token()
    timestamp_utc = datetime.now(timezone.utc).isoformat()
    last_error: Optional[Exception] = None

    for attempt in range(RETRY_MAX_INTENTOS_PIPEFY + 1):
        try:
            _call_pipefy_update_api(
                poliza_id, estado, nota_truncada, session_id, timestamp_utc, token
            )
            _duration_ms = (time.time() - _start_time) * 1000
            logger.info(
                f"Pipefy actualizado exitosamente: poliza={poliza_id}, "
                f"estado='{estado}' (intento {attempt + 1})"
            )
            registrar_tool_call(
                tool_name="actualizar_pipefy",
                params_enmascarados={
                    "poliza_id": poliza_id,
                    "estado": estado,
                    "nota": nota_truncada,
                    "session_id": session_id,
                },
                resultado={"success": True},
                duracion_ms=_duration_ms,
            )
            return True
        except PipefyAPIError as e:
            last_error = e
            logger.warning(
                f"Error actualizando Pipefy (intento {attempt + 1}/"
                f"{RETRY_MAX_INTENTOS_PIPEFY + 1}): {e}"
            )
            registrar_error(
                tipo_error="PipefyAPIError",
                componente="pipefy",
                mensaje_error=str(e),
                num_reintento=attempt,
                accion_mitigacion="retry" if attempt < RETRY_MAX_INTENTOS_PIPEFY else "escalar_humano",
            )
            if attempt < RETRY_MAX_INTENTOS_PIPEFY:
                backoff_seconds = RETRY_BACKOFF_BASE_SEGUNDOS * (attempt + 1)
                logger.info(
                    f"Esperando {backoff_seconds}s antes de reintentar "
                    f"(poliza={poliza_id}, intento {attempt + 2})"
                )
                time.sleep(backoff_seconds)

    _duration_ms = (time.time() - _start_time) * 1000
    logger.error(
        f"Todos los reintentos agotados para actualizar Pipefy: "
        f"poliza={poliza_id}, estado='{estado}'. Ultimo error: {last_error}"
    )
    registrar_tool_call(
        tool_name="actualizar_pipefy",
        params_enmascarados={
            "poliza_id": poliza_id,
            "estado": estado,
            "nota": nota_truncada,
            "session_id": session_id,
        },
        resultado={"success": False, "error": str(last_error)},
        duracion_ms=_duration_ms,
    )
    raise last_error  # type: ignore[misc]


def _call_pipefy_update_api(
    poliza_id: str,
    estado: str,
    nota: str,
    session_id: str,
    timestamp_utc: str,
    token: str,
) -> None:
    """Realiza la llamada HTTP a la API de Pipefy para actualizar el estado.

    Args:
        poliza_id: ID de la póliza (card) a actualizar.
        estado: Nuevo estado a registrar.
        nota: Nota de trazabilidad.
        session_id: ID de sesión AgentCore.
        timestamp_utc: Timestamp ISO 8601 de la operación.
        token: Token Bearer de autenticación.

    Raises:
        PipefyAPIError: Si la API retorna un error HTTP 4xx/5xx.
    """
    mutation = """
    mutation UpdateCardField($cardId: ID!, $fieldId: String!, $value: [UndefinedInput]) {
        updateCardField(input: {card_id: $cardId, field_id: $fieldId, new_value: $value}) {
            success
        }
    }
    """
    variables = {
        "cardId": poliza_id,
        "fieldId": "estado_pipefy",
        "value": [estado],
    }
    body = json.dumps({"query": mutation, "variables": variables}).encode("utf-8")

    req = urllib.request.Request(
        _PIPEFY_API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            if "errors" in data:
                error_msg = data["errors"][0].get(
                    "message", "Error desconocido de Pipefy"
                )
                raise PipefyAPIError(400, error_msg)
    except urllib.error.HTTPError as e:
        raise PipefyAPIError(
            e.code, f"Error HTTP al actualizar poliza {poliza_id}"
        ) from e
    except urllib.error.URLError as e:
        raise PipefyAPIError(
            503, f"Error de conexion al actualizar poliza {poliza_id}: {e}"
        ) from e

    # Agregar comentario con nota y trazabilidad
    comment_mutation = """
    mutation CreateComment($cardId: ID!, $text: String!) {
        createComment(input: {card_id: $cardId, text: $text}) {
            comment { id }
        }
    }
    """
    comment_text = (
        f"[AgentCore] Estado: {estado} | "
        f"Session: {session_id} | "
        f"Timestamp: {timestamp_utc} | "
        f"Nota: {nota}"
    )
    comment_body = json.dumps(
        {
            "query": comment_mutation,
            "variables": {"cardId": poliza_id, "text": comment_text},
        }
    ).encode("utf-8")

    comment_req = urllib.request.Request(
        _PIPEFY_API_URL,
        data=comment_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(comment_req, timeout=30):
            pass
    except Exception:
        logger.warning(
            f"No se pudo agregar comentario de trazabilidad en poliza {poliza_id}"
        )
