import pytest
from app.services.chunking import chunk_text, CHUNK_SIZE, CHUNK_OVERLAP, CHUNK_STEP
import tiktoken

def _make_text(approx_tokens: int) -> str:
    enc = tiktoken.get_encoding("cl100k_base")
    token = enc.encode("hello")[0]
    return enc.decode([token] * approx_tokens)


class TestChunkText:
    def test_empty_string_returns_empty(self):
        assert chunk_text("") == []

    def test_whitespace_only_returns_empty(self):
        assert chunk_text("   \n\n   ") == []

    def test_short_text_produces_single_chunk(self):
        text = _make_text(100)
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert chunks[0].token_count <= CHUNK_SIZE

    def test_chunk_indices_are_sequential(self):
        text = _make_text(1500)
        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_no_chunk_exceeds_chunk_size(self):
        text = _make_text(2000)
        for chunk in chunk_text(text):
            assert chunk.token_count <= CHUNK_SIZE

    def test_token_count_matches_text(self):
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        text = _make_text(600)
        for chunk in chunk_text(text):
            assert chunk.token_count == len(enc.encode(chunk.text))

    def test_overlap_is_present(self):
        """Adjacent chunks share CHUNK_OVERLAP tokens of content."""
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        text = _make_text(1000)
        chunks = chunk_text(text)
        assert len(chunks) >= 2

        tokens_0 = enc.encode(chunks[0].text)
        tokens_1 = enc.encode(chunks[1].text)
        # The tail of chunk 0 should equal the head of chunk 1
        assert tokens_0[-CHUNK_OVERLAP:] == tokens_1[:CHUNK_OVERLAP]

    def test_text_exactly_one_chunk_size(self):
        text = _make_text(CHUNK_SIZE)
        chunks = chunk_text(text)
        assert len(chunks) == 1

    def test_text_exactly_chunk_step_plus_one(self):
        text = _make_text(CHUNK_SIZE + 1)
        chunks = chunk_text(text)
        assert len(chunks) == 2
