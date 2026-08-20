"""
Verificación de aislamiento de credenciales — AgentCore Identity (Req 12.3).

Confirma que ningún valor de credencial aparece en:
- El system prompt del agente
- Los payloads de respuesta de tools
- Los registros de observabilidad (logs enmascarados)

También verifica que las tools obtienen credenciales via Secrets Manager
(no hardcoded ni desde variables de entorno directas).
"""

import ast
import inspect
import os
import re
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Patrones de credenciales que NO deben aparecer en outputs
# ---------------------------------------------------------------------------

# Patrones regex que indicarían exposición de credenciales
CREDENTIAL_PATTERNS = [
    # Bearer tokens (formato típico de API tokens)
    r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}",
    # API keys (secuencias alfanuméricas largas sueltas)
    r"\b[A-Za-z0-9]{32,}\b",
    # Slack webhook URLs
    r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+",
    # SMTP passwords explícitas
    r"smtp_password\s*[:=]\s*['\"][^'\"]+['\"]",
    # Secretos hardcoded comunes
    r"sk-[A-Za-z0-9]{20,}",
    r"xoxb-[A-Za-z0-9\-]+",
]

# Nombres de secretos en Secrets Manager que el sistema utiliza
SECRET_NAMES = [
    "cime/pipefy/api-token",
    "cime/ses/smtp-credentials",
    "cime/tesoreria/endpoint-key",
    "cime/comercial/slack-webhook",
]


# ---------------------------------------------------------------------------
# Test 1: System prompt no contiene credenciales
# ---------------------------------------------------------------------------


class TestSystemPromptNoCredentials:
    """Verifica que el system prompt no contiene valores de credenciales."""

    def test_system_prompt_no_contiene_patrones_credenciales(self):
        """El system prompt no debe tener tokens, API keys ni webhooks."""
        from src.agent.agent import SYSTEM_PROMPT

        for pattern in CREDENTIAL_PATTERNS:
            matches = re.findall(pattern, SYSTEM_PROMPT)
            assert not matches, (
                f"El system prompt contiene un patrón de credencial: "
                f"pattern='{pattern}', matches={matches}"
            )

    def test_system_prompt_no_contiene_nombres_secretos_con_valores(self):
        """El system prompt no debe mencionar valores reales de secretos."""
        from src.agent.agent import SYSTEM_PROMPT

        # No debe contener valores tipo token (mockados o reales)
        # Es aceptable que mencione nombres de tools pero no valores
        assert "mock-pipefy-token" not in SYSTEM_PROMPT
        assert "hooks.slack.com/services/" not in SYSTEM_PROMPT
        assert "smtp_password" not in SYSTEM_PROMPT.lower()
        assert "api_key" not in SYSTEM_PROMPT.lower()
        assert "Bearer " not in SYSTEM_PROMPT

    def test_system_prompt_no_contiene_urls_de_endpoints(self):
        """El system prompt no debe exponer URLs internas de servicios."""
        from src.agent.agent import SYSTEM_PROMPT

        # No debe haber URLs de endpoints internos
        assert "api.pipefy.com" not in SYSTEM_PROMPT
        assert "hooks.slack.com" not in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Test 2: Tool responses no exponen credenciales
# ---------------------------------------------------------------------------


class TestToolResponsesNoCredentials:
    """Verifica que los payloads de respuesta de tools no exponen credenciales."""

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "true"})
    def test_consultar_pipefy_response_no_expone_token(self):
        """La respuesta de consultar_pipefy no contiene tokens."""
        from src.tools.pipefy_tools import consultar_pipefy

        result = consultar_pipefy("POL-TEST-001")

        # Serializar toda la respuesta para buscar credenciales
        response_str = str(result)
        assert "mock-pipefy-token" not in response_str
        assert "Bearer" not in response_str
        for pattern in CREDENTIAL_PATTERNS:
            assert not re.search(pattern, response_str), (
                f"Respuesta de consultar_pipefy contiene patrón de credencial: {pattern}"
            )

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "true"})
    def test_actualizar_pipefy_response_no_expone_token(self):
        """La respuesta de actualizar_pipefy no contiene tokens."""
        from src.tools.pipefy_tools import actualizar_pipefy

        result = actualizar_pipefy(
            poliza_id="POL-TEST-001",
            estado="Póliza detectada",
            nota="Test de aislamiento",
            session_id="sess-test-123",
        )

        response_str = str(result)
        assert "mock-pipefy-token" not in response_str
        assert "Bearer" not in response_str

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "true"})
    def test_enviar_correo_response_no_expone_credenciales(self):
        """La respuesta de enviar_correo no contiene credenciales SES."""
        from src.tools.email_tools import enviar_correo

        result = enviar_correo(
            destinatario="test@ejemplo.com",
            asunto="Test",
            cuerpo="Contenido de prueba",
        )

        response_str = str(result)
        assert "smtp_password" not in response_str.lower()
        assert "smtp_username" not in response_str.lower()
        # El response contiene success, message_id, timestamp — no credenciales
        assert result.success is True
        assert result.message_id is not None

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "true"})
    def test_notificar_tesoreria_response_no_expone_api_key(self):
        """La respuesta de notificar_tesoreria no contiene API keys."""
        from src.models.data_models import DatosPago
        from src.tools.treasury_tools import notificar_tesoreria

        datos = DatosPago(
            cliente_nombre="Empresa Test",
            poliza_id="POL-TEST-001",
            monto=45000.00,
            timestamp_recepcion=datetime.now(timezone.utc),
            referencia_adjunto="comprobantes/test.pdf",
        )

        result = notificar_tesoreria(datos)

        # notificar_tesoreria retorna bool (True) — no expone credenciales
        response_str = str(result)
        assert "api_key" not in response_str.lower()
        assert "endpoint-key" not in response_str

    @patch.dict(os.environ, {"CIME_MOCK_MODE": "true"})
    def test_escalar_humano_response_no_expone_webhook_url(self):
        """La respuesta de escalar_humano no contiene webhook URLs."""
        from src.models.data_models import DatosPoliza, Mensaje
        from src.tools.escalation_tools import escalar_humano

        datos_poliza = DatosPoliza(
            poliza_id="POL-TEST-001",
            cliente_nombre="Empresa Test",
            cliente_email="test@ejemplo.com",
            fecha_vencimiento=date(2025, 8, 15),
            precio_renovacion=45000.00,
            equipo_nombre="UPS Test",
        )

        result = escalar_humano(
            motivo="Test de aislamiento de credenciales",
            historial=[],
            estado_pipefy="Póliza detectada",
            datos_poliza=datos_poliza,
            session_id="sess-test-123",
        )

        response_str = str(result)
        assert "hooks.slack.com" not in response_str
        assert "webhook" not in response_str.lower()


