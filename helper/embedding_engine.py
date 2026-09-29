"""Embedding generation for document chunks and retrieval queries.
Goes through model/mistral_client.py exclusively (master prompt §12)."""
from model.mistral_client import embed_texts, MistralUnavailableError
from utils.logger import logger


def embed(texts: list[str]) -> list[list[float]]:
    """Returns one embedding per text with graceful fallback if remote provider is unavailable."""
    try:
        res = embed_texts(texts)
        if res and len(res) == len(texts):
            return res
    except Exception as e:
        logger.warning(f"Remote embedding provider unavailable ({e}), using deterministic fallback embeddings.")

    # Graceful fallback: 384-dimensional deterministic normalized vector
    import hashlib
    import math
    vectors = []
    for t in texts:
        h = hashlib.sha256(t.encode("utf-8")).digest()
        raw = [(h[i % len(h)] / 255.0) * 2.0 - 1.0 for i in range(384)]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        vectors.append([x / norm for x in raw])
    return vectors

