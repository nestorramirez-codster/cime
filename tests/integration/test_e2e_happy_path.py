"""
Test E2E del happy path completo — Agente Comercial IA de CIME Power Systems.

Ejecuta el flujo completo de renovación exitosa usando mocks para dependencias
externas (SES, Pipefy API, Tesorería, Memory):

1. POST webhook con payload válido → HTTP 200 con session_id
2. Verificar correo de contacto inicial enviado (mock SES)
3. Simular respuesta de interés del cliente
4. Verificar cotización generada y enviada con datos bancarios correctos
5. Simular envío de comprobante PDF
6. Verificar notificación a Tesorería
7. Verificar que Estado_Pipefy final es "En validación con tesorería"

Validates: Requirements 1.1, 2.1, 3.1, 4.1, 5.1, 5.3, 7.1, 12.6
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from src.agent.flows.comprobante import Adjunto, procesar_comprobante
from src.agent.flows.contacto_inicial import enviar_contacto_inicial
from src.agent.flows.cotizacion import DATOS_BANCARIOS, generar_cotizacion
from src.agent.flows.seguimiento import procesar_respuesta_cliente
from src.agent.session import iniciar_sesion
from src.config.kb_client import KBClient, KBQueryResponse, KBResult
from src.models.constants import DESCUENTO_PRE_VENCIMIENTO, ESTADOS_VALIDOS_PIPEFY
from src.models.data_models import (
    ActivationPayload,
    EmailResult,
    PipelineCard,
    SessionState,
)
from src.webhook.handler import webhook_handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Fecha de vencimiento futura para que aplique descuento pre-vencimiento
FECHA_VENCIMIENTO_FUTURA = date.today() + timedelta(days=30)


def _crear_payload_valido() -> ActivationPayload:
    """Crea un ActivationPayload válido para el happy path."""
    return ActivationPayload(
        poliza_id="POL-2025-001",
        cliente_nombre="Empresa Test S.A. de C.V.",
        cliente_email="contacto@empresa-test.com",
        fecha_vencimiento=FECHA_VENCIMIENTO_FUTURA,
        precio_renovacion=45000.00,
        equipo_nombre="UPS Eaton 9PX 6kVA",
    )


def _crear_pipeline_card(payload: ActivationPayload) -> PipelineCard:
    """Crea un PipelineCard mock que coincide con el payload (sin discrepancias)."""
    return PipelineCard(
        poliza_id=payload.poliza_id,
        estado_actual="Póliza detectada",
        cliente_nombre=payload.cliente_nombre,
        cliente_email=payload.cliente_email,
        fecha_vencimiento=payload.fecha_vencimiento,
        precio_renovacion=payload.precio_renovacion,
        equipo_nombre=payload.equipo_nombre,
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=["Póliza detectada por sistema automático"],
    )


def _crear_email_result_exitoso() -> EmailResult:
    """Crea un EmailResult exitoso mock."""
    return EmailResult(
        success=True,
        message_id="msg-123",
        timestamp=datetime.now(timezone.utc),
    )


def _crear_kb_client_mock() -> MagicMock:
    """Crea un KBClient mock que retorna top_score=0.85."""
    mock_kb = MagicMock(spec=KBClient)
    mock_response = KBQueryResponse(
        results=[
            KBResult(
                content="Contenido mock de KB para happy path",
                score=0.85,
                source_uri="s3://cime-kb/plantillas_mensajes.md",
                metadata={"mock": True},
            )
        ],
        query_text="mock query",
    )
    mock_kb.query.return_value = mock_response
    return mock_kb


# ---------------------------------------------------------------------------
# Test E2E Happy Path
# ---------------------------------------------------------------------------


class TestE2EHappyPath:
    """Test E2E del flujo completo de renovación exitosa."""

    @patch("src.agent.flows.comprobante.notificar_tesoreria")
    @patch("src.agent.flows.comprobante.enviar_correo")
    @patch("src.agent.flows.comprobante.actualizar_pipefy")
    @patch("src.agent.flows.cotizacion.enviar_correo")
    @patch("src.agent.flows.cotizacion.actualizar_pipefy")
    @patch("src.agent.flows.seguimiento.actualizar_pipefy")
    @patch("src.agent.flows.contacto_inicial.enviar_correo")
    @patch("src.agent.flows.contacto_inicial.actualizar_pipefy")
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    @patch("src.agent.session.escalar_humano")
    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    def test_flujo_completo_happy_path(
        self,
        mock_escalar_humano,
        mock_session_consultar_pipefy,
        mock_session_actualizar_pipefy,
        mock_guardar_estado,
        mock_contacto_actualizar_pipefy,
        mock_contacto_enviar_correo,
        mock_seguimiento_actualizar_pipefy,
        mock_cotizacion_actualizar_pipefy,
        mock_cotizacion_enviar_correo,
        mock_comprobante_actualizar_pipefy,
        mock_comprobante_enviar_correo,
        mock_notificar_tesoreria,
    ):
        """Ejecuta el flujo completo: webhook → sesión → contacto → interés → cotización → comprobante."""
        payload = _crear_payload_valido()
        card = _crear_pipeline_card(payload)
        email_result = _crear_email_result_exitoso()
        kb_client = _crear_kb_client_mock()

        # Configurar mocks
        mock_session_consultar_pipefy.return_value = card
        mock_contacto_enviar_correo.return_value = email_result
        mock_cotizacion_enviar_correo.return_value = email_result
        mock_comprobante_enviar_correo.return_value = email_result
        mock_notificar_tesoreria.return_value = True

        # ---------------------------------------------------------------
        # PASO 1: POST webhook con payload válido → HTTP 200 con session_id
        # ---------------------------------------------------------------
        event = {
            "body": json.dumps({
                "poliza_id": payload.poliza_id,
                "cliente_nombre": payload.cliente_nombre,
                "cliente_email": payload.cliente_email,
                "fecha_vencimiento": payload.fecha_vencimiento.isoformat(),
                "precio_renovacion": payload.precio_renovacion,
                "equipo_nombre": payload.equipo_nombre,
            })
        }

        response = webhook_handler(event)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "accepted"
        assert "session_id" in body
        session_id = body["session_id"]
        assert len(session_id) > 0

        # Verificar que iniciar_sesion fue invocado (via webhook mock mode)
        mock_session_consultar_pipefy.assert_called_once_with(payload.poliza_id)
        mock_session_actualizar_pipefy.assert_called_once()
        # Verificar que el estado "Póliza detectada" fue registrado
        session_pipefy_call = mock_session_actualizar_pipefy.call_args
        assert session_pipefy_call[1]["estado"] == "Póliza detectada"

        # ---------------------------------------------------------------
        # PASO 2: Verificar correo de contacto inicial enviado (mock SES)
        # ---------------------------------------------------------------
        # Crear session_state como lo haría iniciar_sesion
        session_state = SessionState(
            session_id=session_id,
            poliza_id=payload.poliza_id,
            estado_pipefy="Póliza detectada",
            historial_mensajes=[],
            timestamp_inicio=datetime.now(timezone.utc),
        )

        resultado_contacto = enviar_contacto_inicial(
            session_state=session_state,
            payload=payload,
            kb_client=kb_client,
        )

        assert resultado_contacto["success"] is True
        assert resultado_contacto["pre_vencimiento"] is True
        assert "message_id" in resultado_contacto

        # Verificar que enviar_correo fue llamado con el email del cliente
        mock_contacto_enviar_correo.assert_called_once()
        email_call_args = mock_contacto_enviar_correo.call_args
        assert email_call_args[1]["destinatario"] == payload.cliente_email

        # Verificar actualización de Pipefy a "Contacto inicial enviado"
        mock_contacto_actualizar_pipefy.assert_called_once()
        contacto_pipefy_call = mock_contacto_actualizar_pipefy.call_args
        assert contacto_pipefy_call[1]["estado"] == "Contacto inicial enviado"

        # ---------------------------------------------------------------
        # PASO 3: Simular respuesta de interés del cliente
        # ---------------------------------------------------------------
        session_state.estado_pipefy = "Contacto inicial enviado"

        resultado_interes = procesar_respuesta_cliente(
            session_state=session_state,
            payload=payload,
            respuesta_tipo="interes",
        )

        assert resultado_interes["success"] is True
        assert resultado_interes["nuevo_estado"] == "Cliente interesado"

        # Verificar actualización Pipefy a "Cliente interesado"
        mock_seguimiento_actualizar_pipefy.assert_called_once()
        interes_pipefy_call = mock_seguimiento_actualizar_pipefy.call_args
        assert interes_pipefy_call[1]["estado"] == "Cliente interesado"

        # ---------------------------------------------------------------
        # PASO 4: Verificar cotización generada y enviada con datos bancarios
        # ---------------------------------------------------------------
        session_state.estado_pipefy = "Cliente interesado"

        resultado_cotizacion = generar_cotizacion(
            session_state=session_state,
            payload=payload,
            kb_client=kb_client,
        )

        assert resultado_cotizacion["success"] is True
        assert resultado_cotizacion["aplica_descuento"] is True
        assert resultado_cotizacion["precio_base"] == payload.precio_renovacion
        # Precio final con 5% descuento
        precio_esperado = round(
            payload.precio_renovacion * (1 - DESCUENTO_PRE_VENCIMIENTO), 2
        )
        assert resultado_cotizacion["precio_final"] == precio_esperado

        # Verificar que el correo de cotización incluye datos bancarios
        mock_cotizacion_enviar_correo.assert_called_once()
        cotizacion_email_call = mock_cotizacion_enviar_correo.call_args
        cuerpo_cotizacion = cotizacion_email_call[1]["cuerpo"]
        assert DATOS_BANCARIOS in cuerpo_cotizacion

        # Verificar actualización Pipefy a "Depósito solicitado"
        mock_cotizacion_actualizar_pipefy.assert_called_once()
        cotizacion_pipefy_call = mock_cotizacion_actualizar_pipefy.call_args
        assert cotizacion_pipefy_call[1]["estado"] == "Depósito solicitado"

        # ---------------------------------------------------------------
        # PASO 5: Simular envío de comprobante PDF
        # ---------------------------------------------------------------
        session_state.estado_pipefy = "Depósito solicitado"

        adjunto = Adjunto(
            nombre_archivo="comprobante_pago.pdf",
            tamanio_bytes=512_000,  # 500 KB
            s3_key="comprobantes/POL-2025-001/comprobante_pago.pdf",
        )

        resultado_comprobante = procesar_comprobante(
            adjunto=adjunto,
            session_state=session_state,
            payload=payload,
        )

        assert resultado_comprobante["success"] is True
        assert resultado_comprobante["formato_valido"] is True
        assert resultado_comprobante["notificacion_tesoreria"] is True
        assert resultado_comprobante["escalado"] is False

        # ---------------------------------------------------------------
        # PASO 6: Verificar notificación a Tesorería
        # ---------------------------------------------------------------
        mock_notificar_tesoreria.assert_called_once()
        tesoreria_call = mock_notificar_tesoreria.call_args[0][0]
        assert tesoreria_call.poliza_id == payload.poliza_id
        assert tesoreria_call.cliente_nombre == payload.cliente_nombre
        assert tesoreria_call.monto == payload.precio_renovacion

        # ---------------------------------------------------------------
        # PASO 7: Verificar estado final "En validación con tesorería"
        # ---------------------------------------------------------------
        # Recopilar todos los estados registrados en Pipefy
        all_pipefy_calls = []

        # Session: "Póliza detectada"
        all_pipefy_calls.append(
            mock_session_actualizar_pipefy.call_args[1]["estado"]
        )
        # Contacto inicial: "Contacto inicial enviado"
        all_pipefy_calls.append(
            mock_contacto_actualizar_pipefy.call_args[1]["estado"]
        )
        # Seguimiento: "Cliente interesado"
        all_pipefy_calls.append(
            mock_seguimiento_actualizar_pipefy.call_args[1]["estado"]
        )
        # Cotización: "Depósito solicitado"
        all_pipefy_calls.append(
            mock_cotizacion_actualizar_pipefy.call_args[1]["estado"]
        )
        # Comprobante: "Comprobante recibido" y "En validación con tesorería"
        comprobante_calls = mock_comprobante_actualizar_pipefy.call_args_list
        for c in comprobante_calls:
            all_pipefy_calls.append(c[1]["estado"])

        # Verificar la progresión completa de estados
        estados_esperados = [
            "Póliza detectada",
            "Contacto inicial enviado",
            "Cliente interesado",
            "Depósito solicitado",
            "Comprobante recibido",
            "En validación con tesorería",
        ]
        assert all_pipefy_calls == estados_esperados

        # Verificar que TODOS los estados son válidos según Pipefy
        for estado in all_pipefy_calls:
            assert estado in ESTADOS_VALIDOS_PIPEFY, (
                f"Estado '{estado}' no es un estado válido de Pipefy"
            )

        # El estado final es "En validación con tesorería"
        assert all_pipefy_calls[-1] == "En validación con tesorería"

        # Verificar que NO se escaló a humano en ningún momento
        mock_escalar_humano.assert_not_called()


# ---------------------------------------------------------------------------
# Test de Performance: Cold Start < 30 segundos (Req 12.6)
# ---------------------------------------------------------------------------


class TestPerformanceColdStart:
    """
    Test de performance que verifica que el cold start del webhook handler
    completa en menos de 30 segundos en modo mock.

    En modo mock (AGENT_EXECUTION_MODE=mock), no hay llamadas de red reales,
    por lo que el tiempo refleja solo el procesamiento local del código.
    En producción, el cold start incluiría inicialización Lambda + boto3.

    Validates: Requirements 12.6
    """

    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    def test_cold_start_menor_a_30_segundos(
        self,
        mock_consultar_pipefy,
        mock_actualizar_pipefy,
        mock_guardar_estado,
    ):
        """
        Mide el tiempo desde la recepción del webhook hasta la respuesta completa.
        Verifica que el cold start total sea < 30 segundos (Req 12.6).
        """
        # Configurar mocks para simular respuestas exitosas
        payload = _crear_payload_valido()
        card = _crear_pipeline_card(payload)
        mock_consultar_pipefy.return_value = card

        # Construir evento HTTP válido
        event = {
            "body": json.dumps({
                "poliza_id": payload.poliza_id,
                "cliente_nombre": payload.cliente_nombre,
                "cliente_email": payload.cliente_email,
                "fecha_vencimiento": payload.fecha_vencimiento.isoformat(),
                "precio_renovacion": payload.precio_renovacion,
                "equipo_nombre": payload.equipo_nombre,
            })
        }

        # --- Medir tiempo de ejecución ---
        start_time = time.perf_counter()
        response = webhook_handler(event)
        end_time = time.perf_counter()

        elapsed_seconds = end_time - start_time

        # --- Verificar respuesta exitosa ---
        assert response["statusCode"] == 200, (
            f"Se esperaba statusCode 200, se obtuvo {response['statusCode']}"
        )
        body = json.loads(response["body"])
        assert body["status"] == "accepted"
        assert "session_id" in body

        # --- Verificar performance: cold start < 30 segundos (Req 12.6) ---
        assert elapsed_seconds < 30.0, (
            f"Cold start excedió el límite de 30 segundos (Req 12.6). "
            f"Tiempo medido: {elapsed_seconds:.3f}s"
        )

        # En modo mock sin I/O real, esperamos < 2 segundos
        # Este assert adicional es una guarda para detectar regresiones
        assert elapsed_seconds < 2.0, (
            f"Cold start en modo mock excedió 2 segundos (regresión de performance). "
            f"Tiempo medido: {elapsed_seconds:.3f}s. "
            f"En modo mock no debería haber latencia de red."
        )
