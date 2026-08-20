"""
Paquete de Observabilidad — Agente Comercial IA · CIME Power Systems.

Exporta las 5 funciones de traza y la función de enmascaramiento.
Requisitos: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""

from src.observability.tracer import (
    enmascarar_datos_sensibles,
    registrar_bloqueo_policy,
    registrar_cierre_sesion,
    registrar_error,
    registrar_inicio_sesion,
    registrar_tool_call,
)

__all__ = [
    "enmascarar_datos_sensibles",
    "registrar_inicio_sesion",
    "registrar_tool_call",
    "registrar_error",
    "registrar_cierre_sesion",
    "registrar_bloqueo_policy",
]
