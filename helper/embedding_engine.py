"""Embedding generation for document chunks and retrieval queries.
Goes through model/mistral_client.py exclusively (master prompt §12)."""
from model.mistral_client import embed_texts, MistralUnavailableError
from utils.logger import logger


def embed(texts: list[str]) -> list[list[float]]:
    """Returns one embedding per text. Raises MistralUnavailableError if the
    provider can't be reached — callers ingesting documents should surface
    this as a failed ingestion rather than silently storing zero vectors."""
    try:
        return embed_texts(texts)
    except MistralUnavailableError:
        logger.error("Embedding generation failed: Mistral unavailable")
        raise