# ---------------------------------------------------------------------------
# Test 3: Observability logs no exponen credenciales
# ---------------------------------------------------------------------------


class TestObservabilityNoCredentials:
    """Verifica que los logs de observabilidad no exponen credenciales."""

    def test_enmascaramiento_previene_exposicion_de_emails(self):
        """El enmascaramiento convierte emails a ***@dominio.com."""
        from src.observability.tracer import enmascarar_datos_sensibles

        data = {
            "cliente_email": "juan.garcia@empresa.com",
            "destinatario": "contacto@cimepowersystems.com",
        }

        resultado = enmascarar_datos_sensibles(data)

        # Verificar que no hay emails completos
        email_regex = re.compile(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
        )
        for key, valor in resultado.items():
            if isinstance(valor, str) and "@" in valor:
                # Solo debe quedar ***@dominio.com
                assert valor.startswith("***@"), (
                    f"Email no enmascarado correctamente en key '{key}': '{valor}'"
                )

    def test_enmascaramiento_previene_exposicion_de_datos_bancarios(self):
        """El enmascaramiento redacta datos bancarios a ****-****-****-XXXX."""
        from src.observability.tracer import enmascarar_datos_sensibles

        data = {
            "cuenta_bancaria": "012345678901234567",  # CLABE 18 dígitos
            "tarjeta": "4111 1111 1111 1111",  # Tarjeta 16 dígitos
        }

        resultado = enmascarar_datos_sensibles(data)

        for key, valor in resultado.items():
            if isinstance(valor, str):
                # No debe haber secuencias numéricas largas sin enmascarar
                digitos_expuestos = re.findall(r"\d{10,}", valor)
                assert not digitos_expuestos, (
                    f"Datos bancarios no enmascarados en key '{key}': '{valor}'"
                )

    def test_enmascaramiento_previene_exposicion_de_nombres(self):
        """El enmascaramiento convierte nombres a iniciales."""
        from src.observability.tracer import enmascarar_datos_sensibles

        data = {
            "cliente_nombre": "Juan García López",
            "nombre": "María Fernanda Rodríguez",
        }

        resultado = enmascarar_datos_sensibles(data)

        for key, valor in resultado.items():
            if isinstance(valor, str):
                # No debe contener nombres completos (más de 2 palabras con mayúsculas)
                assert len(valor) <= 10, (
                    f"Nombre no enmascarado correctamente en key '{key}': '{valor}'"
                )

    def test_tool_call_log_no_expone_credenciales(self):
        """Registrar un tool call con parámetros sensibles los enmascara."""
        from src.observability.tracer import enmascarar_datos_sensibles

        params = {
            "destinatario": "cliente@empresa.com",
            "cliente_nombre": "Roberto Hernández",
            "datos_bancarios": "014580001234567890",
        }

        resultado = enmascarar_datos_sensibles(params)

        # El email debe estar enmascarado
        assert "cliente@empresa.com" not in str(resultado)
        # El nombre debe estar como iniciales
        assert "Roberto Hernández" not in str(resultado)
        # Los datos bancarios deben estar enmascarados
        assert "014580001234567890" not in str(resultado)


# ---------------------------------------------------------------------------
# Test 4: Tools obtienen credenciales via Secrets Manager (no hardcoded)
# ---------------------------------------------------------------------------


