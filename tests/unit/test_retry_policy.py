"""
Tests unitarios para la política de retry y manejo de errores de las 5 tools.

Valida:
- Reintentos con backoff para actualizar_pipefy, enviar_correo, notificar_tesoreria
- Circuit breaker de escalar_humano (nunca falla silenciosamente)
- Timeout de consultar_pipefy (30s, sin retry)
- Escalamiento inmediato para email inválido (sin retry)

Requisitos cubiertos: 1.5, 2.6, 2.7, 5.5, 7.4
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models.data_models import DatosPago, DatosPoliza, EmailResult, Mensaje
from src.tools.email_tools import InvalidEmailError, SESError, enviar_correo
from src.tools.escalation_tools import escalar_humano
from src.tools.pipefy_tools import PipefyAPIError, actualizar_pipefy, consultar_pipefy
from src.tools.treasury_tools import NotificationError, notificar_tesoreria


# ---------------------------------------------------------------------------
# Fixtures comunes
# ---------------------------------------------------------------------------


@pytest.fixture
def datos_pago_sample() -> DatosPago:
    """DatosPago de ejemplo para tests de notificar_tesoreria."""
    return DatosPago(
        cliente_nombre="Empresa Test S.A.",
        poliza_id="POL-TEST-001",
        monto=50000.00,
        timestamp_recepcion=datetime(2025, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
        referencia_adjunto="comprobantes/POL-TEST-001/comp.pdf",
    )


@pytest.fixture
def datos_poliza_sample() -> DatosPoliza:
    """DatosPoliza de ejemplo para tests de escalar_humano."""
    return DatosPoliza(
        poliza_id="POL-TEST-001",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=50000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


@pytest.fixture
def historial_sample() -> list[Mensaje]:
    """Historial mínimo para tests de escalar_humano."""
    return [
        Mensaje(
            timestamp=datetime(2025, 7, 1, 10, 0, 0, tzinfo=timezone.utc),
            remitente="agente",
            contenido="Contacto inicial de renovación",
            tipo="contacto_inicial",
        ),
    ]


# ---------------------------------------------------------------------------
# Tests: actualizar_pipefy — Retry con backoff (Req 7.4)
# ---------------------------------------------------------------------------


class TestRetryActualizarPipefy:
    """Retry de actualizar_pipefy: 2 reintentos con backoff 30s/60s."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.pipefy_tools.time.sleep")
    @patch("src.tools.pipefy_tools._call_pipefy_update_api")
    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    def test_fallo_unico_con_reintento_exitoso(
        self, mock_token, mock_api, mock_sleep
    ):
        """Primer intento falla con PipefyAPIError, segundo tiene éxito → True."""
        mock_api.side_effect = [
            PipefyAPIError(500, "Internal Server Error"),
            None,  # éxito en el segundo intento
        ]

        result = actualizar_pipefy(
            poliza_id="POL-001",
            estado="Contacto inicial enviado",
            nota="Test de retry exitoso",
            session_id="session-test-001",
        )

        assert result is True
        assert mock_api.call_count == 2
        # Backoff del primer reintento: 30 * (0+1) = 30s
        mock_sleep.assert_called_once_with(30)

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.pipefy_tools.time.sleep")
    @patch("src.tools.pipefy_tools._call_pipefy_update_api")
    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    def test_todos_reintentos_fallan_lanza_error(
        self, mock_token, mock_api, mock_sleep
    ):
        """Los 3 intentos (1 original + 2 retries) fallan → PipefyAPIError."""
        mock_api.side_effect = PipefyAPIError(503, "Service Unavailable")

        with pytest.raises(PipefyAPIError) as exc_info:
            actualizar_pipefy(
                poliza_id="POL-001",
                estado="Contacto inicial enviado",
                nota="Test todos fallan",
                session_id="session-test-002",
            )

        assert exc_info.value.status_code == 503
        # 1 intento original + 2 reintentos = 3 llamadas
        assert mock_api.call_count == 3
        # Backoffs: 30s (attempt=0), 60s (attempt=1)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(30)
        mock_sleep.assert_any_call(60)


# ---------------------------------------------------------------------------
# Tests: enviar_correo — Retry técnico y email inválido (Req 2.6, 2.7)
# ---------------------------------------------------------------------------


