"""
Tests unitarios para el flujo de escalamiento del Agente Comercial IA.

Valida la detección de triggers de escalamiento y la ejecución
de las acciones post-escalamiento (escalar_humano, correo, Pipefy).

Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 6.9
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

# Configurar modo mock antes de importar módulos
os.environ["CIME_MOCK_MODE"] = "true"

from src.agent.flows.escalamiento import (
    _requiere_asesor_humano,
    _requiere_atencion_personalizada,
    _requiere_facturacion,
    _requiere_negociacion_especial,
    _requiere_soporte_tecnico,
    evaluar_escalamiento,
)
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.data_models import (
    ActivationPayload,
    Mensaje,
    SessionState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def payload():
    """ActivationPayload de prueba."""
    return ActivationPayload(
        poliza_id="POL-001",
        cliente_nombre="Empresa Test S.A.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=date(2025, 8, 15),
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


@pytest.fixture
def session_state():
    """SessionState de prueba con historial mínimo."""
    return SessionState(
        session_id="session-test-001",
        poliza_id="POL-001",
        estado_pipefy="Seguimiento en curso",
        historial_mensajes=[
            Mensaje(
                timestamp=datetime(2025, 7, 1, 10, 0, tzinfo=timezone.utc),
                remitente="agente",
                contenido="Buen día, le contactamos por la renovación.",
                tipo="contacto_inicial",
            ),
            Mensaje(
                timestamp=datetime(2025, 7, 1, 11, 0, tzinfo=timezone.utc),
                remitente="cliente",
                contenido="Hola, tengo dudas.",
                tipo="respuesta_cliente",
            ),
        ],
        timestamp_inicio=datetime(2025, 7, 1, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def kb_client_alta_score():
    """KBClient mock que retorna score alto (≥ 0.70)."""
    client = MagicMock(spec=KBClient)
    response = KBQueryResponse(
        results=[
            KBResult(
                content="Respuesta técnica detallada",
                score=0.85,
                source_uri="s3://bucket/doc.md",
            )
        ],
        query_text="consulta técnica",
    )
    client.query.return_value = response
    return client


@pytest.fixture
def kb_client_baja_score():
    """KBClient mock que retorna score bajo (< 0.70)."""
    client = MagicMock(spec=KBClient)
    response = KBQueryResponse(
        results=[
            KBResult(
                content="Resultado irrelevante",
                score=0.45,
                source_uri="s3://bucket/doc.md",
            )
        ],
        query_text="consulta técnica",
    )
    client.query.return_value = response
    return client


# ---------------------------------------------------------------------------
# Tests de funciones de detección de triggers
# ---------------------------------------------------------------------------


class TestRequiereAsesorHumano:
    """Tests para _requiere_asesor_humano (Req 6.1)."""

    def test_detecta_keyword_asesor(self):
        assert _requiere_asesor_humano("Quiero hablar con un asesor") is True

    def test_detecta_keyword_humano(self):
        assert _requiere_asesor_humano("Necesito un humano") is True

    def test_detecta_keyword_persona(self):
        assert _requiere_asesor_humano("Quiero hablar con una persona") is True

    def test_detecta_frase_hablar_con_alguien(self):
        assert _requiere_asesor_humano("Necesito hablar con alguien real") is True

    def test_no_detecta_sin_keywords(self):
        assert _requiere_asesor_humano("Quiero renovar mi póliza") is False

    def test_case_insensitive(self):
        assert _requiere_asesor_humano("QUIERO UN ASESOR") is True


class TestRequiereNegociacionEspecial:
    """Tests para _requiere_negociacion_especial (Req 6.3)."""

    def test_detecta_descuento_diferente_5(self):
        assert _requiere_negociacion_especial("Necesito un descuento del 10%") is True

    def test_detecta_plazo_diferido(self):
        assert _requiere_negociacion_especial("Puedo pagar en plazo diferido?") is True

    def test_detecta_extension(self):
        assert _requiere_negociacion_especial("Quiero una extensión de cobertura") is True

    def test_detecta_condiciones_especiales(self):
        assert _requiere_negociacion_especial("Necesito condiciones especial") is True

    def test_no_escala_descuento_5_porciento(self):
        """Solo mencionar 5% no debe escalar (es el descuento estándar)."""
        assert _requiere_negociacion_especial("Aplicar el descuento del 5%") is False

    def test_no_detecta_sin_keywords(self):
        assert _requiere_negociacion_especial("Quiero renovar normalmente") is False

    def test_escala_descuento_otro_porcentaje(self):
        assert _requiere_negociacion_especial("Quiero descuento del 20%") is True


class TestRequiereFacturacion:
    """Tests para _requiere_facturacion (Req 6.4)."""

    def test_detecta_factura(self):
        assert _requiere_facturacion("Necesito factura") is True

    def test_detecta_rfc(self):
        assert _requiere_facturacion("Mi RFC es ABC123456") is True

    def test_detecta_datos_fiscales(self):
        assert _requiere_facturacion("Necesito los datos fiscales") is True

    def test_detecta_cfdi(self):
        assert _requiere_facturacion("Requiero CFDI") is True

    def test_detecta_fiscal(self):
        assert _requiere_facturacion("Necesito información fiscal") is True

    def test_no_detecta_sin_keywords(self):
        assert _requiere_facturacion("Quiero renovar mi póliza") is False


class TestRequiereAtencionPersonalizada:
    """Tests para _requiere_atencion_personalizada (Req 6.5)."""

    def test_detecta_queja(self):
        assert _requiere_atencion_personalizada("Tengo una queja") is True

    def test_detecta_inconformidad(self):
        assert _requiere_atencion_personalizada("Estoy en inconformidad") is True

    def test_detecta_molesto(self):
        assert _requiere_atencion_personalizada("Estoy molesto con el servicio") is True

    def test_detecta_insatisfecho(self):
        assert _requiere_atencion_personalizada("Me siento insatisfecho") is True

    def test_detecta_reclamo(self):
        assert _requiere_atencion_personalizada("Quiero poner un reclamo") is True

    def test_no_detecta_sin_keywords(self):
        assert _requiere_atencion_personalizada("Todo bien, gracias") is False


class TestRequiereSoporteTecnico:
    """Tests para _requiere_soporte_tecnico (Req 6.6)."""

    def test_kb_score_bajo_escala(self, kb_client_baja_score):
        """Si KB score < 0.70, la duda no está respondida → escalar."""
        assert _requiere_soporte_tecnico(
            "¿Cómo calibro el UPS?", kb_client_baja_score
        ) is True

    def test_kb_score_alto_no_escala(self, kb_client_alta_score):
        """Si KB score ≥ 0.70, la duda está respondida → no escalar."""
        assert _requiere_soporte_tecnico(
            "¿Cuáles son las reglas comerciales?", kb_client_alta_score
        ) is False

    def test_kb_no_disponible_escala(self):
        """Si kb_client es None, asumir que no se puede responder → escalar."""
        assert _requiere_soporte_tecnico("¿Cómo funciona el equipo?", None) is True

    def test_kb_error_escala(self):
        """Si KB lanza excepción, escalar por precaución."""
        client = MagicMock(spec=KBClient)
        client.query.side_effect = RuntimeError("KB no disponible")
        assert _requiere_soporte_tecnico("Pregunta técnica", client) is True


# ---------------------------------------------------------------------------
# Tests de evaluar_escalamiento (función principal)
# ---------------------------------------------------------------------------


class TestEvaluarEscalamiento:
    """Tests para evaluar_escalamiento — orquestación completa."""

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_asesor_humano_escala_inmediato(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Req 6.1: Solicitud de asesor → escalamiento inmediato."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="Quiero hablar con un asesor por favor",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["escalado"] is True
        assert resultado["trigger"] == "asesor_humano"
        mock_escalar.assert_called_once()
        # Verificar que el motivo es descriptivo
        call_args = mock_escalar.call_args
        assert "asesor humano" in call_args.kwargs.get("motivo", call_args[1].get("motivo", ""))

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_negociacion_especial_escala(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Req 6.3: Negociación especial → escalamiento."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="Necesito un descuento del 15% por favor",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["escalado"] is True
        assert resultado["trigger"] == "negociacion_especial"
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_facturacion_escala(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Req 6.4: Solicitud de facturación → escalamiento."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="Necesito mi factura con CFDI",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["escalado"] is True
        assert resultado["trigger"] == "facturacion"
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_inconformidad_escala(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Req 6.5: Inconformidad o queja → escalamiento."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="Estoy muy molesto con el servicio, quiero poner una queja",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["escalado"] is True
        assert resultado["trigger"] == "atencion_personalizada"
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_soporte_tecnico_kb_baja_escala(
        self,
        mock_escalar,
        mock_correo,
        mock_pipefy,
        session_state,
        payload,
        kb_client_baja_score,
    ):
        """Req 6.6: Duda técnica sin respuesta en KB → escalamiento."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="¿Cómo calibro el voltaje del UPS manualmente?",
            session_state=session_state,
            payload=payload,
            kb_client=kb_client_baja_score,
        )

        assert resultado["escalado"] is True
        assert resultado["trigger"] == "soporte_tecnico"
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_soporte_tecnico_kb_alta_no_escala(
        self,
        mock_escalar,
        mock_correo,
        mock_pipefy,
        session_state,
        payload,
        kb_client_alta_score,
    ):
        """Req 6.6: Duda técnica respondida en KB → NO escalar."""
        resultado = evaluar_escalamiento(
            mensaje_cliente="¿Cuáles son las reglas comerciales de renovación?",
            session_state=session_state,
            payload=payload,
            kb_client=kb_client_alta_score,
        )

        assert resultado["escalado"] is False
        assert resultado["trigger"] == "ninguno"
        mock_escalar.assert_not_called()

    def test_mensaje_vacio_no_escala(self, session_state, payload):
        """Mensaje vacío no debe escalar."""
        resultado = evaluar_escalamiento(
            mensaje_cliente="",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["escalado"] is False
        assert resultado["trigger"] == "ninguno"

    def test_mensaje_normal_no_escala(
        self, session_state, payload, kb_client_alta_score
    ):
        """Mensaje sin trigger no debe escalar."""
        resultado = evaluar_escalamiento(
            mensaje_cliente="Sí, me interesa renovar la póliza",
            session_state=session_state,
            payload=payload,
            kb_client=kb_client_alta_score,
        )

        assert resultado["escalado"] is False
        assert resultado["trigger"] == "ninguno"

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_correo_confirmacion_enviado(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Req 6.2: Tras escalar, se envía correo de confirmación al cliente."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="Necesito hablar con una persona",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["email_confirmacion_enviado"] is True
        mock_correo.assert_called_once()
        # Verificar que el cuerpo menciona 24 horas hábiles
        call_args = mock_correo.call_args
        cuerpo = call_args.kwargs.get("cuerpo", call_args[1].get("cuerpo", ""))
        assert "24 horas hábiles" in cuerpo

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_pipefy_actualizado_escalado_humano(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Req 6.9: Tras escalar, Pipefy se actualiza a 'Escalado a humano'."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="Quiero hablar con un asesor",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["pipefy_actualizado"] is True
        mock_pipefy.assert_called_once()
        call_args = mock_pipefy.call_args
        assert call_args.kwargs.get("estado", call_args[1].get("estado", "")) == "Escalado a humano"

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_memory_no_disponible_incluye_payload(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Req 6.8: Si Memory no disponible, incluir datos del payload."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="Quiero un asesor humano",
            session_state=session_state,
            payload=payload,
            memory_disponible=False,
        )

        assert resultado["escalado"] is True
        # escalar_humano debe recibir datos_poliza con datos del payload
        call_args = mock_escalar.call_args
        datos_poliza = call_args.kwargs.get("datos_poliza")
        assert datos_poliza.poliza_id == payload.poliza_id
        assert datos_poliza.cliente_nombre == payload.cliente_nombre
        assert datos_poliza.cliente_email == payload.cliente_email

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_prioridad_asesor_sobre_otros_triggers(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """El trigger de asesor humano tiene prioridad sobre otros."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        # Mensaje con múltiples triggers: asesor + queja
        resultado = evaluar_escalamiento(
            mensaje_cliente="Estoy molesto, quiero hablar con un asesor",
            session_state=session_state,
            payload=payload,
        )

        # Debe escalar por asesor_humano (prioridad más alta)
        assert resultado["trigger"] == "asesor_humano"

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_correo_falla_no_bloquea_escalamiento(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Si el correo de confirmación falla, el escalamiento continúa."""
        mock_correo.side_effect = Exception("SES no disponible")
        mock_pipefy.return_value = True

        resultado = evaluar_escalamiento(
            mensaje_cliente="Necesito hablar con un asesor",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["escalado"] is True
        assert resultado["email_confirmacion_enviado"] is False
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_pipefy_falla_no_bloquea_escalamiento(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Si Pipefy falla, el escalamiento continúa."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.side_effect = Exception("Pipefy timeout")

        resultado = evaluar_escalamiento(
            mensaje_cliente="Quiero un asesor humano",
            session_state=session_state,
            payload=payload,
        )

        assert resultado["escalado"] is True
        assert resultado["pipefy_actualizado"] is False
        mock_escalar.assert_called_once()

    @patch("src.agent.flows.escalamiento.actualizar_pipefy")
    @patch("src.agent.flows.escalamiento.enviar_correo")
    @patch("src.agent.flows.escalamiento.escalar_humano")
    def test_historial_incluido_en_escalamiento(
        self, mock_escalar, mock_correo, mock_pipefy, session_state, payload
    ):
        """Req 6.9: El historial completo debe incluirse en escalar_humano."""
        mock_correo.return_value = MagicMock(success=True)
        mock_pipefy.return_value = True

        evaluar_escalamiento(
            mensaje_cliente="Quiero hablar con una persona",
            session_state=session_state,
            payload=payload,
        )

        call_args = mock_escalar.call_args
        historial = call_args.kwargs.get("historial")
        assert len(historial) == 2  # 2 mensajes en el fixture
        assert historial[0].remitente == "agente"
        assert historial[1].remitente == "cliente"