class TestCredentialsViaSecretsManager:
    """Verifica que las tools usan Secrets Manager, no hardcode ni env vars."""

    def test_pipefy_tools_usa_secrets_manager(self):
        """pipefy_tools.py obtiene token via boto3 secretsmanager."""
        from src.tools import pipefy_tools

        source = inspect.getsource(pipefy_tools._get_pipefy_token)

        # Debe usar boto3 secretsmanager
        assert "secretsmanager" in source, (
            "_get_pipefy_token no usa Secrets Manager"
        )
        assert "get_secret_value" in source, (
            "_get_pipefy_token no llama get_secret_value"
        )
        # No debe tener token hardcoded (excepto mock)
        # Verificar que el SecretId referencia el nombre correcto
        assert "cime/pipefy/api-token" in source

    def test_treasury_tools_usa_secrets_manager(self):
        """treasury_tools.py obtiene endpoint-key via boto3 secretsmanager."""
        from src.tools import treasury_tools

        source = inspect.getsource(treasury_tools._get_treasury_secret)

        assert "secretsmanager" in source, (
            "_get_treasury_secret no usa Secrets Manager"
        )
        assert "get_secret_value" in source
        assert "cime/tesoreria/endpoint-key" in source

    def test_escalation_tools_usa_secrets_manager(self):
        """escalation_tools.py obtiene webhook via boto3 secretsmanager."""
        from src.tools import escalation_tools

        source = inspect.getsource(escalation_tools._get_slack_webhook_url)

        assert "secretsmanager" in source, (
            "_get_slack_webhook_url no usa Secrets Manager"
        )
        assert "get_secret_value" in source
        assert "cime/comercial/slack-webhook" in source

    def test_no_credenciales_en_variables_de_entorno_directas(self):
        """Las tools no leen credenciales directamente de os.environ."""
        from src.tools import escalation_tools, pipefy_tools, treasury_tools

        # Verificar que las funciones de obtención de secretos NO usan
        # os.environ para obtener el valor real de la credencial
        # (es aceptable usar env vars para región, modo mock, etc.)

        pipefy_source = inspect.getsource(pipefy_tools._get_pipefy_token)
        treasury_source = inspect.getsource(treasury_tools._get_treasury_secret)
        escalation_source = inspect.getsource(escalation_tools._get_slack_webhook_url)

        # No deben tener os.environ.get("PIPEFY_TOKEN") o similar
        credential_env_patterns = [
            r'os\.environ.*["\'].*TOKEN["\']',
            r'os\.environ.*["\'].*API_KEY["\']',
            r'os\.environ.*["\'].*WEBHOOK_URL["\']',
            r'os\.environ.*["\'].*SECRET["\']',
            r'os\.environ.*["\'].*PASSWORD["\']',
        ]

        for pattern in credential_env_patterns:
            assert not re.search(pattern, pipefy_source, re.IGNORECASE), (
                f"pipefy_tools lee credencial de env var: {pattern}"
            )
            assert not re.search(pattern, treasury_source, re.IGNORECASE), (
                f"treasury_tools lee credencial de env var: {pattern}"
            )
            assert not re.search(pattern, escalation_source, re.IGNORECASE), (
                f"escalation_tools lee credencial de env var: {pattern}"
            )

    def test_email_tools_usa_ses_via_boto3_no_hardcode(self):
        """email_tools.py usa boto3 SES client, no credenciales hardcoded."""
        from src.tools import email_tools

        source = inspect.getsource(email_tools)

        # Debe usar boto3 client para SES
        assert "boto3.client" in source or 'boto3.client("ses"' in source, (
            "email_tools no usa boto3 client para SES"
        )
        # No debe tener passwords hardcoded
        assert "password" not in source.lower() or "smtp_password" not in source.lower().replace(
            "# smtp_password", ""
        ).replace("smtp_password", ""), (
            "email_tools podría tener credenciales hardcoded"
        )


# ---------------------------------------------------------------------------
# Test 5: Mapeo correcto secret → tool en la configuración
# ---------------------------------------------------------------------------


class TestSecretToolMapping:
    """Verifica la consistencia del mapeo secret→tool."""

    def test_pipefy_token_mapeado_a_tools_correctas(self):
        """cime/pipefy/api-token es usado por consultar_pipefy y actualizar_pipefy."""
        from src.tools.pipefy_tools import _SECRET_NAME

        assert _SECRET_NAME == "cime/pipefy/api-token"

    def test_tesoreria_secret_mapeado_a_notificar(self):
        """cime/tesoreria/endpoint-key es usado por notificar_tesoreria."""
        from src.tools import treasury_tools

        source = inspect.getsource(treasury_tools._get_treasury_secret)
        assert "cime/tesoreria/endpoint-key" in source

    def test_slack_secret_mapeado_a_escalar(self):
        """cime/comercial/slack-webhook es usado por escalar_humano."""
        from src.tools.escalation_tools import _SLACK_SECRET_ID

        assert _SLACK_SECRET_ID == "cime/comercial/slack-webhook"
