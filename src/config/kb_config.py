"""
Configuración de la Knowledge Base de Amazon Bedrock con S3 Vectors.

Define todos los parámetros necesarios para la KB del Agente Comercial IA:
- Vector store: S3 Vectors (nativo Bedrock KB)
- Modelo de embeddings: Amazon Titan Embeddings v2
- Chunking: fixed_size, 1000 tokens, overlap 200
- Retrieval: top_k=5, score mínimo 0.70
- Región: us-east-1 (fallback us-west-2)

Requisitos: 11.1, 11.3, 11.4
"""

import os
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constantes de configuración
# ---------------------------------------------------------------------------

# Región principal y fallback
KB_REGION_PRIMARY = "us-east-1"
KB_REGION_FALLBACK = "us-west-2"

# Modelo de embeddings
KB_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
KB_EMBEDDING_MODEL_ARN_TEMPLATE = (
    "arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0"
)

# Vector store
KB_VECTOR_STORE_TYPE = "S3_VECTORS"

# Chunking strategy
KB_CHUNKING_STRATEGY = "FIXED_SIZE"
KB_CHUNK_SIZE_TOKENS = 1000
KB_CHUNK_OVERLAP_TOKENS = 200

# Retrieval configuration
KB_TOP_K = 5
KB_MIN_SCORE_THRESHOLD = 0.70

# Bucket S3 para documentos de KB
KB_BUCKET_NAME_TEMPLATE = "cime-kb-documentos-{account_id}"

# Rutas de documentos en el bucket S3
KB_DOCUMENT_PATHS = [
    "reglas_comerciales.md",
    "catalogo_precios.json",
    "plantillas_mensajes.md",
    "criterios_escalamiento.md",
]

# Directorio local de documentos KB
KB_LOCAL_DOCS_DIR = "docs/kb"


@dataclass
class KBConfig:
    """Configuración completa de la Knowledge Base de Bedrock."""

    # Identificador de la KB (se llena tras crear en AWS)
    knowledge_base_id: Optional[str] = field(
        default_factory=lambda: os.environ.get("CIME_KB_ID", None)
    )

    # Identificador del data source (se llena tras crear en AWS)
    data_source_id: Optional[str] = field(
        default_factory=lambda: os.environ.get("CIME_KB_DATA_SOURCE_ID", None)
    )

    # Región activa
    region: str = field(
        default_factory=lambda: os.environ.get("CIME_KB_REGION", KB_REGION_PRIMARY)
    )

    # Modelo de embeddings
    embedding_model_id: str = KB_EMBEDDING_MODEL_ID

    # Vector store
    vector_store_type: str = KB_VECTOR_STORE_TYPE

    # Chunking
    chunking_strategy: str = KB_CHUNKING_STRATEGY
    chunk_size: int = KB_CHUNK_SIZE_TOKENS
    chunk_overlap: int = KB_CHUNK_OVERLAP_TOKENS

    # Retrieval
    top_k: int = KB_TOP_K
    min_score_threshold: float = KB_MIN_SCORE_THRESHOLD

    # S3 bucket
    bucket_name: Optional[str] = field(default=None)

    # Documentos
    document_paths: list = field(default_factory=lambda: list(KB_DOCUMENT_PATHS))

    # Modo mock para desarrollo local
    mock_mode: bool = field(
        default_factory=lambda: os.environ.get("CIME_KB_MOCK_MODE", "true").lower()
        == "true"
    )

    def __post_init__(self):
        if self.bucket_name is None:
            account_id = os.environ.get("AWS_ACCOUNT_ID", "000000000000")
            self.bucket_name = KB_BUCKET_NAME_TEMPLATE.format(account_id=account_id)

    @property
    def embedding_model_arn(self) -> str:
        """ARN completo del modelo de embeddings."""
        return KB_EMBEDDING_MODEL_ARN_TEMPLATE.format(region=self.region)

    @property
    def s3_document_uris(self) -> list[str]:
        """URIs S3 completos para cada documento de KB."""
        return [f"s3://{self.bucket_name}/{path}" for path in self.document_paths]


def get_kb_config() -> KBConfig:
    """Factory para obtener la configuración de KB con valores del entorno."""
    return KBConfig()
