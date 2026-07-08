import tiktoken
from typing import cast, TYPE_CHECKING
from openai.types.chat import ChatCompletionMessageParam
from prometheus_client import Counter

from app.core.config import settings
from app.services.retrieval import RetrievedChunk

if TYPE_CHECKING:
    from app.models.message import Message

context_truncated_total = Counter(
    "pdftalk_context_truncated_total",
    "Total times context chunks were truncated to fit the token budget",
)

# Budget constants
CONTEXT_TOKEN_BUDGET = settings.CONTEXT_TOKEN_BUDGET
ENCODER = tiktoken.get_encoding("cl100k_base")  # matches chunking.py + gpt-4o-mini / text-embedding-3-small


SYSTEM_PROMPT = """You are a knowledgeable document assistant. Answer the user's question using ONLY the context provided below.

## Output format — follow this EXACTLY

Your response MUST use Markdown like this example:

---
Here is a brief overview of the document:

- **Point one** with relevant detail here [filename.pdf](citation:123e4567-e89b-12d3-a456-426614174000)
- Another point with a **key number like 42%** explained briefly [filename.pdf](citation:123e4567-e89b-12d3-a456-426614174000)
- Third point continuing the structured answer [filename.pdf](citation:123e4567-e89b-12d3-a456-426614174000)
---

Rules you must never break:
1. ALWAYS use `- ` bullet points on separate lines — never run bullets together in a single paragraph
2. Bold (**...**) numeric values, scores, dates, or standout quantities — only where the number is notable
3. One short optional lead sentence is allowed; then go straight to bullets
4. Cite the source document at the end of each bullet using a Markdown link in this EXACT format: `[filename](citation:document_id)`. Do NOT use raw text like `[filename]`.
5. If the user's question cannot be answered from the provided context, respond helpfully like this
   (adapt the wording naturally — do NOT copy this verbatim):

   "That's a great question! Based on the document(s) you've shared, I can see this covers
   [brief inferred topic from the context or filenames]. While I'm not able to answer
   [concise restatement of the user's question] from the content here, here are some
   things I *can* help you with from this document:

   - **[Relevant topic 1 visible in context]** — I can explain or summarise this [filename.pdf](citation:uuid)
   - **[Relevant topic 2 visible in context]** — ask me for more detail [filename.pdf](citation:uuid)
   - **[Relevant topic 3 visible in context]** — this might be related to what you need [filename.pdf](citation:uuid)

   Try rephrasing your question around any of the above, or ask me to summarise the document."

   Important: even in this fallback, cite real document chunks from the context using the citation link format.
6. Do not make up facts or use knowledge outside the provided context.
7. NEVER say \"I don't have enough information\". Always pivot to what you *can* help with."""

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
        # Each chunk is formatted as: [filename | document_id]\n{text}\n
        # Count the label overhead too so the budget is accurate
        label = f"[{chunk.filename} | {chunk.document_id}]\n"
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
        parts.append(f"[{chunk.filename} | {chunk.document_id}]\n{chunk.text}")

    context_block = "\n\n---\n\n".join(parts)
    return context_block, included


def build_history_block(messages: list["Message"], budget: int | None = None) -> list[dict[str, str]]:
    if budget is None:
        budget = settings.HISTORY_TOKEN_BUDGET
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
        # All chunks were either too large to fit the budget or were filtered
        # out by the distance threshold — degenerate case.
        # Provide a hint so the LLM knows exactly which rule to apply.
        context_block = (
            "(No relevant content found in the uploaded documents for this query. "
            "Apply Rule 5 of your instructions: respond warmly, acknowledge what "
            "the document(s) appear to cover based on any filenames or prior "
            "conversation context, and guide the user toward questions you *can* answer.)"
        )

    user_message = f"""Context:
{context_block}

Question: {question}"""

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if history_messages:
        messages.extend(build_history_block(history_messages))

    messages.append({"role": "user", "content": user_message})

    return cast(list[ChatCompletionMessageParam], messages), included_chunks
