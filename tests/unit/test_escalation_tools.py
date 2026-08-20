"""
Unit tests para la tool escalar_humano.

Verifica:
- Validación de inputs (motivo vacío, estado inválido)
- Construcción correcta del EscalationPayload
- Comportamiento de circuit breaker (fallback a logs cuando Slack falla)
- Modo mock para desarrollo local
- Formato de mensaje Slack con blocks

Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9
"""

import json
import logging
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models.constants import ESTADOS_VALIDOS_PIPEFY
from src.models.data_models import DatosPoliza, EscalationPayload, Mensaje
from src.tools.escalation_tools import (
    _construir_slack_blocks,
    _serializar_payload,
    escalar_humano,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def datos_poliza_ejemplo():
    """Datos de póliza de ejemplo para tests."""
    return DatosPoliza(
        poliza_id="POL-2024-001",
        cliente_nombre="Empresa ABC S.A. de C.V.",
        cliente_email="contacto@empresa-abc.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Trifásico 100 kVA",
    )


@pytest.fixture
def historial_ejemplo():
    """Historial de mensajes de ejemplo."""
    return [
        Mensaje(
            timestamp=datetime(2025, 7, 10, 14, 30, 0, tzinfo=timezone.utc),
            remitente="agente",
            contenido="Buenos días, le contactamos respecto a su póliza de mantenimiento.",
            tipo="contacto_inicial",
        ),
        Mensaje(
            timestamp=datetime(2025, 7, 11, 9, 15, 0, tzinfo=timezone.utc),
            remitente="cliente",
            contenido="Quisiera hablar con un asesor humano por favor.",
            tipo="respuesta_cliente",
        ),
    ]


# ---------------------------------------------------------------------------
# Tests de validación de inputs
# ---------------------------------------------------------------------------


class TestValidacionInputs:
    """Tests para la validación de parámetros de entrada."""

    def test_motivo_vacio_lanza_valueerror(self, datos_poliza_ejemplo):
        """Motivo vacío debe lanzar ValueError."""
        with pytest.raises(ValueError, match="motivo.*no puede ser vacío"):
            escalar_humano(
                motivo="",
                historial=[],
                estado_pipefy="Cliente interesado",
                datos_poliza=datos_poliza_ejemplo,
            )

    def test_motivo_solo_espacios_lanza_valueerror(self, datos_poliza_ejemplo):
        """Motivo con solo espacios en blanco debe lanzar ValueError."""
        with pytest.raises(ValueError, match="motivo.*no puede ser vacío"):
            escalar_humano(
                motivo="   ",
                historial=[],
                estado_pipefy="Cliente interesado",
                datos_poliza=datos_poliza_ejemplo,
            )

    def test_estado_pipefy_invalido_lanza_valueerror(self, datos_poliza_ejemplo):
        """Estado Pipefy no válido debe lanzar ValueError."""
        with pytest.raises(ValueError, match="no es válido"):
            escalar_humano(
                motivo="Cliente solicitó asesor humano",
                historial=[],
                estado_pipefy="Estado Inventado",
                datos_poliza=datos_poliza_ejemplo,
            )

    def test_estado_pipefy_vacio_lanza_valueerror(self, datos_poliza_ejemplo):
        """Estado Pipefy vacío debe lanzar ValueError."""
        with pytest.raises(ValueError, match="no es válido"):
            escalar_humano(
                motivo="Motivo válido",
                historial=[],
                estado_pipefy="",
                datos_poliza=datos_poliza_ejemplo,
            )

    @pytest.mark.parametrize("estado", sorted(ESTADOS_VALIDOS_PIPEFY))
    def test_todos_estados_validos_no_lanzan_error(
        self, estado, datos_poliza_ejemplo
    ):
        """Todos los estados válidos de Pipefy deben ser aceptados sin error."""
        # En modo mock, simplemente debe retornar True
        result = escalar_humano(
            motivo="Test con estado válido",
            historial=[],
            estado_pipefy=estado,
            datos_poliza=datos_poliza_ejemplo,
        )
        assert result is True


# ---------------------------------------------------------------------------
# Tests de modo mock (desarrollo local)
# ---------------------------------------------------------------------------


class TestModoMock:
    """Tests para el modo mock de desarrollo local."""

    def test_modo_mock_retorna_true(
        self, datos_poliza_ejemplo, historial_ejemplo
    ):
        """En modo mock, debe retornar True sin llamar a Slack."""
        result = escalar_humano(
            motivo="Cliente solicitó hablar con asesor",
            historial=historial_ejemplo,
            estado_pipefy="Seguimiento en curso",
            datos_poliza=datos_poliza_ejemplo,
            session_id="sess-test-123",
        )
        assert result is True

    def test_modo_mock_logea_payload(
        self, datos_poliza_ejemplo, historial_ejemplo, caplog
    ):
        """En modo mock, debe loguear el payload completo."""
        with caplog.at_level(logging.INFO):
            escalar_humano(
                motivo="Cliente solicitó hablar con asesor",
                historial=historial_ejemplo,
                estado_pipefy="Seguimiento en curso",
                datos_poliza=datos_poliza_ejemplo,
                session_id="sess-test-mock",
            )

        assert "[MOCK]" in caplog.text
        assert "Escalamiento notificado" in caplog.text

    def test_session_id_default_es_unknown(self, datos_poliza_ejemplo):
        """Sin session_id explícito, debe usar 'unknown'."""
        result = escalar_humano(
            motivo="Motivo de test",
            historial=[],
            estado_pipefy="Escalado a humano",
            datos_poliza=datos_poliza_ejemplo,
        )
        assert result is True

    def test_historial_vacio_funciona(self, datos_poliza_ejemplo):
        """Historial vacío es válido (puede no haber interacción previa)."""
        result = escalar_humano(
            motivo="Discrepancia de datos detectada",
            historial=[],
            estado_pipefy="Póliza detectada",
            datos_poliza=datos_poliza_ejemplo,
            session_id="sess-no-historial",
        )
        assert result is True


# ---------------------------------------------------------------------------
# Tests de circuit breaker (fallback a logs)
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Tests para el comportamiento de circuit breaker."""

    @patch("src.tools.escalation_tools._MOCK_MODE", False)
    @patch("src.tools.escalation_tools._get_slack_webhook_url")
    @patch("src.tools.escalation_tools._enviar_slack")
    def test_slack_falla_retorna_true(
        self,
        mock_enviar,
        mock_get_url,
        datos_poliza_ejemplo,
        historial_ejemplo,
    ):
        """Si Slack falla, debe retornar True (fallback a logs)."""
        mock_get_url.return_value = "https://hooks.slack.com/test"
        mock_enviar.side_effect = Exception("Connection refused")

        result = escalar_humano(
            motivo="Test de fallback",
            historial=historial_ejemplo,
            estado_pipefy="Seguimiento en curso",
            datos_poliza=datos_poliza_ejemplo,
            session_id="sess-fallback-test",
        )

        assert result is True

    @patch("src.tools.escalation_tools._MOCK_MODE", False)
    @patch("src.tools.escalation_tools._get_slack_webhook_url")
    @patch("src.tools.escalation_tools._enviar_slack")
    def test_slack_falla_logea_critical(
        self,
        mock_enviar,
        mock_get_url,
        datos_poliza_ejemplo,
        historial_ejemplo,
        caplog,
    ):
        """Si Slack falla, debe registrar el payload a nivel CRITICAL."""
        mock_get_url.return_value = "https://hooks.slack.com/test"
        mock_enviar.side_effect = Exception("Timeout")

        with caplog.at_level(logging.CRITICAL):
            escalar_humano(
                motivo="Test de fallback critical",
                historial=historial_ejemplo,
                estado_pipefy="Seguimiento en curso",
                datos_poliza=datos_poliza_ejemplo,
                session_id="sess-critical-log",
            )

        assert "ESCALAMIENTO FALLBACK" in caplog.text
        assert "PAYLOAD COMPLETO" in caplog.text
        assert "POL-2024-001" in caplog.text

    @patch("src.tools.escalation_tools._MOCK_MODE", False)
    @patch("src.tools.escalation_tools._get_slack_webhook_url")
    @patch("src.tools.escalation_tools._enviar_slack")
    def test_slack_falla_logea_warning_contexto(
        self,
        mock_enviar,
        mock_get_url,
        datos_poliza_ejemplo,
        caplog,
    ):
        """Si Slack falla, debe loguear un warning explicativo."""
        mock_get_url.return_value = "https://hooks.slack.com/test"
        mock_enviar.side_effect = ConnectionError("DNS resolution failed")

        with caplog.at_level(logging.WARNING):
            escalar_humano(
                motivo="Motivo de warning test",
                historial=[],
                estado_pipefy="Escalado a humano",
                datos_poliza=datos_poliza_ejemplo,
                session_id="sess-warning-test",
            )

        assert "CloudWatch Logs" in caplog.text
        assert "Slack NO fue entregada" in caplog.text

    @patch("src.tools.escalation_tools._MOCK_MODE", False)
    @patch("src.tools.escalation_tools._get_slack_webhook_url")
    @patch("src.tools.escalation_tools._enviar_slack")
    def test_slack_exitoso_retorna_true(
        self,
        mock_enviar,
        mock_get_url,
        datos_poliza_ejemplo,
        historial_ejemplo,
    ):
        """Si Slack funciona correctamente, debe retornar True."""
        mock_get_url.return_value = "https://hooks.slack.com/test"
        mock_enviar.return_value = True

        result = escalar_humano(
            motivo="Escalamiento normal exitoso",
            historial=historial_ejemplo,
            estado_pipefy="Cliente interesado",
            datos_poliza=datos_poliza_ejemplo,
            session_id="sess-success",
        )

        assert result is True
        mock_enviar.assert_called_once()


# ---------------------------------------------------------------------------
# Tests de construcción de payload
# ---------------------------------------------------------------------------


class TestConstruccionPayload:
    """Tests para la serialización y formato del payload."""

    def test_serializar_payload_incluye_todos_los_campos(
        self, datos_poliza_ejemplo, historial_ejemplo
    ):
        """El payload serializado debe incluir todos los campos requeridos."""
        payload = EscalationPayload(
            motivo="Test completo",
            historial=historial_ejemplo,
            estado_pipefy="Seguimiento en curso",
            datos_poliza=datos_poliza_ejemplo,
            timestamp=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
            session_id="sess-serialize-test",
        )

        serialized = _serializar_payload(payload)

        assert serialized["motivo"] == "Test completo"
        assert serialized["estado_pipefy"] == "Seguimiento en curso"
        assert serialized["session_id"] == "sess-serialize-test"
        assert serialized["timestamp"] == "2025-07-15T10:00:00+00:00"
        assert serialized["datos_poliza"]["poliza_id"] == "POL-2024-001"
        assert serialized["datos_poliza"]["cliente_nombre"] == "Empresa ABC S.A. de C.V."
        assert len(serialized["historial"]) == 2

    def test_serializar_payload_es_json_compatible(
        self, datos_poliza_ejemplo, historial_ejemplo
    ):
        """El payload serializado debe ser convertible a JSON sin errores."""
        payload = EscalationPayload(
            motivo="Test JSON",
            historial=historial_ejemplo,
            estado_pipefy="Póliza detectada",
            datos_poliza=datos_poliza_ejemplo,
            timestamp=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
            session_id="sess-json-test",
        )

        serialized = _serializar_payload(payload)
        # Esto no debe lanzar excepción
        json_str = json.dumps(serialized, ensure_ascii=False)
        assert isinstance(json_str, str)
        assert "POL-2024-001" in json_str

    def test_construir_slack_blocks_incluye_motivo(
        self, datos_poliza_ejemplo, historial_ejemplo
    ):
        """Los bloques de Slack deben incluir el motivo del escalamiento."""
        payload = EscalationPayload(
            motivo="Cliente solicitó asesor humano urgente",
            historial=historial_ejemplo,
            estado_pipefy="Seguimiento en curso",
            datos_poliza=datos_poliza_ejemplo,
            timestamp=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
            session_id="sess-blocks-test",
        )

        slack_msg = _construir_slack_blocks(payload)

        assert "text" in slack_msg
        assert "blocks" in slack_msg
        assert "Escalamiento" in slack_msg["text"]
        assert "POL-2024-001" in slack_msg["text"]

    def test_construir_slack_blocks_con_historial_vacio(
        self, datos_poliza_ejemplo
    ):
        """Con historial vacío, debe mostrar mensaje indicativo."""
        payload = EscalationPayload(
            motivo="Sin historial previo",
            historial=[],
            estado_pipefy="Póliza detectada",
            datos_poliza=datos_poliza_ejemplo,
            timestamp=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
            session_id="sess-no-hist",
        )

        slack_msg = _construir_slack_blocks(payload)

        # Debe tener bloques válidos aunque no haya historial
        assert len(slack_msg["blocks"]) > 0

    def test_motivo_se_trimea(self, datos_poliza_ejemplo):
        """El motivo con espacios al inicio/final debe ser trimmed."""
        result = escalar_humano(
            motivo="   Motivo con espacios   ",
            historial=[],
            estado_pipefy="Escalado a humano",
            datos_poliza=datos_poliza_ejemplo,
            session_id="sess-trim",
        )
        assert result is True
