from dataclasses import dataclass
import tiktoken

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNK_STEP = CHUNK_SIZE - CHUNK_OVERLAP  # 448


@dataclass
class ChunkData:
    chunk_index: int
    text: str
    token_count: int


def chunk_text(text: str) -> list[ChunkData]:
    """
    Split text into CHUNK_SIZE-token chunks with CHUNK_OVERLAP-token overlap.
    Uses cl100k_base encoding (matches text-embedding-3-small).

    Returns an empty list if text is empty or contains no tokens.
    """
    if not text or not text.strip():
        return []

    enc = tiktoken.get_encoding("cl100k_base")
    tokens = enc.encode(text)

    if not tokens:
        return []

    chunks: list[ChunkData] = []
    start = 0

    while start < len(tokens):
        end = min(start + CHUNK_SIZE, len(tokens))
        window = tokens[start:end]
        chunk_text_str = enc.decode(window)

        chunks.append(ChunkData(
            chunk_index=len(chunks),
            text=chunk_text_str,
            token_count=len(window),
        ))

        if end == len(tokens):
            break

        start += CHUNK_STEP

    return chunks