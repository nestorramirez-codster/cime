"""
Cliente wrapper para interactuar con la Knowledge Base de Amazon Bedrock.

Provee funciones para:
- Consultar la KB con texto y obtener resultados con scores
- Disparar un job de sincronización/ingestión
- Verificar el estado de indexación de documentos
- Modo mock para desarrollo local (keyword-based scoring)

Requisitos: 11.1, 11.3, 11.4
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.config.kb_config import KBConfig, get_kb_config

logger = logging.getLogger(__name__)


@dataclass
class KBResult:
    """Resultado individual de una consulta a la Knowledge Base."""

    content: str
    score: float
    source_uri: str
    metadata: dict = field(default_factory=dict)


@dataclass
class KBQueryResponse:
    """Respuesta completa de una consulta a la KB."""

    results: list[KBResult]
    query_text: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def top_score(self) -> float:
        """Score máximo entre los resultados."""
        if not self.results:
            return 0.0
        return max(r.score for r in self.results)

    @property
    def has_relevant_results(self) -> bool:
        """True si al menos un resultado supera el umbral mínimo de score."""
        config = get_kb_config()
        return self.top_score >= config.min_score_threshold


@dataclass
class IngestionJobStatus:
    """Estado de un job de ingestión/sincronización."""

    job_id: str
    status: str  # "IN_PROGRESS" | "COMPLETE" | "FAILED"
    documents_scanned: int = 0
    documents_indexed: int = 0
    documents_failed: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Mock para desarrollo local
# ---------------------------------------------------------------------------

# Palabras clave asociadas a cada documento para el mock
_MOCK_DOCUMENT_KEYWORDS: dict[str, list[str]] = {
    "reglas_comerciales.md": [
        "regla", "comercial", "ventana", "descuento", "pre-vencimiento",
        "5%", "renovación", "negocio", "condición", "política",
        "30 días", "vencimiento", "plazo",
    ],
    "catalogo_precios.json": [
        "precio", "catálogo", "equipo", "plan", "mantenimiento",
        "costo", "monto", "tarifa", "UPS", "cotización",
    ],
    "plantillas_mensajes.md": [
        "plantilla", "mensaje", "correo", "contacto", "encuesta",
        "confirmación", "escalamiento", "pre-vencimiento", "post-vencimiento",
        "template", "email",
    ],
    "criterios_escalamiento.md": [
        "escalar", "escalamiento", "humano", "asesor", "negociación",
        "queja", "inconformidad", "técnico", "facturación", "criterio",
    ],
}


def _mock_score(query: str, keywords: list[str]) -> float:
    """Calcula un score mock basado en coincidencia de keywords."""
    query_lower = query.lower()
    matches = sum(1 for kw in keywords if kw.lower() in query_lower)
    if not keywords:
        return 0.0
    # Score normalizado entre 0 y 1
    raw_score = matches / len(keywords)
    # Escalar para que keywords relevantes den >= 0.70
    return min(1.0, raw_score * 3.5)


def _mock_query(query_text: str, config: KBConfig) -> KBQueryResponse:
    """Ejecuta una consulta mock usando coincidencia de keywords."""
    results = []
    for doc_path, keywords in _MOCK_DOCUMENT_KEYWORDS.items():
        score = _mock_score(query_text, keywords)
        if score > 0.0:
            results.append(
                KBResult(
                    content=f"[Mock content from {doc_path} for query: '{query_text}']",
                    score=round(score, 4),
                    source_uri=f"s3://{config.bucket_name}/{doc_path}",
                    metadata={"document": doc_path, "mock": True},
                )
            )

    # Ordenar por score descendente y limitar a top_k
    results.sort(key=lambda r: r.score, reverse=True)
    results = results[: config.top_k]

    return KBQueryResponse(results=results, query_text=query_text)


def _mock_start_ingestion(config: KBConfig) -> IngestionJobStatus:
    """Simula el inicio de un job de ingestión."""
    return IngestionJobStatus(
        job_id="mock-ingestion-job-001",
        status="COMPLETE",
        documents_scanned=len(config.document_paths),
        documents_indexed=len(config.document_paths),
        documents_failed=0,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


def _mock_get_ingestion_status(
    job_id: str, config: KBConfig
) -> IngestionJobStatus:
    """Retorna estado mock de un job de ingestión."""
    return IngestionJobStatus(
        job_id=job_id,
        status="COMPLETE",
        documents_scanned=len(config.document_paths),
        documents_indexed=len(config.document_paths),
        documents_failed=0,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Cliente principal
# ---------------------------------------------------------------------------


class KBClient:
    """Cliente para interactuar con la Knowledge Base de Amazon Bedrock.

    Soporta modo mock para desarrollo local y modo real con boto3.
    """

    def __init__(self, config: Optional[KBConfig] = None):
        self.config = config or get_kb_config()
        self._bedrock_agent_client = None
        self._bedrock_agent_runtime_client = None

    def _get_agent_client(self):
        """Obtiene el cliente boto3 bedrock-agent (lazy init)."""
        if self._bedrock_agent_client is None:
            import boto3

            self._bedrock_agent_client = boto3.client(
                "bedrock-agent", region_name=self.config.region
            )
        return self._bedrock_agent_client

    def _get_runtime_client(self):
        """Obtiene el cliente boto3 bedrock-agent-runtime (lazy init)."""
        if self._bedrock_agent_runtime_client is None:
            import boto3

            self._bedrock_agent_runtime_client = boto3.client(
                "bedrock-agent-runtime", region_name=self.config.region
            )
        return self._bedrock_agent_runtime_client

    def query(self, query_text: str, top_k: Optional[int] = None) -> KBQueryResponse:
        """Consulta la Knowledge Base con un texto y retorna resultados con scores.

        Args:
            query_text: Texto de la consulta (pregunta o contexto).
            top_k: Número máximo de resultados. Si None, usa config.top_k.

        Returns:
            KBQueryResponse con los resultados ordenados por score descendente.

        Raises:
            ValueError: Si query_text está vacío.
            RuntimeError: Si la KB no está configurada (sin knowledge_base_id en modo real).
        """
        if not query_text or not query_text.strip():
            raise ValueError("query_text no puede estar vacío")

        effective_top_k = top_k if top_k is not None else self.config.top_k

        if self.config.mock_mode:
            logger.info(f"[MOCK] Consultando KB con: '{query_text[:50]}...'")
            response = _mock_query(query_text, self.config)
            response.results = response.results[:effective_top_k]
            return response

        # Modo real con boto3
        if not self.config.knowledge_base_id:
            raise RuntimeError(
                "knowledge_base_id no configurado. "
                "Establece la variable CIME_KB_ID o configura el ID tras crear la KB."
            )

        client = self._get_runtime_client()
        response = client.retrieve(
            knowledgeBaseId=self.config.knowledge_base_id,
            retrievalQuery={"text": query_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": effective_top_k,
                }
            },
        )

        results = []
        for item in response.get("retrievalResults", []):
            score = item.get("score", 0.0)
            content_text = item.get("content", {}).get("text", "")
            source_uri = (
                item.get("location", {}).get("s3Location", {}).get("uri", "")
            )
            results.append(
                KBResult(
                    content=content_text,
                    score=score,
                    source_uri=source_uri,
                    metadata=item.get("metadata", {}),
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return KBQueryResponse(results=results, query_text=query_text)

    def start_ingestion_job(self) -> IngestionJobStatus:
        """Inicia un job de sincronización/ingestión de la KB.

        Sincroniza los documentos del bucket S3 con el vector store.

        Returns:
            IngestionJobStatus con el ID del job y estado inicial.

        Raises:
            RuntimeError: Si la KB o data source no están configurados.
        """
        if self.config.mock_mode:
            logger.info("[MOCK] Iniciando job de ingestión")
            return _mock_start_ingestion(self.config)

        if not self.config.knowledge_base_id or not self.config.data_source_id:
            raise RuntimeError(
                "knowledge_base_id y data_source_id deben estar configurados "
                "para iniciar un job de ingestión."
            )

        client = self._get_agent_client()
        response = client.start_ingestion_job(
            knowledgeBaseId=self.config.knowledge_base_id,
            dataSourceId=self.config.data_source_id,
        )

        job_info = response.get("ingestionJob", {})
        return IngestionJobStatus(
            job_id=job_info.get("ingestionJobId", ""),
            status=job_info.get("status", "IN_PROGRESS"),
            started_at=job_info.get("startedAt"),
        )

    def get_ingestion_status(self, job_id: str) -> IngestionJobStatus:
        """Obtiene el estado de un job de ingestión.

        Args:
            job_id: ID del job retornado por start_ingestion_job.

        Returns:
            IngestionJobStatus con el estado actual del job.
        """
        if self.config.mock_mode:
            logger.info(f"[MOCK] Consultando estado de ingestión: {job_id}")
            return _mock_get_ingestion_status(job_id, self.config)

        if not self.config.knowledge_base_id or not self.config.data_source_id:
            raise RuntimeError(
                "knowledge_base_id y data_source_id deben estar configurados."
            )

        client = self._get_agent_client()
        response = client.get_ingestion_job(
            knowledgeBaseId=self.config.knowledge_base_id,
            dataSourceId=self.config.data_source_id,
            ingestionJobId=job_id,
        )

        job_info = response.get("ingestionJob", {})
        stats = job_info.get("statistics", {})
        return IngestionJobStatus(
            job_id=job_info.get("ingestionJobId", job_id),
            status=job_info.get("status", "UNKNOWN"),
            documents_scanned=stats.get("numberOfDocumentsScanned", 0),
            documents_indexed=stats.get("numberOfNewDocumentsIndexed", 0)
            + stats.get("numberOfModifiedDocumentsIndexed", 0),
            documents_failed=stats.get("numberOfDocumentsFailed", 0),
            started_at=job_info.get("startedAt"),
            completed_at=job_info.get("updatedAt"),
        )

    def verify_documents_indexed(self) -> dict[str, bool]:
        """Verifica que cada documento de la KB está indexado correctamente.

        Ejecuta una consulta por cada documento usando sus keywords y
        verifica que el score supera el umbral mínimo.

        Returns:
            Dict con nombre de documento → True si está correctamente indexado.
        """
        if self.config.mock_mode:
            logger.info("[MOCK] Verificando documentos indexados")
            # En modo mock, todos los documentos están indexados
            return {doc: True for doc in self.config.document_paths}

        verification_queries = {
            "reglas_comerciales.md": "reglas comerciales ventana descuento renovación",
            "catalogo_precios.json": "catálogo precios equipo plan mantenimiento",
            "plantillas_mensajes.md": "plantilla mensaje correo contacto inicial",
            "criterios_escalamiento.md": "criterios escalamiento humano asesor",
        }

        results = {}
        for doc_path in self.config.document_paths:
            query = verification_queries.get(doc_path, doc_path)
            try:
                response = self.query(query)
                # Verificar si algún resultado apunta al documento esperado
                doc_found = any(
                    doc_path in r.source_uri
                    and r.score >= self.config.min_score_threshold
                    for r in response.results
                )
                results[doc_path] = doc_found
            except Exception as e:
                logger.error(f"Error verificando {doc_path}: {e}")
                results[doc_path] = False

        return results
