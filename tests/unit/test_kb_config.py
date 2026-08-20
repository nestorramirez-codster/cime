"""
Tests unitarios para la configuración y cliente de Knowledge Base.

Verifica:
- Valores correctos de configuración según diseño (Req 11.1, 11.3, 11.4)
- Modo mock del KBClient funciona correctamente
- Consultas mock retornan scores válidos
- Verificación de documentos indexados
- Job de ingestión mock
"""

import os
from unittest.mock import patch

import pytest

from src.config.kb_config import (
    KB_CHUNK_OVERLAP_TOKENS,
    KB_CHUNK_SIZE_TOKENS,
    KB_CHUNKING_STRATEGY,
    KB_EMBEDDING_MODEL_ID,
    KB_MIN_SCORE_THRESHOLD,
    KB_REGION_FALLBACK,
    KB_REGION_PRIMARY,
    KB_TOP_K,
    KB_VECTOR_STORE_TYPE,
    KBConfig,
    get_kb_config,
)
from src.config.kb_client import KBClient, KBQueryResponse, KBResult


class TestKBConfig:
    """Tests de configuración de la Knowledge Base."""

    def test_region_primary_is_us_east_1(self):
        assert KB_REGION_PRIMARY == "us-east-1"

    def test_region_fallback_is_us_west_2(self):
        assert KB_REGION_FALLBACK == "us-west-2"

    def test_embedding_model_is_titan_v2(self):
        assert KB_EMBEDDING_MODEL_ID == "amazon.titan-embed-text-v2:0"

    def test_vector_store_is_s3_vectors(self):
        assert KB_VECTOR_STORE_TYPE == "S3_VECTORS"

    def test_chunking_strategy_fixed_size(self):
        assert KB_CHUNKING_STRATEGY == "FIXED_SIZE"

    def test_chunk_size_is_1000(self):
        assert KB_CHUNK_SIZE_TOKENS == 1000

    def test_chunk_overlap_is_200(self):
        assert KB_CHUNK_OVERLAP_TOKENS == 200

    def test_top_k_is_5(self):
        assert KB_TOP_K == 5

    def test_min_score_threshold_is_070(self):
        assert KB_MIN_SCORE_THRESHOLD == 0.70

    def test_default_config_values(self):
        config = KBConfig()
        assert config.chunk_size == 1000
        assert config.chunk_overlap == 200
        assert config.top_k == 5
        assert config.min_score_threshold == 0.70
        assert config.embedding_model_id == "amazon.titan-embed-text-v2:0"
        assert config.vector_store_type == "S3_VECTORS"
        assert config.chunking_strategy == "FIXED_SIZE"

    def test_bucket_name_template(self):
        with patch.dict(os.environ, {"AWS_ACCOUNT_ID": "123456789012"}):
            config = KBConfig(bucket_name=None)
            config.__post_init__()
            assert config.bucket_name == "cime-kb-documentos-123456789012"

    def test_bucket_name_default_account(self):
        env = {k: v for k, v in os.environ.items() if k != "AWS_ACCOUNT_ID"}
        with patch.dict(os.environ, env, clear=True):
            config = KBConfig(bucket_name=None)
            config.__post_init__()
            assert "000000000000" in config.bucket_name

    def test_document_paths_has_4_documents(self):
        config = KBConfig()
        assert len(config.document_paths) == 4
        assert "reglas_comerciales.md" in config.document_paths
        assert "catalogo_precios.json" in config.document_paths
        assert "plantillas_mensajes.md" in config.document_paths
        assert "criterios_escalamiento.md" in config.document_paths

    def test_embedding_model_arn(self):
        config = KBConfig(region="us-east-1")
        assert "us-east-1" in config.embedding_model_arn
        assert "amazon.titan-embed-text-v2:0" in config.embedding_model_arn

    def test_s3_document_uris(self):
        config = KBConfig(bucket_name="test-bucket")
        uris = config.s3_document_uris
        assert len(uris) == 4
        assert all(uri.startswith("s3://test-bucket/") for uri in uris)

    @patch.dict(os.environ, {"CIME_KB_MOCK_MODE": "true"})
    def test_mock_mode_enabled_by_default(self):
        config = KBConfig()
        assert config.mock_mode is True

    @patch.dict(os.environ, {"CIME_KB_MOCK_MODE": "false"})
    def test_mock_mode_disabled(self):
        config = KBConfig()
        assert config.mock_mode is False

    def test_get_kb_config_factory(self):
        config = get_kb_config()
        assert isinstance(config, KBConfig)