class TestRetryEnviarCorreo:
    """Retry de enviar_correo: 1 reintento tras 60s para errores técnicos."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.email_tools.time.sleep")
    @patch("src.tools.email_tools._get_ses_client")
    def test_fallo_tecnico_reintenta_una_vez_exitoso(
        self, mock_get_client, mock_sleep
    ):
        """Primer envío falla con error técnico, segundo éxito → EmailResult."""
        mock_client = MagicMock()
        mock_client.send_email.side_effect = [
            Exception("Throttling"),
            {"MessageId": "ses-retry-ok-123"},
        ]
        mock_get_client.return_value = mock_client

        result = enviar_correo(
            destinatario="valid@empresa.com",
            asunto="Renovación póliza",
            cuerpo="<p>Estimado cliente...</p>",
        )

        assert isinstance(result, EmailResult)
        assert result.success is True
        assert result.message_id == "ses-retry-ok-123"
        assert mock_client.send_email.call_count == 2
        mock_sleep.assert_called_once_with(60)

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.email_tools.time.sleep")
    @patch("src.tools.email_tools._get_ses_client")
    def test_dos_fallos_tecnicos_lanza_ses_error(
        self, mock_get_client, mock_sleep
    ):
        """Ambos intentos fallan con error técnico → SESError (agente escala)."""
        mock_client = MagicMock()
        mock_client.send_email.side_effect = Exception("Service Unavailable")
        mock_get_client.return_value = mock_client

        with pytest.raises(SESError):
            enviar_correo(
                destinatario="valid@empresa.com",
                asunto="Test fallo total",
                cuerpo="<p>Body</p>",
            )

        # 1 intento + 1 retry = 2 llamadas
        assert mock_client.send_email.call_count == 2
        mock_sleep.assert_called_once_with(60)

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.email_tools.time.sleep")
    def test_email_invalido_no_reintenta_escala_inmediato(self, mock_sleep):
        """Email inválido → InvalidEmailError inmediato, sin retry (Req 2.7)."""
        with pytest.raises(InvalidEmailError) as exc_info:
            enviar_correo(
                destinatario="correo-sin-arroba",
                asunto="Test",
                cuerpo="Hola",
            )

        assert exc_info.value.email == "correo-sin-arroba"
        # No se debe esperar para retry — email inválido es inmediato
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: notificar_tesoreria — Retry con backoff 60s (Req 5.5)
# ---------------------------------------------------------------------------


class TestRetryNotificarTesoreria:
    """Retry de notificar_tesoreria: 1 reintento tras 60s."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.treasury_tools.time.sleep")
    @patch("src.tools.treasury_tools._post_to_treasury")
    @patch(
        "src.tools.treasury_tools._get_treasury_secret",
        return_value={"url": "https://treasury.internal/api", "api_key": "key-123"},
    )
    def test_fallo_unico_con_reintento_exitoso(
        self, mock_secret, mock_post, mock_sleep, datos_pago_sample
    ):
        """Primer POST falla, segundo éxito → True."""
        mock_post.side_effect = [
            NotificationError("Connection reset"),
            True,
        ]

        result = notificar_tesoreria(datos_pago_sample)

        assert result is True
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(60)

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.treasury_tools.time.sleep")
    @patch("src.tools.treasury_tools._post_to_treasury")
    @patch(
        "src.tools.treasury_tools._get_treasury_secret",
        return_value={"url": "https://treasury.internal/api", "api_key": "key-123"},
    )
    def test_dos_fallos_consecutivos_lanza_error(
        self, mock_secret, mock_post, mock_sleep, datos_pago_sample
    ):
        """Ambos intentos fallan → NotificationError (agente debe escalar)."""
        mock_post.side_effect = NotificationError("Server error 500")

        with pytest.raises(NotificationError):
            notificar_tesoreria(datos_pago_sample)

        # 1 intento original + 1 retry = 2 llamadas
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(60)

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.treasury_tools.time.sleep")
    @patch("src.tools.treasury_tools._post_to_treasury")
    @patch(
        "src.tools.treasury_tools._get_treasury_secret",
        return_value={"url": "https://treasury.internal/api", "api_key": "key-123"},
    )
    def test_timeout_tras_reintentos_lanza_timeout_error(
        self, mock_secret, mock_post, mock_sleep, datos_pago_sample
    ):
        """Timeout en ambos intentos → TimeoutError propagado."""
        mock_post.side_effect = TimeoutError("Timeout de 60s")

        with pytest.raises(TimeoutError):
            notificar_tesoreria(datos_pago_sample)

        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(60)


