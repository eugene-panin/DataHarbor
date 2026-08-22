"""Qdrant vector store helper for DataHarbor Core (RAG / similarity search)."""
from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "dataharbor")
DEFAULT_VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "512"))


def _resolve_url() -> str:
    url = QDRANT_URL
    if os.path.exists("/.dockerenv") and ("127.0.0.1" in url or "localhost" in url):
        return "http://qdrant:6333"
    return url


def get_qdrant_client():
    """Return a Qdrant client, or None if the service is unreachable."""
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        logger.error("qdrant-client is not installed")
        return None

    try:
        kwargs: dict[str, Any] = {"url": _resolve_url()}
        if QDRANT_API_KEY:
            kwargs["api_key"] = QDRANT_API_KEY
        client = QdrantClient(**kwargs)
        client.get_collections()
        return client
    except Exception as e:
        logger.error("Failed to connect to Qdrant at %s: %s", _resolve_url(), e)
        return None


def ensure_collection(
    collection_name: str = QDRANT_COLLECTION,
    vector_size: int = DEFAULT_VECTOR_SIZE,
    distance: str = "Cosine",
) -> bool:
    """Create the collection if it does not exist."""
    client = get_qdrant_client()
    if not client:
        return False

    try:
        from qdrant_client.http import models as qmodels

        existing = {c.name for c in client.get_collections().collections}
        if collection_name in existing:
            return True

        distance_map = {
            "Cosine": qmodels.Distance.COSINE,
            "Euclid": qmodels.Distance.EUCLID,
            "Dot": qmodels.Distance.DOT,
        }
        client.create_collection(
            collection_name=collection_name,
            vectors_config=qmodels.VectorParams(
                size=vector_size,
                distance=distance_map.get(distance, qmodels.Distance.COSINE),
            ),
        )
        logger.info("Created Qdrant collection '%s' (size=%s)", collection_name, vector_size)
        return True
    except Exception as e:
        logger.error("Failed to ensure Qdrant collection '%s': %s", collection_name, e)
        return False


def upsert_vectors(
    points: Sequence[dict[str, Any]],
    collection_name: str = QDRANT_COLLECTION,
) -> bool:
    """Upsert points: each item needs ``id``, ``vector``, optional ``payload``."""
    if not points:
        return True

    client = get_qdrant_client()
    if not client:
        return False

    try:
        from qdrant_client.http import models as qmodels

        qpoints = [
            qmodels.PointStruct(
                id=p["id"],
                vector=p["vector"],
                payload=p.get("payload") or {},
            )
            for p in points
        ]
        client.upsert(collection_name=collection_name, points=qpoints)
        logger.info("Upserted %s vectors into '%s'", len(qpoints), collection_name)
        return True
    except Exception as e:
        logger.error("Qdrant upsert failed for '%s': %s", collection_name, e)
        return False


def search_vectors(
    query_vector: list[float],
    *,
    collection_name: str = QDRANT_COLLECTION,
    limit: int = 10,
    score_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Search nearest vectors; returns id/score/payload dicts."""
    client = get_qdrant_client()
    if not client:
        return []

    try:
        hits = client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=limit,
            score_threshold=score_threshold,
        )
        return [
            {"id": hit.id, "score": hit.score, "payload": hit.payload or {}}
            for hit in hits
        ]
    except Exception as e:
        logger.error("Qdrant search failed for '%s': %s", collection_name, e)
        return []
