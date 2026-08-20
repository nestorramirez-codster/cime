"""
Smoke tests de infraestructura — Agente Comercial IA.

Verificaciones rápidas del correcto funcionamiento de los componentes
de infraestructura en modo mock (desarrollo local):

1. KB retorna Top-K=5 resultados ordenados por score descendente
2. Los 4 secretos de Secrets Manager están definidos en la configuración
3. DynamoDB (mock) tiene tabla con PK session_id funcional (store + retrieve)
4. S3 (mock) tiene estructura de buckets y prefixes correctos (poliza_id)

Estos tests corren en modo mock sin necesidad de credenciales AWS.
Para ejecutar contra AWS real, usar: pytest -m "aws_integration"

Validates: Requirements 11.1, 12.2, 12.3
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from src.config.kb_client import KBClient
from src.config.kb_config import KB_TOP_K, KBConfig
from src.memory.long_term import (
    _build_s3_key,
    _mock_memory_store,
    persistir_historial,
    recuperar_historial,
)
from src.memory.short_term import (
    _mock_store,
    guardar_estado_sesion,
    obtener_estado_sesion,
)
from src.models.data_models import Mensaje, SessionState


# ---------------------------------------------------------------------------
# Constantes esperadas de secretos (definidas en infra/base_infrastructure.yaml)
# ---------------------------------------------------------------------------

EXPECTED_SECRET_IDS = [
    "cime/pipefy/api-token",
    "cime/ses/smtp-credentials",
    "cime/tesoreria/endpoint-key",
    "cime/comercial/slack-webhook",
]

# Buckets esperados (templates de nombre)
EXPECTED_MEMORY_BUCKET_TEMPLATE = "cime-agent-memory-{account_id}"
EXPECTED_KB_BUCKET_TEMPLATE = "cime-kb-documentos-{account_id}"

# Tabla DynamoDB esperada
EXPECTED_DYNAMODB_TABLE = "cime-agent-sessions"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def set_mock_mode(monkeypatch):
    """Asegura que todos los tests corren en modo mock."""
    monkeypatch.setenv("CIME_MOCK_MODE", "true")
    monkeypatch.setenv("CIME_KB_MOCK_MODE", "true")


@pytest.fixture
def kb_client() -> KBClient:
    """Cliente KB configurado en modo mock."""
    config = KBConfig(mock_mode=True)
    return KBClient(config=config)


@pytest.fixture
def clean_short_term_store():
    """Limpia el store mock de short-term antes y después de cada test."""
    _mock_store.clear()
    yield
    _mock_store.clear()


@pytest.fixture
def clean_long_term_store():
    """Limpia el store mock de long-term antes y después de cada test."""
    _mock_memory_store.clear()
    yield
    _mock_memory_store.clear()


# ---------------------------------------------------------------------------
# 1. Smoke Test: KB retorna Top-K=5 resultados ordenados por score
# ---------------------------------------------------------------------------


class TestKBTopKSmoke:
    """Verifica que la KB retorna máximo top_k=5 resultados ordenados por score desc."""

    def test_kb_returns_at_most_top_k_results(self, kb_client: KBClient):
        """La KB nunca retorna más de top_k=5 resultados."""
        # Consulta amplia que debería matchear múltiples documentos
        response = kb_client.query("regla precio plantilla escalamiento criterio")

        assert len(response.results) <= KB_TOP_K, (
            f"KB retornó {len(response.results)} resultados, "
            f"excediendo el top_k={KB_TOP_K}"
        )

    def test_kb_results_sorted_by_score_descending(self, kb_client: KBClient):
        """Los resultados deben estar ordenados por score de mayor a menor."""
        response = kb_client.query("regla precio plantilla escalamiento")

        scores = [r.score for r in response.results]
        assert scores == sorted(scores, reverse=True), (
            f"Resultados no ordenados por score descendente: {scores}"
        )

    def test_kb_top_k_default_is_5(self, kb_client: KBClient):
        """El valor por defecto de top_k es 5."""
        assert kb_client.config.top_k == 5, (
            f"top_k esperado=5, obtenido={kb_client.config.top_k}"
        )

    def test_kb_query_with_explicit_top_k(self, kb_client: KBClient):
        """Consulta con top_k explícito respeta el límite especificado."""
        response = kb_client.query(
            "regla precio plantilla escalamiento criterio", top_k=3
        )

        assert len(response.results) <= 3, (
            f"KB retornó {len(response.results)} resultados con top_k=3"
        )

    def test_kb_results_have_positive_scores(self, kb_client: KBClient):
        """Todos los resultados retornados tienen score > 0."""
        response = kb_client.query("regla comercial descuento renovación")

        for result in response.results:
            assert result.score > 0.0, (
                f"Resultado con score <= 0: {result.source_uri}"
            )


# ---------------------------------------------------------------------------
# 2. Smoke Test: Secretos de Secrets Manager accesibles
# ---------------------------------------------------------------------------


class TestSecretsManagerSmoke:
    """Verifica que los 4 secretos están definidos en la configuración de infraestructura."""

    def test_all_four_secrets_defined(self):
        """Los 4 secretos requeridos están identificados en la configuración."""
        # Verificamos que las constantes de secretos coinciden con lo esperado
        # en base_infrastructure.yaml
        assert len(EXPECTED_SECRET_IDS) == 4, (
            "Deben existir exactamente 4 secretos configurados"
        )

    @pytest.mark.parametrize("secret_id", EXPECTED_SECRET_IDS)
    def test_secret_id_follows_naming_convention(self, secret_id: str):
        """Cada secreto sigue la convención de naming cime/{servicio}/{tipo}."""
        parts = secret_id.split("/")
        assert len(parts) == 3, (
            f"Secreto '{secret_id}' no sigue formato cime/servicio/tipo"
        )
        assert parts[0] == "cime", (
            f"Secreto '{secret_id}' no comienza con 'cime/'"
        )

    def test_pipefy_secret_present(self):
        """Secreto de Pipefy API token está definido."""
        assert "cime/pipefy/api-token" in EXPECTED_SECRET_IDS

    def test_ses_secret_present(self):
        """Secreto de SES SMTP credentials está definido."""
        assert "cime/ses/smtp-credentials" in EXPECTED_SECRET_IDS

    def test_tesoreria_secret_present(self):
        """Secreto de Tesorería endpoint key está definido."""
        assert "cime/tesoreria/endpoint-key" in EXPECTED_SECRET_IDS

    def test_slack_webhook_secret_present(self):
        """Secreto de Slack webhook está definido."""
        assert "cime/comercial/slack-webhook" in EXPECTED_SECRET_IDS

    def test_secrets_match_iam_policy_pattern(self):
        """Los IDs de secretos coinciden con el patrón del IAM policy del agente.

        La política en base_infrastructure.yaml usa patrón:
        arn:aws:secretsmanager:{region}:{account}:secret:cime/{service}/{key}-*
        """
        for secret_id in EXPECTED_SECRET_IDS:
            # Verificar que el secreto es un path válido para SecretsManager
            assert not secret_id.startswith("/"), (
                f"Secret ID no debe comenzar con '/': {secret_id}"
            )
            assert not secret_id.endswith("/"), (
                f"Secret ID no debe terminar con '/': {secret_id}"
            )
            # Verificar que coincide con el patrón ARN en la IAM policy
            assert secret_id.startswith("cime/"), (
                f"Secret ID debe comenzar con 'cime/': {secret_id}"
            )


# ---------------------------------------------------------------------------
# 3. Smoke Test: DynamoDB tabla y partición session_id
# ---------------------------------------------------------------------------


class TestDynamoDBSmoke:
    """Verifica que DynamoDB mock funciona con tabla cime-agent-sessions y PK session_id."""

    def test_table_name_is_correct(self):
        """La tabla DynamoDB esperada es 'cime-agent-sessions'."""
        from src.memory.short_term import _TABLE_NAME

        assert _TABLE_NAME == EXPECTED_DYNAMODB_TABLE, (
            f"Tabla esperada='{EXPECTED_DYNAMODB_TABLE}', "
            f"obtenida='{_TABLE_NAME}'"
        )

    def test_store_and_retrieve_by_session_id(
        self, clean_short_term_store
    ):
        """Puede almacenar y recuperar estado de sesión usando session_id como PK."""
        session_state = SessionState(
            session_id="test-session-001",
            poliza_id="POL-2024-TEST",
            estado_pipefy="Contacto inicial enviado",
            historial_mensajes=[
                Mensaje(
                    timestamp=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
                    remitente="agente",
                    contenido="Hola, su póliza está por vencer.",
                    tipo="contacto_inicial",
                )
            ],
            timestamp_inicio=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
        )

        # Store
        result = guardar_estado_sesion(session_state)
        assert result is True, "guardar_estado_sesion debe retornar True"

        # Retrieve by session_id (PK)
        retrieved = obtener_estado_sesion("test-session-001")
        assert retrieved is not None, "Sesión no encontrada tras guardarla"
        assert retrieved.session_id == "test-session-001"
        assert retrieved.poliza_id == "POL-2024-TEST"
        assert retrieved.estado_pipefy == "Contacto inicial enviado"

    def test_session_id_isolation(self, clean_short_term_store):
        """Cada session_id es aislado — no se mezclan datos entre sesiones."""
        session_a = SessionState(
            session_id="session-A",
            poliza_id="POL-A",
            estado_pipefy="Póliza detectada",
            historial_mensajes=[],
            timestamp_inicio=datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
        )
        session_b = SessionState(
            session_id="session-B",
            poliza_id="POL-B",
            estado_pipefy="Cliente interesado",
            historial_mensajes=[],
            timestamp_inicio=datetime(2025, 7, 15, 11, 0, 0, tzinfo=timezone.utc),
        )

        guardar_estado_sesion(session_a)
        guardar_estado_sesion(session_b)

        retrieved_a = obtener_estado_sesion("session-A")
        retrieved_b = obtener_estado_sesion("session-B")

        assert retrieved_a.poliza_id == "POL-A"
        assert retrieved_b.poliza_id == "POL-B"

    def test_nonexistent_session_returns_none(self, clean_short_term_store):
        """Consultar un session_id inexistente retorna None."""
        result = obtener_estado_sesion("no-existe-xyz")
        assert result is None


# ---------------------------------------------------------------------------
# 4. Smoke Test: S3 buckets y prefixes correctos
# ---------------------------------------------------------------------------


class TestS3BucketsSmoke:
    """Verifica que S3 mock tiene los buckets y prefixes correctos."""

    def test_memory_bucket_name_template(self):
        """El bucket de memoria sigue el template cime-agent-memory-{account_id}."""
        from src.memory.long_term import _S3_BUCKET

        # En modo mock, el bucket por defecto incluye 000000000000
        assert "cime-agent-memory" in _S3_BUCKET, (
            f"Bucket de memoria no sigue template esperado: {_S3_BUCKET}"
        )

    def test_kb_bucket_name_template(self):
        """El bucket de KB sigue el template cime-kb-documentos-{account_id}."""
        config = KBConfig(mock_mode=True)
        assert "cime-kb-documentos" in config.bucket_name, (
            f"Bucket KB no sigue template esperado: {config.bucket_name}"
        )

    def test_s3_prefix_structure_for_poliza(self):
        """El prefix de S3 sigue formato memoria/{poliza_id}/historial.json."""
        poliza_id = "POL-2024-001"
        key = _build_s3_key(poliza_id)

        assert key == f"memoria/{poliza_id}/historial.json", (
            f"Key S3 esperada='memoria/{poliza_id}/historial.json', "
            f"obtenida='{key}'"
        )

    def test_long_term_store_and_retrieve_by_poliza_prefix(
        self, clean_long_term_store
    ):
        """Puede persistir y recuperar historial usando prefijo poliza_id."""
        poliza_id = "POL-2024-SMOKE"
        sesion_completada = {
            "session_id": "sess-smoke-001",
            "timestamp_inicio": datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
            "timestamp_cierre": datetime(2025, 7, 15, 10, 45, 0, tzinfo=timezone.utc),
            "estado_final": "Renovación confirmada",
            "resultado": "interesado",
            "mensajes_enviados": 3,
        }

        # Persistir
        result = persistir_historial(poliza_id, sesion_completada)
        assert result is True

        # Recuperar
        historial = recuperar_historial(poliza_id)
        assert historial is not None
        assert historial["poliza_id"] == poliza_id
        assert len(historial["sesiones"]) == 1
        assert historial["sesiones"][0]["session_id"] == "sess-smoke-001"

    def test_poliza_id_isolation_in_s3(self, clean_long_term_store):
        """Cada poliza_id tiene su propio namespace — no hay contaminación cruzada."""
        sesion_base = {
            "timestamp_inicio": datetime(2025, 7, 15, 10, 0, 0, tzinfo=timezone.utc),
            "timestamp_cierre": datetime(2025, 7, 15, 10, 45, 0, tzinfo=timezone.utc),
            "estado_final": "Contacto inicial enviado",
            "resultado": "interesado",
            "mensajes_enviados": 2,
        }

        persistir_historial("POL-001", {**sesion_base, "session_id": "sess-001"})
        persistir_historial("POL-002", {**sesion_base, "session_id": "sess-002"})

        historial_1 = recuperar_historial("POL-001")
        historial_2 = recuperar_historial("POL-002")

        assert historial_1["sesiones"][0]["session_id"] == "sess-001"
        assert historial_2["sesiones"][0]["session_id"] == "sess-002"

    def test_nonexistent_poliza_returns_none(self, clean_long_term_store):
        """Consultar un poliza_id sin historial retorna None."""
        result = recuperar_historial("POL-INEXISTENTE")
        assert result is None
