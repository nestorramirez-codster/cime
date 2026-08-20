"""
Unit tests para src/tools/treasury_tools.py

Valida el comportamiento de notificar_tesoreria incluyendo:
- Mock mode (retorna True sin POST)
- Serialización correcta de DatosPago
- Retry ante fallo técnico
- Timeout y propagación de excepciones
- Obtención de secretos
"""

import json
import os
import time
import urllib.error
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models.data_models import DatosPago
from src.tools.treasury_tools import (
    NotificationError,
    _serialize_datos_pago,
    notificar_tesoreria,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def datos_pago_sample():
    """DatosPago de ejemplo para tests."""
    return DatosPago(
        cliente_nombre="Empresa Test SA",
        poliza_id="POL-2024-042",
        monto=15000.50,
        timestamp_recepcion=datetime(2025, 7, 15, 10, 30, 0, tzinfo=timezone.utc),
        referencia_adjunto="comprobantes/2025/07/POL-2024-042/comprobante.pdf",
    )


@pytest.fixture
def mock_secret():
    """Secreto mock de Tesorería."""
    return {
        "url": "https://tesoreria.cime.internal/api/v1/notificacion-pago",
        "api_key": "test-api-key-12345",
    }


# ---------------------------------------------------------------------------
# Tests: Mock mode
# ---------------------------------------------------------------------------


class TestMockMode:
    """Tests para el modo mock de desarrollo local."""

    def test_mock_mode_returns_true(self, datos_pago_sample, monkeypatch):
        """En mock mode, retorna True sin hacer POST."""
        monkeypatch.setenv("CIME_MOCK_MODE", "true")
        result = notificar_tesoreria(datos_pago_sample)
        assert result is True

    def test_mock_mode_case_insensitive(self, datos_pago_sample, monkeypatch):
        """CIME_MOCK_MODE es case-insensitive (True/TRUE/true)."""
        monkeypatch.setenv("CIME_MOCK_MODE", "True")
        result = notificar_tesoreria(datos_pago_sample)
        assert result is True

    def test_non_mock_mode_attempts_real_call(self, datos_pago_sample, monkeypatch):
        """Sin CIME_MOCK_MODE, intenta obtener secretos y hacer POST."""
        monkeypatch.delenv("CIME_MOCK_MODE", raising=False)
        with pytest.raises((RuntimeError, NotificationError)):
            notificar_tesoreria(datos_pago_sample)


# ---------------------------------------------------------------------------
# Tests: Serialización
# ---------------------------------------------------------------------------


class TestSerializacion:
    """Tests para la serialización de DatosPago."""

    def test_serializa_todos_los_campos(self, datos_pago_sample):
        """La serialización incluye todos los campos requeridos."""
        body = _serialize_datos_pago(datos_pago_sample)
        payload = json.loads(body)

        assert payload["cliente_nombre"] == "Empresa Test SA"
        assert payload["poliza_id"] == "POL-2024-042"
        assert payload["monto"] == 15000.50
        assert payload["timestamp_recepcion"] == "2025-07-15T10:30:00+00:00"
        assert payload["referencia_adjunto"] == (
            "comprobantes/2025/07/POL-2024-042/comprobante.pdf"
        )

    def test_serializa_a_utf8(self, datos_pago_sample):
        """El resultado es bytes UTF-8 válido."""
        body = _serialize_datos_pago(datos_pago_sample)
        assert isinstance(body, bytes)
        # Verificar que se puede decodificar
        decoded = body.decode("utf-8")
        assert "Empresa Test SA" in decoded

    def test_serializa_caracteres_especiales(self):
        """Soporta nombres con caracteres especiales (acentos, ñ)."""
        datos = DatosPago(
            cliente_nombre="José García Ñoño",
            poliza_id="POL-2024-001",
            monto=5000.00,
            timestamp_recepcion=datetime(2025, 1, 1, tzinfo=timezone.utc),
            referencia_adjunto="comprobantes/test.pdf",
        )
        body = _serialize_datos_pago(datos)
        payload = json.loads(body)
        assert payload["cliente_nombre"] == "José García Ñoño"


# ---------------------------------------------------------------------------
# Tests: Flujo exitoso con POST
# ---------------------------------------------------------------------------


class TestFlujoExitoso:
    """Tests para el flujo normal de notificación exitosa."""

    @patch("src.tools.treasury_tools._get_treasury_secret")
    @patch("src.tools.treasury_tools.urllib.request.urlopen")
    def test_post_exitoso_retorna_true(
        self, mock_urlopen, mock_secret_fn, datos_pago_sample, mock_secret, monkeypatch
    ):
        """POST exitoso (HTTP 200) retorna True."""
        monkeypatch.delenv("CIME_MOCK_MODE", raising=False)
        mock_secret_fn.return_value = mock_secret

        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = notificar_tesoreria(datos_pago_sample)
        assert result is True

    @patch("src.tools.treasury_tools._get_treasury_secret")
    @patch("src.tools.treasury_tools.urllib.request.urlopen")
    def test_post_envia_headers_correctos(
        self, mock_urlopen, mock_secret_fn, datos_pago_sample, mock_secret, monkeypatch
    ):
        """El POST incluye Content-Type y Authorization correctos."""
        monkeypatch.delenv("CIME_MOCK_MODE", raising=False)
        mock_secret_fn.return_value = mock_secret

        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        notificar_tesoreria(datos_pago_sample)

        # Verificar que se llamó urlopen con un Request
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        assert request_obj.get_header("Content-type") == "application/json"
        assert request_obj.get_header("Authorization") == "Bearer test-api-key-12345"


# ---------------------------------------------------------------------------
# Tests: Retry y errores
# ---------------------------------------------------------------------------


class TestRetryYErrores:
    """Tests para la lógica de retry y manejo de errores."""

    @patch("src.tools.treasury_tools.time.sleep")
    @patch("src.tools.treasury_tools._get_treasury_secret")
    @patch("src.tools.treasury_tools.urllib.request.urlopen")
    def test_retry_tras_primer_fallo(
        self, mock_urlopen, mock_secret_fn, mock_sleep,
        datos_pago_sample, mock_secret, monkeypatch
    ):
        """Reintenta una vez tras fallo técnico y tiene éxito."""
        monkeypatch.delenv("CIME_MOCK_MODE", raising=False)
        mock_secret_fn.return_value = mock_secret

        # Primer intento falla, segundo éxito
        mock_response_ok = MagicMock()
        mock_response_ok.getcode.return_value = 200
        mock_response_ok.__enter__ = MagicMock(return_value=mock_response_ok)
        mock_response_ok.__exit__ = MagicMock(return_value=False)

        mock_urlopen.side_effect = [
            urllib.error.URLError("Connection refused"),
            mock_response_ok,
        ]

        result = notificar_tesoreria(datos_pago_sample)
        assert result is True
        # Verificó que se esperó el backoff
        mock_sleep.assert_called_once_with(60)

    @patch("src.tools.treasury_tools.time.sleep")
    @patch("src.tools.treasury_tools._get_treasury_secret")
    @patch("src.tools.treasury_tools.urllib.request.urlopen")
    def test_notification_error_tras_reintentos_agotados(
        self, mock_urlopen, mock_secret_fn, mock_sleep,
        datos_pago_sample, mock_secret, monkeypatch
    ):
        """Lanza NotificationError si ambos intentos fallan."""
        monkeypatch.delenv("CIME_MOCK_MODE", raising=False)
        mock_secret_fn.return_value = mock_secret

        mock_urlopen.side_effect = [
            urllib.error.URLError("Connection refused"),
            urllib.error.URLError("Connection refused"),
        ]

        with pytest.raises(NotificationError):
            notificar_tesoreria(datos_pago_sample)

    @patch("src.tools.treasury_tools.time.sleep")
    @patch("src.tools.treasury_tools._get_treasury_secret")
    @patch("src.tools.treasury_tools.urllib.request.urlopen")
    def test_timeout_error_propagado(
        self, mock_urlopen, mock_secret_fn, mock_sleep,
        datos_pago_sample, mock_secret, monkeypatch
    ):
        """TimeoutError se propaga tras agotar reintentos."""
        monkeypatch.delenv("CIME_MOCK_MODE", raising=False)
        mock_secret_fn.return_value = mock_secret

        # Simular timeout en ambos intentos
        timeout_err = urllib.error.URLError(OSError("timed out"))
        mock_urlopen.side_effect = [timeout_err, timeout_err]

        with pytest.raises(TimeoutError):
            notificar_tesoreria(datos_pago_sample)

    @patch("src.tools.treasury_tools.time.sleep")
    @patch("src.tools.treasury_tools._get_treasury_secret")
    @patch("src.tools.treasury_tools.urllib.request.urlopen")
    def test_maximo_2_intentos_totales(
        self, mock_urlopen, mock_secret_fn, mock_sleep,
        datos_pago_sample, mock_secret, monkeypatch
    ):
        """Solo intenta 2 veces en total (1 original + 1 reintento)."""
        monkeypatch.delenv("CIME_MOCK_MODE", raising=False)
        mock_secret_fn.return_value = mock_secret

        mock_urlopen.side_effect = urllib.error.URLError("fail")

        with pytest.raises(NotificationError):
            notificar_tesoreria(datos_pago_sample)

        assert mock_urlopen.call_count == 2
