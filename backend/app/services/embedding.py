# T-33 will implement this fully.

def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Accepts a list of text strings.
    Returns a list of 1536-dimensional float vectors, one per input text.
    Batches internally (groups of 100).
    Vectors are L2-normalised.

    Raises:
        NotImplementedError: until T-33 is implemented.
        DailyQuotaExceededError: when the user's daily token budget is exhausted.
    """
    raise NotImplementedError("T-33: implement embedding service before running ingestion.")