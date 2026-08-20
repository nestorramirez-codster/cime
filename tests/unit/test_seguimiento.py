"""
Tests unitarios para el flujo de seguimiento multi-etapa.

Verifica la máquina de estados del Requisito 3:
- Interés del cliente → "Cliente interesado"
- Rechazo pre-vencimiento → oferta de descuento
- Rechazo post-vencimiento → escalar a humano
- Sin respuesta 48h → recordatorio
- Rechazo de oferta → encuesta
- Sin respuesta 72h → "No renovada / sin respuesta"
- Actualización a "Seguimiento en curso" al inicio de cada mensaje (Req 3.9)

Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.agent.flows.seguimiento import (
    TIPOS_RESPUESTA_VALIDOS,
    _cerrar_sin_respuesta,
    _enviar_encuesta_no_renovacion,
    _enviar_seguimiento_48h,
    _manejar_interes,
    _manejar_rechazo_post_vencimiento,
    _manejar_rechazo_pre_vencimiento,
    procesar_respuesta_cliente,
)
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.constants import DESCUENTO_PRE_VENCIMIENTO
from src.models.data_models import (
    ActivationPayload,
    EmailResult,
    SessionState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session_state():
    """SessionState de prueba con estado 'Contacto inicial enviado'."""
    return SessionState(
        session_id="test-session-001",
        poliza_id="POL-2025-001",
        estado_pipefy="Contacto inicial enviado",
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )


@pytest.fixture
def payload_pre_vencimiento():
    """Payload con fecha de vencimiento futura (pre-vencimiento)."""
    return ActivationPayload(
        poliza_id="POL-2025-001",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date.today() + timedelta(days=15),
        precio_renovacion=50000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


@pytest.fixture
def payload_post_vencimiento():
    """Payload con fecha de vencimiento pasada (post-vencimiento)."""
    return ActivationPayload(
        poliza_id="POL-2025-002",
        cliente_nombre="Empresa Vencida S.A.",
        cliente_email="contacto@empresa-vencida.com",
        fecha_vencimiento=date.today() - timedelta(days=10),
        precio_renovacion=35000.00,
        equipo_nombre="Generador CAT 500kW",
    )


@pytest.fixture
def mock_kb_client():
    """KBClient mock que retorna resultados con score suficiente."""
    client = MagicMock(spec=KBClient)
    client.query.return_value = KBQueryResponse(
        results=[
            KBResult(
                content="[Plantilla de prueba para descuento]",
                score=0.85,
                source_uri="s3://test/plantillas_mensajes.md",
            )
        ],
        query_text="test query",
    )
    return client


@pytest.fixture
def mock_email_success():
    """EmailResult exitoso."""
    return EmailResult(
        success=True,
        message_id="mock-msg-001",
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Tests: procesar_respuesta_cliente (router principal)
# ---------------------------------------------------------------------------


class TestProcesarRespuestaCliente:
    """Tests para el router principal de la máquina de estados."""

    def test_tipo_respuesta_invalido_lanza_error(
        self, session_state, payload_pre_vencimiento
    ):
        """Tipo de respuesta no válido debe lanzar ValueError."""
        with pytest.raises(ValueError, match="no es válido"):
            procesar_respuesta_cliente(
                session_state=session_state,
                payload=payload_pre_vencimiento,
                respuesta_tipo="tipo_invalido",
            )

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_interes_delega_correctamente(
        self, mock_pipefy, session_state, payload_pre_vencimiento
    ):
        """respuesta_tipo='interes' debe actualizar a 'Cliente interesado'."""
        mock_pipefy.return_value = True

        result = procesar_respuesta_cliente(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            respuesta_tipo="interes",
        )

        assert result["success"] is True
        assert result["nuevo_estado"] == "Cliente interesado"
        mock_pipefy.assert_called_once()
        call_kwargs = mock_pipefy.call_args[1]
        assert call_kwargs["estado"] == "Cliente interesado"

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_rechazo_pre_vencimiento_envia_oferta(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """Rechazo pre-vencimiento debe enviar oferta de descuento."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        result = procesar_respuesta_cliente(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            respuesta_tipo="rechazo",
            kb_client=mock_kb_client,
        )

        assert result["success"] is True
        assert result["descuento_porcentaje"] == DESCUENTO_PRE_VENCIMIENTO
        mock_correo.assert_called_once()

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    @patch("src.agent.flows.seguimiento.escalar_humano")
    def test_rechazo_post_vencimiento_escala(
        self,
        mock_escalar,
        mock_pipefy,
        session_state,
        payload_post_vencimiento,
    ):
        """Rechazo post-vencimiento debe escalar a humano."""
        mock_pipefy.return_value = True
        mock_escalar.return_value = True

        result = procesar_respuesta_cliente(
            session_state=session_state,
            payload=payload_post_vencimiento,
            respuesta_tipo="rechazo",
        )

        assert result["success"] is True
        assert result["nuevo_estado"] == "Escalado a humano"
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_sin_respuesta_48h_envia_recordatorio(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_email_success,
    ):
        """48h sin respuesta debe enviar recordatorio."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        result = procesar_respuesta_cliente(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            respuesta_tipo="sin_respuesta_48h",
        )

        assert result["success"] is True
        assert "Recordatorio" in result["motivo"] or "recordatorio" in result["motivo"].lower()
        mock_correo.assert_called_once()

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_rechazo_oferta_envia_encuesta(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """Rechazo de oferta debe enviar encuesta de motivos."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        result = procesar_respuesta_cliente(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            respuesta_tipo="rechazo_oferta",
            kb_client=mock_kb_client,
        )

        assert result["success"] is True
        assert "encuesta" in result["motivo"].lower()
        mock_correo.assert_called_once()

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_sin_respuesta_72h_cierra(
        self, mock_pipefy, session_state, payload_pre_vencimiento
    ):
        """72h sin respuesta debe cerrar como 'No renovada / sin respuesta'."""
        mock_pipefy.return_value = True

        result = procesar_respuesta_cliente(
            session_state=session_state,
            payload=payload_pre_vencimiento,
            respuesta_tipo="sin_respuesta_72h",
        )

        assert result["success"] is True
        assert result["nuevo_estado"] == "No renovada / sin respuesta"
        mock_pipefy.assert_called_once()
        call_kwargs = mock_pipefy.call_args[1]
        assert call_kwargs["estado"] == "No renovada / sin respuesta"


