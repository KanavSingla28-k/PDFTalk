from dataclasses import dataclass
import tiktoken
from typing import Iterable

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNK_STEP = CHUNK_SIZE - CHUNK_OVERLAP  # 448


@dataclass
class ChunkData:
    chunk_index: int
    text: str
    token_count: int


def chunk_text(text_stream: str | Iterable[str]) -> list[ChunkData]:
    """
    Split text into CHUNK_SIZE-token chunks with CHUNK_OVERLAP-token overlap.
    Uses cl100k_base encoding (matches text-embedding-3-small).

    Accepts either a single string or an iterable of strings (for stream processing).
    Returns an empty list if text is empty or contains no tokens.
    """
    if isinstance(text_stream, str):
        text_stream = [text_stream]

    enc = tiktoken.get_encoding("cl100k_base")
    chunks: list[ChunkData] = []
    buffer_tokens = []

    for text_block in text_stream:
        if not text_block or not text_block.strip():
            continue

        tokens = enc.encode(text_block)
        buffer_tokens.extend(tokens)

        while len(buffer_tokens) >= CHUNK_SIZE:
            window = buffer_tokens[:CHUNK_SIZE]
            chunks.append(ChunkData(
                chunk_index=len(chunks),
                text=enc.decode(window),
                token_count=len(window),
            ))
            buffer_tokens = buffer_tokens[CHUNK_STEP:]

    # Emit a trailing chunk only if it contains tokens that were not already
    # emitted as overlap from the previous chunk.
    if buffer_tokens and (
        not chunks or len(buffer_tokens) > CHUNK_OVERLAP
    ):
        chunks.append(
            ChunkData(
                chunk_index=len(chunks),
                text=enc.decode(buffer_tokens),
                token_count=len(buffer_tokens),
            )
        )   

    return chunks
