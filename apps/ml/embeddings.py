import logging

logger = logging.getLogger(__name__)

_MODEL_CACHE: dict[tuple[str, str], object] = {}


def _get_sentence_transformer(model_name: str, device: str):
    """Cache the loaded model per (name, device) — building a fresh
    SentenceTransformer on every call reloads it from disk (or re-downloads
    it) each time, making embedding more than a handful of items in a run
    prohibitively slow."""
    key = (model_name, device)
    if key not in _MODEL_CACHE:
        from sentence_transformers import SentenceTransformer

        _MODEL_CACHE[key] = SentenceTransformer(model_name, device=device)
    return _MODEL_CACHE[key]


def get_best_torch_device() -> str:
    """Auto-detects best available compute device: Apple Metal MPS -> NVIDIA CUDA -> CPU."""
    try:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            logger.info("Apple Silicon Metal MPS acceleration DETECTED!")
            return "mps"
        elif torch.cuda.is_available():
            logger.info(f"NVIDIA CUDA Acceleration DETECTED: {torch.cuda.get_device_name(0)}")
            return "cuda"
    except Exception as e:
        logger.debug(f"PyTorch device resolution fallback: {e}")
    return "cpu"

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


def generate_multimodal_embedding(text: str, media_type: str = "text") -> list[float]:
    """Generates a vector embedding with hardware acceleration (MPS/CUDA/CPU).

    Returns the embedding model's own native dimensionality (384 for the
    default "all-MiniLM-L6-v2") — it used to be silently zero-padded/
    truncated to a hardcoded 512, which is not a real 512-dimensional
    embedding: appending zeros doesn't add information, and truncating
    would drop real signal, so any similarity search over these vectors
    was comparing corrupted representations without any indication why
    results were degraded. Store these in a Qdrant collection configured
    for this model's actual output size (QDRANT_VECTOR_SIZE), not a fixed
    512.

    Requires optional extra: ``uv sync --extra ml``.
    """
    from apps.ml import require_ml

    require_ml("sentence_transformers")

    device = get_best_torch_device()
    logger.info(
        f"Generating embedding for type '{media_type}' (len={len(text)}) "
        f"with '{EMBEDDING_MODEL_NAME}' on device '{device}'"
    )
    model = _get_sentence_transformer(EMBEDDING_MODEL_NAME, device)
    return model.encode(text).tolist()

if __name__ == "__main__":
    vec = generate_multimodal_embedding("Test Apple Silicon Metal MPS acceleration")
    print(f"Generated vector length: {len(vec)}, first 5 elements: {vec[:5]}")
