"""
Módulo del Agente Comercial IA de CIME Power Systems.

Expone la factory function y el system prompt del agente principal
implementado con Strands Agents SDK + Claude Sonnet 3.5 (Amazon Bedrock).
"""

from src.agent.agent import (
    AGENT_TOOLS,
    SYSTEM_PROMPT,
    crear_agente,
    obtener_agente,
)

__all__ = [
    "SYSTEM_PROMPT",
    "AGENT_TOOLS",
    "crear_agente",
    "obtener_agente",
]
