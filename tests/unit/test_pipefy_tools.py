"""
Tests unitarios para src/tools/pipefy_tools.py - consultar_pipefy.

Cobertura:
- Validacion de poliza_id vacio -> ValueError
- Modo mock retorna PipelineCard valido
- Manejo de errores HTTP 4xx/5xx -> PipefyAPIError
- Timeout de 30 segundos -> TimeoutError
- Parseo correcto de respuesta Pipefy a PipelineCard
"""

from __future__ import annotations

import json
import os
import urllib.error
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.models.constants import TIMEOUT_CONSULTAR_PIPEFY_SEGUNDOS
from src.models.data_models import PipelineCard
from src.tools.pipefy_tools import (
    InvalidStateTransitionError,
    PipefyAPIError,
    _is_mock_mode,
    _parse_pipefy_response,
    consultar_pipefy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def set_mock_mode_off(monkeypatch):
    """Por defecto, desactiva el mock mode para los tests de integracion simulada."""
    monkeypatch.setenv("CIME_MOCK_MODE", "false")


@pytest.fixture
def set_mock_mode_on(monkeypatch):
    """Activa el mock mode."""
    monkeypatch.setenv("CIME_MOCK_MODE", "true")


@pytest.fixture
def sample_pipefy_response() -> dict[str, Any]:
    """Respuesta valida simulada de la API GraphQL de Pipefy."""
    return {
        "data": {
            "cards": {
                "edges": [
                    {
                        "node": {
                            "id": "12345",
                            "title": "POL-2025-001",
                            "current_phase": {
                                "name": "Cliente interesado"
                            },
                            "fields": [
                                {"name": "poliza_id", "value": "POL-2025-001"},
                                {"name": "cliente_nombre", "value": "Acme Corp S.A."},
                                {"name": "cliente_email", "value": "contacto@acme.com"},
                                {"name": "fecha_vencimiento", "value": "2025-09-30"},
                                {"name": "precio_renovacion", "value": "72500.00"},
                                {"name": "equipo_nombre", "value": "UPS Eaton 9PX 11kVA"},
                            ],
                            "updated_at": "2025-07-10T14:30:00Z",
                            "comments": [
                                {"text": "Primer contacto realizado"},
                                {"text": "Cliente respondio con interes"},
                            ],
                        }
                    }
                ]
            }
        }
    }


# ---------------------------------------------------------------------------
# Tests: Validacion de entrada
# ---------------------------------------------------------------------------


class TestValidacionEntrada:
    """Tests de validacion del parametro poliza_id."""

    def test_poliza_id_vacio_raises_value_error(self):
        """poliza_id vacio debe lanzar ValueError."""
        with pytest.raises(ValueError, match="poliza_id no puede estar vacio"):
            consultar_pipefy("")

    def test_poliza_id_none_raises_value_error(self):
        """poliza_id None debe lanzar ValueError."""
        with pytest.raises(ValueError, match="poliza_id no puede estar vacio"):
            consultar_pipefy(None)  # type: ignore

    def test_poliza_id_solo_espacios_raises_value_error(self):
        """poliza_id con solo espacios debe lanzar ValueError."""
        with pytest.raises(ValueError, match="poliza_id no puede estar vacio"):
            consultar_pipefy("   ")


# ---------------------------------------------------------------------------
# Tests: Modo mock
# ---------------------------------------------------------------------------


class TestModoMock:
    """Tests de comportamiento en modo mock."""

    def test_mock_mode_retorna_pipeline_card(self, set_mock_mode_on):
        """En modo mock, consultar_pipefy retorna un PipelineCard valido."""
        result = consultar_pipefy("POL-2025-001")

        assert isinstance(result, PipelineCard)
        assert result.poliza_id == "POL-2025-001"
        assert result.cliente_nombre != ""
        assert result.cliente_email != ""
        assert result.precio_renovacion > 0
        assert isinstance(result.fecha_vencimiento, date)
        assert isinstance(result.timestamp_ultima_actualizacion, datetime)
        assert isinstance(result.notas, list)

    def test_mock_mode_usa_poliza_id_proporcionado(self, set_mock_mode_on):
        """El mock respeta el poliza_id pasado como argumento."""
        result = consultar_pipefy("POL-CUSTOM-99")
        assert result.poliza_id == "POL-CUSTOM-99"

    def test_is_mock_mode_true(self, monkeypatch):
        """_is_mock_mode() retorna True cuando CIME_MOCK_MODE=true."""
        monkeypatch.setenv("CIME_MOCK_MODE", "true")
        assert _is_mock_mode() is True

    def test_is_mock_mode_false(self, monkeypatch):
        """_is_mock_mode() retorna False cuando CIME_MOCK_MODE=false."""
        monkeypatch.setenv("CIME_MOCK_MODE", "false")
        assert _is_mock_mode() is False

    def test_is_mock_mode_default_true(self, monkeypatch):
        """_is_mock_mode() retorna True por defecto si la variable no existe."""
        monkeypatch.delenv("CIME_MOCK_MODE", raising=False)
        assert _is_mock_mode() is True


# ---------------------------------------------------------------------------
# Tests: Parseo de respuesta
# ---------------------------------------------------------------------------


class TestParseoRespuesta:
    """Tests de _parse_pipefy_response."""

    def test_parseo_exitoso(self, sample_pipefy_response):
        """Respuesta valida se mapea correctamente a PipelineCard."""
        result = _parse_pipefy_response("POL-2025-001", sample_pipefy_response)

        assert result.poliza_id == "POL-2025-001"
        assert result.estado_actual == "Cliente interesado"
        assert result.cliente_nombre == "Acme Corp S.A."
        assert result.cliente_email == "contacto@acme.com"
        assert result.fecha_vencimiento == date(2025, 9, 30)
        assert result.precio_renovacion == 72500.00
        assert result.equipo_nombre == "UPS Eaton 9PX 11kVA"
        assert result.timestamp_ultima_actualizacion == datetime(
            2025, 7, 10, 14, 30, 0, tzinfo=timezone.utc
        )
        assert len(result.notas) == 2
        assert "Primer contacto realizado" in result.notas

    def test_parseo_sin_edges_raises_error(self):
        """Respuesta sin edges lanza PipefyAPIError 404."""
        data = {"data": {"cards": {"edges": []}}}
        with pytest.raises(PipefyAPIError) as exc_info:
            _parse_pipefy_response("POL-NONE", data)
        assert exc_info.value.status_code == 404

    def test_parseo_respuesta_malformada_raises_error(self):
        """Respuesta con estructura inesperada lanza PipefyAPIError 500."""
        data = {"data": {"cards": {"edges": [{"node": None}]}}}
        with pytest.raises(PipefyAPIError) as exc_info:
            _parse_pipefy_response("POL-BAD", data)
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# Tests: Errores HTTP (modo real)
# ---------------------------------------------------------------------------


class TestErroresHTTP:
    """Tests de manejo de errores HTTP en modo real."""

    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_http_404_raises_pipefy_api_error(self, mock_urlopen, mock_token):
        """HTTP 404 se convierte en PipefyAPIError con status_code 404."""
        error_body = json.dumps({"message": "Card not found"}).encode()
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.pipefy.com/graphql",
            code=404,
            msg="Not Found",
            hdrs={},  # type: ignore
            fp=BytesIO(error_body),
        )

        with pytest.raises(PipefyAPIError) as exc_info:
            consultar_pipefy("POL-NOT-FOUND")
        assert exc_info.value.status_code == 404

    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_http_500_raises_pipefy_api_error(self, mock_urlopen, mock_token):
        """HTTP 500 se convierte en PipefyAPIError con status_code 500."""
        error_body = json.dumps({"message": "Internal Server Error"}).encode()
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.pipefy.com/graphql",
            code=500,
            msg="Internal Server Error",
            hdrs={},  # type: ignore
            fp=BytesIO(error_body),
        )

        with pytest.raises(PipefyAPIError) as exc_info:
            consultar_pipefy("POL-ERR-500")
        assert exc_info.value.status_code == 500

    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_http_401_raises_pipefy_api_error(self, mock_urlopen, mock_token):
        """HTTP 401 se convierte en PipefyAPIError (credenciales invalidas)."""
        error_body = json.dumps({"message": "Unauthorized"}).encode()
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.pipefy.com/graphql",
            code=401,
            msg="Unauthorized",
            hdrs={},  # type: ignore
            fp=BytesIO(error_body),
        )

        with pytest.raises(PipefyAPIError) as exc_info:
            consultar_pipefy("POL-UNAUTH")
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    """Tests de manejo de timeout."""

    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_timeout_raises_timeout_error(self, mock_urlopen, mock_token):
        """Timeout de red se convierte en TimeoutError."""
        mock_urlopen.side_effect = urllib.error.URLError(
            reason=TimeoutError("timed out")
        )

        with pytest.raises(TimeoutError) as exc_info:
            consultar_pipefy("POL-TIMEOUT")
        assert "30 segundos" in str(exc_info.value)

    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_timeout_string_in_url_error(self, mock_urlopen, mock_token):
        """URLError con 'timed out' en el mensaje se interpreta como timeout."""
        mock_urlopen.side_effect = urllib.error.URLError(
            reason="Connection timed out"
        )

        with pytest.raises(TimeoutError):
            consultar_pipefy("POL-TIMEOUT-2")


