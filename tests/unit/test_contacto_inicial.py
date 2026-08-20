"""
Unit tests para el flujo de contacto inicial.

Cubre:
- Pre-vencimiento incluye mención de descuento 5%
- Post-vencimiento excluye mención de descuento
- KB score < 0.70 dispara escalamiento a humano
- Envío exitoso de correo actualiza estado en Pipefy
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.agent.flows.contacto_inicial import (
    _es_pre_vencimiento,
    _formatear_precio,
    enviar_contacto_inicial,
)
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.data_models import ActivationPayload, SessionState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_state():
    """SessionState de prueba."""
    return SessionState(
        session_id="test-session-001",
        poliza_id="POL-TEST-001",
        estado_pipefy="Póliza detectada",
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )


@pytest.fixture
def payload_pre_vencimiento():
    """Payload con fecha de vencimiento futura (pre-vencimiento)."""
    return ActivationPayload(
        poliza_id="POL-TEST-001",
        cliente_nombre="Empresa Test S.A. de C.V.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date.today() + timedelta(days=15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


@pytest.fixture
def payload_post_vencimiento():
    """Payload con fecha de vencimiento pasada (post-vencimiento)."""
    return ActivationPayload(
        poliza_id="POL-TEST-002",
        cliente_nombre="Empresa Vencida S.A.",
        cliente_email="admin@empresa-vencida.com",
        fecha_vencimiento=date.today() - timedelta(days=10),
        precio_renovacion=72500.50,
        equipo_nombre="UPS APC Smart-UPS 10kVA",
    )


@pytest.fixture
def mock_kb_client_high_score():
    """KBClient que retorna score alto (>= 0.70)."""
    kb = MagicMock(spec=KBClient)
    kb.query.return_value = KBQueryResponse(
        results=[
            KBResult(
                content="Plantilla de contacto inicial...",
                score=0.85,
                source_uri="s3://cime-kb/plantillas_mensajes.md",
            )
        ],
        query_text="plantilla mensaje correo",
    )
    return kb


@pytest.fixture
def mock_kb_client_low_score():
    """KBClient que retorna score bajo (< 0.70)."""
    kb = MagicMock(spec=KBClient)
    kb.query.return_value = KBQueryResponse(
        results=[
            KBResult(
                content="Resultado poco relevante",
                score=0.45,
                source_uri="s3://cime-kb/other.md",
            )
        ],
        query_text="plantilla mensaje correo",
    )
    return kb


# ---------------------------------------------------------------------------
# Tests: _formatear_precio
# ---------------------------------------------------------------------------


class TestFormatearPrecio:
    def test_formato_con_agrupacion_y_decimales(self):
        assert _formatear_precio(45000.00) == "45,000.00 MXN"

    def test_formato_centavos(self):
        assert _formatear_precio(72500.50) == "72,500.50 MXN"

    def test_formato_precio_grande(self):
        assert _formatear_precio(1250000.99) == "1,250,000.99 MXN"

    def test_formato_precio_sin_centavos(self):
        assert _formatear_precio(100.0) == "100.00 MXN"


# ---------------------------------------------------------------------------
# Tests: _es_pre_vencimiento
# ---------------------------------------------------------------------------


class TestEsPreVencimiento:
    def test_fecha_futura_es_pre_vencimiento(self):
        assert _es_pre_vencimiento(date.today() + timedelta(days=1)) is True

    def test_fecha_hoy_no_es_pre_vencimiento(self):
        # fecha_vencimiento == hoy → no es ">" hoy, así que es post
        assert _es_pre_vencimiento(date.today()) is False

    def test_fecha_pasada_no_es_pre_vencimiento(self):
        assert _es_pre_vencimiento(date.today() - timedelta(days=5)) is False


# ---------------------------------------------------------------------------
# Tests: enviar_contacto_inicial — Pre-vencimiento incluye descuento
# ---------------------------------------------------------------------------


class TestContactoInicialPreVencimiento:
    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_pre_vencimiento_incluye_descuento(
        self,
        mock_enviar_correo,
        mock_actualizar_pipefy,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client_high_score,
    ):
        """El correo pre-vencimiento DEBE incluir mención del 5% de descuento."""
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-123", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        result = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            kb_client=mock_kb_client_high_score,
        )

        assert result["success"] is True
        assert result["pre_vencimiento"] is True

        # Verificar que el correo contiene mención del descuento
        call_args = mock_enviar_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo") or call_args[1].get("cuerpo", "")
        if not cuerpo:
            # Intentar positional args
            cuerpo = call_args[0][2] if len(call_args[0]) > 2 else ""

        assert "5%" in cuerpo
        assert "descuento" in cuerpo.lower()

    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_pre_vencimiento_contiene_datos_personalizados(
        self,
        mock_enviar_correo,
        mock_actualizar_pipefy,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client_high_score,
    ):
        """El correo incluye nombre del cliente, equipo, fecha y precio."""
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-456", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        enviar_contacto_inicial(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            kb_client=mock_kb_client_high_score,
        )

        call_args = mock_enviar_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo") or call_args[1].get("cuerpo", "")
        if not cuerpo:
            cuerpo = call_args[0][2] if len(call_args[0]) > 2 else ""

        assert payload_pre_vencimiento.cliente_nombre in cuerpo
        assert payload_pre_vencimiento.equipo_nombre in cuerpo
        assert "45,000.00 MXN" in cuerpo


# ---------------------------------------------------------------------------
# Tests: enviar_contacto_inicial — Post-vencimiento excluye descuento
# ---------------------------------------------------------------------------


class TestContactoInicialPostVencimiento:
    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_post_vencimiento_excluye_descuento(
        self,
        mock_enviar_correo,
        mock_actualizar_pipefy,
        session_state,
        payload_post_vencimiento,
        mock_kb_client_high_score,
    ):
        """El correo post-vencimiento NO debe incluir mención del 5% de descuento."""
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-789", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        result = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload_post_vencimiento,
            kb_client=mock_kb_client_high_score,
        )

        assert result["success"] is True
        assert result["pre_vencimiento"] is False

        # Verificar que NO contiene mención del descuento
        call_args = mock_enviar_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo") or call_args[1].get("cuerpo", "")
        if not cuerpo:
            cuerpo = call_args[0][2] if len(call_args[0]) > 2 else ""

        assert "5%" not in cuerpo
        assert "descuento" not in cuerpo.lower()

    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_post_vencimiento_contiene_datos_personalizados(
        self,
        mock_enviar_correo,
        mock_actualizar_pipefy,
        session_state,
        payload_post_vencimiento,
        mock_kb_client_high_score,
    ):
        """El correo post-vencimiento incluye nombre, equipo, fecha y precio."""
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-101", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        enviar_contacto_inicial(
            session_state=session_state,
            payload=payload_post_vencimiento,
            kb_client=mock_kb_client_high_score,
        )

        call_args = mock_enviar_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo") or call_args[1].get("cuerpo", "")
        if not cuerpo:
            cuerpo = call_args[0][2] if len(call_args[0]) > 2 else ""

        assert payload_post_vencimiento.cliente_nombre in cuerpo
        assert payload_post_vencimiento.equipo_nombre in cuerpo
        assert "72,500.50 MXN" in cuerpo


# ---------------------------------------------------------------------------
# Tests: KB score < 0.70 dispara escalamiento
# ---------------------------------------------------------------------------


class TestContactoInicialKBScoreBajo:
    @patch("src.agent.flows.contacto_inicial.escalar_humano")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_kb_score_bajo_escala_humano(
        self,
        mock_enviar_correo,
        mock_escalar_humano,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client_low_score,
    ):
        """Si KB score < 0.70, se escala a humano y NO se envía correo."""
        mock_escalar_humano.return_value = True

        result = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            kb_client=mock_kb_client_low_score,
        )

        assert result["success"] is False
        assert "escalado" in result["motivo"].lower()

        # No se envía correo
        mock_enviar_correo.assert_not_called()

        # Se invoca escalamiento
        mock_escalar_humano.assert_called_once()
        call_kwargs = mock_escalar_humano.call_args.kwargs
        assert "score" in call_kwargs["motivo"].lower()
        assert call_kwargs["session_id"] == session_state.session_id


# ---------------------------------------------------------------------------
# Tests: Envío exitoso actualiza Pipefy
# ---------------------------------------------------------------------------


class TestContactoInicialActualizaPipefy:
    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_envio_exitoso_actualiza_pipefy(
        self,
        mock_enviar_correo,
        mock_actualizar_pipefy,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client_high_score,
    ):
        """Tras envío exitoso de correo, se actualiza Pipefy con estado y timestamp."""
        mock_enviar_correo.return_value = MagicMock(
            success=True, message_id="msg-202", error_code=None
        )
        mock_actualizar_pipefy.return_value = True

        result = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            kb_client=mock_kb_client_high_score,
        )

        assert result["success"] is True

        # Verificar que actualizar_pipefy fue llamado con los parámetros correctos
        mock_actualizar_pipefy.assert_called_once()
        call_kwargs = mock_actualizar_pipefy.call_args.kwargs
        assert call_kwargs["poliza_id"] == payload_pre_vencimiento.poliza_id
        assert call_kwargs["estado"] == "Contacto inicial enviado"
        assert call_kwargs["session_id"] == session_state.session_id
        # La nota debe contener timestamp UTC
        assert "UTC" in call_kwargs["nota"]

    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    def test_envio_fallido_no_actualiza_pipefy(
        self,
        mock_enviar_correo,
        mock_actualizar_pipefy,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client_high_score,
    ):
        """Si el envío del correo falla, NO se actualiza Pipefy."""
        mock_enviar_correo.return_value = MagicMock(
            success=False, message_id=None, error_code="technical_error"
        )

        result = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            kb_client=mock_kb_client_high_score,
        )

        assert result["success"] is False
        mock_actualizar_pipefy.assert_not_called()