# ---------------------------------------------------------------------------
# Tests: _manejar_interes (Req 3.1, 3.2)
# ---------------------------------------------------------------------------


class TestManejarInteres:
    """Tests para el manejo de interés del cliente."""

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_actualiza_pipefy_a_cliente_interesado(
        self, mock_pipefy, session_state, payload_pre_vencimiento
    ):
        """Debe actualizar Pipefy a 'Cliente interesado' (Req 3.1)."""
        mock_pipefy.return_value = True

        result = _manejar_interes(session_state, payload_pre_vencimiento)

        assert result["success"] is True
        assert result["nuevo_estado"] == "Cliente interesado"
        assert result["siguiente_accion"] == "generar_cotizacion"
        mock_pipefy.assert_called_once_with(
            poliza_id="POL-2025-001",
            estado="Cliente interesado",
            nota=pytest.approx(mock_pipefy.call_args[1]["nota"], abs=None),
            session_id="test-session-001",
        )

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_usa_session_id_correcto(
        self, mock_pipefy, session_state, payload_pre_vencimiento
    ):
        """Debe pasar el session_id correcto a actualizar_pipefy."""
        mock_pipefy.return_value = True

        _manejar_interes(session_state, payload_pre_vencimiento)

        call_kwargs = mock_pipefy.call_args[1]
        assert call_kwargs["session_id"] == "test-session-001"


# ---------------------------------------------------------------------------
# Tests: _manejar_rechazo_pre_vencimiento (Req 3.3)
# ---------------------------------------------------------------------------


