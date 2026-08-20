"""
Tests unitarios para src/tools/email_tools.py.
Requisitos: 2.1, 2.6, 2.7, 4.5, 4.8
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models.data_models import EmailResult
from src.tools.email_tools import (
    InvalidEmailError,
    SESError,
    enviar_correo,
    _es_email_valido,
)


# ---------------------------------------------------------------------------
# Tests de validación de email
# ---------------------------------------------------------------------------


class TestValidacionEmail:
    """Tests para la validación de formato de email RFC 5321."""

    def test_email_valido_simple(self):
        assert _es_email_valido("usuario@dominio.com") is True

    def test_email_valido_con_subdominio(self):
        assert _es_email_valido("user@sub.domain.co.mx") is True

    def test_email_valido_con_caracteres_especiales(self):
        assert _es_email_valido("user.name+tag@example.org") is True

    def test_email_invalido_sin_arroba(self):
        assert _es_email_valido("sindominio.com") is False

    def test_email_invalido_sin_dominio(self):
        assert _es_email_valido("user@") is False

    def test_email_invalido_sin_tld(self):
        assert _es_email_valido("user@dominio") is False

    def test_email_invalido_vacio(self):
        assert _es_email_valido("") is False

    def test_email_invalido_none(self):
        assert _es_email_valido(None) is False

    def test_email_invalido_espacios(self):
        assert _es_email_valido("   ") is False


# ---------------------------------------------------------------------------
# Tests de modo mock
# ---------------------------------------------------------------------------


class TestModoMock:
    """Tests para enviar_correo en modo mock (desarrollo local)."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "true"})
    def test_mock_retorna_email_result_exitoso(self):
        result = enviar_correo(
            destinatario="cliente@ejemplo.com",
            asunto="Renovación de póliza",
            cuerpo="<p>Estimado cliente...</p>",
        )

        assert isinstance(result, EmailResult)
        assert result.success is True
        assert result.message_id is not None
        assert result.message_id.startswith("mock-")
        assert isinstance(result.timestamp, datetime)
        assert result.error_code is None
        assert result.error_type is None

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "true"})
    def test_mock_con_adjuntos(self):
        result = enviar_correo(
            destinatario="cliente@ejemplo.com",
            asunto="Cotización adjunta",
            cuerpo="<p>Adjunto cotización</p>",
            adjuntos=["docs/cotizacion_001.pdf", "docs/terminos.pdf"],
        )

        assert result.success is True
        assert result.message_id is not None

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "true"})
    def test_mock_email_invalido_lanza_excepcion(self):
        """Incluso en mock, la validación de email debe ejecutarse primero."""
        with pytest.raises(InvalidEmailError) as exc_info:
            enviar_correo(
                destinatario="no-es-email",
                asunto="Test",
                cuerpo="Hola",
            )
        assert "no-es-email" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests de InvalidEmailError (no reintento)
# ---------------------------------------------------------------------------


