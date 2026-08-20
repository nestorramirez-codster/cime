"""
Webhook Handler — Punto de entrada HTTP para activaciones de Zapier.

Recibe un HTTP POST con el ActivationPayload de Zapier, valida el payload,
genera un session_id único, invoca el AgentCore Runtime (o modo mock local)
y retorna la respuesta a Zapier en < 30 segundos (Req 12.6).

Funciona como:
- AWS Lambda handler (event/context)
- FastAPI endpoint (si se integra con una app FastAPI)

La invocación al AgentCore Runtime en modo producción es asíncrona (fire-and-forget)
para garantizar que la respuesta HTTP llega a Zapier dentro del SLA de 30s.
En modo mock, la sesión se inicia de forma síncrona para facilitar testing local.

Requisitos: 1.1, 12.6
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any

from src.models.data_models import ActivationPayload
from src.models.validators import es_payload_valido, obtener_campos_invalidos
from src.observability.tracer import registrar_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Modo de ejecución: "mock" (local) o "prod" (AWS AgentCore Runtime)
# ---------------------------------------------------------------------------
EXECUTION_MODE = os.environ.get("AGENT_EXECUTION_MODE", "mock")


# ---------------------------------------------------------------------------
# Parsing del payload JSON → ActivationPayload
# ---------------------------------------------------------------------------


def _parsear_payload(body: dict[str, Any]) -> ActivationPayload:
    """
    Parsea un diccionario JSON al dataclass ActivationPayload.

    Realiza conversión de tipos:
    - fecha_vencimiento: str ISO 8601 → date
    - precio_renovacion: str/int/float → float

    Args:
        body: Diccionario con los campos del payload.

    Returns:
        Instancia de ActivationPayload.

    Raises:
        ValueError: Si algún campo no puede ser convertido al tipo esperado.
        KeyError: Si faltan campos obligatorios en el body.
    """
    # Extraer campos con valores por defecto seguros para evitar KeyError
    poliza_id = body.get("poliza_id", "")
    cliente_nombre = body.get("cliente_nombre", "")
    cliente_email = body.get("cliente_email", "")
    fecha_vencimiento_raw = body.get("fecha_vencimiento", "")
    precio_renovacion_raw = body.get("precio_renovacion", 0)
    equipo_nombre = body.get("equipo_nombre", "")

    # Convertir fecha_vencimiento de string a date
    fecha_vencimiento: date
    if isinstance(fecha_vencimiento_raw, date):
        fecha_vencimiento = fecha_vencimiento_raw
    elif isinstance(fecha_vencimiento_raw, str) and fecha_vencimiento_raw.strip():
        fecha_vencimiento = date.fromisoformat(fecha_vencimiento_raw.strip())
    else:
        # Valor inválido — se asigna un placeholder para que el validador lo rechace
        fecha_vencimiento = date(1900, 1, 1)

    # Convertir precio_renovacion a float
    try:
        precio_renovacion = float(precio_renovacion_raw) if precio_renovacion_raw else 0.0
    except (TypeError, ValueError):
        precio_renovacion = 0.0

    return ActivationPayload(
        poliza_id=str(poliza_id) if poliza_id is not None else "",
        cliente_nombre=str(cliente_nombre) if cliente_nombre is not None else "",
        cliente_email=str(cliente_email) if cliente_email is not None else "",
        fecha_vencimiento=fecha_vencimiento,
        precio_renovacion=precio_renovacion,
        equipo_nombre=str(equipo_nombre) if equipo_nombre is not None else "",
    )


# ---------------------------------------------------------------------------
# Invocación del AgentCore Runtime (modo producción via boto3)
# ---------------------------------------------------------------------------


def _invocar_agentcore_runtime(
    payload: ActivationPayload, session_id: str
) -> dict[str, Any]:
    """
    Invoca el AgentCore Runtime via AWS SDK (boto3 bedrock-agent-runtime).

    Solo se usa en modo producción. En modo mock, se usa iniciar_sesion() local.

    Args:
        payload: ActivationPayload validado.
        session_id: Identificador único de sesión generado.

    Returns:
        Diccionario con el resultado de la invocación.
    """
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    agent_id = os.environ.get("AGENTCORE_AGENT_ID", "")
    agent_alias_id = os.environ.get("AGENTCORE_AGENT_ALIAS_ID", "")

    client = boto3.client("bedrock-agent-runtime", region_name=region)

    # Construir el input text con el payload serializado
    input_text = json.dumps(
        {
            "poliza_id": payload.poliza_id,
            "cliente_nombre": payload.cliente_nombre,
            "cliente_email": payload.cliente_email,
            "fecha_vencimiento": payload.fecha_vencimiento.isoformat(),
            "precio_renovacion": payload.precio_renovacion,
            "equipo_nombre": payload.equipo_nombre,
        },
        ensure_ascii=False,
    )

    response = client.invoke_agent(
        agentId=agent_id,
        agentAliasId=agent_alias_id,
        sessionId=session_id,
        inputText=input_text,
    )

    return {"success": True, "response": response}


def _invocar_agentcore_runtime_async(
    payload: ActivationPayload, session_id: str
) -> None:
    """
    Invoca el AgentCore Runtime de forma asíncrona (fire-and-forget).

    Lanza un thread daemon que ejecuta la invocación al runtime sin bloquear
    la respuesta HTTP al webhook de Zapier. Esto garantiza cumplir con el SLA
    de < 30 segundos de respuesta (Req 12.6).

    Cualquier error en la invocación se registra en Observability sin afectar
    la respuesta HTTP ya enviada.

    Args:
        payload: ActivationPayload validado.
        session_id: Identificador único de sesión.
    """

    def _run() -> None:
        try:
            _invocar_agentcore_runtime(payload, session_id)
            logger.info(
                f"AgentCore Runtime invocado exitosamente "
                f"(async) para sesión {session_id}"
            )
        except Exception as e:
            logger.error(
                f"Error en invocación async de AgentCore Runtime "
                f"para sesión {session_id}: {e}"
            )
            registrar_error(
                tipo_error=type(e).__name__,
                componente="webhook_async",
                mensaje_error=str(e),
                num_reintento=0,
                accion_mitigacion="log_fallback",
            )

    thread = threading.Thread(target=_run, daemon=True, name=f"agentcore-{session_id}")
    thread.start()


# ---------------------------------------------------------------------------
# Handler principal (Lambda + FastAPI compatible)
# ---------------------------------------------------------------------------


def webhook_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """
    Handler principal del webhook que recibe activaciones de Zapier.

    Flujo:
    1. Extraer y parsear el body JSON del evento HTTP
    2. Validar el ActivationPayload
    3. Si inválido → HTTP 400 con campos en error
    4. Generar session_id (UUID4)
    5. Invocar AgentCore Runtime (prod) o iniciar_sesion() (mock)
    6. Retornar HTTP 200 con {"status": "accepted", "session_id": "..."}

    Cumple con Req 12.6: respuesta en < 30 segundos.

    Args:
        event: Evento HTTP (Lambda proxy integration o dict con "body").
        context: Contexto Lambda (opcional, puede ser None para FastAPI).

    Returns:
        Diccionario con statusCode, headers y body JSON para API Gateway.
    """
    # --- Paso 1: Extraer body del evento ---
    try:
        body = _extraer_body(event)
    except Exception as e:
        logger.error(f"Error extrayendo body del webhook: {e}")
        return _respuesta_error(
            status_code=400,
            error="invalid_request",
            message=f"No se pudo parsear el body del request: {str(e)}",
        )

    # --- Paso 2: Parsear payload ---
    try:
        payload = _parsear_payload(body)
    except (ValueError, TypeError) as e:
        logger.error(f"Error parseando ActivationPayload: {e}")
        return _respuesta_error(
            status_code=400,
            error="parse_error",
            message=f"Error al parsear el payload: {str(e)}",
        )

    # --- Paso 3: Validar payload ---
    if not es_payload_valido(payload):
        campos_invalidos = obtener_campos_invalidos(payload)
        logger.warning(
            f"Payload inválido recibido en webhook. Campos: {campos_invalidos}"
        )
        return _respuesta_error(
            status_code=400,
            error="validation_error",
            message="El payload no cumple con los criterios de validación.",
            details={"campos_invalidos": campos_invalidos},
        )

    # --- Paso 4: Generar session_id ---
    session_id = str(uuid.uuid4())

    # --- Paso 5: Invocar AgentCore Runtime o modo mock ---
    try:
        if EXECUTION_MODE == "prod":
            # Fire-and-forget: responder a Zapier inmediatamente (Req 12.6)
            _invocar_agentcore_runtime_async(payload, session_id)
        else:
            # Modo mock: invocar iniciar_sesion() directamente (síncrono)
            from src.agent.session import iniciar_sesion

            resultado = iniciar_sesion(payload, session_id)
            if not resultado.get("success"):
                logger.warning(
                    f"Sesión {session_id} no iniciada: {resultado.get('reason')}"
                )
                # Aún retornamos 200 a Zapier con status accepted
                # ya que el payload fue recibido y procesado correctamente.
                # Los errores de lógica de negocio (estado bloqueante, etc.)
                # no son errores del webhook en sí.

    except Exception as e:
        logger.error(
            f"Error invocando AgentCore Runtime para sesión {session_id}: {e}"
        )
        registrar_error(
            tipo_error=type(e).__name__,
            componente="webhook",
            mensaje_error=str(e),
            num_reintento=0,
            accion_mitigacion="retornar_500",
        )
        return _respuesta_error(
            status_code=500,
            error="runtime_error",
            message="Error interno al procesar la activación.",
            details={"session_id": session_id},
        )

    # --- Paso 6: Retornar respuesta exitosa (Req 12.6) ---
    logger.info(
        f"Webhook procesado exitosamente. session_id={session_id}, "
        f"poliza_id={payload.poliza_id}"
    )

    return _respuesta_exitosa(session_id)


# ---------------------------------------------------------------------------
# Funciones auxiliares
# ---------------------------------------------------------------------------


def _extraer_body(event: dict[str, Any]) -> dict[str, Any]:
    """
    Extrae el body JSON del evento HTTP.

    Soporta:
    - Lambda proxy integration (body como string JSON)
    - Dict directo (para FastAPI o tests)
    """
    if "body" in event:
        body_raw = event["body"]
        if isinstance(body_raw, str):
            return json.loads(body_raw)
        elif isinstance(body_raw, dict):
            return body_raw
        else:
            raise ValueError(f"Tipo de body inesperado: {type(body_raw)}")
    else:
        # Asumir que el evento es el body directamente
        return event


def _respuesta_exitosa(session_id: str) -> dict[str, Any]:
    """
    Construye la respuesta HTTP 200 exitosa para Zapier.

    Format: {"status": "accepted", "session_id": "..."}
    """
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(
            {
                "status": "accepted",
                "session_id": session_id,
            },
            ensure_ascii=False,
        ),
    }


def _respuesta_error(
    status_code: int,
    error: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Construye una respuesta HTTP de error.

    Args:
        status_code: Código HTTP (400 o 500).
        error: Código de error corto.
        message: Descripción del error.
        details: Detalles adicionales (opcional).
    """
    body: dict[str, Any] = {
        "status": "error",
        "error": error,
        "message": message,
    }
    if details:
        body["details"] = details

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
