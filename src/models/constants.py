"""
Constantes del dominio para el Agente Comercial IA de CIME Power Systems.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Estados válidos del tablero operativo de Pipefy (Req 7.1, 9.4)
# Ningún tool call puede registrar un estado fuera de este conjunto.
# ---------------------------------------------------------------------------
ESTADOS_VALIDOS_PIPEFY: frozenset[str] = frozenset({
    "Póliza detectada",
    "Contacto inicial enviado",
    "Seguimiento en curso",
    "Cliente interesado",
    "Depósito solicitado",
    "Comprobante recibido",
    "En validación con tesorería",
    "Renovación confirmada",
    "Escalado a humano",
    "No renovada / sin respuesta",
})

# Estados que bloquean una nueva activación del agente (Req 1.6)
ESTADOS_BLOQUEANTES: frozenset[str] = frozenset({
    "Renovación confirmada",
    "Escalado a humano",
})

# Estados en los que el agente NO debe incluir datos bancarios (Req 4.4, 9.2)
ESTADOS_CON_DATOS_BANCARIOS: frozenset[str] = frozenset({
    "Cliente interesado",
    "Depósito solicitado",
})

# ---------------------------------------------------------------------------
# Tipos de mensaje en el historial conversacional
# ---------------------------------------------------------------------------
class TipoMensaje:
    """Valores válidos para el campo `tipo` en la dataclass Mensaje."""

    CONTACTO_INICIAL = "contacto_inicial"
    SEGUIMIENTO = "seguimiento"
    COTIZACION = "cotizacion"
    CONFIRMACION_COMPROBANTE = "confirmacion_comprobante"
    ENCUESTA = "encuesta"
    RESPUESTA_CLIENTE = "respuesta_cliente"

    TODOS: frozenset[str] = frozenset({
        "contacto_inicial",
        "seguimiento",
        "cotizacion",
        "confirmacion_comprobante",
        "encuesta",
        "respuesta_cliente",
    })


# ---------------------------------------------------------------------------
# Tipos de remitente
# ---------------------------------------------------------------------------
class Remitente:
    AGENTE = "agente"
    CLIENTE = "cliente"

    TODOS: frozenset[str] = frozenset({"agente", "cliente"})


# ---------------------------------------------------------------------------
# Formatos de comprobante aceptados (Req 5.1, 5.6)
# ---------------------------------------------------------------------------
FORMATOS_COMPROBANTE_ACEPTADOS: frozenset[str] = frozenset({
    "PDF", "JPG", "PNG", "JPEG",
})

# Tamaño máximo de comprobante: 10 MB (Req 5.1)
TAMANIO_MAXIMO_COMPROBANTE_BYTES: int = 10 * 1024 * 1024  # 10 MB

# ---------------------------------------------------------------------------
# Parámetros comerciales (Req 3, 4.3)
# ---------------------------------------------------------------------------
DESCUENTO_PRE_VENCIMIENTO: float = 0.05  # 5 %

# Ventana comercial inicial: 30 días antes del vencimiento (configurable)
VENTANA_COMERCIAL_DIAS: int = 30

# ---------------------------------------------------------------------------
# Parámetros de Knowledge Base (Req 11.1, 11.2)
# ---------------------------------------------------------------------------
KB_SCORE_MINIMO: float = 0.70
KB_TOP_K: int = 5

# ---------------------------------------------------------------------------
# Parámetros de retry (Req 1.5, 2.6, 4.5, 5.5, 7.4)
# ---------------------------------------------------------------------------
RETRY_MAX_INTENTOS_PIPEFY: int = 2          # actualizar_pipefy
RETRY_MAX_INTENTOS_CORREO: int = 1          # enviar_correo (error técnico)
RETRY_MAX_INTENTOS_TESORERIA: int = 1       # notificar_tesoreria
RETRY_BACKOFF_BASE_SEGUNDOS: int = 30       # Primer backoff
TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS: int = 30
TIMEOUT_NOTIFICAR_TESORERIA_SEGUNDOS: int = 60
RETRY_BACKOFF_CORREO_SEGUNDOS: int = 60

# ---------------------------------------------------------------------------
# Observabilidad: tamaño máximo de traza (Req 10.1)
# ---------------------------------------------------------------------------
OBSERVABILITY_MAX_ENTRY_BYTES: int = 10 * 1024  # 10 KB

# ---------------------------------------------------------------------------
# Memory TTL (Req 8.3, 8.5)
# ---------------------------------------------------------------------------
MEMORY_SHORT_TERM_TTL_HORAS: int = 24
MEMORY_COMPROBANTE_TTL_MINUTOS: int = 10
MEMORY_LONG_TERM_WRITE_TIMEOUT_SEGUNDOS: int = 30
