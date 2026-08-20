"""
Tool de escalamiento a intervención humana para el Agente Comercial IA.

Implementa `escalar_humano`: el circuit breaker final del sistema.
Nunca debe fallar silenciosamente. Si la notificación vía Slack falla,
registra el payload completo en CloudWatch Logs como fallback.

Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import List

from src.models.constants import ESTADOS_VALIDOS_PIPEFY
from src.models.data_models import (
    DatosPoliza,
    EscalationPayload,
    Mensaje,
)
from src.observability.tracer import registrar_error, registrar_tool_call

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

_MOCK_MODE = os.environ.get("CIME_MOCK_MODE", "true").lower() == "true"
_SLACK_SECRET_ID = "cime/comercial/slack-webhook"


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _get_slack_webhook_url() -> str:
    """
    Obtiene la URL del webhook de Slack desde AWS Secrets Manager.

    En modo mock, retorna una URL ficticia.
    En modo real, consulta Secrets Manager con el secreto 'cime/comercial/slack-webhook'.

    Returns:
        URL del webhook de Slack para notificaciones de escalamiento.
    """
    if _MOCK_MODE:
        return "https://hooks.slack.com/services/mock/webhook/url"

    import boto3

    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=_SLACK_SECRET_ID)
    secret = json.loads(response["SecretString"])
    return secret.get("webhook_url", "")


def _serializar_payload(payload: EscalationPayload) -> dict:
    """
    Serializa el EscalationPayload a un diccionario JSON-compatible.

    Convierte objetos datetime y date a strings ISO 8601.

    Args:
        payload: El payload de escalamiento a serializar.

    Returns:
        Diccionario serializable a JSON.
    """

    def _convert(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        return obj

    raw = asdict(payload)

    def _deep_convert(d):
        if isinstance(d, dict):
            return {k: _deep_convert(v) for k, v in d.items()}
        if isinstance(d, list):
            return [_deep_convert(item) for item in d]
        return _convert(d)

    return _deep_convert(raw)


def _construir_slack_blocks(payload: EscalationPayload) -> dict:
    """
    Construye el payload de Slack con bloques formateados para el Equipo Comercial.

    Args:
        payload: EscalationPayload con todos los datos del escalamiento.

    Returns:
        Diccionario con la estructura de mensaje de Slack (blocks + text fallback).
    """
    # Resumen del historial: últimos 3 mensajes o menos
    historial_resumen = ""
    ultimos_mensajes = payload.historial[-3:] if payload.historial else []
    for msg in ultimos_mensajes:
        ts = msg.timestamp.strftime("%Y-%m-%d %H:%M") if isinstance(msg.timestamp, datetime) else str(msg.timestamp)
        historial_resumen += f"• [{ts}] {msg.remitente}: {msg.contenido[:100]}\n"

    if not historial_resumen:
        historial_resumen = "_Sin historial de mensajes._"

    # Texto fallback para clientes de Slack que no soportan blocks
    fallback_text = (
        f"🚨 Escalamiento: {payload.motivo} | "
        f"Póliza: {payload.datos_poliza.poliza_id} | "
        f"Cliente: {payload.datos_poliza.cliente_nombre}"
    )

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚨 Escalamiento a Equipo Comercial",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Motivo:*\n{payload.motivo}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Estado Pipefy:*\n{payload.estado_pipefy}",
                },
            ],
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Póliza:*\n{payload.datos_poliza.poliza_id}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Cliente:*\n{payload.datos_poliza.cliente_nombre}",
                },
            ],
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Email:*\n{payload.datos_poliza.cliente_email}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Equipo:*\n{payload.datos_poliza.equipo_nombre}",
                },
            ],
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Vencimiento:*\n"
                        f"{payload.datos_poliza.fecha_vencimiento.isoformat()}"
                    ),
                },
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Precio renovación:*\n"
                        f"${payload.datos_poliza.precio_renovacion:,.2f} MXN"
                    ),
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Últimos mensajes del historial:*\n{historial_resumen}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"Session: `{payload.session_id}` | "
                        f"Timestamp: {payload.timestamp.isoformat()}"
                    ),
                }
            ],
        },
    ]

    return {"text": fallback_text, "blocks": blocks}


def _enviar_slack(webhook_url: str, slack_payload: dict) -> bool:
    """
    Envía el payload al webhook de Slack.

    Args:
        webhook_url: URL completa del webhook de Slack.
        slack_payload: Diccionario con blocks y text para Slack.

    Returns:
        True si Slack responde con HTTP 200.

    Raises:
        Exception: Si hay cualquier error de red o Slack responde con error.
    """
    import requests

    response = requests.post(
        webhook_url,
        json=slack_payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return True


# ---------------------------------------------------------------------------
# Tool pública: escalar_humano
# ---------------------------------------------------------------------------


def escalar_humano(
    motivo: str,
    historial: List[Mensaje],
    estado_pipefy: str,
    datos_poliza: DatosPoliza,
    session_id: str = "unknown",
) -> bool:
    """
    Escala el caso al Equipo Comercial con contexto completo.

    Este es el CIRCUIT BREAKER FINAL del sistema. Nunca falla silenciosamente.
    Si la notificación vía Slack falla, registra el payload completo en
    CloudWatch Logs (nivel CRITICAL) como fallback de observabilidad.

    Args:
        motivo: Descripción específica del motivo de escalamiento (no vacío).
        historial: Lista completa de mensajes intercambiados con el cliente.
        estado_pipefy: Estado actual de la póliza en Pipefy.
        datos_poliza: Datos completos de la póliza (del payload de activación).
        session_id: Identificador de sesión AgentCore (default: "unknown").

    Returns:
        True siempre. El escalamiento queda registrado ya sea vía Slack o
        en CloudWatch Logs como fallback.

    Raises:
        ValueError: Si `motivo` está vacío o `estado_pipefy` no es un
            estado válido de Pipefy.
    """
    _start_time = time.time()

    # --- Validaciones previas (Req 6.9) ---
    if not motivo or not motivo.strip():
        raise ValueError(
            "El motivo de escalamiento no puede ser vacío. "
            "Debe describir la razón específica del escalamiento."
        )

    if estado_pipefy not in ESTADOS_VALIDOS_PIPEFY:
        raise ValueError(
            f"Estado Pipefy '{estado_pipefy}' no es válido. "
            f"Estados permitidos: {sorted(ESTADOS_VALIDOS_PIPEFY)}"
        )

    # --- Construir EscalationPayload completo (Req 6.9) ---
    timestamp_utc = datetime.now(timezone.utc)

    payload = EscalationPayload(
        motivo=motivo.strip(),
        historial=historial,
        estado_pipefy=estado_pipefy,
        datos_poliza=datos_poliza,
        timestamp=timestamp_utc,
        session_id=session_id,
    )

    logger.info(
        f"Escalamiento iniciado: motivo='{motivo[:50]}...', "
        f"poliza={datos_poliza.poliza_id}, "
        f"estado={estado_pipefy}, session={session_id}"
    )

    # --- Modo mock para desarrollo local ---
    if _MOCK_MODE:
        payload_dict = _serializar_payload(payload)
        logger.info(
            f"[MOCK] Escalamiento notificado al Equipo Comercial:\n"
            f"{json.dumps(payload_dict, indent=2, ensure_ascii=False)}"
        )
        _duration_ms = (time.time() - _start_time) * 1000
        registrar_tool_call(
            tool_name="escalar_humano",
            params_enmascarados={
                "motivo": motivo,
                "estado_pipefy": estado_pipefy,
                "poliza_id": datos_poliza.poliza_id,
                "session_id": session_id,
            },
            resultado={"success": True},
            duracion_ms=_duration_ms,
        )
        return True

    # --- Modo real: notificar vía Slack webhook ---
    try:
        webhook_url = _get_slack_webhook_url()
        slack_payload = _construir_slack_blocks(payload)
        _enviar_slack(webhook_url, slack_payload)

        _duration_ms = (time.time() - _start_time) * 1000
        logger.info(
            f"Escalamiento notificado exitosamente vía Slack: "
            f"poliza={datos_poliza.poliza_id}, session={session_id}"
        )
        registrar_tool_call(
            tool_name="escalar_humano",
            params_enmascarados={
                "motivo": motivo,
                "estado_pipefy": estado_pipefy,
                "poliza_id": datos_poliza.poliza_id,
                "session_id": session_id,
            },
            resultado={"success": True},
            duracion_ms=_duration_ms,
        )
        return True

    except Exception as e:
        _duration_ms = (time.time() - _start_time) * 1000

        # --- CIRCUIT BREAKER: fallback a CloudWatch Logs ---
        # Nunca fallar silenciosamente. Registrar el payload completo
        # a nivel CRITICAL para que sea visible en CloudWatch Logs.
        payload_dict = _serializar_payload(payload)

        logger.critical(
            f"ESCALAMIENTO FALLBACK - Slack webhook falló pero el escalamiento "
            f"queda registrado en logs. Error: {e}. "
            f"PAYLOAD COMPLETO DE ESCALAMIENTO: "
            f"{json.dumps(payload_dict, ensure_ascii=False)}"
        )

        logger.warning(
            f"El escalamiento para póliza {datos_poliza.poliza_id} "
            f"(session={session_id}) fue registrado en CloudWatch Logs "
            f"como fallback. La notificación vía Slack NO fue entregada. "
            f"Error original: {type(e).__name__}: {e}"
        )

        # Registrar error técnico en tracer
        registrar_error(
            tipo_error=type(e).__name__,
            componente="escalation",
            mensaje_error=f"Slack webhook falló: {e}",
            num_reintento=0,
            accion_mitigacion="log_fallback",
        )

        registrar_tool_call(
            tool_name="escalar_humano",
            params_enmascarados={
                "motivo": motivo,
                "estado_pipefy": estado_pipefy,
                "poliza_id": datos_poliza.poliza_id,
                "session_id": session_id,
            },
            resultado={"success": True, "fallback": "cloudwatch_logs"},
            duracion_ms=_duration_ms,
        )

        # Retornamos True: el escalamiento está "registrado" en logs
        # aunque Slack no haya sido notificado.
        return True
