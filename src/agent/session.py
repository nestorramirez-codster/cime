"""
Lógica de validación y arranque de sesión del Agente Comercial IA.

Implementa el flujo inicial de activación:
1. Validar payload
2. Consultar estado actual en Pipefy
3. Detectar discrepancias entre payload y Pipefy (Req 6.7)
4. Verificar estados bloqueantes (Req 1.6)
5. Registrar inicio de sesión en Pipefy ("Póliza detectada")
6. Persistir estado en Memory de corto plazo

Requisitos: 1.1, 1.4, 1.6, 1.7, 6.7
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from src.models.constants import ESTADOS_BLOQUEANTES
from src.models.data_models import (
    ActivationPayload,
    DatosPoliza,
    PipelineCard,
    SessionState,
)
from src.models.validators import es_payload_valido, obtener_campos_invalidos
from src.memory.short_term import guardar_estado_sesion
from src.observability.tracer import (
    registrar_cierre_sesion,
    registrar_error,
    registrar_inicio_sesion,
)
from src.tools.escalation_tools import escalar_humano
from src.tools.pipefy_tools import actualizar_pipefy, consultar_pipefy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Detección de discrepancias (Req 6.7)
# ---------------------------------------------------------------------------


def _detectar_discrepancias(
    payload: ActivationPayload, card: PipelineCard
) -> list[str]:
    """Detecta discrepancias entre el payload de activación y los datos de Pipefy.

    Compara precio (umbral >1%), nombre del cliente y fecha de vencimiento.

    Args:
        payload: Datos recibidos del webhook de Zapier.
        card: Datos actuales consultados desde Pipefy.

    Returns:
        Lista de descripciones de discrepancias encontradas (vacía si no hay).
    """
    discrepancias: list[str] = []

    # Precio difiere más del 1%
    if payload.precio_renovacion > 0:
        diferencia_precio = (
            abs(payload.precio_renovacion - card.precio_renovacion)
            / payload.precio_renovacion
        )
        if diferencia_precio > 0.01:
            discrepancias.append(
                f"Precio difiere >1%: payload={payload.precio_renovacion}, "
                f"pipefy={card.precio_renovacion}"
            )

    # Nombre del cliente difiere
    if (
        payload.cliente_nombre.strip().lower()
        != card.cliente_nombre.strip().lower()
    ):
        discrepancias.append(
            f"Nombre del cliente difiere: payload='{payload.cliente_nombre}', "
            f"pipefy='{card.cliente_nombre}'"
        )

    # Fecha de vencimiento difiere
    if payload.fecha_vencimiento != card.fecha_vencimiento:
        discrepancias.append(
            f"Fecha de vencimiento difiere: payload={payload.fecha_vencimiento}, "
            f"pipefy={card.fecha_vencimiento}"
        )

    return discrepancias


# ---------------------------------------------------------------------------
# Función principal: iniciar_sesion
# ---------------------------------------------------------------------------


def iniciar_sesion(
    payload: ActivationPayload, session_id: str
) -> dict[str, Any]:
    """Valida el payload y arranca una sesión de seguimiento comercial.

    Flujo:
    1. Validar payload con `es_payload_valido()`
    2. Si inválido: registrar error, actualizar Pipefy a "No renovada / sin respuesta", terminar
    3. Consultar Pipefy con `consultar_pipefy(poliza_id)`
    4. Si estado bloqueante (Req 1.6): terminar sin acción
    5. Si hay discrepancias (Req 6.7): escalar inmediatamente
    6. Actualizar Pipefy a "Póliza detectada" (Req 1.7)
    7. Persistir estado en Memory

    Args:
        payload: ActivationPayload recibido del webhook de Zapier.
        session_id: Identificador único de sesión generado por AgentCore Runtime.

    Returns:
        Diccionario con resultado:
        - {"success": True, "session_state": SessionState} si la sesión inició
        - {"success": False, "reason": "...", "error_details": [...]} si falló
    """
    # --- Traza: Inicio de sesión (Req 10.1) ---
    _session_start_time = time.time()
    poliza_id_traza = getattr(payload, "poliza_id", "desconocido") or "desconocido"
    registrar_inicio_sesion(
        poliza_id=poliza_id_traza,
        session_id=session_id,
        timestamp_inicio=datetime.now(timezone.utc),
        estado_pipefy_inicial="pendiente_validacion",
    )

    # --- Paso 1: Validar payload (Req 1.2, 1.3) ---
    if not es_payload_valido(payload):
        campos_invalidos = obtener_campos_invalidos(payload)
        logger.error(
            f"Payload inválido para sesión {session_id}. "
            f"Campos con error: {campos_invalidos}"
        )

        # Registrar error en observabilidad (Req 10.3)
        registrar_error(
            tipo_error="ValidationError",
            componente="session",
            mensaje_error=f"Payload inválido: campos {campos_invalidos}",
            num_reintento=0,
            accion_mitigacion="terminar_sesion",
        )

        # Actualizar Pipefy a "No renovada / sin respuesta"
        poliza_id = getattr(payload, "poliza_id", None)
        if poliza_id and isinstance(poliza_id, str) and poliza_id.strip():
            try:
                actualizar_pipefy(
                    poliza_id=poliza_id,
                    estado="No renovada / sin respuesta",
                    nota=f"Payload inválido: campos {campos_invalidos}",
                    session_id=session_id,
                )
            except Exception as e:
                logger.warning(
                    f"No se pudo actualizar Pipefy tras payload inválido: {e}"
                )

        # Traza: Cierre de sesión por payload inválido (Req 10.4)
        _duracion_total = (time.time() - _session_start_time) * 1000
        registrar_cierre_sesion(
            estado_final="No renovada / sin respuesta",
            duracion_total_ms=_duracion_total,
            mensajes_enviados=0,
            motivo_cierre="payload_invalido",
        )

        return {
            "success": False,
            "reason": "payload_invalido",
            "error_details": campos_invalidos,
        }

    # --- Paso 2: Consultar estado actual en Pipefy (Req 1.4) ---
    try:
        card: PipelineCard = consultar_pipefy(payload.poliza_id)
    except Exception as e:
        logger.error(
            f"Error consultando Pipefy para póliza {payload.poliza_id}, "
            f"sesión {session_id}: {e}"
        )
        # Registrar error técnico (Req 10.3)
        registrar_error(
            tipo_error=type(e).__name__,
            componente="pipefy",
            mensaje_error=str(e),
            num_reintento=0,
            accion_mitigacion="terminar_sesion",
        )
        # Traza: Cierre de sesión por error de consulta (Req 10.4)
        _duracion_total = (time.time() - _session_start_time) * 1000
        registrar_cierre_sesion(
            estado_final="error",
            duracion_total_ms=_duracion_total,
            mensajes_enviados=0,
            motivo_cierre="error_consulta_pipefy",
        )
        return {
            "success": False,
            "reason": "error_consulta_pipefy",
            "error_details": [str(e)],
        }

    # --- Paso 3: Verificar estado bloqueante (Req 1.6) ---
    if card.estado_actual in ESTADOS_BLOQUEANTES:
        logger.info(
            f"Estado bloqueante '{card.estado_actual}' para póliza "
            f"{payload.poliza_id}. Sesión {session_id} terminada sin acción."
        )
        # Traza: Cierre de sesión por estado bloqueante (Req 10.4)
        _duracion_total = (time.time() - _session_start_time) * 1000
        registrar_cierre_sesion(
            estado_final=card.estado_actual,
            duracion_total_ms=_duracion_total,
            mensajes_enviados=0,
            motivo_cierre="estado_bloqueante",
        )
        return {
            "success": False,
            "reason": "estado_bloqueante",
            "error_details": [
                f"Estado actual '{card.estado_actual}' impide nueva activación"
            ],
        }

    # --- Paso 4: Detectar discrepancias (Req 6.7) ---
    discrepancias = _detectar_discrepancias(payload, card)
    if discrepancias:
        logger.warning(
            f"Discrepancias detectadas para póliza {payload.poliza_id}: "
            f"{discrepancias}. Escalando a humano."
        )

        # Registrar error por discrepancia (Req 10.3)
        registrar_error(
            tipo_error="DiscrepanciaError",
            componente="session",
            mensaje_error=f"Discrepancias payload/Pipefy: {'; '.join(discrepancias)}",
            num_reintento=0,
            accion_mitigacion="escalar_humano",
        )

        datos_poliza = DatosPoliza(
            poliza_id=payload.poliza_id,
            cliente_nombre=payload.cliente_nombre,
            cliente_email=payload.cliente_email,
            fecha_vencimiento=payload.fecha_vencimiento,
            precio_renovacion=payload.precio_renovacion,
            equipo_nombre=payload.equipo_nombre,
        )

        try:
            escalar_humano(
                motivo=(
                    f"Discrepancia entre payload y Pipefy: "
                    f"{'; '.join(discrepancias)}"
                ),
                historial=[],
                estado_pipefy=card.estado_actual,
                datos_poliza=datos_poliza,
                session_id=session_id,
            )
        except Exception as e:
            logger.error(f"Error al escalar por discrepancia: {e}")
            registrar_error(
                tipo_error=type(e).__name__,
                componente="escalation",
                mensaje_error=str(e),
                num_reintento=0,
                accion_mitigacion="log_fallback",
            )

        # Traza: Cierre de sesión por discrepancia (Req 10.4)
        _duracion_total = (time.time() - _session_start_time) * 1000
        registrar_cierre_sesion(
            estado_final=card.estado_actual,
            duracion_total_ms=_duracion_total,
            mensajes_enviados=0,
            motivo_cierre="discrepancia_datos",
        )

        return {
            "success": False,
            "reason": "discrepancia_datos",
            "error_details": discrepancias,
        }

    # --- Paso 5: Actualizar Pipefy a "Póliza detectada" (Req 1.7) ---
    try:
        actualizar_pipefy(
            poliza_id=payload.poliza_id,
            estado="Póliza detectada",
            nota="Sesión de seguimiento iniciada por AgentCore",
            session_id=session_id,
        )
    except Exception as e:
        logger.error(
            f"Error actualizando Pipefy a 'Póliza detectada' "
            f"para póliza {payload.poliza_id}: {e}"
        )
        # Registrar error técnico (Req 10.3)
        registrar_error(
            tipo_error=type(e).__name__,
            componente="pipefy",
            mensaje_error=str(e),
            num_reintento=0,
            accion_mitigacion="terminar_sesion",
        )
        # Traza: Cierre de sesión por error de actualización (Req 10.4)
        _duracion_total = (time.time() - _session_start_time) * 1000
        registrar_cierre_sesion(
            estado_final="error",
            duracion_total_ms=_duracion_total,
            mensajes_enviados=0,
            motivo_cierre="error_actualizar_pipefy",
        )
        return {
            "success": False,
            "reason": "error_actualizar_pipefy",
            "error_details": [str(e)],
        }

    # --- Paso 6: Crear y persistir estado de sesión ---
    session_state = SessionState(
        session_id=session_id,
        poliza_id=payload.poliza_id,
        estado_pipefy="Póliza detectada",
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )

    try:
        guardar_estado_sesion(session_state)
    except Exception as e:
        logger.warning(
            f"Error guardando estado de sesión {session_id} en Memory: {e}. "
            f"La sesión continuará sin persistencia inicial."
        )

    logger.info(
        f"Sesión {session_id} iniciada exitosamente para póliza "
        f"{payload.poliza_id}. Estado: 'Póliza detectada'."
    )

    return {
        "success": True,
        "session_state": session_state,
    }