class TestManejarRechazoPreVencimiento:
    """Tests para rechazo pre-vencimiento con oferta de descuento."""

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_envia_oferta_con_descuento_5_porciento(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """Debe enviar oferta con descuento del 5% (Req 3.3)."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        result = _manejar_rechazo_pre_vencimiento(
            session_state, payload_pre_vencimiento, mock_kb_client
        )

        assert result["success"] is True
        assert result["descuento_porcentaje"] == 0.05
        # Precio original: 50000, descuento 5% = 47500
        assert result["precio_con_descuento"] == 47500.00

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_correo_contiene_descuento_y_precio(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """El correo debe contener el porcentaje de descuento y el precio."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        _manejar_rechazo_pre_vencimiento(
            session_state, payload_pre_vencimiento, mock_kb_client
        )

        call_kwargs = mock_correo.call_args[1]
        cuerpo = call_kwargs["cuerpo"]
        assert "5%" in cuerpo
        assert "47,500.00 MXN" in cuerpo
        assert "50,000.00 MXN" in cuerpo

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_actualiza_pipefy_a_seguimiento_en_curso(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """Debe actualizar Pipefy a 'Seguimiento en curso' (Req 3.9)."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        _manejar_rechazo_pre_vencimiento(
            session_state, payload_pre_vencimiento, mock_kb_client
        )

        # Primera llamada debe ser "Seguimiento en curso"
        first_call_kwargs = mock_pipefy.call_args_list[0][1]
        assert first_call_kwargs["estado"] == "Seguimiento en curso"

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_consulta_kb_para_plantilla(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """Debe consultar la KB para obtener la plantilla de descuento."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        _manejar_rechazo_pre_vencimiento(
            session_state, payload_pre_vencimiento, mock_kb_client
        )

        mock_kb_client.query.assert_called_once()
        query_text = mock_kb_client.query.call_args[0][0]
        assert "descuento" in query_text.lower()

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_error_envio_correo_retorna_fallo(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
    ):
        """Si enviar_correo falla, debe retornar success=False."""
        mock_pipefy.return_value = True
        mock_correo.return_value = EmailResult(
            success=False,
            message_id=None,
            timestamp=datetime.now(timezone.utc),
            error_code="SES_TIMEOUT",
        )

        result = _manejar_rechazo_pre_vencimiento(
            session_state, payload_pre_vencimiento, mock_kb_client
        )

        assert result["success"] is False
        assert "Error" in result["motivo"]


# ---------------------------------------------------------------------------
# Tests: _manejar_rechazo_post_vencimiento (Req 3.4)
# ---------------------------------------------------------------------------


class TestManejarRechazoPostVencimiento:
    """Tests para rechazo post-vencimiento con escalamiento."""

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    @patch("src.agent.flows.seguimiento.escalar_humano")
    def test_escala_a_humano(
        self, mock_escalar, mock_pipefy, session_state, payload_post_vencimiento
    ):
        """Debe invocar escalar_humano (Req 3.4)."""
        mock_pipefy.return_value = True
        mock_escalar.return_value = True

        result = _manejar_rechazo_post_vencimiento(
            session_state, payload_post_vencimiento
        )

        assert result["success"] is True
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    @patch("src.agent.flows.seguimiento.escalar_humano")
    def test_incluye_contexto_completo_en_escalamiento(
        self, mock_escalar, mock_pipefy, session_state, payload_post_vencimiento
    ):
        """Escalamiento debe incluir historial y estado (Req 3.4)."""
        mock_pipefy.return_value = True
        mock_escalar.return_value = True

        _manejar_rechazo_post_vencimiento(
            session_state, payload_post_vencimiento
        )

        call_kwargs = mock_escalar.call_args[1]
        assert call_kwargs["historial"] == session_state.historial_mensajes
        assert call_kwargs["estado_pipefy"] == session_state.estado_pipefy
        assert call_kwargs["session_id"] == "test-session-001"
        assert "vencimiento" in call_kwargs["motivo"].lower()

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    @patch("src.agent.flows.seguimiento.escalar_humano")
    def test_actualiza_pipefy_a_escalado(
        self, mock_escalar, mock_pipefy, session_state, payload_post_vencimiento
    ):
        """Debe actualizar Pipefy a 'Escalado a humano'."""
        mock_pipefy.return_value = True
        mock_escalar.return_value = True

        result = _manejar_rechazo_post_vencimiento(
            session_state, payload_post_vencimiento
        )

        assert result["nuevo_estado"] == "Escalado a humano"
        # Verificar que actualizar_pipefy fue llamado con "Escalado a humano"
        call_kwargs = mock_pipefy.call_args[1]
        assert call_kwargs["estado"] == "Escalado a humano"


# ---------------------------------------------------------------------------
# Tests: _enviar_seguimiento_48h (Req 3.5)
# ---------------------------------------------------------------------------


class TestEnviarSeguimiento48h:
    """Tests para el recordatorio de 48h."""

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_envia_recordatorio_con_oferta_vigente(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_email_success,
    ):
        """Debe enviar recordatorio con la oferta vigente (Req 3.5)."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        result = _enviar_seguimiento_48h(session_state, payload_pre_vencimiento)

        assert result["success"] is True
        mock_correo.assert_called_once()
        call_kwargs = mock_correo.call_args[1]
        # Debe incluir el precio con descuento
        assert "47,500.00 MXN" in call_kwargs["cuerpo"]
        # Debe mencionar fecha de vencimiento como fecha límite
        assert payload_pre_vencimiento.fecha_vencimiento.isoformat() in call_kwargs["cuerpo"]

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_actualiza_pipefy_seguimiento_en_curso(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_email_success,
    ):
        """Debe actualizar Pipefy a 'Seguimiento en curso' (Req 3.9)."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        _enviar_seguimiento_48h(session_state, payload_pre_vencimiento)

        first_call_kwargs = mock_pipefy.call_args_list[0][1]
        assert first_call_kwargs["estado"] == "Seguimiento en curso"


