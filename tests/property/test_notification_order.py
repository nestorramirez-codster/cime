"""
Property-Based Test — Propiedad 12: Orden temporal de notificación de comprobante.

Feature: agente-comercial-polizas
Property 12: Orden temporal de notificación de comprobante

**Validates: Requirements 5.3**

Para N eventos de recepción de comprobante con adjuntos válidos, verificar que
`timestamp(confirmacion_cliente) < timestamp(notificacion_tesoreria)`.

Es decir, enviar_correo (confirmación al cliente) se invoca SIEMPRE ANTES de
notificar_tesoreria. Esto garantiza que el cliente recibe la confirmación de
recepción previo a que Tesorería sea notificada (Req 5.3).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.agent.flows.comprobante import Adjunto, procesar_comprobante
from src.models.constants import (
    FORMATOS_COMPROBANTE_ACEPTADOS,
    TAMANIO_MAXIMO_COMPROBANTE_BYTES,
)
from src.models.data_models import ActivationPayload, SessionState


# ---------------------------------------------------------------------------
# Estrategias Hypothesis
# ---------------------------------------------------------------------------

# Extensiones válidas para comprobantes
_extensiones_validas = sorted(FORMATOS_COMPROBANTE_ACEPTADOS)

_st_extension_valida = st.sampled_from(_extensiones_validas).flatmap(
    lambda ext: st.sampled_from([ext.lower(), ext.upper(), ext.capitalize()])
)

# Nombre base del archivo (sin punto)
_st_nombre_base = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        blacklist_characters=".\x00/\\",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: "." not in s and len(s.strip()) > 0)

# Nombre de archivo con extensión válida
_st_nombre_archivo_valido = st.tuples(_st_nombre_base, _st_extension_valida).map(
    lambda t: f"{t[0]}.{t[1]}"
)

# Tamaño válido: 1 byte hasta el máximo permitido
_st_tamanio_valido = st.integers(min_value=1, max_value=TAMANIO_MAXIMO_COMPROBANTE_BYTES)

# S3 key para referencia del adjunto
_st_s3_key = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=5,
    max_size=30,
).map(lambda s: f"comprobantes/{s}.pdf")

# Campos de texto no vacíos para datos del cliente
_st_texto_no_vacio = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=30,
).filter(lambda s: bool(s.strip()))

# Precio de renovación positivo
_st_precio_positivo = st.floats(
    min_value=1000.0,
    max_value=500_000.0,
    allow_nan=False,
    allow_infinity=False,
)

# Fecha de vencimiento
_st_fecha = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2030, 12, 31),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crear_session_state(poliza_id: str = "POL-PROP12") -> SessionState:
    """Crea un SessionState válido para el test."""
    return SessionState(
        session_id="test-session-prop12",
        poliza_id=poliza_id,
        estado_pipefy="Depósito solicitado",
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )


# ===========================================================================
# PROPERTY TEST — Propiedad 12: Orden temporal de notificación de comprobante
# ===========================================================================


class TestProperty12OrdenTemporalNotificacion:
    """
    Feature: agente-comercial-polizas
    Property 12: Orden temporal de notificación de comprobante

    **Validates: Requirements 5.3**

    Para N eventos de recepción de comprobante con adjuntos válidos,
    verificar que enviar_correo (confirmación al cliente) se ejecuta
    ANTES de notificar_tesoreria.
    """

    @given(
        nombre_archivo=_st_nombre_archivo_valido,
        tamanio=_st_tamanio_valido,
        s3_key=_st_s3_key,
        cliente_nombre=_st_texto_no_vacio,
        equipo_nombre=_st_texto_no_vacio,
        precio=_st_precio_positivo,
        fecha=_st_fecha,
    )
    @settings(
        max_examples=100,
        deadline=10000,
        suppress_health_check=[HealthCheck.too_slow],
    )
    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.escalar_humano")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_confirmacion_cliente_precede_notificacion_tesoreria(
        self,
        mock_enviar_correo: MagicMock,
        mock_actualizar_pipefy: MagicMock,
        mock_escalar_humano: MagicMock,
        mock_notificar_tesoreria: MagicMock,
        nombre_archivo: str,
        tamanio: int,
        s3_key: str,
        cliente_nombre: str,
        equipo_nombre: str,
        precio: float,
        fecha: date,
    ) -> None:
        """
        Req 5.3 — Para cada comprobante válido procesado, la confirmación al
        cliente (enviar_correo de confirmación de recepción) DEBE ocurrir
        temporalmente ANTES de notificar_tesoreria.

        Verificación: se usa un contador de orden de llamadas para registrar
        la secuencia exacta en que se invocan enviar_correo y notificar_tesoreria.
        """
        # Rastreador de orden de llamadas
        call_order: List[str] = []

        def _track_enviar_correo(*args, **kwargs):
            call_order.append("enviar_correo")
            return MagicMock(
                success=True, message_id="msg-prop12", error_code=None
            )

        def _track_notificar_tesoreria(*args, **kwargs):
            call_order.append("notificar_tesoreria")
            return True

        mock_enviar_correo.side_effect = _track_enviar_correo
        mock_notificar_tesoreria.side_effect = _track_notificar_tesoreria
        mock_actualizar_pipefy.return_value = True

        # Construir adjunto válido
        adjunto = Adjunto(
            nombre_archivo=nombre_archivo,
            tamanio_bytes=tamanio,
            s3_key=s3_key,
        )

        # Construir payload
        payload = ActivationPayload(
            poliza_id="POL-PROP12-TEST",
            cliente_nombre=cliente_nombre,
            cliente_email="test@example.com",
            fecha_vencimiento=fecha,
            precio_renovacion=precio,
            equipo_nombre=equipo_nombre,
        )

        session_state = _crear_session_state()

        # Ejecutar flujo de procesamiento de comprobante
        result = procesar_comprobante(
            adjunto=adjunto,
            session_state=session_state,
            payload=payload,
        )

        # --- Verificación de la propiedad temporal ---
        # El adjunto es válido, por lo que el flujo debe completar
        # los pasos 3 (confirmación) y 4 (notificar tesorería).
        assert result["formato_valido"] is True, (
            f"El adjunto '{nombre_archivo}' ({tamanio} bytes) debería ser válido "
            f"pero fue rechazado: {result.get('motivo', '')}"
        )

        # enviar_correo debe haberse llamado (confirmación al cliente)
        assert "enviar_correo" in call_order, (
            f"enviar_correo no fue invocado para el comprobante válido "
            f"'{nombre_archivo}'. call_order={call_order}"
        )

        # notificar_tesoreria debe haberse llamado
        assert "notificar_tesoreria" in call_order, (
            f"notificar_tesoreria no fue invocado para el comprobante válido "
            f"'{nombre_archivo}'. call_order={call_order}"
        )

        # PROPIEDAD CLAVE (Req 5.3):
        # El índice de enviar_correo (confirmación) DEBE ser MENOR que
        # el índice de notificar_tesoreria (notificación a tesorería).
        idx_confirmacion = call_order.index("enviar_correo")
        idx_tesoreria = call_order.index("notificar_tesoreria")

        assert idx_confirmacion < idx_tesoreria, (
            f"VIOLACIÓN Req 5.3: La confirmación al cliente (enviar_correo) "
            f"debe ocurrir ANTES de notificar_tesoreria.\n"
            f"Orden observado: {call_order}\n"
            f"idx(enviar_correo)={idx_confirmacion}, "
            f"idx(notificar_tesoreria)={idx_tesoreria}\n"
            f"Adjunto: '{nombre_archivo}' ({tamanio} bytes)"
        )
