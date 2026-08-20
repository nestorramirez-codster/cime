"""
Unit tests para la tool actualizar_pipefy.

Verifica:
- Validación de estado antes de invocar la API (Req 7.1, 7.3, 9.4)
- Truncamiento de nota a 200 caracteres (Req 7.2)
- Inclusión de session_id, timestamp UTC y nota en el payload
- Política de retry con backoff 30s → 60s (Req 7.4)
- Modo mock para desarrollo local
"""

import os
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

from src.models.constants import ESTADOS_VALIDOS_PIPEFY
from src.tools.pipefy_tools import (
    actualizar_pipefy,
    InvalidStateTransitionError,
    PipefyAPIError,
    _mock_pipefy_states,
)


# ---------------------------------------------------------------------------
# Fixture: asegurar modo mock
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_mode_enabled(monkeypatch):
    """Asegurar que los tests corren en modo mock."""
    monkeypatch.setenv("CIME_MOCK_MODE", "true")
    # Limpiar estado mock entre tests
    _mock_pipefy_states.clear()
    yield
    _mock_pipefy_states.clear()


# ---------------------------------------------------------------------------
# Tests de validación de estado (Req 7.1, 7.3, 9.4)
# ---------------------------------------------------------------------------


class TestValidacionEstado:
    """Verificar que solo se aceptan estados válidos."""

    def test_estado_invalido_lanza_error(self):
        """Un estado que no está en ESTADOS_VALIDOS_PIPEFY lanza InvalidStateTransitionError."""
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            actualizar_pipefy(
                poliza_id="POL-001",
                estado="Estado Inventado",
                nota="Nota de prueba",
                session_id="sess-123",
            )
        assert exc_info.value.estado_destino == "Estado Inventado"

    def test_estado_vacio_lanza_error(self):
        """Un estado vacío lanza InvalidStateTransitionError."""
        with pytest.raises(InvalidStateTransitionError):
            actualizar_pipefy(
                poliza_id="POL-001",
                estado="",
                nota="Nota",
                session_id="sess-123",
            )

    def test_estado_con_typo_lanza_error(self):
        """Un estado con typo (parecido a uno válido) lanza error."""
        with pytest.raises(InvalidStateTransitionError):
            actualizar_pipefy(
                poliza_id="POL-001",
                estado="Poliza detectada",  # falta la ó
                nota="Nota",
                session_id="sess-123",
            )

    @pytest.mark.parametrize("estado", sorted(ESTADOS_VALIDOS_PIPEFY))
    def test_todos_los_estados_validos_son_aceptados(self, estado):
        """Cada uno de los 10 estados válidos no lanza error."""
        result = actualizar_pipefy(
            poliza_id="POL-001",
            estado=estado,
            nota="Nota test",
            session_id="sess-abc",
        )
        assert result is True


# ---------------------------------------------------------------------------
# Tests de truncamiento de nota (Req 7.2)
# ---------------------------------------------------------------------------


class TestTruncamientoNota:
    """Verificar que la nota se trunca a 200 caracteres."""

    def test_nota_larga_se_trunca_a_200(self):
        """Una nota de más de 200 chars se guarda truncada."""
        nota_larga = "A" * 500
        actualizar_pipefy(
            poliza_id="POL-002",
            estado="Póliza detectada",
            nota=nota_larga,
            session_id="sess-456",
        )
        stored = _mock_pipefy_states["POL-002"]
        assert len(stored["nota"]) == 200

    def test_nota_corta_no_se_modifica(self):
        """Una nota corta se mantiene sin cambios."""
        nota_corta = "Contacto inicial enviado correctamente"
        actualizar_pipefy(
            poliza_id="POL-003",
            estado="Contacto inicial enviado",
            nota=nota_corta,
            session_id="sess-789",
        )
        stored = _mock_pipefy_states["POL-003"]
        assert stored["nota"] == nota_corta

    def test_nota_exactamente_200_chars(self):
        """Una nota de exactamente 200 chars se mantiene."""
        nota_200 = "B" * 200
        actualizar_pipefy(
            poliza_id="POL-004",
            estado="Seguimiento en curso",
            nota=nota_200,
            session_id="sess-000",
        )
        stored = _mock_pipefy_states["POL-004"]
        assert len(stored["nota"]) == 200
        assert stored["nota"] == nota_200

    def test_nota_vacia_es_valida(self):
        """Una nota vacía es aceptada."""
        actualizar_pipefy(
            poliza_id="POL-005",
            estado="Póliza detectada",
            nota="",
            session_id="sess-111",
        )
        stored = _mock_pipefy_states["POL-005"]
        assert stored["nota"] == ""