# ---------------------------------------------------------------------------
# Tests: _enviar_encuesta_no_renovacion (Req 3.6)
# ---------------------------------------------------------------------------


class TestEnviarEncuestaNoRenovacion:
    """Tests para la encuesta de motivos de no renovación."""

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_envia_encuesta_con_opciones(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """Debe enviar encuesta con opciones de motivos (Req 3.6)."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        result = _enviar_encuesta_no_renovacion(
            session_state, payload_pre_vencimiento, mock_kb_client
        )

        assert result["success"] is True
        mock_correo.assert_called_once()
        call_kwargs = mock_correo.call_args[1]
        cuerpo = call_kwargs["cuerpo"]
        # Debe contener opciones de motivos
        assert "presupuesto" in cuerpo.lower() or "precio" in cuerpo.lower()
        assert "proveedor" in cuerpo.lower() or "alternativo" in cuerpo.lower()

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_consulta_kb_para_plantilla_encuesta(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """Debe consultar la KB para la plantilla de encuesta."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        _enviar_encuesta_no_renovacion(
            session_state, payload_pre_vencimiento, mock_kb_client
        )

        mock_kb_client.query.assert_called_once()
        query_text = mock_kb_client.query.call_args[0][0]
        assert "encuesta" in query_text.lower()

    @patch("src.agent.flows.seguimiento.enviar_correo")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_actualiza_pipefy_seguimiento_en_curso(
        self,
        mock_pipefy,
        mock_correo,
        session_state,
        payload_pre_vencimiento,
        mock_kb_client,
        mock_email_success,
    ):
        """Debe actualizar Pipefy a 'Seguimiento en curso' (Req 3.9)."""
        mock_pipefy.return_value = True
        mock_correo.return_value = mock_email_success

        _enviar_encuesta_no_renovacion(
            session_state, payload_pre_vencimiento, mock_kb_client
        )

        first_call_kwargs = mock_pipefy.call_args_list[0][1]
        assert first_call_kwargs["estado"] == "Seguimiento en curso"


# ---------------------------------------------------------------------------
# Tests: _cerrar_sin_respuesta (Req 3.7)
# ---------------------------------------------------------------------------


class TestCerrarSinRespuesta:
    """Tests para el cierre por 72h sin respuesta."""

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_actualiza_a_no_renovada(
        self, mock_pipefy, session_state, payload_pre_vencimiento
    ):
        """Debe actualizar Pipefy a 'No renovada / sin respuesta' (Req 3.7)."""
        mock_pipefy.return_value = True

        result = _cerrar_sin_respuesta(session_state, payload_pre_vencimiento)

        assert result["success"] is True
        assert result["nuevo_estado"] == "No renovada / sin respuesta"
        call_kwargs = mock_pipefy.call_args[1]
        assert call_kwargs["estado"] == "No renovada / sin respuesta"

    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    def test_incluye_timestamp_cierre(
        self, mock_pipefy, session_state, payload_pre_vencimiento
    ):
        """Debe incluir el timestamp de cierre en la respuesta."""
        mock_pipefy.return_value = True

        result = _cerrar_sin_respuesta(session_state, payload_pre_vencimiento)

        assert "timestamp_cierre" in result
        # Verificar que es un ISO timestamp válido
        datetime.fromisoformat(result["timestamp_cierre"])


# ---------------------------------------------------------------------------
# Tests: Constantes y validaciones
# ---------------------------------------------------------------------------


class TestConstantesYValidaciones:
    """Tests para tipos de respuesta válidos y validaciones."""

    def test_tipos_respuesta_validos_completos(self):
        """Todos los tipos esperados deben estar definidos."""
        esperados = {
            "interes",
            "rechazo",
            "sin_respuesta_48h",
            "rechazo_oferta",
            "sin_respuesta_72h",
        }
        assert TIPOS_RESPUESTA_VALIDOS == esperados

    def test_descuento_es_5_porciento(self):
        """El descuento pre-vencimiento debe ser exactamente 5%."""
        assert DESCUENTO_PRE_VENCIMIENTO == 0.05
