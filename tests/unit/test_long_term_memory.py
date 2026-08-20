"""
Tests unitarios para src/memory/long_term.py.

Valida la capa de Memory de largo plazo (S3 JSON) en modo mock:
- Persistencia y recuperación de historial por póliza
- Validación de campos obligatorios y formato
- Serialización/deserialización con timestamps ISO 8601
- Acumulación de múltiples sesiones

Requisitos: 8.2, 8.3, 8.4
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

# Asegurar modo mock antes de importar el módulo
os.environ["CIME_MOCK_MODE"] = "true"

from src.memory.long_term import (
    _crear_historial_vacio,
    _deserializar_historial,
    _mock_memory_store,
    _normalizar_timestamps,
    _serializar_historial,
    _validar_sesion_completada,
    persistir_historial,
    recuperar_historial,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def limpiar_mock_store():
    """Limpia el almacenamiento mock antes de cada test."""
    _mock_memory_store.clear()
    yield
    _mock_memory_store.clear()


@pytest.fixture
def sesion_valida() -> dict:
    """Sesión completada con todos los campos válidos."""
    return {
        "session_id": "sess-test-001",
        "timestamp_inicio": "2025-07-15T10:00:00Z",
        "timestamp_cierre": "2025-07-15T10:45:00Z",
        "estado_final": "En validación con tesorería",
        "resultado": "interesado",
        "mensajes_enviados": 3,
    }


@pytest.fixture
def sesion_con_datetime() -> dict:
    """Sesión completada con timestamps como objetos datetime."""
    return {
        "session_id": "sess-test-002",
        "timestamp_inicio": datetime(2025, 7, 16, 9, 0, 0, tzinfo=timezone.utc),
        "timestamp_cierre": datetime(2025, 7, 16, 9, 30, 0, tzinfo=timezone.utc),
        "estado_final": "Escalado a humano",
        "resultado": "escalado",
        "mensajes_enviados": 5,
    }


# ---------------------------------------------------------------------------
# Tests: Validación de sesión completada
# ---------------------------------------------------------------------------


class TestValidarSesionCompletada:
    """Tests para la validación de campos de sesion_completada."""

    def test_sesion_valida_no_lanza_error(self, sesion_valida):
        """Una sesión con todos los campos válidos no debe lanzar excepción."""
        _validar_sesion_completada(sesion_valida)  # No debería lanzar

    def test_campo_faltante_session_id(self, sesion_valida):
        """Debe fallar si falta session_id."""
        del sesion_valida["session_id"]
        with pytest.raises(ValueError, match="session_id"):
            _validar_sesion_completada(sesion_valida)

    def test_campo_faltante_timestamp_inicio(self, sesion_valida):
        """Debe fallar si falta timestamp_inicio."""
        del sesion_valida["timestamp_inicio"]
        with pytest.raises(ValueError, match="timestamp_inicio"):
            _validar_sesion_completada(sesion_valida)

    def test_campo_faltante_resultado(self, sesion_valida):
        """Debe fallar si falta resultado."""
        del sesion_valida["resultado"]
        with pytest.raises(ValueError, match="resultado"):
            _validar_sesion_completada(sesion_valida)

    def test_resultado_invalido(self, sesion_valida):
        """Debe fallar si resultado no es uno de los valores permitidos."""
        sesion_valida["resultado"] = "comprado"
        with pytest.raises(ValueError, match="no es válido"):
            _validar_sesion_completada(sesion_valida)

    def test_mensajes_enviados_negativo(self, sesion_valida):
        """Debe fallar si mensajes_enviados es negativo."""
        sesion_valida["mensajes_enviados"] = -1
        with pytest.raises(ValueError, match="entero >= 0"):
            _validar_sesion_completada(sesion_valida)

    def test_mensajes_enviados_no_entero(self, sesion_valida):
        """Debe fallar si mensajes_enviados no es entero."""
        sesion_valida["mensajes_enviados"] = 3.5
        with pytest.raises(ValueError, match="entero >= 0"):
            _validar_sesion_completada(sesion_valida)

    @pytest.mark.parametrize(
        "resultado",
        ["interesado", "rechazó", "no respondió", "escalado"],
    )
    def test_todos_los_resultados_validos(self, sesion_valida, resultado):
        """Todos los resultados definidos deben ser aceptados."""
        sesion_valida["resultado"] = resultado
        _validar_sesion_completada(sesion_valida)  # No debería lanzar


# ---------------------------------------------------------------------------
# Tests: Normalización de timestamps
# ---------------------------------------------------------------------------


class TestNormalizarTimestamps:
    """Tests para la normalización de timestamps a ISO 8601."""

    def test_datetime_con_timezone_se_convierte_a_iso(self):
        """Datetime con timezone se formatea como ISO 8601 con Z."""
        sesion = {
            "timestamp_inicio": datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
            "timestamp_cierre": datetime(2025, 7, 15, 10, 45, 0, tzinfo=timezone.utc),
        }
        resultado = _normalizar_timestamps(sesion)
        assert resultado["timestamp_inicio"] == "2025-07-15T10:00:00Z"
        assert resultado["timestamp_cierre"] == "2025-07-15T10:45:00Z"

    def test_datetime_sin_timezone_asume_utc(self):
        """Datetime naive se asume como UTC."""
        sesion = {
            "timestamp_inicio": datetime(2025, 1, 1, 0, 0, 0),
            "timestamp_cierre": datetime(2025, 1, 1, 1, 0, 0),
        }
        resultado = _normalizar_timestamps(sesion)
        assert resultado["timestamp_inicio"] == "2025-01-01T00:00:00Z"
        assert resultado["timestamp_cierre"] == "2025-01-01T01:00:00Z"

    def test_string_no_se_modifica(self):
        """Si los timestamps ya son strings, se mantienen."""
        sesion = {
            "timestamp_inicio": "2025-07-15T10:00:00Z",
            "timestamp_cierre": "2025-07-15T10:45:00Z",
        }
        resultado = _normalizar_timestamps(sesion)
        assert resultado["timestamp_inicio"] == "2025-07-15T10:00:00Z"
        assert resultado["timestamp_cierre"] == "2025-07-15T10:45:00Z"

    def test_otros_campos_no_se_modifican(self):
        """Campos que no son timestamps no se alteran."""
        sesion = {
            "session_id": "sess-xyz",
            "timestamp_inicio": "2025-07-15T10:00:00Z",
            "timestamp_cierre": "2025-07-15T10:45:00Z",
            "resultado": "interesado",
        }
        resultado = _normalizar_timestamps(sesion)
        assert resultado["session_id"] == "sess-xyz"
        assert resultado["resultado"] == "interesado"


# ---------------------------------------------------------------------------
# Tests: Serialización / Deserialización
# ---------------------------------------------------------------------------


class TestSerializacion:
    """Tests para serialización y deserialización round-trip."""

    def test_round_trip_historial(self):
        """Serializar y deserializar produce el mismo dict."""
        historial = {
            "poliza_id": "POL-2024-001",
            "sesiones": [
                {
                    "session_id": "sess-abc",
                    "timestamp_inicio": "2025-07-15T10:00:00Z",
                    "timestamp_cierre": "2025-07-15T10:45:00Z",
                    "estado_final": "En validación con tesorería",
                    "resultado": "interesado",
                    "mensajes_enviados": 3,
                }
            ],
        }
        json_str = _serializar_historial(historial)
        resultado = _deserializar_historial(json_str)
        assert resultado == historial

    def test_serializar_caracteres_unicode(self):
        """Serializa correctamente caracteres especiales (acentos, ñ)."""
        historial = {
            "poliza_id": "POL-2024-ÑÉ",
            "sesiones": [
                {
                    "session_id": "sess-ñ",
                    "timestamp_inicio": "2025-01-01T00:00:00Z",
                    "timestamp_cierre": "2025-01-01T01:00:00Z",
                    "estado_final": "No renovada / sin respuesta",
                    "resultado": "rechazó",
                    "mensajes_enviados": 0,
                }
            ],
        }
        json_str = _serializar_historial(historial)
        assert "rechazó" in json_str
        resultado = _deserializar_historial(json_str)
        assert resultado["sesiones"][0]["resultado"] == "rechazó"


# ---------------------------------------------------------------------------
# Tests: persistir_historial (mock)
# ---------------------------------------------------------------------------


class TestPersistirHistorial:
    """Tests para la función pública persistir_historial."""

    def test_persistir_primera_sesion(self, sesion_valida):
        """Persiste correctamente la primera sesión de una póliza."""
        resultado = persistir_historial("POL-001", sesion_valida)
        assert resultado is True
        assert "POL-001" in _mock_memory_store
        assert len(_mock_memory_store["POL-001"]["sesiones"]) == 1
        assert _mock_memory_store["POL-001"]["poliza_id"] == "POL-001"

    def test_persistir_multiples_sesiones(self, sesion_valida):
        """Acumula múltiples sesiones para la misma póliza."""
        persistir_historial("POL-001", sesion_valida)

        segunda_sesion = {
            "session_id": "sess-test-002",
            "timestamp_inicio": "2025-07-20T14:00:00Z",
            "timestamp_cierre": "2025-07-20T14:30:00Z",
            "estado_final": "Escalado a humano",
            "resultado": "escalado",
            "mensajes_enviados": 2,
        }
        persistir_historial("POL-001", segunda_sesion)

        assert len(_mock_memory_store["POL-001"]["sesiones"]) == 2
        assert _mock_memory_store["POL-001"]["sesiones"][0]["session_id"] == "sess-test-001"
        assert _mock_memory_store["POL-001"]["sesiones"][1]["session_id"] == "sess-test-002"

    def test_persistir_con_datetime_normaliza_timestamps(self, sesion_con_datetime):
        """Datetime objects se normalizan a strings ISO 8601."""
        persistir_historial("POL-002", sesion_con_datetime)

        sesiones = _mock_memory_store["POL-002"]["sesiones"]
        assert sesiones[0]["timestamp_inicio"] == "2025-07-16T09:00:00Z"
        assert sesiones[0]["timestamp_cierre"] == "2025-07-16T09:30:00Z"

    def test_persistir_poliza_id_vacio_lanza_error(self, sesion_valida):
        """poliza_id vacío debe lanzar ValueError."""
        with pytest.raises(ValueError, match="no puede estar vacío"):
            persistir_historial("", sesion_valida)

    def test_persistir_poliza_id_none_lanza_error(self, sesion_valida):
        """poliza_id None debe lanzar ValueError."""
        with pytest.raises(ValueError):
            persistir_historial(None, sesion_valida)  # type: ignore

    def test_persistir_sesion_invalida_lanza_error(self):
        """Sesión sin campos obligatorios debe lanzar ValueError."""
        with pytest.raises(ValueError, match="Campos obligatorios faltantes"):
            persistir_historial("POL-001", {"session_id": "sess-x"})

    def test_persistir_polizas_diferentes_aisladas(self, sesion_valida):
        """Pólizas diferentes tienen historiales independientes."""
        persistir_historial("POL-001", sesion_valida)

        otra_sesion = dict(sesion_valida)
        otra_sesion["session_id"] = "sess-otra"
        persistir_historial("POL-002", otra_sesion)

        assert len(_mock_memory_store["POL-001"]["sesiones"]) == 1
        assert len(_mock_memory_store["POL-002"]["sesiones"]) == 1

    def test_persistir_mensajes_enviados_cero(self, sesion_valida):
        """Acepta mensajes_enviados = 0 como válido."""
        sesion_valida["mensajes_enviados"] = 0
        resultado = persistir_historial("POL-003", sesion_valida)
        assert resultado is True


# ---------------------------------------------------------------------------
# Tests: recuperar_historial (mock)
# ---------------------------------------------------------------------------


class TestRecuperarHistorial:
    """Tests para la función pública recuperar_historial."""

    def test_recuperar_sin_historial_retorna_none(self):
        """Si no hay historial previo, retorna None."""
        resultado = recuperar_historial("POL-INEXISTENTE")
        assert resultado is None

    def test_recuperar_historial_existente(self, sesion_valida):
        """Recupera correctamente el historial persistido."""
        persistir_historial("POL-001", sesion_valida)
        resultado = recuperar_historial("POL-001")

        assert resultado is not None
        assert resultado["poliza_id"] == "POL-001"
        assert len(resultado["sesiones"]) == 1
        assert resultado["sesiones"][0]["session_id"] == "sess-test-001"
        assert resultado["sesiones"][0]["resultado"] == "interesado"
        assert resultado["sesiones"][0]["mensajes_enviados"] == 3

    def test_recuperar_multiples_sesiones(self, sesion_valida):
        """Recupera todas las sesiones acumuladas."""
        persistir_historial("POL-001", sesion_valida)

        segunda = {
            "session_id": "sess-test-002",
            "timestamp_inicio": "2025-07-20T14:00:00Z",
            "timestamp_cierre": "2025-07-20T14:30:00Z",
            "estado_final": "No renovada / sin respuesta",
            "resultado": "no respondió",
            "mensajes_enviados": 4,
        }
        persistir_historial("POL-001", segunda)

        resultado = recuperar_historial("POL-001")
        assert resultado is not None
        assert len(resultado["sesiones"]) == 2

    def test_recuperar_poliza_id_vacio_lanza_error(self):
        """poliza_id vacío debe lanzar ValueError."""
        with pytest.raises(ValueError, match="no puede estar vacío"):
            recuperar_historial("")

    def test_recuperar_poliza_id_none_lanza_error(self):
        """poliza_id None debe lanzar ValueError."""
        with pytest.raises(ValueError):
            recuperar_historial(None)  # type: ignore

    def test_recuperar_preserva_estructura_json(self, sesion_valida):
        """La estructura recuperada coincide con la especificación del diseño."""
        persistir_historial("POL-2024-001", sesion_valida)
        resultado = recuperar_historial("POL-2024-001")

        assert resultado is not None
        # Verificar estructura top-level
        assert "poliza_id" in resultado
        assert "sesiones" in resultado
        assert isinstance(resultado["sesiones"], list)

        # Verificar campos de sesión
        sesion = resultado["sesiones"][0]
        assert "session_id" in sesion
        assert "timestamp_inicio" in sesion
        assert "timestamp_cierre" in sesion
        assert "estado_final" in sesion
        assert "resultado" in sesion
        assert "mensajes_enviados" in sesion


# ---------------------------------------------------------------------------
# Tests: Helper _crear_historial_vacio
# ---------------------------------------------------------------------------


class TestCrearHistorialVacio:
    """Tests para la creación de estructura base."""

    def test_estructura_base_correcta(self):
        """La estructura base tiene poliza_id y sesiones vacías."""
        result = _crear_historial_vacio("POL-TEST")
        assert result == {"poliza_id": "POL-TEST", "sesiones": []}
