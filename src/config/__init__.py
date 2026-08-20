"""Módulo de configuración del Agente Comercial IA."""

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

__all__ = [
    "KBConfig",
    "KBClient",
    "KBQueryResponse",
    "KBResult",
    "get_kb_config",
    "KB_REGION_PRIMARY",
    "KB_REGION_FALLBACK",
    "KB_EMBEDDING_MODEL_ID",
    "KB_VECTOR_STORE_TYPE",
    "KB_CHUNKING_STRATEGY",
    "KB_CHUNK_SIZE_TOKENS",
    "KB_CHUNK_OVERLAP_TOKENS",
    "KB_TOP_K",
    "KB_MIN_SCORE_THRESHOLD",
]