# ---------------------------------------------------------------------------
# Tests: Flujo exitoso (modo real simulado)
# ---------------------------------------------------------------------------


class TestFlujoExitoso:
    """Tests del flujo exitoso con respuesta simulada."""

    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_consulta_exitosa_retorna_pipeline_card(
        self, mock_urlopen, mock_token, sample_pipefy_response
    ):
        """Una consulta exitosa retorna un PipelineCard correctamente mapeado."""
        response_body = json.dumps(sample_pipefy_response).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = consultar_pipefy("POL-2025-001")

        assert isinstance(result, PipelineCard)
        assert result.poliza_id == "POL-2025-001"
        assert result.estado_actual == "Cliente interesado"
        assert result.cliente_nombre == "Acme Corp S.A."

    @patch("src.tools.pipefy_tools._get_pipefy_token", return_value="fake-token")
    @patch("src.tools.pipefy_tools.urllib.request.urlopen")
    def test_graphql_errors_raises_pipefy_api_error(
        self, mock_urlopen, mock_token
    ):
        """Errores GraphQL en respuesta 200 se convierten en PipefyAPIError."""
        error_response = {
            "errors": [{"message": "Field 'poliza_id' not found"}]
        }
        response_body = json.dumps(error_response).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = response_body
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        with pytest.raises(PipefyAPIError) as exc_info:
            consultar_pipefy("POL-GQL-ERR")
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Tests: Excepciones personalizadas
# ---------------------------------------------------------------------------


class TestExcepciones:
    """Tests de las excepciones personalizadas."""

    def test_pipefy_api_error_attributes(self):
        """PipefyAPIError tiene los atributos correctos."""
        err = PipefyAPIError(429, "Rate limited")
        assert err.status_code == 429
        assert err.message == "Rate limited"
        assert "429" in str(err)
        assert "Rate limited" in str(err)

    def test_invalid_state_transition_error_attributes(self):
        """InvalidStateTransitionError tiene los atributos correctos."""
        err = InvalidStateTransitionError(
            "Renovacion confirmada", "Contacto inicial enviado"
        )
        assert err.estado_actual == "Renovacion confirmada"
        assert err.estado_destino == "Contacto inicial enviado"
        assert "Renovacion confirmada" in str(err)
        assert "Contacto inicial enviado" in str(err)

    def test_invalid_state_transition_error_custom_message(self):
        """InvalidStateTransitionError acepta mensaje personalizado."""
        err = InvalidStateTransitionError(
            "A", "B", "Transicion no permitida por reglas de negocio"
        )
        assert err.message == "Transicion no permitida por reglas de negocio"