class TestInvalidEmailError:
    """Tests para que email inválido lance InvalidEmailError sin reintentar."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    def test_email_invalido_lanza_inmediatamente(self):
        with pytest.raises(InvalidEmailError):
            enviar_correo(
                destinatario="correo-invalido",
                asunto="Test",
                cuerpo="Hola",
            )

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    def test_email_vacio_lanza_inmediatamente(self):
        with pytest.raises(InvalidEmailError):
            enviar_correo(
                destinatario="",
                asunto="Test",
                cuerpo="Hola",
            )

    def test_invalid_email_error_contiene_email(self):
        error = InvalidEmailError("bad@")
        assert error.email == "bad@"
        assert "bad@" in error.message


# ---------------------------------------------------------------------------
# Tests de SES con errores técnicos y retry
# ---------------------------------------------------------------------------


class TestSESRetry:
    """Tests para el comportamiento de retry en errores técnicos de SES."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.email_tools._get_ses_client")
    @patch("src.tools.email_tools.time.sleep")
    def test_error_tecnico_reintenta_una_vez(self, mock_sleep, mock_get_client):
        """Error técnico debe reintentar 1 vez después de 60s (Req 2.6)."""
        mock_client = MagicMock()
        mock_client.send_email.side_effect = Exception("Throttling")
        mock_get_client.return_value = mock_client

        with pytest.raises(SESError):
            enviar_correo(
                destinatario="valid@email.com",
                asunto="Test",
                cuerpo="Body",
            )

        # Debe haber intentado 2 veces (1 original + 1 retry)
        assert mock_client.send_email.call_count == 2
        # Debe esperar 60 segundos entre intentos
        mock_sleep.assert_called_once_with(60)

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.email_tools._get_ses_client")
    @patch("src.tools.email_tools.time.sleep")
    def test_exito_en_retry_retorna_resultado(self, mock_sleep, mock_get_client):
        """Si el retry tiene éxito, retorna EmailResult exitoso."""
        mock_client = MagicMock()
        # Primer intento falla, segundo tiene éxito
        mock_client.send_email.side_effect = [
            Exception("Throttling"),
            {"MessageId": "ses-msg-123"},
        ]
        mock_get_client.return_value = mock_client

        result = enviar_correo(
            destinatario="valid@email.com",
            asunto="Test",
            cuerpo="Body",
        )

        assert result.success is True
        assert result.message_id == "ses-msg-123"
        assert mock_client.send_email.call_count == 2

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.email_tools._get_ses_client")
    def test_email_rechazado_por_ses_no_reintenta(self, mock_get_client):
        """SES MessageRejected → InvalidEmailError sin retry (Req 2.7)."""
        mock_client = MagicMock()
        error = Exception("MessageRejected")
        error.response = {"Error": {"Code": "MessageRejected"}}
        mock_client.send_email.side_effect = error
        mock_get_client.return_value = mock_client

        with pytest.raises(InvalidEmailError):
            enviar_correo(
                destinatario="rejected@domain.com",
                asunto="Test",
                cuerpo="Body",
            )

        # Solo un intento — no reintenta para errores de validación
        assert mock_client.send_email.call_count == 1


# ---------------------------------------------------------------------------
# Tests de envío exitoso
# ---------------------------------------------------------------------------


class TestEnvioExitoso:
    """Tests para el flujo exitoso de envío de correo."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.email_tools._get_ses_client")
    def test_envio_simple_exitoso(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "abc-123"}
        mock_get_client.return_value = mock_client

        result = enviar_correo(
            destinatario="cliente@empresa.com",
            asunto="Renovación póliza #POL-001",
            cuerpo="<p>Estimado cliente...</p>",
        )

        assert result.success is True
        assert result.message_id == "abc-123"
        assert isinstance(result.timestamp, datetime)
        assert result.timestamp.tzinfo == timezone.utc
        assert result.error_code is None

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "false"})
    @patch("src.tools.email_tools._get_ses_client")
    def test_envio_con_adjuntos_usa_raw_email(self, mock_get_client):
        """Cuando hay adjuntos, debe usar send_raw_email."""
        mock_client = MagicMock()
        mock_client.send_raw_email.return_value = {"MessageId": "raw-456"}
        mock_get_client.return_value = mock_client

        # Mock del S3 client via boto3.client dentro de la función
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": MagicMock(read=lambda: b"PDF content")
        }

        with patch("boto3.client", return_value=mock_s3):
            result = enviar_correo(
                destinatario="cliente@empresa.com",
                asunto="Cotización con adjunto",
                cuerpo="<p>Adjunto</p>",
                adjuntos=["documentos/cotizacion.pdf"],
            )

        assert result.success is True
        assert result.message_id == "raw-456"
        mock_client.send_raw_email.assert_called_once()


# ---------------------------------------------------------------------------
# Tests de SESError
# ---------------------------------------------------------------------------


class TestSESError:
    """Tests para la excepción SESError."""

    def test_ses_error_contiene_error_code(self):
        error = SESError(error_code="ServiceUnavailable")
        assert error.error_code == "ServiceUnavailable"
        assert "ServiceUnavailable" in error.message

    def test_ses_error_con_mensaje_custom(self):
        error = SESError(
            error_code="Throttling",
            message="Demasiados requests",
        )
        assert error.error_code == "Throttling"
        assert error.message == "Demasiados requests"
