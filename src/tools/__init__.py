"""
Tools MCP para el Agente Comercial IA de CIME Power Systems.

Expone las 5 herramientas que el agente puede invocar vía AgentCore Gateway:
- consultar_pipefy: Consultar estado de una póliza en Pipefy
- actualizar_pipefy: Actualizar estado en Pipefy con trazabilidad
- enviar_correo: Enviar correo vía Amazon SES
- notificar_tesoreria: Notificar a Tesorería sobre comprobantes
- escalar_humano: Escalar caso a equipo comercial (circuit breaker final)
"""

from src.tools.email_tools import InvalidEmailError, SESError, enviar_correo
from src.tools.escalation_tools import escalar_humano
from src.tools.pipefy_tools import (
    InvalidStateTransitionError,
    PipefyAPIError,
    actualizar_pipefy,
    consultar_pipefy,
)
from src.tools.treasury_tools import NotificationError, notificar_tesoreria

__all__ = [
    # Tools
    "consultar_pipefy",
    "actualizar_pipefy",
    "enviar_correo",
    "notificar_tesoreria",
    "escalar_humano",
    # Exceptions
    "PipefyAPIError",
    "InvalidStateTransitionError",
    "InvalidEmailError",
    "SESError",
    "NotificationError",
]
