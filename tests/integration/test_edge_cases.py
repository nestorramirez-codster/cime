"""
Tests de casos de borde críticos — Agente Comercial IA de CIME Power Systems.

Verifica comportamientos en condiciones límite y errores:
1. Payload con correo inválido → HTTP 400 sin crear sesión
2. Estado Pipefy bloqueante → sesión termina sin acción
3. KB con score < 0.70 → escalamiento inmediato
4. Discrepancia de datos entre payload y Pipefy → escalamiento sin enviar correo
5. Comprobante con formato no soportado (.doc) → solicitud de reenvío
6. Comprobante de 10 MB + 1 byte → solicitud de reenvío

Validates: Requirements 1.5, 1.6, 2.7, 5.6, 6.7, 11.2
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.agent.flows.comprobante import Adjunto, procesar_comprobante
from src.agent.flows.contacto_inicial import enviar_contacto_inicial
from src.agent.session import iniciar_sesion
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.constants import (
    FORMATOS_COMPROBANTE_ACEPTADOS,
    TAMANIO_MAXIMO_COMPROBANTE_BYTES,
)
from src.models.data_models import (
    ActivationPayload,
    EmailResult,
    PipelineCard,
    SessionState,
)
from src.webhook.handler import webhook_handler


# ---------------------------------------------------------------------------
# Fixtures compartidos
# ---------------------------------------------------------------------------

FECHA_VENCIMIENTO_FUTURA = date.today() + timedelta(days=30)


def _payload_valido() -> ActivationPayload:
    """Crea un ActivationPayload válido base para los tests."""
    return ActivationPayload(
        poliza_id="POL-EDGE-001",
        cliente_nombre="Empresa Edge S.A.",
        cliente_email="contacto@empresa-edge.com",
        fecha_vencimiento=FECHA_VENCIMIENTO_FUTURA,
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


def _pipeline_card(payload: ActivationPayload, **overrides) -> PipelineCard:
    """Crea un PipelineCard que coincide con el payload, con overrides opcionales."""
    defaults = dict(
        poliza_id=payload.poliza_id,
        estado_actual="Póliza detectada",
        cliente_nombre=payload.cliente_nombre,
        cliente_email=payload.cliente_email,
        fecha_vencimiento=payload.fecha_vencimiento,
        precio_renovacion=payload.precio_renovacion,
        equipo_nombre=payload.equipo_nombre,
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=[],
    )
    defaults.update(overrides)
    return PipelineCard(**defaults)


def _session_state(session_id: str = "sess-edge-001", poliza_id: str = "POL-EDGE-001") -> SessionState:
    """Crea un SessionState base para tests."""
    return SessionState(
        session_id=session_id,
        poliza_id=poliza_id,
        estado_pipefy="Póliza detectada",
        historial_mensajes=[],
        timestamp_inicio=datetime.now(timezone.utc),
    )


def _email_result_exitoso() -> EmailResult:
    return EmailResult(
        success=True,
        message_id="msg-edge-001",
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Tests de Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests de casos de borde críticos del Agente Comercial."""

    # -------------------------------------------------------------------
    # 1. Payload con correo inválido → HTTP 400 sin crear sesión
    # Validates: Requirements 1.5, 2.7
    # -------------------------------------------------------------------
    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    def test_email_invalido_retorna_400_sin_sesion(self):
        """POST webhook con email 'no-es-email' retorna HTTP 400 sin crear sesión."""
        event = {
            "body": json.dumps({
                "poliza_id": "POL-EDGE-001",
                "cliente_nombre": "Empresa Edge S.A.",
                "cliente_email": "no-es-email",
                "fecha_vencimiento": FECHA_VENCIMIENTO_FUTURA.isoformat(),
                "precio_renovacion": 45000.00,
                "equipo_nombre": "UPS Eaton 9PX 6kVA",
            })
        }

        response = webhook_handler(event)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["status"] == "error"
        assert body["error"] == "validation_error"
        assert "cliente_email" in body["details"]["campos_invalidos"]

    # -------------------------------------------------------------------
    # 2. Estado Pipefy bloqueante → sesión termina sin acción
    # Validates: Requirements 1.6
    # -------------------------------------------------------------------
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    @patch("src.agent.session.escalar_humano")
    def test_estado_bloqueante_termina_sin_accion(
        self,
        mock_escalar_humano,
        mock_consultar_pipefy,
        mock_actualizar_pipefy,
        mock_guardar_estado,
    ):
        """Estado 'Renovación confirmada' (bloqueante) termina sesión sin acción."""
        payload = _payload_valido()
        card = _pipeline_card(payload, estado_actual="Renovación confirmada")
        mock_consultar_pipefy.return_value = card

        resultado = iniciar_sesion(payload, "sess-bloqueante-001")

        assert resultado["success"] is False
        assert resultado["reason"] == "estado_bloqueante"
        # No se envía correo (actualizar_pipefy no se llama para avanzar estado)
        mock_actualizar_pipefy.assert_not_called()
        # No se escala a humano
        mock_escalar_humano.assert_not_called()
        # No se guarda estado en memory
        mock_guardar_estado.assert_not_called()

    # -------------------------------------------------------------------
    # 3. KB con score < 0.70 → escalamiento inmediato
    # Validates: Requirements 11.2
    # -------------------------------------------------------------------
    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    @patch("src.agent.flows.contacto_inicial.escalar_humano")
    def test_kb_score_bajo_escala_humano(
        self,
        mock_escalar_humano,
        mock_enviar_correo,
        mock_actualizar_pipefy,
    ):
        """KB con top_score=0.50 (<0.70) causa escalamiento inmediato."""
        payload = _payload_valido()
        session_state = _session_state()

        # Mock KB con score bajo
        mock_kb = MagicMock(spec=KBClient)
        mock_response = KBQueryResponse(
            results=[
                KBResult(
                    content="Contenido irrelevante",
                    score=0.50,
                    source_uri="s3://cime-kb/doc.md",
                    metadata={},
                )
            ],
            query_text="plantilla mensaje correo contacto inicial",
        )
        mock_kb.query.return_value = mock_response

        resultado = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload,
            kb_client=mock_kb,
        )

        assert resultado["success"] is False
        # Verificar que se escaló a humano con motivo que mencione "score"
        mock_escalar_humano.assert_called_once()
        motivo_escalamiento = mock_escalar_humano.call_args[1]["motivo"]
        assert "score" in motivo_escalamiento.lower()
        # No se envía correo al cliente
        mock_enviar_correo.assert_not_called()
        # No se actualiza Pipefy
        mock_actualizar_pipefy.assert_not_called()

    # -------------------------------------------------------------------
    # 4. Discrepancia de datos entre payload y Pipefy → escalamiento
    # Validates: Requirements 6.7
    # -------------------------------------------------------------------
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    @patch("src.agent.session.escalar_humano")
    def test_discrepancia_datos_escala_sin_enviar_correo(
        self,
        mock_escalar_humano,
        mock_consultar_pipefy,
        mock_actualizar_pipefy,
        mock_guardar_estado,
    ):
        """Discrepancia de precio >1% escala a humano sin enviar correo."""
        payload = _payload_valido()  # precio_renovacion=45000
        # Pipefy tiene un precio diferente (>1% diferencia)
        card = _pipeline_card(payload, precio_renovacion=50000.00)
        mock_consultar_pipefy.return_value = card

        resultado = iniciar_sesion(payload, "sess-discrepancia-001")

        assert resultado["success"] is False
        assert resultado["reason"] == "discrepancia_datos"
        # Se escaló a humano
        mock_escalar_humano.assert_called_once()
        # No se actualizó Pipefy (no se avanzó de estado)
        mock_actualizar_pipefy.assert_not_called()
        # No se guardó estado en memory
        mock_guardar_estado.assert_not_called()

    # -------------------------------------------------------------------
    # 5. Comprobante con formato no soportado (.doc) → solicitud de reenvío
    # Validates: Requirements 5.6
    # -------------------------------------------------------------------
    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_comprobante_formato_no_soportado_solicita_reenvio(
        self,
        mock_enviar_correo,
        mock_actualizar_pipefy,
        mock_notificar_tesoreria,
    ):
        """Comprobante .doc solicita reenvío con formatos aceptados listados."""
        payload = _payload_valido()
        session_state = _session_state()
        mock_enviar_correo.return_value = _email_result_exitoso()

        adjunto = Adjunto(
            nombre_archivo="documento.doc",
            tamanio_bytes=1000,
            s3_key="comprobantes/POL-EDGE-001/documento.doc",
        )

        resultado = procesar_comprobante(
            adjunto=adjunto,
            session_state=session_state,
            payload=payload,
        )

        assert resultado["success"] is False
        assert resultado["formato_valido"] is False
        # Se envió correo de solicitud de reenvío
        mock_enviar_correo.assert_called_once()
        cuerpo_correo = mock_enviar_correo.call_args[1]["cuerpo"]
        # El correo lista los formatos aceptados
        for formato in FORMATOS_COMPROBANTE_ACEPTADOS:
            assert formato in cuerpo_correo
        # No se notificó a tesorería
        mock_notificar_tesoreria.assert_not_called()
        # No se actualizó Pipefy
        mock_actualizar_pipefy.assert_not_called()

    # -------------------------------------------------------------------
    # 6. Comprobante de 10 MB + 1 byte → solicitud de reenvío
    # Validates: Requirements 5.6
    # -------------------------------------------------------------------
    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.comprobante.enviar_correo")
    def test_comprobante_excede_tamanio_maximo_solicita_reenvio(
        self,
        mock_enviar_correo,
        mock_actualizar_pipefy,
        mock_notificar_tesoreria,
    ):
        """Comprobante PDF de 10MB+1 byte solicita reenvío por exceder tamaño."""
        payload = _payload_valido()
        session_state = _session_state()
        mock_enviar_correo.return_value = _email_result_exitoso()

        adjunto = Adjunto(
            nombre_archivo="comprobante.pdf",
            tamanio_bytes=TAMANIO_MAXIMO_COMPROBANTE_BYTES + 1,  # 10 MB + 1 byte
            s3_key="comprobantes/POL-EDGE-001/comprobante.pdf",
        )

        resultado = procesar_comprobante(
            adjunto=adjunto,
            session_state=session_state,
            payload=payload,
        )

        assert resultado["success"] is False
        assert resultado["formato_valido"] is False
        # Se envió correo de solicitud de reenvío
        mock_enviar_correo.assert_called_once()
        cuerpo_correo = mock_enviar_correo.call_args[1]["cuerpo"]
        # El correo menciona el tamaño máximo
        assert "10" in cuerpo_correo  # 10 MB
        # No se notificó a tesorería
        mock_notificar_tesoreria.assert_not_called()
        # No se actualizó Pipefy
        mock_actualizar_pipefy.assert_not_called()
