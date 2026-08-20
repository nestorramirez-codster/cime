"""
Tests unitarios para la capa de Memory de corto plazo (DynamoDB).

Verifica:
- Guardar y recuperar estado de sesión
- TTL de 24 horas para sesiones
- TTL de 10 minutos para datos de comprobante (Req 8.5)
- Aislamiento de sesiones (Req 12.7)
- Eliminación de datos de comprobante
- Validación de entradas

Requisitos: 8.1, 8.5, 12.7
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# Asegurar modo mock
os.environ["CIME_MOCK_MODE"] = "true"

from src.memory.short_term import (
    _calcular_ttl_comprobante,
    _calcular_ttl_sesion,
    _deserializar_session_state,
    _reset_mock_store,
    _serializar_session_state,
    eliminar_dato_comprobante,
    guardar_estado_sesion,
    obtener_estado_sesion,
)
from src.models.constants import (
    MEMORY_COMPROBANTE_TTL_MINUTOS,
    MEMORY_SHORT_TERM_TTL_HORAS,
)
from src.models.data_models import (
    DatosComprobanteTemp,
    Mensaje,
    SessionState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def limpiar_mock_store():
    """Limpia el store mock antes y después de cada test."""
    _reset_mock_store()
    yield
    _reset_mock_store()


def _crear_session_state(
    session_id: str = "test-session-001",
    poliza_id: str = "POL-2025-001",
    con_comprobante: bool = False,
) -> SessionState:
    """Crea un SessionState de prueba."""
    mensajes = [
        Mensaje(
            timestamp=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            remitente="agente",
            contenido="Buen día, le escribimos sobre su póliza.",
            tipo="contacto_inicial",
        ),
        Mensaje(
            timestamp=datetime(2025, 1, 15, 10, 5, 0, tzinfo=timezone.utc),
            remitente="cliente",
            contenido="Sí, me interesa renovar.",
            tipo="respuesta_cliente",
        ),
    ]

    comprobante = None
    if con_comprobante:
        comprobante = DatosComprobanteTemp(
            referencia_adjunto="s3://cime-bucket/comprobantes/comp-001.pdf",
            monto=45000.00,
            timestamp_recepcion=datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
            formato="PDF",
            tamanio_bytes=2_500_000,
        )

    return SessionState(
        session_id=session_id,
        poliza_id=poliza_id,
        estado_pipefy="Cliente interesado",
        historial_mensajes=mensajes,
        timestamp_inicio=datetime(2025, 1, 15, 9, 55, 0, tzinfo=timezone.utc),
        datos_comprobante=comprobante,
    )


# ---------------------------------------------------------------------------
# Tests: guardar_estado_sesion
# ---------------------------------------------------------------------------


class TestGuardarEstadoSesion:
    """Tests para la función guardar_estado_sesion."""

    def test_guardar_sesion_basica(self):
        """Guarda una sesión sin comprobante y verifica que retorna True."""
        session = _crear_session_state()
        resultado = guardar_estado_sesion(session)
        assert resultado is True

    def test_guardar_sesion_con_comprobante(self):
        """Guarda una sesión con datos de comprobante."""
        session = _crear_session_state(con_comprobante=True)
        resultado = guardar_estado_sesion(session)
        assert resultado is True

    def test_guardar_session_id_vacio_lanza_error(self):
        """session_id vacío lanza ValueError."""
        session = _crear_session_state(session_id="")
        with pytest.raises(ValueError, match="session_id no puede estar vacío"):
            guardar_estado_sesion(session)

    def test_guardar_session_id_espacios_lanza_error(self):
        """session_id con solo espacios lanza ValueError."""
        session = _crear_session_state(session_id="   ")
        with pytest.raises(ValueError, match="session_id no puede estar vacío"):
            guardar_estado_sesion(session)

    def test_guardar_sobreescribe_sesion_existente(self):
        """Guardar con mismo session_id sobreescribe el estado previo."""
        session = _crear_session_state()
        guardar_estado_sesion(session)

        # Actualizar estado
        session.estado_pipefy = "Depósito solicitado"
        guardar_estado_sesion(session)

        recuperada = obtener_estado_sesion("test-session-001")
        assert recuperada is not None
        assert recuperada.estado_pipefy == "Depósito solicitado"


# ---------------------------------------------------------------------------
# Tests: obtener_estado_sesion
# ---------------------------------------------------------------------------


class TestObtenerEstadoSesion:
    """Tests para la función obtener_estado_sesion."""

    def test_obtener_sesion_existente(self):
        """Recupera correctamente una sesión guardada."""
        session = _crear_session_state()
        guardar_estado_sesion(session)

        recuperada = obtener_estado_sesion("test-session-001")
        assert recuperada is not None
        assert recuperada.session_id == "test-session-001"
        assert recuperada.poliza_id == "POL-2025-001"
        assert recuperada.estado_pipefy == "Cliente interesado"
        assert len(recuperada.historial_mensajes) == 2

    def test_obtener_sesion_no_existente(self):
        """Retorna None para session_id que no existe."""
        resultado = obtener_estado_sesion("no-existe-123")
        assert resultado is None

    def test_obtener_session_id_vacio_lanza_error(self):
        """session_id vacío lanza ValueError."""
        with pytest.raises(ValueError, match="session_id no puede estar vacío"):
            obtener_estado_sesion("")

    def test_obtener_sesion_con_comprobante_vigente(self):
        """Recupera sesión con comprobante que no ha expirado."""
        session = _crear_session_state(con_comprobante=True)
        guardar_estado_sesion(session)

        recuperada = obtener_estado_sesion("test-session-001")
        assert recuperada is not None
        assert recuperada.datos_comprobante is not None
        assert recuperada.datos_comprobante.monto == 45000.00
        assert recuperada.datos_comprobante.formato == "PDF"

    def test_obtener_sesion_historial_preservado(self):
        """Verifica que el historial de mensajes se deserializa correctamente."""
        session = _crear_session_state()
        guardar_estado_sesion(session)

        recuperada = obtener_estado_sesion("test-session-001")
        assert recuperada is not None
        assert recuperada.historial_mensajes[0].remitente == "agente"
        assert recuperada.historial_mensajes[0].tipo == "contacto_inicial"
        assert recuperada.historial_mensajes[1].remitente == "cliente"
        assert "renovar" in recuperada.historial_mensajes[1].contenido


# ---------------------------------------------------------------------------
# Tests: eliminar_dato_comprobante
# ---------------------------------------------------------------------------


class TestEliminarDatoComprobante:
    """Tests para la función eliminar_dato_comprobante."""

    def test_eliminar_comprobante_existente(self):
        """Elimina datos de comprobante de una sesión."""
        session = _crear_session_state(con_comprobante=True)
        guardar_estado_sesion(session)

        resultado = eliminar_dato_comprobante("test-session-001")
        assert resultado is True

        # Verificar que ya no tiene comprobante
        recuperada = obtener_estado_sesion("test-session-001")
        assert recuperada is not None
        assert recuperada.datos_comprobante is None

    def test_eliminar_comprobante_sesion_sin_comprobante(self):
        """Eliminar comprobante de sesión sin comprobante retorna True."""
        session = _crear_session_state(con_comprobante=False)
        guardar_estado_sesion(session)

        resultado = eliminar_dato_comprobante("test-session-001")
        assert resultado is True

    def test_eliminar_comprobante_sesion_inexistente(self):
        """Eliminar comprobante de sesión inexistente retorna False."""
        resultado = eliminar_dato_comprobante("no-existe-999")
        assert resultado is False

    def test_eliminar_session_id_vacio_lanza_error(self):
        """session_id vacío lanza ValueError."""
        with pytest.raises(ValueError, match="session_id no puede estar vacío"):
            eliminar_dato_comprobante("")

    def test_eliminar_comprobante_no_afecta_otros_campos(self):
        """Eliminar comprobante preserva el resto del estado de sesión."""
        session = _crear_session_state(con_comprobante=True)
        guardar_estado_sesion(session)

        eliminar_dato_comprobante("test-session-001")

        recuperada = obtener_estado_sesion("test-session-001")
        assert recuperada is not None
        assert recuperada.poliza_id == "POL-2025-001"
        assert recuperada.estado_pipefy == "Cliente interesado"
        assert len(recuperada.historial_mensajes) == 2


# ---------------------------------------------------------------------------
# Tests: Aislamiento de sesiones (Req 12.7)
# ---------------------------------------------------------------------------


class TestAislamientoSesiones:
    """Tests para verificar aislamiento entre sesiones distintas."""

    def test_sesiones_distintas_no_se_mezclan(self):
        """Sesión A no puede ver datos de sesión B."""
        session_a = _crear_session_state(
            session_id="session-A", poliza_id="POL-A"
        )
        session_b = _crear_session_state(
            session_id="session-B", poliza_id="POL-B"
        )
        session_b.estado_pipefy = "Depósito solicitado"

        guardar_estado_sesion(session_a)
        guardar_estado_sesion(session_b)

        recuperada_a = obtener_estado_sesion("session-A")
        recuperada_b = obtener_estado_sesion("session-B")

        assert recuperada_a is not None
        assert recuperada_b is not None
        assert recuperada_a.poliza_id == "POL-A"
        assert recuperada_b.poliza_id == "POL-B"
        assert recuperada_a.estado_pipefy == "Cliente interesado"
        assert recuperada_b.estado_pipefy == "Depósito solicitado"

    def test_eliminar_comprobante_no_afecta_otra_sesion(self):
        """Eliminar comprobante de A no toca comprobante de B."""
        session_a = _crear_session_state(
            session_id="session-A", con_comprobante=True
        )
        session_b = _crear_session_state(
            session_id="session-B", con_comprobante=True
        )

        guardar_estado_sesion(session_a)
        guardar_estado_sesion(session_b)

        eliminar_dato_comprobante("session-A")

        recuperada_a = obtener_estado_sesion("session-A")
        recuperada_b = obtener_estado_sesion("session-B")

        assert recuperada_a is not None
        assert recuperada_a.datos_comprobante is None
        assert recuperada_b is not None
        assert recuperada_b.datos_comprobante is not None


# ---------------------------------------------------------------------------
# Tests: TTL y expiración
# ---------------------------------------------------------------------------


class TestTTLExpiracion:
    """Tests para verificar comportamiento de TTL."""

    def test_ttl_sesion_24_horas(self):
        """El TTL calculado es aproximadamente 24 horas en el futuro."""
        ttl = _calcular_ttl_sesion()
        ahora = int(time.time())
        diferencia_horas = (ttl - ahora) / 3600

        assert abs(diferencia_horas - MEMORY_SHORT_TERM_TTL_HORAS) < 0.01

    def test_ttl_comprobante_10_minutos(self):
        """El TTL de comprobante es aproximadamente 10 minutos en el futuro."""
        ttl = _calcular_ttl_comprobante()
        ahora = int(time.time())
        diferencia_minutos = (ttl - ahora) / 60

        assert abs(diferencia_minutos - MEMORY_COMPROBANTE_TTL_MINUTOS) < 0.01

    def test_sesion_expirada_retorna_none(self):
        """Una sesión con TTL expirado retorna None al obtenerla."""
        session = _crear_session_state()
        guardar_estado_sesion(session)

        # Forzar expiración del TTL en el mock store
        from src.memory.short_term import _mock_store

        _mock_store["test-session-001"]["expiry_time"] = int(time.time()) - 1

        resultado = obtener_estado_sesion("test-session-001")
        assert resultado is None

    def test_comprobante_expirado_se_omite(self):
        """Comprobante con TTL expirado se excluye al deserializar."""
        session = _crear_session_state(con_comprobante=True)
        guardar_estado_sesion(session)

        # Forzar expiración del TTL de comprobante
        from src.memory.short_term import _mock_store

        _mock_store["test-session-001"]["comprobante_expiry_time"] = (
            int(time.time()) - 1
        )

        recuperada = obtener_estado_sesion("test-session-001")
        assert recuperada is not None
        assert recuperada.datos_comprobante is None


# ---------------------------------------------------------------------------
# Tests: Serialización round-trip
# ---------------------------------------------------------------------------


class TestSerializacion:
    """Tests para verificar que la serialización es consistente."""

    def test_roundtrip_session_sin_comprobante(self):
        """Serializar y deserializar preserva todos los campos."""
        session = _crear_session_state()
        item = _serializar_session_state(session)
        recuperada = _deserializar_session_state(item)

        assert recuperada.session_id == session.session_id
        assert recuperada.poliza_id == session.poliza_id
        assert recuperada.estado_pipefy == session.estado_pipefy
        assert len(recuperada.historial_mensajes) == len(session.historial_mensajes)
        assert recuperada.timestamp_inicio == session.timestamp_inicio
        assert recuperada.datos_comprobante is None

    def test_roundtrip_session_con_comprobante(self):
        """Serializar y deserializar preserva datos de comprobante."""
        session = _crear_session_state(con_comprobante=True)
        item = _serializar_session_state(session)
        recuperada = _deserializar_session_state(item)

        assert recuperada.datos_comprobante is not None
        assert recuperada.datos_comprobante.monto == 45000.00
        assert recuperada.datos_comprobante.formato == "PDF"
        assert recuperada.datos_comprobante.tamanio_bytes == 2_500_000

    def test_roundtrip_mensajes_preserva_contenido(self):
        """Serialización preserva contenido y metadatos de mensajes."""
        session = _crear_session_state()
        item = _serializar_session_state(session)
        recuperada = _deserializar_session_state(item)

        for original, recuperado in zip(
            session.historial_mensajes, recuperada.historial_mensajes
        ):
            assert original.timestamp == recuperado.timestamp
            assert original.remitente == recuperado.remitente
            assert original.contenido == recuperado.contenido
            assert original.tipo == recuperado.tipo
