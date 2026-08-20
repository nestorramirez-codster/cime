"""
AgentCore Policy — Guardrails determinísticos del Agente Comercial IA.

Este paquete implementa los guardrails que interceptan cada tool call antes
de ejecutarlo, bloqueando acciones fuera de los límites comerciales y de
seguridad aprobados por CIME Power Systems.

Requisitos: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
"""

from src.policy.guardrails import PolicyBlockResult, PolicyGuardrail

__all__ = ["PolicyGuardrail", "PolicyBlockResult"]
