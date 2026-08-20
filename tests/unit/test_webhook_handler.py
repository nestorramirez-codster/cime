"""
Tests unitarios para src/webhook/handler.py — Webhook de activación Zapier.

Cubre:
- POST con payload válido → HTTP 200 con {"status": "accepted", "session_id": "..."}
- POST con payload inválido → HTTP 400 con error de validación
- POST con body no parseable → HTTP 400 con error de parsing
- Invocación del AgentCore Runtime (mock) con session_id generado
- Respuesta retornada en formato compatible con API Gateway Lambda proxy

Requisitos: 1.1, 12.6
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.webhook.handler import (
    _extraer_body,
    _parsear_payload,
    _respuesta_error,
    _respuesta_exitosa,
    webhook_handler,
)
from src.models.data_models import ActivationPayload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def body_valido() -> dict:
    """Body JSON válido que simula el POST de Zapier."""
    return {
        "poliza_id": "POL-2024-001",
        "cliente_nombre": "Empresa Test S.A.",
        "cliente_email": "contacto@empresa-test.com",
        "fecha_vencimiento": "2025-08-15",
        "precio_renovacion": 45000.00,
        "equipo_nombre": "UPS Eaton 9PX 6kVA",
    }


@pytest.fixture
def body_invalido_email() -> dict:
    """Body con email inválido."""
    return {
        "poliza_id": "POL-2024-001",
        "cliente_nombre": "Empresa Test S.A.",
        "cliente_email": "no-es-email",
        "fecha_vencimiento": "2025-08-15",
        "precio_renovacion": 45000.00,
        "equipo_nombre": "UPS Eaton 9PX 6kVA",
    }


@pytest.fixture
def body_invalido_precio_cero() -> dict:
    """Body con precio = 0 (inválido, debe ser > 0)."""
    return {
        "poliza_id": "POL-2024-001",
        "cliente_nombre": "Empresa Test S.A.",
        "cliente_email": "contacto@empresa-test.com",
        "fecha_vencimiento": "2025-08-15",
        "precio_renovacion": 0,
        "equipo_nombre": "UPS Eaton 9PX 6kVA",
    }


@pytest.fixture
def body_campos_vacios() -> dict:
    """Body con campos vacíos."""
    return {
        "poliza_id": "",
        "cliente_nombre": "",
        "cliente_email": "",
        "fecha_vencimiento": "",
        "precio_renovacion": 0,
        "equipo_nombre": "",
    }


@pytest.fixture
def evento_lambda_valido(body_valido: dict) -> dict:
    """Evento Lambda proxy integration con body válido."""
    return {
        "body": json.dumps(body_valido),
        "httpMethod": "POST",
        "path": "/webhook/activate",
    }


@pytest.fixture
def evento_lambda_invalido(body_invalido_email: dict) -> dict:
    """Evento Lambda proxy integration con body inválido."""
    return {
        "body": json.dumps(body_invalido_email),
        "httpMethod": "POST",
        "path": "/webhook/activate",
    }


# ---------------------------------------------------------------------------
# Tests: _extraer_body
# ---------------------------------------------------------------------------


class TestExtraerBody:
    """Tests para la extracción del body del evento HTTP."""

    def test_body_como_string_json(self, body_valido: dict):
        """Body como string JSON (Lambda proxy integration)."""
        event = {"body": json.dumps(body_valido)}
        resultado = _extraer_body(event)
        assert resultado == body_valido

    def test_body_como_dict(self, body_valido: dict):
        """Body como dict (FastAPI o tests directos)."""
        event = {"body": body_valido}
        resultado = _extraer_body(event)
        assert resultado == body_valido

    def test_evento_sin_body_key(self, body_valido: dict):
        """Si no hay key 'body', el evento completo es el body."""
        resultado = _extraer_body(body_valido)
        assert resultado == body_valido

    def test_body_string_invalido_lanza_error(self):
        """Body string que no es JSON válido lanza excepción."""
        event = {"body": "esto no es json"}
        with pytest.raises(json.JSONDecodeError):
            _extraer_body(event)


# ---------------------------------------------------------------------------
# Tests: _parsear_payload
# ---------------------------------------------------------------------------


class TestParsearPayload:
    """Tests para la conversión de dict a ActivationPayload."""

    def test_parseo_correcto_campos_completos(self, body_valido: dict):
        """Body con todos los campos válidos parsea correctamente."""
        payload = _parsear_payload(body_valido)
        assert payload.poliza_id == "POL-2024-001"
        assert payload.cliente_nombre == "Empresa Test S.A."
        assert payload.cliente_email == "contacto@empresa-test.com"
        assert payload.fecha_vencimiento == date(2025, 8, 15)
        assert payload.precio_renovacion == 45000.00
        assert payload.equipo_nombre == "UPS Eaton 9PX 6kVA"

    def test_parseo_fecha_string_iso(self):
        """Fecha como string ISO 8601 se convierte a date."""
        body = {
            "poliza_id": "POL-001",
            "cliente_nombre": "Test",
            "cliente_email": "test@test.com",
            "fecha_vencimiento": "2025-12-31",
            "precio_renovacion": 1000,
            "equipo_nombre": "Equipo A",
        }
        payload = _parsear_payload(body)
        assert payload.fecha_vencimiento == date(2025, 12, 31)

    def test_parseo_precio_como_entero(self):
        """Precio como entero se convierte a float."""
        body = {
            "poliza_id": "POL-001",
            "cliente_nombre": "Test",
            "cliente_email": "test@test.com",
            "fecha_vencimiento": "2025-08-15",
            "precio_renovacion": 50000,
            "equipo_nombre": "Equipo A",
        }
        payload = _parsear_payload(body)
        assert payload.precio_renovacion == 50000.0
        assert isinstance(payload.precio_renovacion, float)

    def test_parseo_precio_como_string(self):
        """Precio como string numérico se convierte a float."""
        body = {
            "poliza_id": "POL-001",
            "cliente_nombre": "Test",
            "cliente_email": "test@test.com",
            "fecha_vencimiento": "2025-08-15",
            "precio_renovacion": "35000.50",
            "equipo_nombre": "Equipo A",
        }
        payload = _parsear_payload(body)
        assert payload.precio_renovacion == 35000.50

    def test_parseo_campos_faltantes_usan_valores_por_defecto(self):
        """Campos faltantes usan valores por defecto (para que el validador los rechace)."""
        body = {}
        payload = _parsear_payload(body)
        assert payload.poliza_id == ""
        assert payload.cliente_nombre == ""
        assert payload.cliente_email == ""
        assert payload.precio_renovacion == 0.0

    def test_parseo_fecha_invalida_usa_placeholder(self):
        """Fecha inválida usa placeholder date(1900,1,1)."""
        body = {
            "poliza_id": "POL-001",
            "cliente_nombre": "Test",
            "cliente_email": "test@test.com",
            "fecha_vencimiento": "no-es-fecha",
            "precio_renovacion": 1000,
            "equipo_nombre": "Equipo A",
        }
        # fromisoformat lanza ValueError en formato no ISO
        with pytest.raises(ValueError):
            _parsear_payload(body)


# ---------------------------------------------------------------------------
# Tests: webhook_handler — Happy path (payload válido → HTTP 200)
# ---------------------------------------------------------------------------


class TestWebhookHandlerExitoso:
    """Payload válido → HTTP 200 con status accepted y session_id."""

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.webhook.handler.registrar_error")
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_retorna_status_200(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        mock_registrar_error: MagicMock,
        evento_lambda_valido: dict,
    ):
        """Payload válido → statusCode 200."""
        from src.models.data_models import PipelineCard
        from datetime import datetime, timezone

        mock_consultar.return_value = PipelineCard(
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
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        resultado = webhook_handler(evento_lambda_valido)

        assert resultado["statusCode"] == 200

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.webhook.handler.registrar_error")
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_body_contiene_status_accepted(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        mock_registrar_error: MagicMock,
        evento_lambda_valido: dict,
    ):
        """El body de la respuesta contiene {"status": "accepted"}."""
        from src.models.data_models import PipelineCard
        from datetime import datetime, timezone

        mock_consultar.return_value = PipelineCard(
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
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        resultado = webhook_handler(evento_lambda_valido)
        body = json.loads(resultado["body"])

        assert body["status"] == "accepted"

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.webhook.handler.registrar_error")
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_body_contiene_session_id_uuid(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        mock_registrar_error: MagicMock,
        evento_lambda_valido: dict,
    ):
        """El body de la respuesta contiene un session_id formato UUID."""
        import uuid
        from src.models.data_models import PipelineCard
        from datetime import datetime, timezone

        mock_consultar.return_value = PipelineCard(
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
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        resultado = webhook_handler(evento_lambda_valido)
        body = json.loads(resultado["body"])

        # Verificar que session_id es un UUID válido
        session_id = body["session_id"]
        parsed = uuid.UUID(session_id, version=4)
        assert str(parsed) == session_id

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.webhook.handler.registrar_error")
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_headers_content_type_json(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        mock_registrar_error: MagicMock,
        evento_lambda_valido: dict,
    ):
        """Los headers incluyen Content-Type: application/json."""
        from src.models.data_models import PipelineCard
        from datetime import datetime, timezone

        mock_consultar.return_value = PipelineCard(
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
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        resultado = webhook_handler(evento_lambda_valido)

        assert resultado["headers"]["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Tests: webhook_handler — Payload inválido → HTTP 400
# ---------------------------------------------------------------------------


class TestWebhookHandlerPayloadInvalido:
    """Payload inválido → HTTP 400 con detalles del error."""

    def test_email_invalido_retorna_400(self, evento_lambda_invalido: dict):
        """Email inválido → statusCode 400."""
        resultado = webhook_handler(evento_lambda_invalido)
        assert resultado["statusCode"] == 400

    def test_email_invalido_retorna_error_validacion(
        self, evento_lambda_invalido: dict
    ):
        """Email inválido → error 'validation_error'."""
        resultado = webhook_handler(evento_lambda_invalido)
        body = json.loads(resultado["body"])
        assert body["status"] == "error"
        assert body["error"] == "validation_error"

    def test_email_invalido_incluye_campos_invalidos(
        self, evento_lambda_invalido: dict
    ):
        """Email inválido → details incluye 'cliente_email'."""
        resultado = webhook_handler(evento_lambda_invalido)
        body = json.loads(resultado["body"])
        assert "cliente_email" in body["details"]["campos_invalidos"]

    def test_precio_cero_retorna_400(self, body_invalido_precio_cero: dict):
        """Precio = 0 → statusCode 400."""
        evento = {"body": json.dumps(body_invalido_precio_cero)}
        resultado = webhook_handler(evento)
        assert resultado["statusCode"] == 400

    def test_campos_vacios_retorna_400(self, body_campos_vacios: dict):
        """Todos los campos vacíos → statusCode 400."""
        evento = {"body": json.dumps(body_campos_vacios)}
        resultado = webhook_handler(evento)
        assert resultado["statusCode"] == 400

    def test_campos_vacios_incluye_multiples_errores(
        self, body_campos_vacios: dict
    ):
        """Múltiples campos inválidos → todos listados en details."""
        evento = {"body": json.dumps(body_campos_vacios)}
        resultado = webhook_handler(evento)
        body = json.loads(resultado["body"])
        campos = body["details"]["campos_invalidos"]
        assert len(campos) >= 3  # al menos poliza_id, cliente_nombre, cliente_email


# ---------------------------------------------------------------------------
# Tests: webhook_handler — Body no parseable → HTTP 400
# ---------------------------------------------------------------------------


class TestWebhookHandlerBodyInvalido:
    """Body que no se puede parsear como JSON → HTTP 400."""

    def test_body_no_json_retorna_400(self):
        """Body con string no JSON → statusCode 400."""
        evento = {"body": "esto no es json válido"}
        resultado = webhook_handler(evento)
        assert resultado["statusCode"] == 400

    def test_body_no_json_retorna_error_request(self):
        """Body no JSON → error 'invalid_request'."""
        evento = {"body": "no-json"}
        resultado = webhook_handler(evento)
        body = json.loads(resultado["body"])
        assert body["error"] == "invalid_request"

    def test_body_vacio_retorna_400(self):
        """Body vacío (string vacía) → statusCode 400."""
        evento = {"body": ""}
        resultado = webhook_handler(evento)
        assert resultado["statusCode"] == 400


# ---------------------------------------------------------------------------
# Tests: webhook_handler — Error de runtime → HTTP 500
# ---------------------------------------------------------------------------


class TestWebhookHandlerErrorRuntime:
    """Error en la invocación del AgentCore Runtime → HTTP 500."""

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.webhook.handler.registrar_error")
    @patch("src.agent.session.iniciar_sesion")
    def test_excepcion_en_runtime_retorna_500(
        self,
        mock_iniciar: MagicMock,
        mock_registrar_error: MagicMock,
        body_valido: dict,
    ):
        """Excepción durante iniciar_sesion → statusCode 500."""
        mock_iniciar.side_effect = RuntimeError("Conexión perdida con Bedrock")

        evento = {"body": json.dumps(body_valido)}

        with patch("src.webhook.handler.es_payload_valido", return_value=True):
            with patch(
                "src.webhook.handler._parsear_payload"
            ) as mock_parsear:
                mock_parsear.return_value = ActivationPayload(
                    poliza_id="POL-2024-001",
                    cliente_nombre="Empresa Test S.A.",
                    cliente_email="contacto@empresa-test.com",
                    fecha_vencimiento=date(2025, 8, 15),
                    precio_renovacion=45000.00,
                    equipo_nombre="UPS Eaton 9PX 6kVA",
                )
                resultado = webhook_handler(evento)

        assert resultado["statusCode"] == 500

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.webhook.handler.registrar_error")
    @patch("src.agent.session.iniciar_sesion")
    def test_excepcion_registra_error_en_observability(
        self,
        mock_iniciar: MagicMock,
        mock_registrar_error: MagicMock,
        body_valido: dict,
    ):
        """Excepción en runtime → registrar_error invocado."""
        mock_iniciar.side_effect = RuntimeError("Conexión perdida con Bedrock")

        evento = {"body": json.dumps(body_valido)}

        with patch("src.webhook.handler.es_payload_valido", return_value=True):
            with patch(
                "src.webhook.handler._parsear_payload"
            ) as mock_parsear:
                mock_parsear.return_value = ActivationPayload(
                    poliza_id="POL-2024-001",
                    cliente_nombre="Empresa Test S.A.",
                    cliente_email="contacto@empresa-test.com",
                    fecha_vencimiento=date(2025, 8, 15),
                    precio_renovacion=45000.00,
                    equipo_nombre="UPS Eaton 9PX 6kVA",
                )
                webhook_handler(evento)

        mock_registrar_error.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: _respuesta_exitosa y _respuesta_error (helpers)
# ---------------------------------------------------------------------------


class TestRespuestasHelper:
    """Tests para las funciones auxiliares de respuesta HTTP."""

    def test_respuesta_exitosa_formato_correcto(self):
        """_respuesta_exitosa genera el formato esperado."""
        resp = _respuesta_exitosa("test-session-123")
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["status"] == "accepted"
        assert body["session_id"] == "test-session-123"

    def test_respuesta_error_formato_correcto(self):
        """_respuesta_error genera el formato de error esperado."""
        resp = _respuesta_error(
            status_code=400,
            error="validation_error",
            message="Campos inválidos",
            details={"campos_invalidos": ["email"]},
        )
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["status"] == "error"
        assert body["error"] == "validation_error"
        assert body["message"] == "Campos inválidos"
        assert body["details"]["campos_invalidos"] == ["email"]

    def test_respuesta_error_sin_details(self):
        """_respuesta_error funciona sin details."""
        resp = _respuesta_error(
            status_code=500,
            error="runtime_error",
            message="Error interno",
        )
        body = json.loads(resp["body"])
        assert "details" not in body


# ---------------------------------------------------------------------------
# Tests: Invocación directa con body como dict (FastAPI pattern)
# ---------------------------------------------------------------------------


class TestWebhookHandlerFastAPIPattern:
    """El handler acepta el body como dict directo (sin key 'body')."""

    @patch("src.webhook.handler.EXECUTION_MODE", "mock")
    @patch("src.webhook.handler.registrar_error")
    @patch("src.agent.session.guardar_estado_sesion")
    @patch("src.agent.session.actualizar_pipefy")
    @patch("src.agent.session.consultar_pipefy")
    def test_body_directo_funciona(
        self,
        mock_consultar: MagicMock,
        mock_actualizar: MagicMock,
        mock_guardar: MagicMock,
        mock_registrar_error: MagicMock,
        body_valido: dict,
    ):
        """Pasando el body directamente como evento → funciona igual."""
        from src.models.data_models import PipelineCard
        from datetime import datetime, timezone

        mock_consultar.return_value = PipelineCard(
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
        mock_actualizar.return_value = True
        mock_guardar.return_value = True

        # Pasamos body_valido directamente (sin key "body")
        resultado = webhook_handler(body_valido)

        assert resultado["statusCode"] == 200
        body = json.loads(resultado["body"])
        assert body["status"] == "accepted"
        assert "session_id" in body


# ---------------------------------------------------------------------------
# Tests: Modo producción — invocación asíncrona (fire-and-forget)
# ---------------------------------------------------------------------------


class TestWebhookHandlerModoProd:
    """Verifica que en modo prod la invocación es asíncrona y no bloquea."""

    @patch("src.webhook.handler.EXECUTION_MODE", "prod")
    @patch("src.webhook.handler._invocar_agentcore_runtime_async")
    def test_modo_prod_invoca_async(
        self,
        mock_async: MagicMock,
        body_valido: dict,
    ):
        """En modo prod, se invoca _invocar_agentcore_runtime_async."""
        evento = {"body": json.dumps(body_valido)}
        resultado = webhook_handler(evento)

        assert resultado["statusCode"] == 200
        mock_async.assert_called_once()

    @patch("src.webhook.handler.EXECUTION_MODE", "prod")
    @patch("src.webhook.handler._invocar_agentcore_runtime_async")
    def test_modo_prod_responde_antes_de_que_runtime_termine(
        self,
        mock_async: MagicMock,
        body_valido: dict,
    ):
        """La respuesta HTTP se retorna sin esperar al runtime (fire-and-forget)."""
        # mock_async no bloquea (por defecto MagicMock retorna inmediato)
        # Esto simula que la función async lanza un thread y retorna al instante
        evento = {"body": json.dumps(body_valido)}

        resultado = webhook_handler(evento)

        assert resultado["statusCode"] == 200
        # Verificar que _invocar_agentcore_runtime_async fue llamada
        # (es decir, no se usó la versión síncrona)
        mock_async.assert_called_once()
        # Verificar que los args son el payload parseado y un session_id
        args = mock_async.call_args[0]
        assert hasattr(args[0], "poliza_id")  # ActivationPayload
        assert isinstance(args[1], str)       # session_id (UUID string)

    @patch("src.webhook.handler.EXECUTION_MODE", "prod")
    @patch("src.webhook.handler._invocar_agentcore_runtime")
    def test_invocar_async_usa_thread_daemon(
        self,
        mock_runtime: MagicMock,
        body_valido: dict,
    ):
        """_invocar_agentcore_runtime_async lanza un thread daemon."""
        import time
        from src.webhook.handler import _invocar_agentcore_runtime_async
        from src.models.data_models import ActivationPayload

        payload = ActivationPayload(
            poliza_id="POL-001",
            cliente_nombre="Test",
            cliente_email="test@test.com",
            fecha_vencimiento=date(2025, 8, 15),
            precio_renovacion=45000.00,
            equipo_nombre="UPS Test",
        )

        # Simular que el runtime tarda 2 segundos
        def slow_runtime(*args, **kwargs):
            time.sleep(0.5)
            return {"success": True}

        mock_runtime.side_effect = slow_runtime

        start = time.time()
        _invocar_agentcore_runtime_async(payload, "test-session-123")
        elapsed = time.time() - start

        # La función retorna inmediato (< 0.1s) porque lanza un thread
        assert elapsed < 0.1

        # Esperar a que el thread termine para verificar que sí se invocó
        time.sleep(1.0)
        mock_runtime.assert_called_once()

    @patch("src.webhook.handler.EXECUTION_MODE", "prod")
    @patch("src.webhook.handler._invocar_agentcore_runtime_async")
    def test_modo_prod_retorna_session_id(
        self,
        mock_async: MagicMock,
        body_valido: dict,
    ):
        """Modo prod retorna session_id válido en la respuesta."""
        import uuid

        evento = {"body": json.dumps(body_valido)}
        resultado = webhook_handler(evento)

        body = json.loads(resultado["body"])
        session_id = body["session_id"]
        parsed = uuid.UUID(session_id, version=4)
        assert str(parsed) == session_id
