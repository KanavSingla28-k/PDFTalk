import uuid

from app.services.retrieval import RetrievedChunk
from app.services.prompt import build_context_block, build_messages, ENCODER

def make_chunk(text: str, filename: str = "doc.pdf") -> RetrievedChunk:
    token_count = len(ENCODER.encode(text))
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=0,
        text=text,
        token_count=token_count,
        filename=filename,
        distance=0.1
    )

class TestPromptBuilder:
    def test_build_context_fits_under_budget(self):
        # We know each label "[doc.pdf]\n" is around 4-5 tokens.
        # Let's create chunks that easily fit within 3000 together,
        # and one that pushes it over.
        from app.services.prompt import context_truncated_total
        initial_val = context_truncated_total._value.get()
        
        # 1 token per word (roughly)
        chunk1 = make_chunk("word " * 500, "doc.pdf")
        chunk2 = make_chunk("word " * 2000, "doc.pdf")
        chunk3 = make_chunk("word " * 600, "doc.pdf")
        
        chunks = [chunk1, chunk2, chunk3]
        context, included = build_context_block(chunks)
        
        assert len(included) == 2
        assert included == [chunk1, chunk2]
        assert "word" in context
        assert context_truncated_total._value.get() == initial_val + 1

    def test_build_context_skips_large_chunk(self):
        from app.services.prompt import context_truncated_total
        initial_val = context_truncated_total._value.get()
        
        # A chunk that is larger than the budget alone
        chunk1 = make_chunk("word " * 3100, "doc.pdf")
        # A small chunk that fits
        chunk2 = make_chunk("word " * 10, "doc.pdf")
        
        context, included = build_context_block([chunk1, chunk2])
        assert len(included) == 1
        assert included == [chunk2]
        assert context_truncated_total._value.get() == initial_val + 1

    def test_build_messages_with_no_chunks(self):
        messages, included = build_messages([], "What is life?")
        assert len(included) == 0
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "(No relevant content found in the uploaded documents" in messages[1]["content"]
        assert "What is life?" in messages[1]["content"]

    def test_build_messages_with_chunks(self):
        chunk = make_chunk("The answer is 42.", "hitchhiker.pdf")
        messages, included = build_messages([chunk], "What is the answer?")
        
        assert len(included) == 1
        assert "hitchhiker.pdf" in messages[1]["content"]
        assert "The answer is 42." in messages[1]["content"]
        assert "What is the answer?" in messages[1]["content"]
