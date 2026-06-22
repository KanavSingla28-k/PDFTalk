import tiktoken
from typing import cast, TYPE_CHECKING
from openai.types.chat import ChatCompletionMessageParam
from prometheus_client import Counter

from app.services.retrieval import RetrievedChunk

if TYPE_CHECKING:
    from app.models.message import Message

context_truncated_total = Counter(
    "pdftalk_context_truncated_total",
    "Total times context chunks were truncated to fit the token budget",
)

# Budget constants
CONTEXT_TOKEN_BUDGET = 3_000
ENCODER = tiktoken.get_encoding("cl100k_base")  # matches chunking.py + gpt-4o-mini / text-embedding-3-small


SYSTEM_PROMPT = """You are a precise document assistant. Answer the user's question using ONLY the context provided below.

Rules:
- Cite the source filename in square brackets after each claim, e.g. [report.pdf]
- If the answer is not in the context, say exactly: "I don't have enough information in the provided documents to answer that."
- Do not make up facts, infer beyond the context, or use outside knowledge
- Be concise and direct"""

# ----------------------------------------------------------------------------
# Internal Helpers
# ----------------------------------------------------------------------------

def _count_tokens(text: str) -> int:
    return len(ENCODER.encode(text))

# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def build_context_block(chunks: list[RetrievedChunk]) -> tuple[str, list[RetrievedChunk]]:
    """
    Fit as many whole chunks as possible within CONTEXT_TOKEN_BUDGET.
    Chunks are assumed to arrive pre-ranked by similarity (best first).

    Soft truncation: a chunk is either included in full or dropped entirely.
    A half-chunk mid-sentence adds noise without adding signal.

    Returns:
        - The assembled context string
        - The subset of chunks that were actually included (for citation tracking)
    """
    included: list[RetrievedChunk] = []
    tokens_used = 0

    for chunk in chunks:
        # Each chunk is formatted as: [filename]\n{text}\n
        # Count the label overhead too so the budget is accurate
        label = f"[{chunk.filename}]\n"
        label_tokens = _count_tokens(label)
        chunk_total = chunk.token_count + label_tokens

        if tokens_used + chunk_total > CONTEXT_TOKEN_BUDGET:
            # This chunk would exceed the budget — skip it and keep trying
            # smaller ones that might still fit (chunks are not guaranteed
            # to be uniform size)
            continue

        included.append(chunk)
        tokens_used += chunk_total

    if len(included) < len(chunks):
        context_truncated_total.inc()

    # Build the final context string from the included chunks
    parts: list[str] = []
    for chunk in included:
        parts.append(f"[{chunk.filename}]\n{chunk.text}")

    context_block = "\n\n---\n\n".join(parts)
    return context_block, included


def build_history_block(messages: list["Message"], budget: int = 1500) -> list[dict[str, str]]:
    """
    Fit as many recent messages as possible within the budget.
    Walks newest to oldest, keeping chronological order in the output.
    If the most recent message alone exceeds the budget, it truncates the start
    to keep the most recent context.
    """
    accumulated_tokens = 0
    selected: list[dict[str, str]] = []

    for message in reversed(messages):
        if accumulated_tokens + message.token_count <= budget:
            selected.insert(0, {"role": message.role.value, "content": message.content})
            accumulated_tokens += message.token_count
        elif not selected:
            # This is the most recent message and it alone exceeds budget
            # Truncate to fit remaining budget, keeping the end of the message
            tokens = ENCODER.encode(message.content)
            allowed_tokens = budget - accumulated_tokens
            if allowed_tokens > 0:
                truncated_content = ENCODER.decode(tokens[-allowed_tokens:])
                selected.insert(0, {"role": message.role.value, "content": truncated_content})
            break
        else:
            break   # older messages don't fit, stop here

    return selected

def build_messages(
    chunks: list[RetrievedChunk],
    question: str,
    history_messages: list["Message"] | None = None,
) -> tuple[list[ChatCompletionMessageParam], list[RetrievedChunk]]:
    """
    Assemble the OpenAI messages list for the chat completion call.

    Returns:
        - messages: list ready to pass directly to openai client
        - included_chunks: the chunks that fit the budget (for citation
          tracking in the response — T-39 can surface these to the frontend)
    """
    context_block, included_chunks = build_context_block(chunks)

    if not included_chunks:
        # All chunks were too large individually — degenerate case.
        # Return a context-free prompt; the LLM will hit the "I don't know" rule.
        context_block = "(No context available)"

    user_message = f"""Context:
{context_block}

Question: {question}"""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if history_messages:
        messages.extend(build_history_block(history_messages))

    messages.append({"role": "user", "content": user_message})

    return cast(list[ChatCompletionMessageParam], messages), included_chunks
