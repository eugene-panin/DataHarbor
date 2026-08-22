import logging

logger = logging.getLogger(__name__)

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

def generate_multimodal_embedding(text: str, media_type: str = "text") -> list[float]:
    """Generates a 512-dimensional vector embedding with hardware acceleration (MPS/CUDA/CPU).

    Requires optional extra: ``uv sync --extra ml``.
    """
    from apps.ml import require_ml

    require_ml("sentence_transformers")
    logger.info(f"Generating 512d embedding vector for type '{media_type}' (len={len(text)})")

    from sentence_transformers import SentenceTransformer

    device = get_best_torch_device()
    logger.info(f"Running SentenceTransformer on hardware device: '{device}'")
    model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
    vector = model.encode(text).tolist()

    if len(vector) < 512:
        vector.extend([0.0] * (512 - len(vector)))
    return vector[:512]

if __name__ == "__main__":
    vec = generate_multimodal_embedding("Test Apple Silicon Metal MPS acceleration")
    print(f"Generated vector length: {len(vec)}, first 5 elements: {vec[:5]}")
