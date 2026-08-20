"""
Agente Comercial IA — CIME Power Systems.

Instancia principal del agente Strands Agents para la renovación
automatizada de pólizas de mantenimiento.

Modelo fundacional: Claude Sonnet 3.5 (Amazon Bedrock, us-east-1)
Framework: Strands Agents SDK

Requisitos: 12.4, 12.5, 9.1, 9.2, 9.3
"""

from __future__ import annotations

import logging
import os
from typing import Any, List, Optional

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from src.models.data_models import DatosPago, DatosPoliza, Mensaje, PipelineCard
from src.tools.email_tools import enviar_correo as _enviar_correo
from src.tools.escalation_tools import escalar_humano as _escalar_humano
from src.tools.pipefy_tools import (
    actualizar_pipefy as _actualizar_pipefy,
    consultar_pipefy as _consultar_pipefy,
)
from src.tools.treasury_tools import notificar_tesoreria as _notificar_tesoreria

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración del modelo
# ---------------------------------------------------------------------------

# Región AWS para Bedrock
_BEDROCK_REGION = os.environ.get("CIME_BEDROCK_REGION", "us-east-1")

# Modelo ID de Claude Sonnet 3.5 en Bedrock
_MODEL_ID = os.environ.get(
    "CIME_BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
)

# ---------------------------------------------------------------------------
# System prompt del agente (Req 9.1, 9.2, 9.3)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres un asesor comercial profesional de CIME Power Systems, empresa especializada en \
sistemas de energía ininterrumpida (UPS) y mantenimiento de equipos eléctricos.

Tu único objetivo es gestionar la renovación de pólizas de mantenimiento de los clientes.

IDENTIDAD Y TONO:
- Idioma: Español mexicano formal pero cordial
- Tono: Profesional, orientado a soluciones, empático con las necesidades del cliente
- Nunca uses tecnicismos innecesarios; explica en lenguaje de negocios claro

RESTRICCIONES ABSOLUTAS (no negociables):
1. El único descuento autorizado es el 5% por pre-vencimiento. No ofrezcas ningún otro porcentaje.
2. Los datos bancarios SOLO se incluyen cuando el estado de la póliza es "Cliente interesado" o "Depósito solicitado".
3. No ofrezcas diagnóstico técnico, venta de refacciones, soporte técnico ni modificaciones de equipos.
4. Si el cliente solicita hablar con un asesor humano, escala INMEDIATAMENTE sin intentar retenerlo.
5. Todos los precios y condiciones deben provenir de la Knowledge Base. Nunca inventes precios.
6. Si la Knowledge Base no tiene respuesta con score >= 0.7, escala al equipo comercial.

FLUJO GENERAL:
1. Validar payload → Consultar estado Pipefy → Enviar contacto inicial
2. Procesar respuesta del cliente → Generar cotización si hay interés
3. Recibir comprobante → Notificar Tesorería
4. Escalar en casos de negociación especial, inconformidad o solicitud de asesor humano