# ---------------------------------------------------------------------------
# Tests: consultar_pipefy — Timeout 30s sin retry (Req 1.5)
# ---------------------------------------------------------------------------


class TestTimeoutConsultarPipefy:
    """consultar_pipefy: timeout de 30s termina sesión, sin retry."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.pipefy_tools.time.sleep")
    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_timeout_30s_lanza_timeout_error(
        self, mock_urlopen, mock_token, mock_sleep
    ):
        """Si la API excede 30s → TimeoutError con mensaje descriptivo."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("timed out")

        with pytest.raises(TimeoutError) as exc_info:
            consultar_pipefy("POL-TIMEOUT-001")

        assert "30" in str(exc_info.value)

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.pipefy_tools.time.sleep")
    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_timeout_termina_sesion_sin_retry(
        self, mock_urlopen, mock_token, mock_sleep
    ):
        """Después del timeout NO se reintenta — solo 1 llamada a urlopen."""
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("timed out")

        with pytest.raises(TimeoutError):
            consultar_pipefy("POL-TIMEOUT-002")

        # Solo una llamada — no hay retry para consultar_pipefy
        assert mock_urlopen.call_count == 1
        # No se debe invocar sleep (no hay backoff)
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: escalar_humano — Circuit breaker (Req 6.1-6.9)
# ---------------------------------------------------------------------------


class TestCircuitBreakerEscalarHumano:
    """escalar_humano: circuit breaker final, nunca falla silenciosamente."""

    @patch("src.tools.escalation_tools._MOCK_MODE", False)
    @patch("src.tools.escalation_tools._enviar_slack")
    @patch(
        "src.tools.escalation_tools._get_slack_webhook_url",
        return_value="https://hooks.slack.com/services/T/B/X",
    )
    def test_escalar_humano_siempre_retorna_true(
        self, mock_webhook, mock_slack, datos_poliza_sample, historial_sample
    ):
        """Incluso si Slack falla, escalar_humano retorna True (circuit breaker)."""
        mock_slack.side_effect = Exception("Slack webhook timeout")

        result = escalar_humano(
            motivo="Error técnico en envío de correo tras reintentos agotados",
            historial=historial_sample,
            estado_pipefy="Contacto inicial enviado",
            datos_poliza=datos_poliza_sample,
            session_id="session-cb-001",
        )

        assert result is True

    @patch("src.tools.escalation_tools._MOCK_MODE", False)
    @patch("src.tools.escalation_tools._enviar_slack")
    @patch(
        "src.tools.escalation_tools._get_slack_webhook_url",
        return_value="https://hooks.slack.com/services/T/B/X",
    )
    def test_escalar_humano_con_fallback_logs(
        self, mock_webhook, mock_slack, datos_poliza_sample, historial_sample, caplog
    ):
        """Cuando Slack falla, registra en logs CRITICAL como fallback."""
        mock_slack.side_effect = ConnectionError("Network unreachable")

        import logging

        with caplog.at_level(logging.CRITICAL):
            result = escalar_humano(
                motivo="Notificación a tesorería fallida tras reintentos",
                historial=historial_sample,
                estado_pipefy="Comprobante recibido",
                datos_poliza=datos_poliza_sample,
                session_id="session-cb-002",
            )

        assert result is True
        # Verifica que se registró un log CRITICAL con el fallback
        critical_logs = [r for r in caplog.records if r.levelno == logging.CRITICAL]
        assert len(critical_logs) >= 1
        assert "ESCALAMIENTO FALLBACK" in critical_logs[0].message

    @patch("src.tools.escalation_tools._MOCK_MODE", False)
    @patch("src.tools.escalation_tools._enviar_slack", return_value=True)
    @patch(
        "src.tools.escalation_tools._get_slack_webhook_url",
        return_value="https://hooks.slack.com/services/T/B/X",
    )
    def test_escalar_humano_exito_slack_retorna_true(
        self, mock_webhook, mock_slack, datos_poliza_sample, historial_sample
    ):
        """Cuando Slack funciona correctamente, también retorna True."""
        result = escalar_humano(
            motivo="Cliente solicita hablar con un humano",
            historial=historial_sample,
            estado_pipefy="Seguimiento en curso",
            datos_poliza=datos_poliza_sample,
            session_id="session-cb-003",
        )

        assert result is True
        mock_slack.assert_called_once()
