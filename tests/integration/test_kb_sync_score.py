"""
Smoke test de Knowledge Base: verificar score >= 0.70 para cada documento.

Para cada documento cargado en la KB, consulta con sus términos clave
y verifica que el top_score del resultado sea >= 0.70 (umbral mínimo
configurado en KB_MIN_SCORE_THRESHOLD).

Funciona en modo mock (CIME_KB_MOCK_MODE=true) para desarrollo local.
Para ejecutar contra AWS real, usar: pytest -m "aws_integration"

Validates: Requirements 11.4
"""

from __future__ import annotations

import os

import pytest

from src.config.kb_client import KBClient
from src.config.kb_config import KB_MIN_SCORE_THRESHOLD, KBConfig


# ---------------------------------------------------------------------------
# Markers y skip logic
# ---------------------------------------------------------------------------

# Marker para tests que requieren AWS real (no mock)
aws_integration = pytest.mark.skipif(
    os.environ.get("CIME_KB_MOCK_MODE", "true").lower() == "true",
    reason="Requiere AWS real (CIME_KB_MOCK_MODE=false y credenciales configuradas)",
)


# ---------------------------------------------------------------------------
# Consultas representativas por documento
# ---------------------------------------------------------------------------

# Cada entrada mapea nombre del documento → query con términos clave relevantes
DOCUMENT_QUERIES: dict[str, str] = {
    "reglas_comerciales.md": "regla comercial descuento pre-vencimiento renovación",
    "catalogo_precios.json": "precio catálogo equipo plan mantenimiento cotización",
    "plantillas_mensajes.md": "plantilla mensaje correo contacto confirmación",
    "criterios_escalamiento.md": "escalar escalamiento humano asesor criterio",
}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def kb_client() -> KBClient:
    """Cliente KB configurado en modo mock para desarrollo local."""
    config = KBConfig(mock_mode=True)
    return KBClient(config=config)


# ---------------------------------------------------------------------------
# Smoke tests — Modo mock (desarrollo local)
# ---------------------------------------------------------------------------


class TestKBScoreSmokeLocal:
    """Verifica que cada documento obtiene score >= 0.70 en modo mock."""

    @pytest.mark.parametrize(
        "doc_name,query",
        list(DOCUMENT_QUERIES.items()),
        ids=list(DOCUMENT_QUERIES.keys()),
    )
    def test_document_score_above_threshold(
        self, kb_client: KBClient, doc_name: str, query: str
    ):
        """Consulta la KB con términos clave del documento y verifica top_score >= 0.70."""
        response = kb_client.query(query)

        assert response.top_score >= KB_MIN_SCORE_THRESHOLD, (
            f"Documento '{doc_name}': top_score={response.top_score:.4f} "
            f"es menor que el umbral mínimo {KB_MIN_SCORE_THRESHOLD}"
        )
        assert response.has_relevant_results, (
            f"Documento '{doc_name}': has_relevant_results debería ser True "
            f"con top_score={response.top_score:.4f}"
        )

    def test_all_documents_covered(self, kb_client: KBClient):
        """Verifica que todos los documentos de la KB son consultables con score suficiente."""
        failed_docs = []

        for doc_name, query in DOCUMENT_QUERIES.items():
            response = kb_client.query(query)
            if response.top_score < KB_MIN_SCORE_THRESHOLD:
                failed_docs.append(
                    f"{doc_name} (score={response.top_score:.4f})"
                )

        assert not failed_docs, (
            f"Documentos con score < {KB_MIN_SCORE_THRESHOLD}: "
            + ", ".join(failed_docs)
        )


# ---------------------------------------------------------------------------
# Smoke tests — AWS real (requiere credenciales y KB desplegada)
# ---------------------------------------------------------------------------


@aws_integration
class TestKBScoreSmokeAWS:
    """Verifica scores contra la KB real de AWS Bedrock.

    Ejecutar con: CIME_KB_MOCK_MODE=false pytest -m "aws_integration"
    Requiere: CIME_KB_ID, CIME_KB_REGION, credenciales AWS configuradas.
    """

    @pytest.fixture
    def real_kb_client(self) -> KBClient:
        """Cliente KB configurado para AWS real."""
        config = KBConfig(mock_mode=False)
        return KBClient(config=config)

    @pytest.mark.parametrize(
        "doc_name,query",
        list(DOCUMENT_QUERIES.items()),
        ids=list(DOCUMENT_QUERIES.keys()),
    )
    def test_document_score_above_threshold_aws(
        self, real_kb_client: KBClient, doc_name: str, query: str
    ):
        """Consulta la KB real con términos clave y verifica top_score >= 0.70."""
        response = real_kb_client.query(query)

        assert response.top_score >= KB_MIN_SCORE_THRESHOLD, (
            f"[AWS] Documento '{doc_name}': top_score={response.top_score:.4f} "
            f"es menor que el umbral mínimo {KB_MIN_SCORE_THRESHOLD}"
        )
        assert response.has_relevant_results, (
            f"[AWS] Documento '{doc_name}': has_relevant_results debería ser True"
        )