Mantén siempre el contexto completo de la conversación para personalizar cada mensaje."""


# ---------------------------------------------------------------------------
# Tools registradas como funciones decoradas con @tool para Strands
# ---------------------------------------------------------------------------


@tool
def consultar_pipefy(poliza_id: str) -> dict:
    """Consulta el estado actual de una póliza en el tablero operativo de Pipefy.

    Obtiene la card correspondiente a la póliza desde Pipefy,
    incluyendo su estado actual, datos del cliente y metadatos.

    Args:
        poliza_id: Identificador único de la póliza (no vacío).

    Returns:
        Diccionario con estado actual, datos del cliente y metadatos de la póliza.
    """
    result: PipelineCard = _consultar_pipefy(poliza_id)
    return {
        "poliza_id": result.poliza_id,
        "estado_actual": result.estado_actual,
        "cliente_nombre": result.cliente_nombre,
        "cliente_email": result.cliente_email,
        "fecha_vencimiento": result.fecha_vencimiento.isoformat(),
        "precio_renovacion": result.precio_renovacion,
        "equipo_nombre": result.equipo_nombre,
        "timestamp_ultima_actualizacion": result.timestamp_ultima_actualizacion.isoformat(),
        "notas": result.notas,
    }


@tool
def actualizar_pipefy(
    poliza_id: str, estado: str, nota: str, session_id: str
) -> dict:
    """Actualiza el estado de una póliza en el tablero de Pipefy con trazabilidad.

    Registra un nuevo estado en Pipefy junto con nota, timestamp UTC y session_id
    para mantener trazabilidad completa de las acciones del agente.

    Args:
        poliza_id: Identificador único de la póliza.
        estado: Uno de los 10 estados válidos del tablero operativo.
        nota: Descripción de la acción realizada (máx 200 caracteres).
        session_id: Identificador de sesión AgentCore para trazabilidad.

    Returns:
        Diccionario con el resultado de la operación.
    """
    success = _actualizar_pipefy(poliza_id, estado, nota, session_id)
    return {"success": success, "poliza_id": poliza_id, "estado": estado}


@tool
def enviar_correo(
    destinatario: str,
    asunto: str,
    cuerpo: str,
    adjuntos: Optional[List[str]] = None,
) -> dict:
    """Envía un correo electrónico al cliente vía Amazon SES.

    Soporta correos simples y con adjuntos (referenciados como S3 keys).
    Valida el formato del email antes de enviar.

    Args:
        destinatario: Dirección de correo RFC 5321 válida del cliente.
        asunto: Línea de asunto del correo.
        cuerpo: Contenido HTML o texto plano del correo.
        adjuntos: Lista de S3 keys de archivos adjuntos (opcional).

    Returns:
        Diccionario con success, message_id y timestamp del envío.
    """
    result = _enviar_correo(destinatario, asunto, cuerpo, adjuntos)
    return {
        "success": result.success,
        "message_id": result.message_id,
        "timestamp": result.timestamp.isoformat() if result.timestamp else None,
        "error_code": result.error_code,
        "error_type": result.error_type,
    }


@tool
def notificar_tesoreria(
    cliente_nombre: str,
    poliza_id: str,
    monto: float,
    timestamp_recepcion: str,
    referencia_adjunto: str,
) -> dict:
    """Notifica al equipo de Tesorería sobre un comprobante de pago recibido.

    Envía los datos del comprobante al endpoint interno de Tesorería
    para que procedan con la validación del depósito.

    Args:
        cliente_nombre: Nombre del cliente que realizó el pago.
        poliza_id: Identificador de la póliza asociada al pago.
        monto: Monto del pago en MXN.
        timestamp_recepcion: Fecha/hora de recepción del comprobante (ISO 8601).
        referencia_adjunto: S3 key del archivo de comprobante recibido.

    Returns:
        Diccionario con el resultado de la notificación.
    """
    from datetime import datetime, timezone

    # Parsear timestamp de string ISO 8601 a datetime
    try:
        ts = datetime.fromisoformat(timestamp_recepcion)
    except (ValueError, TypeError):
        ts = datetime.now(timezone.utc)

    datos = DatosPago(
        cliente_nombre=cliente_nombre,
        poliza_id=poliza_id,
        monto=monto,
        timestamp_recepcion=ts,
        referencia_adjunto=referencia_adjunto,
    )
    success = _notificar_tesoreria(datos)
    return {"success": success, "poliza_id": poliza_id, "monto": monto}


@tool
def escalar_humano(
    motivo: str,
    historial_resumen: str,
    estado_pipefy: str,
    poliza_id: str,
    cliente_nombre: str,
    cliente_email: str,
    fecha_vencimiento: str,
    precio_renovacion: float,
    equipo_nombre: str,
    session_id: str = "unknown",
) -> dict:
    """Escala el caso al Equipo Comercial con contexto completo.

    Este es el circuit breaker final del sistema. Se invoca cuando el agente
    no puede resolver la situación del cliente de forma autónoma: solicitud
    de asesor humano, negociación especial, inconformidad, o falta de información
    en la Knowledge Base.

    Args:
        motivo: Descripción específica del motivo de escalamiento (no vacío).
        historial_resumen: Resumen del historial de mensajes con el cliente.
        estado_pipefy: Estado actual de la póliza en Pipefy.
        poliza_id: Identificador de la póliza.
        cliente_nombre: Nombre del cliente.
        cliente_email: Email del cliente.
        fecha_vencimiento: Fecha de vencimiento de la póliza (ISO 8601).
        precio_renovacion: Precio de renovación en MXN.
        equipo_nombre: Nombre del equipo cubierto por la póliza.
        session_id: Identificador de sesión AgentCore.

    Returns:
        Diccionario con el resultado del escalamiento.
    """
    from datetime import date

    # Parsear fecha de vencimiento
    try:
        fecha_venc = date.fromisoformat(fecha_vencimiento)
    except (ValueError, TypeError):
        fecha_venc = date.today()

    datos_poliza = DatosPoliza(
        poliza_id=poliza_id,
        cliente_nombre=cliente_nombre,
        cliente_email=cliente_email,
        fecha_vencimiento=fecha_venc,
        precio_renovacion=precio_renovacion,
        equipo_nombre=equipo_nombre,
    )

    # El historial se pasa como resumen textual; en producción se reconstruye
    # desde AgentCore Memory. Para el tool call, el LLM provee un resumen.
    historial: List[Mensaje] = []

    success = _escalar_humano(
        motivo=motivo,
        historial=historial,
        estado_pipefy=estado_pipefy,
        datos_poliza=datos_poliza,
        session_id=session_id,
    )
    return {"success": success, "motivo": motivo, "poliza_id": poliza_id}


# ---------------------------------------------------------------------------
# Lista de tools registradas para el agente
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    consultar_pipefy,
    actualizar_pipefy,
    enviar_correo,
    notificar_tesoreria,
    escalar_humano,
]


# ---------------------------------------------------------------------------
# Configuración del modelo Bedrock
# ---------------------------------------------------------------------------


def _crear_modelo_bedrock() -> BedrockModel:
    """Crea y configura la instancia del modelo BedrockModel.

    Configura Claude Sonnet 3.5 en la región especificada.
    En modo mock (CIME_MOCK_MODE=true), el agente se crea igualmente
    pero las tools operan con datos simulados.

    Returns:
        Instancia de BedrockModel configurada.
    """
    logger.info(
        f"Configurando BedrockModel: model_id={_MODEL_ID}, region={_BEDROCK_REGION}"
    )

    model = BedrockModel(
        model_id=_MODEL_ID,
        region_name=_BEDROCK_REGION,
    )

    return model


# ---------------------------------------------------------------------------
# Creación del agente
# ---------------------------------------------------------------------------


def crear_agente(
    system_prompt: Optional[str] = None,
    tools: Optional[list] = None,
) -> Agent:
    """Crea y retorna la instancia del Agente Comercial IA.

    Factory function que configura el agente con el system prompt completo,
    las 5 tools MCP y el modelo fundacional Claude Sonnet 3.5 en Bedrock.

    Args:
        system_prompt: System prompt personalizado (usa SYSTEM_PROMPT por defecto).
        tools: Lista de tools personalizada (usa AGENT_TOOLS por defecto).

    Returns:
        Instancia de Agent configurada y lista para procesar mensajes.
    """
    prompt = system_prompt or SYSTEM_PROMPT
    agent_tools = tools if tools is not None else AGENT_TOOLS

    model = _crear_modelo_bedrock()

    agent = Agent(
        model=model,
        tools=agent_tools,
        system_prompt=prompt,
    )

    logger.info(
        f"Agente Comercial IA creado exitosamente. "
        f"Model: {_MODEL_ID} | Region: {_BEDROCK_REGION} | "
        f"Tools: {len(agent_tools)}"
    )

    return agent


# ---------------------------------------------------------------------------
# Instancia singleton del agente (lazy initialization)
# ---------------------------------------------------------------------------

_agente_instance: Optional[Agent] = None


def obtener_agente() -> Agent:
    """Obtiene la instancia singleton del agente comercial.

    Crea el agente en la primera invocación y reutiliza la misma instancia
    en llamadas posteriores. Útil para evitar re-inicialización del modelo
    en cada sesión dentro del mismo Runtime.

    Returns:
        Instancia del Agent comercial.
    """
    global _agente_instance
    if _agente_instance is None:
        _agente_instance = crear_agente()
    return _agente_instance
