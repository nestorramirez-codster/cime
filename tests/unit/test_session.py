"""
Tests unitarios para src/agent/session.py — lógica de arranque de sesión.

Cubre:
- Payload válido → sesión inicia, Pipefy actualizado a "Póliza detectada"
- Payload inválido → sesión rechazada, Pipefy actualizado a "No renovada / sin respuesta"
- Estado bloqueante → sesión terminada sin acción
- Discrepancia de datos → escalar_humano invocado inmediatamente
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.agent.session import iniciar_sesion, _detectar_discrepancias
from src.models.data_models import ActivationPayload, PipelineCard, SessionState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def payload_valido() -> ActivationPayload:
    """Payload completamente válido para tests."""
    return ActivationPayload(
        poliza_id="POL-2024-001",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


@pytest.fixture
def payload_invalido() -> ActivationPayload:
    """Payload con campos inválidos."""
    return ActivationPayload(
        poliza_id="POL-2024-001",
        cliente_nombre="",  # vacío → inválido
        cliente_email="email-invalido",  # sin @ → inválido
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=-100.0,  # negativo → inválido
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


@pytest.fixture
def card_normal() -> PipelineCard:
    """PipelineCard con datos consistentes al payload_valido."""
    return PipelineCard(
        poliza_id="POL-2024-001",
        estado_actual="Póliza detectada",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=[],
    )


@pytest.fixture
def card_bloqueante() -> PipelineCard:
    """PipelineCard en estado bloqueante."""
    return PipelineCard(
        poliza_id="POL-2024-001",
        estado_actual="Renovación confirmada",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=[],
    )


@pytest.fixture
def card_discrepancia_precio() -> PipelineCard:
    """PipelineCard con precio discrepante (>1% diferencia)."""
    return PipelineCard(
        poliza_id="POL-2024-001",
        estado_actual="Póliza detectada",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=50000.00,  # >1% diferencia vs 45000
        equipo_nombre="UPS Eaton 9PX 6kVA",
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=[],
    )


@pytest.fixture
def card_discrepancia_nombre() -> PipelineCard:
    """PipelineCard con nombre de cliente discrepante."""
    return PipelineCard(
        poliza_id="POL-2024-001",
        estado_actual="Póliza detectada",
        cliente_nombre="Otra Empresa S.A.",  # diferente
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=[],
    )


@pytest.fixture
def card_discrepancia_fecha() -> PipelineCard:
    """PipelineCard con fecha de vencimiento discrepante."""
    return PipelineCard(
        poliza_id="POL-2024-001",
        estado_actual="Póliza detectada",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 9, 30),  # diferente
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=[],
    )


# ---------------------------------------------------------------------------
# Tests: Payload válido → sesión inicia exitosamente
# ---------------------------------------------------------------------------


class TestIniciarSesionExitosa:
    """Payload válido con datos consistentes → sesión arranca."""

    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_sesion_inicia_con_payload_valido(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        payload_valido: ActivationPayload,
        card_normal: PipelineCard,
    ):
        """Payload válido y sin discrepancias → success=True y estado persistido."""
        mock_consultar.return_value = card_normal
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        resultado = iniciar_sesion(payload_valido, "sess-001")

        assert resultado["success"] is True
        assert isinstance(resultado["session_state"], SessionState)
        assert resultado["session_state"].session_id == "sess-001"
        assert resultado["session_state"].poliza_id == "POL-2024-001"
        assert resultado["session_state"].estado_pipefy == "Póliza detectada"

    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_pipefy_actualizado_a_poliza_detectada(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        payload_valido: ActivationPayload,
        card_normal: PipelineCard,
    ):
        """Verifica que actualizar_pipefy se llama con 'Póliza detectada'."""
        mock_consultar.return_value = card_normal
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        iniciar_sesion(payload_valido, "sess-001")

        mock_actualizar.assert_called_once_with(
            poliza_id="POL-2024-001",
            estado="Póliza detectada",
            nota="Sesión de seguimiento iniciada por AgentCore",
            session_id="sess-001",
        )

    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_estado_sesion_persistido_en_memory(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        payload_valido: ActivationPayload,
        card_normal: PipelineCard,
    ):
        """Verifica que guardar_estado_sesion se invoca con SessionState correcto."""
        mock_consultar.return_value = card_normal
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        iniciar_sesion(payload_valido, "sess-001")

        mock_guardar.assert_called_once()
        session_state = mock_guardar.call_args[0][0]
        assert session_state.session_id == "sess-001"
        assert session_state.poliza_id == "POL-2024-001"
        assert session_state.estado_pipefy == "Póliza detectada"
        assert session_state.historial_mensajes == []


# ---------------------------------------------------------------------------
# Tests: Payload inválido → sesión rechazada
# ---------------------------------------------------------------------------


class TestIniciarSesionPayloadInvalido:
    """Payload inválido → rechazo, error registrado, Pipefy actualizado."""

    @patch("src.agent.session.actualizar_pipefy")
    def test_payload_invalido_retorna_failure(
        self,
        mock_actualizar: MagicMock,
        payload_invalido: ActivationPayload,
    ):
        """Payload con campos inválidos → success=False."""
        mock_actualizar.return_value = True

        resultado = iniciar_sesion(payload_invalido, "sess-002")

        assert resultado["success"] is False
        assert resultado["reason"] == "payload_invalido"
        assert len(resultado["error_details"]) > 0

    @patch("src.agent.session.actualizar_pipefy")
    def test_payload_invalido_identifica_campos_erroneos(
        self,
        mock_actualizar: MagicMock,
        payload_invalido: ActivationPayload,
    ):
        """Los error_details incluyen los campos específicos que fallaron."""
        mock_actualizar.return_value = True

        resultado = iniciar_sesion(payload_invalido, "sess-002")

        assert "cliente_nombre" in resultado["error_details"]
        assert "cliente_email" in resultado["error_details"]
        assert "precio_renovacion" in resultado["error_details"]

    @patch("src.agent.session.actualizar_pipefy")
    def test_payload_invalido_actualiza_pipefy_no_renovada(
        self,
        mock_actualizar: MagicMock,
        payload_invalido: ActivationPayload,
    ):
        """Pipefy se actualiza a 'No renovada / sin respuesta' con payload inválido."""
        mock_actualizar.return_value = True

        iniciar_sesion(payload_invalido, "sess-002")

        mock_actualizar.assert_called_once()
        call_kwargs = mock_actualizar.call_args[1]
        assert call_kwargs["estado"] == "No renovada / sin respuesta"
        assert call_kwargs["poliza_id"] == "POL-2024-001"

    @patch("src.agent.session.actualizar_pipefy")
    def test_payload_invalido_no_consulta_pipefy(
        self,
        mock_actualizar: MagicMock,
        payload_invalido: ActivationPayload,
    ):
        """Si el payload es inválido, no se llama consultar_pipefy."""
        mock_actualizar.return_value = True

        with patch("src.agent.session.consultar_pipefy") as mock_consultar:
            iniciar_sesion(payload_invalido, "sess-002")
            mock_consultar.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Estado bloqueante → sesión terminada sin acción
# ---------------------------------------------------------------------------


class TestIniciarSesionEstadoBloqueante:
    """Estado bloqueante en Pipefy → sesión termina sin ejecutar acciones."""

    @patch("src.agent.session.consultar_pipefy")
    def test_estado_renovacion_confirmada_bloquea(
        self,
        mock_consultar: MagicMock,
        payload_valido: ActivationPayload,
        card_bloqueante: PipelineCard,
    ):
        """Estado 'Renovación confirmada' bloquea la sesión."""
        mock_consultar.return_value = card_bloqueante

        resultado = iniciar_sesion(payload_valido, "sess-003")

        assert resultado["success"] is False
        assert resultado["reason"] == "estado_bloqueante"

    @patch("src.agent.session.consultar_pipefy")
    def test_estado_escalado_a_humano_bloquea(
        self,
        mock_consultar: MagicMock,
        payload_valido: ActivationPayload,
    ):
        """Estado 'Escalado a humano' también bloquea la sesión."""
        card = PipelineCard(
            poliza_id="POL-2024-001",
            estado_actual="Escalado a humano",
            cliente_nombre="Empresa Test S.A.",
            cliente_email="contacto@empresa-test.com",
            fecha_vencimiento=date(2025, 8, 15),
            precio_renovacion=45000.00,
            equipo_nombre="UPS Eaton 9PX 6kVA",
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[],
        )
        mock_consultar.return_value = card

        resultado = iniciar_sesion(payload_valido, "sess-003")

        assert resultado["success"] is False
        assert resultado["reason"] == "estado_bloqueante"

    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_estado_bloqueante_no_actualiza_pipefy(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        payload_valido: ActivationPayload,
        card_bloqueante: PipelineCard,
    ):
        """Con estado bloqueante, no se invoca actualizar_pipefy."""
        mock_consultar.return_value = card_bloqueante

        iniciar_sesion(payload_valido, "sess-003")

        mock_actualizar.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Discrepancia de datos → escalar_humano invocado
# ---------------------------------------------------------------------------


class TestIniciarSesionDiscrepancias:
    """Discrepancias entre payload y Pipefy → escalamiento inmediato."""

    @patch("src.agent.session.escalar_humano")
    @patch("src.agent.session.consultar_pipefy")
    def test_discrepancia_precio_escala(
        self,
        mock_consultar: MagicMock,
        mock_escalar: MagicMock,
        payload_valido: ActivationPayload,
        card_discrepancia_precio: PipelineCard,
    ):
        """Precio con >1% diferencia → escalar_humano invocado."""
        mock_consultar.return_value = card_discrepancia_precio
        mock_escalar.return_value = True

        resultado = iniciar_sesion(payload_valido, "sess-004")

        assert resultado["success"] is False
        assert resultado["reason"] == "discrepancia_datos"
        mock_escalar.assert_called_once()

    @patch("src.agent.session.escalar_humano")
    @patch("src.agent.session.consultar_pipefy")
    def test_discrepancia_nombre_escala(
        self,
        mock_consultar: MagicMock,
        mock_escalar: MagicMock,
        payload_valido: ActivationPayload,
        card_discrepancia_nombre: PipelineCard,
    ):
        """Nombre del cliente diferente → escalar_humano invocado."""
        mock_consultar.return_value = card_discrepancia_nombre
        mock_escalar.return_value = True

        resultado = iniciar_sesion(payload_valido, "sess-004")

        assert resultado["success"] is False
        assert resultado["reason"] == "discrepancia_datos"
        mock_escalar.assert_called_once()

    @patch("src.agent.session.escalar_humano")
    @patch("src.agent.session.consultar_pipefy")
    def test_discrepancia_fecha_escala(
        self,
        mock_consultar: MagicMock,
        mock_escalar: MagicMock,
        payload_valido: ActivationPayload,
        card_discrepancia_fecha: PipelineCard,
    ):
        """Fecha de vencimiento diferente → escalar_humano invocado."""
        mock_consultar.return_value = card_discrepancia_fecha
        mock_escalar.return_value = True

        resultado = iniciar_sesion(payload_valido, "sess-004")

        assert resultado["success"] is False
        assert resultado["reason"] == "discrepancia_datos"
        mock_escalar.assert_called_once()

    @patch("src.agent.session.escalar_humano")
    @patch("src.agent.session.consultar_pipefy")
    def test_discrepancia_no_envia_correo(
        self,
        mock_consultar: MagicMock,
        mock_escalar: MagicMock,
        payload_valido: ActivationPayload,
        card_discrepancia_precio: PipelineCard,
    ):
        """Con discrepancia, NO se actualiza Pipefy a 'Póliza detectada'."""
        mock_consultar.return_value = card_discrepancia_precio
        mock_escalar.return_value = True

        with patch("src.agent.session.actualizar_pipefy") as mock_actualizar:
            iniciar_sesion(payload_valido, "sess-004")
            mock_actualizar.assert_not_called()

    @patch("src.agent.session.escalar_humano")
    @patch("src.agent.session.consultar_pipefy")
    def test_escalar_incluye_motivo_discrepancia(
        self,
        mock_consultar: MagicMock,
        mock_escalar: MagicMock,
        payload_valido: ActivationPayload,
        card_discrepancia_precio: PipelineCard,
    ):
        """El motivo de escalamiento describe la discrepancia."""
        mock_consultar.return_value = card_discrepancia_precio
        mock_escalar.return_value = True

        iniciar_sesion(payload_valido, "sess-004")

        call_kwargs = mock_escalar.call_args[1]
        assert "Discrepancia" in call_kwargs["motivo"]
        assert "Precio" in call_kwargs["motivo"]


# ---------------------------------------------------------------------------
# Tests: _detectar_discrepancias (función auxiliar)
# ---------------------------------------------------------------------------


class TestDetectarDiscrepancias:
    """Tests directos de la función de detección de discrepancias."""

    def test_sin_discrepancias(
        self, payload_valido: ActivationPayload, card_normal: PipelineCard
    ):
        """Datos iguales → lista vacía."""
        result = _detectar_discrepancias(payload_valido, card_normal)
        assert result == []

    def test_precio_dentro_de_umbral(self, payload_valido: ActivationPayload):
        """Precio con <1% diferencia no genera discrepancia."""
        card = PipelineCard(
            poliza_id="POL-2024-001",
            estado_actual="Póliza detectada",
            cliente_nombre="Empresa Test S.A.",
            cliente_email="contacto@empresa-test.com",
            fecha_vencimiento=date(2025, 8, 15),
            precio_renovacion=45400.00,  # ~0.89% diferencia → OK
            equipo_nombre="UPS Eaton 9PX 6kVA",
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[],
        )
        result = _detectar_discrepancias(payload_valido, card)
        assert result == []

    def test_precio_fuera_de_umbral(self, payload_valido: ActivationPayload):
        """Precio con >1% diferencia genera discrepancia."""
        card = PipelineCard(
            poliza_id="POL-2024-001",
            estado_actual="Póliza detectada",
            cliente_nombre="Empresa Test S.A.",
            cliente_email="contacto@empresa-test.com",
            fecha_vencimiento=date(2025, 8, 15),
            precio_renovacion=46000.00,  # ~2.2% diferencia → discrepancia
            equipo_nombre="UPS Eaton 9PX 6kVA",
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[],
        )
        result = _detectar_discrepancias(payload_valido, card)
        assert len(result) == 1
        assert "Precio" in result[0]

    def test_nombre_case_insensitive(self, payload_valido: ActivationPayload):
        """Comparación de nombre es case-insensitive."""
        card = PipelineCard(
            poliza_id="POL-2024-001",
            estado_actual="Póliza detectada",
            cliente_nombre="empresa test s.a.",  # mismo pero minúsculas
            cliente_email="contacto@empresa-test.com",
            fecha_vencimiento=date(2025, 8, 15),
            precio_renovacion=45000.00,
            equipo_nombre="UPS Eaton 9PX 6kVA",
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[],
        )
        result = _detectar_discrepancias(payload_valido, card)
        assert result == []

    def test_multiples_discrepancias(self, payload_valido: ActivationPayload):
        """Varios campos diferentes → múltiples discrepancias."""
        card = PipelineCard(
            poliza_id="POL-2024-001",
            estado_actual="Póliza detectada",
            cliente_nombre="Otra Empresa",
            cliente_email="contacto@empresa-test.com",
            fecha_vencimiento=date(2025, 12, 31),
            precio_renovacion=60000.00,
            equipo_nombre="UPS Eaton 9PX 6kVA",
            timestamp_ultima_actualizacion=datetime.now(timezone.utc),
            notas=[],
        )
        result = _detectar_discrepancias(payload_valido, card)
        assert len(result) == 3
