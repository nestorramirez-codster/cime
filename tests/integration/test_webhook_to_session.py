"""
Test de integración: webhook Zapier → sesión AgentCore.

Verifica el flujo completo desde la recepción del HTTP POST del webhook
hasta la creación de una sesión en AgentCore con session_id retornado,
así como el rechazo correcto de payloads inválidos.

Validates: Requirements 1.1, 1.2, 1.3
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.models.data_models import PipelineCard
from src.webhook.handler import webhook_handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FECHA_VENCIMIENTO_FUTURA = date.today() + timedelta(days=30)


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch):
    """Configura el entorno en modo mock para todas las pruebas."""
    monkeypatch.setenv("CIME_MOCK_MODE", "true")
    monkeypatch.setenv("AGENT_EXECUTION_MODE", "mock")


@pytest.fixture
def payload_valido() -> dict:
    """Payload HTTP válido que simula el POST de Zapier."""
    return {
        "poliza_id": "POL-2025-INT-001",
        "cliente_nombre": "Integración Test S.A. de C.V.",
        "cliente_email": "integracion@empresa-test.com",
        "fecha_vencimiento": FECHA_VENCIMIENTO_FUTURA.isoformat(),
        "precio_renovacion": 52000.00,
        "equipo_nombre": "UPS Eaton 9PX 10kVA",
    }


@pytest.fixture
def evento_http_valido(payload_valido: dict) -> dict:
    """Evento HTTP (Lambda proxy integration) con payload válido."""
    return {
        "body": json.dumps(payload_valido),
        "httpMethod": "POST",
        "path": "/webhook/activate",
    }


@pytest.fixture
def pipeline_card_compatible(payload_valido: dict) -> PipelineCard:
    """PipelineCard que coincide con el payload (sin discrepancias)."""
    return PipelineCard(
        poliza_id=payload_valido["poliza_id"],
        estado_actual="Póliza detectada",
        cliente_nombre=payload_valido["cliente_nombre"],
        cliente_email=payload_valido["cliente_email"],
        fecha_vencimiento=FECHA_VENCIMIENTO_FUTURA,
        precio_renovacion=payload_valido["precio_renovacion"],
        equipo_nombre=payload_valido["equipo_nombre"],
        timestamp_ultima_actualizacion=datetime.now(timezone.utc),
        notas=[],
    )


# ---------------------------------------------------------------------------
# Test: Payload válido → HTTP 200 con session_id (integración webhook→sesión)
# ---------------------------------------------------------------------------


class TestWebhookToSessionValid:
    """
    Verifica que un HTTP POST con payload válido crea una sesión
    en AgentCore con session_id retornado.

    Validates: Requirements 1.1, 1.2
    """

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    @patch("src.agent.session.escalar_humano")
    def test_payload_valido_crea_sesion_con_session_id(
        self,
        mock_escalar: MagicMock,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        evento_http_valido: dict,
        pipeline_card_compatible: PipelineCard,
    ):
        """
        POST con payload válido → statusCode=200,
        body contiene status="accepted" y session_id UUID válido.
        La sesión se inicia correctamente en AgentCore (mock).
        """
        mock_consultar.return_value = pipeline_card_compatible
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        # Ejecutar el webhook completo (integración handler → session)
        response = webhook_handler(evento_http_valido)

        # Verificar respuesta HTTP
        assert response["statusCode"] == 200
        assert response["headers"]["Content-Type"] == "application/json"

        body = json.loads(response["body"])
        assert body["status"] == "accepted"
        assert "session_id" in body

        # Verificar que session_id es un UUID4 válido
        session_id = body["session_id"]
        parsed_uuid = uuid.UUID(session_id, version=4)
        assert str(parsed_uuid) == session_id

        # Verificar que se consultó Pipefy (integración con session.py)
        mock_consultar.assert_called_once_with("POL-2025-INT-001")

        # Verificar que se actualizó Pipefy a "Póliza detectada"
        mock_actualizar.assert_called_once()
        call_kwargs = mock_actualizar.call_args[1]
        assert call_kwargs["estado"] == "Póliza detectada"
        assert call_kwargs["poliza_id"] == "POL-2025-INT-001"

        # Verificar que se persistió el estado de sesión en Memory
        mock_guardar.assert_called_once()
        session_state_guardado = mock_guardar.call_args[0][0]
        assert session_state_guardado.session_id == session_id
        assert session_state_guardado.poliza_id == "POL-2025-INT-001"
        assert session_state_guardado.estado_pipefy == "Póliza detectada"

        # No se escaló a humano
        mock_escalar.assert_not_called()

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    @patch("src.agent.session.escalar_humano")
    def test_session_id_es_unico_por_cada_invocacion(
        self,
        mock_escalar: MagicMock,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        evento_http_valido: dict,
        pipeline_card_compatible: PipelineCard,
    ):
        """
        Cada invocación del webhook genera un session_id distinto.
        """
        mock_consultar.return_value = pipeline_card_compatible
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        response_1 = webhook_handler(evento_http_valido)
        response_2 = webhook_handler(evento_http_valido)

        body_1 = json.loads(response_1["body"])
        body_2 = json.loads(response_2["body"])

        assert body_1["session_id"] != body_2["session_id"]


# ---------------------------------------------------------------------------
# Test: Payload inválido → HTTP 400 sin crear sesión
# ---------------------------------------------------------------------------


class TestWebhookToSessionInvalid:
    """
    Verifica que un POST con payload inválido retorna HTTP 400
    sin crear sesión en AgentCore.

    Validates: Requirements 1.2, 1.3
    """

    def test_email_invalido_retorna_400_sin_crear_sesion(self):
        """
        Email con formato inválido → statusCode=400, error="validation_error".
        No se crea sesión ni se consulta/actualiza Pipefy.
        """
        payload_email_invalido = {
            "poliza_id": "POL-2025-INT-002",
            "cliente_nombre": "Empresa Inválida S.A.",
            "cliente_email": "no-es-un-email-valido",
            "fecha_vencimiento": FECHA_VENCIMIENTO_FUTURA.isoformat(),
            "precio_renovacion": 30000.00,
            "equipo_nombre": "Generador CAT 500kW",
        }
        evento = {"body": json.dumps(payload_email_invalido)}

        response = webhook_handler(evento)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["status"] == "error"
        assert body["error"] == "validation_error"
        assert "cliente_email" in body["details"]["campos_invalidos"]
        # No debe haber session_id en la respuesta
        assert "session_id" not in body

    def test_campo_requerido_faltante_retorna_400(self):
        """
        Payload sin campo obligatorio (poliza_id vacío) → statusCode=400.
        """
        payload_sin_poliza = {
            "poliza_id": "",
            "cliente_nombre": "Empresa Test",
            "cliente_email": "test@empresa.com",
            "fecha_vencimiento": FECHA_VENCIMIENTO_FUTURA.isoformat(),
            "precio_renovacion": 25000.00,
            "equipo_nombre": "UPS APC 3kVA",
        }
        evento = {"body": json.dumps(payload_sin_poliza)}

        response = webhook_handler(evento)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["status"] == "error"
        assert body["error"] == "validation_error"
        assert "poliza_id" in body["details"]["campos_invalidos"]

    def test_precio_renovacion_cero_retorna_400(self):
        """
        precio_renovacion = 0 (debe ser > 0) → statusCode=400.
        """
        payload_precio_cero = {
            "poliza_id": "POL-2025-INT-003",
            "cliente_nombre": "Empresa Precio Cero",
            "cliente_email": "precio@empresa.com",
            "fecha_vencimiento": FECHA_VENCIMIENTO_FUTURA.isoformat(),
            "precio_renovacion": 0,
            "equipo_nombre": "Transformador 100kVA",
        }
        evento = {"body": json.dumps(payload_precio_cero)}

        response = webhook_handler(evento)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["status"] == "error"
        assert body["error"] == "validation_error"
        assert "precio_renovacion" in body["details"]["campos_invalidos"]

    def test_precio_renovacion_negativo_retorna_400(self):
        """
        precio_renovacion < 0 → statusCode=400.
        """
        payload_precio_negativo = {
            "poliza_id": "POL-2025-INT-004",
            "cliente_nombre": "Empresa Negativo",
            "cliente_email": "negativo@empresa.com",
            "fecha_vencimiento": FECHA_VENCIMIENTO_FUTURA.isoformat(),
            "precio_renovacion": -5000.00,
            "equipo_nombre": "Motor Eléctrico 50HP",
        }
        evento = {"body": json.dumps(payload_precio_negativo)}

        response = webhook_handler(evento)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["status"] == "error"
        assert body["error"] == "validation_error"
        assert "precio_renovacion" in body["details"]["campos_invalidos"]

    def test_multiples_campos_invalidos_reportados(self):
        """
        Payload con múltiples campos inválidos → todos reportados en la respuesta.
        """
        payload_todo_invalido = {
            "poliza_id": "",
            "cliente_nombre": "",
            "cliente_email": "invalido",
            "fecha_vencimiento": FECHA_VENCIMIENTO_FUTURA.isoformat(),
            "precio_renovacion": -1,
            "equipo_nombre": "",
        }
        evento = {"body": json.dumps(payload_todo_invalido)}

        response = webhook_handler(evento)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        campos_invalidos = body["details"]["campos_invalidos"]
        # Debe reportar al menos poliza_id, cliente_nombre, cliente_email,
        # precio_renovacion y equipo_nombre
        assert "poliza_id" in campos_invalidos
        assert "cliente_nombre" in campos_invalidos
        assert "cliente_email" in campos_invalidos
        assert "precio_renovacion" in campos_invalidos
        assert "equipo_nombre" in campos_invalidos