# ---------------------------------------------------------------------------
# Tests de payload (session_id, timestamp, nota)
# ---------------------------------------------------------------------------


class TestPayloadActualizacion:
    """Verificar que el payload incluye session_id, timestamp UTC y nota."""

    def test_payload_incluye_session_id(self):
        """El estado almacenado incluye el session_id correcto."""
        actualizar_pipefy(
            poliza_id="POL-010",
            estado="Cliente interesado",
            nota="Cliente confirmó interés",
            session_id="sess-XYZ-999",
        )
        stored = _mock_pipefy_states["POL-010"]
        assert stored["session_id"] == "sess-XYZ-999"

    def test_payload_incluye_timestamp_utc(self):
        """El estado almacenado incluye un timestamp ISO 8601 UTC."""
        before = datetime.now(timezone.utc)
        actualizar_pipefy(
            poliza_id="POL-011",
            estado="Depósito solicitado",
            nota="Cotización enviada",
            session_id="sess-ts-001",
        )
        after = datetime.now(timezone.utc)

        stored = _mock_pipefy_states["POL-011"]
        ts = datetime.fromisoformat(stored["timestamp"])
        assert ts.tzinfo is not None  # tiene timezone
        assert before <= ts <= after

    def test_payload_incluye_nota_truncada(self):
        """El estado almacenado contiene la nota (truncada si es necesario)."""
        actualizar_pipefy(
            poliza_id="POL-012",
            estado="Comprobante recibido",
            nota="Comprobante PDF recibido del cliente",
            session_id="sess-nota-001",
        )
        stored = _mock_pipefy_states["POL-012"]
        assert stored["nota"] == "Comprobante PDF recibido del cliente"


