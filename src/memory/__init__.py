"""
Módulo de Memory para el Agente Comercial IA de CIME Power Systems.

Provee gestión de memoria conversacional:
- Long-term Memory (S3 JSON): historial por póliza persistido indefinidamente.

Requisitos: 8.2, 8.3, 8.4
"""

from src.memory.long_term import persistir_historial, recuperar_historial

__all__ = ["persistir_historial", "recuperar_historial"]