class TestKBClient:
    """Tests del cliente wrapper de KB."""

    def setup_method(self):
        """Configurar cliente en modo mock para cada test."""
        self.config = KBConfig(mock_mode=True, bucket_name="test-kb-bucket")
        self.client = KBClient(config=self.config)

    def test_query_returns_response(self):
        response = self.client.query("reglas comerciales descuento renovación")
        assert isinstance(response, KBQueryResponse)
        assert len(response.results) > 0

    def test_query_results_have_scores(self):
        response = self.client.query("precio catálogo equipo mantenimiento")
        for result in response.results:
            assert isinstance(result, KBResult)
            assert 0.0 <= result.score <= 1.0

    def test_query_results_ordered_by_score(self):
        response = self.client.query("reglas comerciales")
        scores = [r.score for r in response.results]
        assert scores == sorted(scores, reverse=True)

    def test_query_respects_top_k(self):
        response = self.client.query("reglas precio plantilla escalar", top_k=2)
        assert len(response.results) <= 2

    def test_query_empty_text_raises_error(self):
        with pytest.raises(ValueError, match="vacío"):
            self.client.query("")

    def test_query_whitespace_only_raises_error(self):
        with pytest.raises(ValueError, match="vacío"):
            self.client.query("   ")

    def test_query_relevant_keywords_get_high_score(self):
        """Consultas con keywords relevantes deben obtener score >= 0.70."""
        response = self.client.query(
            "reglas comerciales ventana descuento pre-vencimiento"
        )
        assert response.top_score >= 0.70

    def test_query_irrelevant_text_gets_low_score(self):
        """Consultas sin keywords relevantes deben obtener score bajo."""
        response = self.client.query("xyz123 abcdef")
        assert response.top_score < 0.70

    def test_has_relevant_results_property(self):
        response = self.client.query(
            "reglas comerciales ventana descuento pre-vencimiento"
        )
        assert response.has_relevant_results is True

    def test_results_include_source_uri(self):
        response = self.client.query("precio catálogo equipo")
        for result in response.results:
            assert result.source_uri.startswith("s3://")

    def test_start_ingestion_job_mock(self):
        status = self.client.start_ingestion_job()
        assert status.status == "COMPLETE"
        assert status.documents_indexed == 4
        assert status.documents_failed == 0
        assert status.job_id != ""

    def test_get_ingestion_status_mock(self):
        status = self.client.get_ingestion_status("mock-job-001")
        assert status.status == "COMPLETE"
        assert status.documents_scanned == 4

    def test_verify_documents_indexed_mock(self):
        result = self.client.verify_documents_indexed()
        assert len(result) == 4
        assert all(indexed for indexed in result.values())
        assert "reglas_comerciales.md" in result
        assert "catalogo_precios.json" in result
        assert "plantillas_mensajes.md" in result
        assert "criterios_escalamiento.md" in result

    def test_real_mode_requires_kb_id(self):
        """En modo real sin KB ID, query debe lanzar RuntimeError."""
        real_config = KBConfig(mock_mode=False, knowledge_base_id=None)
        client = KBClient(config=real_config)
        with pytest.raises(RuntimeError, match="knowledge_base_id"):
            client.query("test query")

    def test_real_mode_ingestion_requires_ids(self):
        """En modo real sin IDs, start_ingestion_job debe lanzar RuntimeError."""
        real_config = KBConfig(
            mock_mode=False, knowledge_base_id=None, data_source_id=None
        )
        client = KBClient(config=real_config)
        with pytest.raises(RuntimeError):
            client.start_ingestion_job()