# ---------------------------------------------------------------------------
# Tests de retry con backoff (Req 7.4) — Modo real simulado
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    """Verificar la política de retry: 2 reintentos, backoff 30s → 60s."""

    def test_exito_en_primer_intento_no_reintenta(self, monkeypatch):
        """Si el primer intento es exitoso, no se hacen reintentos."""
        monkeypatch.setenv("CIME_MOCK_MODE", "false")
        import src.tools.pipefy_tools as module

        mock_call = MagicMock(return_value=None)
        mock_token = MagicMock(return_value="test-token")

        with patch.object(module, "_call_pipefy_update_api", mock_call), \
             patch.object(module, "_get_pipefy_token", mock_token), \
             patch("time.sleep") as mock_sleep:
            result = actualizar_pipefy(
                poliza_id="POL-020",
                estado="Póliza detectada",
                nota="Test retry",
                session_id="sess-retry-001",
            )
        assert result is True
        assert mock_call.call_count == 1
        mock_sleep.assert_not_called()

    def test_fallo_primer_intento_exito_segundo(self, monkeypatch):
        """Si falla el primer intento pero el segundo es exitoso."""
        monkeypatch.setenv("CIME_MOCK_MODE", "false")
        import src.tools.pipefy_tools as module

        mock_call = MagicMock(
            side_effect=[PipefyAPIError(408, "timeout"), None]
        )
        mock_token = MagicMock(return_value="test-token")

        with patch.object(module, "_call_pipefy_update_api", mock_call), \
             patch.object(module, "_get_pipefy_token", mock_token), \
             patch("time.sleep") as mock_sleep:
            result = actualizar_pipefy(
                poliza_id="POL-021",
                estado="Contacto inicial enviado",
                nota="Retry exitoso",
                session_id="sess-retry-002",
            )
        assert result is True
        assert mock_call.call_count == 2
        # Primer backoff: 30s
        mock_sleep.assert_called_once_with(30)

    def test_dos_fallos_exito_tercero(self, monkeypatch):
        """Si fallan los dos primeros pero el tercero (último reintento) es exitoso."""
        monkeypatch.setenv("CIME_MOCK_MODE", "false")
        import src.tools.pipefy_tools as module

        mock_call = MagicMock(
            side_effect=[
                PipefyAPIError(408, "timeout"),
                PipefyAPIError(500, "server error"),
                None,
            ]
        )
        mock_token = MagicMock(return_value="test-token")

        with patch.object(module, "_call_pipefy_update_api", mock_call), \
             patch.object(module, "_get_pipefy_token", mock_token), \
             patch("time.sleep") as mock_sleep:
            result = actualizar_pipefy(
                poliza_id="POL-022",
                estado="Seguimiento en curso",
                nota="Segundo retry exitoso",
                session_id="sess-retry-003",
            )
        assert result is True
        assert mock_call.call_count == 3
        # Backoffs: 30s y luego 60s
        assert mock_sleep.call_args_list[0][0][0] == 30
        assert mock_sleep.call_args_list[1][0][0] == 60

    def test_tres_fallos_lanza_error(self, monkeypatch):
        """Si los 3 intentos fallan, se lanza PipefyAPIError."""
        monkeypatch.setenv("CIME_MOCK_MODE", "false")
        import src.tools.pipefy_tools as module

        last_error = PipefyAPIError(500, "final failure")
        mock_call = MagicMock(
            side_effect=[
                PipefyAPIError(408, "first failure"),
                PipefyAPIError(503, "second failure"),
                last_error,
            ]
        )
        mock_token = MagicMock(return_value="test-token")

        with patch.object(module, "_call_pipefy_update_api", mock_call), \
             patch.object(module, "_get_pipefy_token", mock_token), \
             patch("time.sleep"):
            with pytest.raises(PipefyAPIError) as exc_info:
                actualizar_pipefy(
                    poliza_id="POL-023",
                    estado="En validación con tesorería",
                    nota="Todos los reintentos agotan",
                    session_id="sess-retry-004",
                )
        assert exc_info.value.status_code == 500
        assert mock_call.call_count == 3

    def test_backoff_values_correctos(self, monkeypatch):
        """Verificar que el backoff es 30s → 60s exactos."""
        monkeypatch.setenv("CIME_MOCK_MODE", "false")
        import src.tools.pipefy_tools as module

        mock_call = MagicMock(
            side_effect=[
                PipefyAPIError(500, "fail 1"),
                PipefyAPIError(500, "fail 2"),
                PipefyAPIError(500, "fail 3"),
            ]
        )
        mock_token = MagicMock(return_value="test-token")

        with patch.object(module, "_call_pipefy_update_api", mock_call), \
             patch.object(module, "_get_pipefy_token", mock_token), \
             patch("time.sleep") as mock_sleep:
            with pytest.raises(PipefyAPIError):
                actualizar_pipefy(
                    poliza_id="POL-024",
                    estado="Póliza detectada",
                    nota="Verificar backoff",
                    session_id="sess-backoff",
                )

        # Primer reintento espera 30s, segundo reintento espera 60s
        sleep_calls = [call[0][0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [30, 60]


# ---------------------------------------------------------------------------
# Tests de modo mock
# ---------------------------------------------------------------------------


class TestModoMock:
    """Verificar funcionamiento en modo mock para desarrollo local."""

    def test_mock_retorna_true(self):
        """En modo mock, la función retorna True."""
        result = actualizar_pipefy(
            poliza_id="POL-MOCK-001",
            estado="Póliza detectada",
            nota="Test mock",
            session_id="sess-mock-001",
        )
        assert result is True

    def test_mock_almacena_estado(self):
        """En modo mock, el estado queda almacenado internamente."""
        actualizar_pipefy(
            poliza_id="POL-MOCK-002",
            estado="Renovación confirmada",
            nota="Renovación exitosa",
            session_id="sess-mock-002",
        )
        assert "POL-MOCK-002" in _mock_pipefy_states
        assert _mock_pipefy_states["POL-MOCK-002"]["estado"] == "Renovación confirmada"

    def test_validacion_ocurre_antes_de_mock(self):
        """La validación de estado se ejecuta incluso en modo mock."""
        with pytest.raises(InvalidStateTransitionError):
            actualizar_pipefy(
                poliza_id="POL-MOCK-003",
                estado="Estado Falso",
                nota="Debe fallar",
                session_id="sess-mock-003",
            )
        # No debe haber registro en el mock
        assert "POL-MOCK-003" not in _mock_pipefy_states
