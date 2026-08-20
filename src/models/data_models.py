"""
Modelos de datos para el Agente Comercial IA de CIME Power Systems.
Requisitos: 1.2, 4.1, 5.3, 6.9, 7.1, 8.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional


@dataclass
class Mensaje:
    """Unidad atómica del historial conversacional."""

    timestamp: datetime
    remitente: str      # "agente" | "cliente"
    contenido: str
    tipo: str           # Ver TipoMensaje en constants.py


@dataclass
class DatosComprobanteTemp:
    """
    Datos temporales del comprobante de pago recibido.
    TTL: 10 minutos tras confirmar recepción (Req 8.5).
    """

    referencia_adjunto: str     # S3 key del archivo
    monto: float
    timestamp_recepcion: datetime
    formato: str                # "PDF" | "JPG" | "PNG" | "JPEG"
    tamanio_bytes: int


@dataclass
class ActivationPayload:
    """
    Payload enviado por Zapier al AgentCore Runtime vía HTTP POST.
    Todos los campos son obligatorios (Req 1.2).
    """

    poliza_id: str              # No vacío. ID único de la póliza en Pipefy
    cliente_nombre: str         # No vacío. Nombre del cliente o empresa
    cliente_email: str          # Email válido RFC 5321
    fecha_vencimiento: date     # Fecha ISO 8601 válida (formato YYYY-MM-DD)
    precio_renovacion: float    # Valor numérico > 0 (MXN)
    equipo_nombre: str          # No vacío. Nombre del equipo cubierto


@dataclass
class DatosPoliza:
    """Datos completos de la póliza para escalamientos y notificaciones."""

    poliza_id: str
    cliente_nombre: str
    cliente_email: str
    fecha_vencimiento: date
    precio_renovacion: float
    equipo_nombre: str


@dataclass
class SessionState:
    """Estado completo de una sesión activa en AgentCore Memory (short-term)."""

    session_id: str                     # UUID generado por AgentCore Runtime
    poliza_id: str                      # Referencia al ActivationPayload
    estado_pipefy: str                  # Último estado registrado exitosamente
    historial_mensajes: List[Mensaje]   # Todos los mensajes del hilo activo
    timestamp_inicio: datetime          # UTC
    datos_comprobante: Optional[DatosComprobanteTemp] = None  # TTL: 10 min


@dataclass
class EscalationPayload:
    """Payload enviado a la tool escalar_humano."""

    motivo: str                     # No vacío. Descripción específica del motivo
    historial: List[Mensaje]        # Historial completo de la sesión
    estado_pipefy: str              # Estado actual de la póliza
    datos_poliza: DatosPoliza       # Datos del ActivationPayload original
    timestamp: datetime             # UTC. Momento del escalamiento
    session_id: str                 # Para trazabilidad en Observability


@dataclass
class DatosPago:
    """Datos del comprobante recibido, enviados a notificar_tesoreria."""

    cliente_nombre: str             # Nombre del cliente
    poliza_id: str                  # Identificador de la póliza
    monto: float                    # Monto de la cotización enviada (MXN)
    timestamp_recepcion: datetime   # UTC. Momento de recepción del comprobante
    referencia_adjunto: str         # S3 key del archivo adjunto recibido


@dataclass
class PipelineCard:
    """Respuesta de la tool consultar_pipefy."""

    poliza_id: str
    estado_actual: str                      # Uno de los 10 estados válidos
    cliente_nombre: str
    cliente_email: str
    fecha_vencimiento: date
    precio_renovacion: float
    equipo_nombre: str
    timestamp_ultima_actualizacion: datetime
    notas: List[str] = field(default_factory=list)  # Notas históricas del tablero


@dataclass
class EmailResult:
    """Respuesta de la tool enviar_correo."""

    success: bool
    message_id: Optional[str]      # ID de mensaje SES si success=True
    timestamp: datetime             # UTC. Momento de envío confirmado
    error_code: Optional[str] = None
    error_type: Optional[str] = None   # "invalid_email" | "technical_error" | "timeout"
