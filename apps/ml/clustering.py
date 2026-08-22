import logging
from typing import Any

logger = logging.getLogger(__name__)

def cluster_embeddings(vectors: list[list[float]], min_cluster_size: int = 2) -> dict[str, Any]:
    """Cluster vector embeddings with HDBSCAN. Requires ``uv sync --extra ml``."""
    from apps.ml import require_ml

    require_ml("hdbscan")
    logger.info(
        "Clustering %s vector embeddings using HDBSCAN (min_cluster_size=%s)",
        len(vectors),
        min_cluster_size,
    )

    if not vectors:
        return {"clusters": {}, "outliers": 0}

    import hdbscan
    import numpy as np

    X = np.array(vectors)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size, min_samples=1, metric="euclidean"
    )
    labels = clusterer.fit_predict(X)
    return {
        "clusters": {int(idx): int(label) for idx, label in enumerate(labels)},
        "num_clusters": len(set(labels) - {-1}),
    }
