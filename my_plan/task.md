# T-72 · Persistent Chat History — Implementation Plan

**Depends on:** T-22 (auth), T-27 (document ownership), T-34/T-37 (retrieval + prompt builder), T-39/T-40 (SSE streaming), T-69 (metrics)
**Blocks:** Nothing downstream yet — this is additive to the existing query path.

This plan sequences the work so each step lands independently testable, in an order that de-risks the parts most likely to break existing behavior (`/query/ask`) before building UI on top of them.

---

## Locked Design Decisions

| Decision | Resolution |
|---|---|
| Auto-naming | Created as `"New Chat"` → after first user message, if title is still `"New Chat"`, overwrite with a truncated version of the question. `PATCH` rename always available; auto-title never fires again once overwritten. |
| Conversation context bounding | Token-budgeted truncation, walked newest→oldest, separate budget from document context. |
| Document deletion mid-chat (partial) | Chat continues, flags missing doc(s), query still works with remaining documents. |
| Document deletion mid-chat (all) | `409` error — chat is unusable, must be deleted. |
| `document_ids` storage | `JSONB` column on `Chat`, no join table. |
| Partial stream durability | `Message.status` field (`complete` / `truncated`) so partial assistant responses survive disconnects/crashes. |
| Chat deletion | Hard delete — no soft-delete/archive. |
| Token budget split | Documents: 3,000 tokens (existing, unchanged). History: 1,500 tokens (new). |
| `POST /chats` rate limit | 10/min/user. |

---

## T-72.1 — Database Models + Migration

**Files:** `backend/app/models/chat.py`, `backend/app/models/message.py`, new Alembic revision

### Why this goes first
Everything else — service layer, router, frontend — depends on the schema existing. Getting the schema wrong here means a second migration later to fix column types or relationships mid-build, which costs more than spending extra time up front.

### `Chat` model

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | PK, `gen_random_uuid()` default — matches existing `users`/`documents` pattern (T-04) |
| `user_id` | `UUID` | FK → `users.id`, `ON DELETE CASCADE` — same cascade behavior as `documents` |
| `title` | `TEXT NOT NULL DEFAULT 'New Chat'` | No DB-level length cap; truncation happens before insert |
| `document_ids` | `JSONB NOT NULL DEFAULT '[]'` | List of UUID strings. JSON chosen over a native UUID array because SQLAlchemy's JSONB mapping is simpler to work with (`list[str]` in/out, no array-type quirks between asyncpg and the ORM) |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` | **Must be bumped on every new message**, not just on rename — the sidebar sort is `ORDER BY updated_at DESC`. The message-insert code path in T-72.4 needs to touch the parent `Chat` row too. Flagging now so it isn't forgotten later. |

### `Message` model

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | PK |
| `chat_id` | `UUID` | FK → `chats.id`, `ON DELETE CASCADE` |
| `role` | Postgres native enum (`user`, `assistant`, `system`) | Same approach as `Document.status` — DB rejects garbage values, not just app-layer validation |
| `content` | `TEXT NOT NULL` | |
| `token_count` | `INTEGER NOT NULL` | Computed once at write time via `tiktoken`. Stored so T-72.3's history-budgeting walk never re-tokenizes old messages on every request. This is a deliberate denormalization for performance — worth a one-line comment in the model file so a future reader doesn't think it's redundant and remove it. |
| `status` | Enum (`complete`, `truncated`) | Default `complete` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` | |

### Indexes

- `idx_chats_user_id_updated_at ON chats(user_id, updated_at DESC)` — composite, not two single-column indexes, because it matches the sidebar's exact query pattern: `WHERE user_id = ? ORDER BY updated_at DESC`.
- `idx_messages_chat_id_created_at ON messages(chat_id, created_at)` — history hydration is always "all messages for this chat, in order."

### Migration mechanics

Same gotcha as T-04: create enums and tables in one revision, write a clean `downgrade()` that drops tables *before* enums (Postgres won't let you drop an enum type while a column still references it). Test `alembic downgrade -1` actually works before moving on.

### Open decision to make here, not later

Should `Chat.document_ids` allow an empty list at the DB level, or should the constraint live entirely in the service layer? **Recommendation:** DB allows it, service layer enforces non-empty on create. Keeps the migration simple and validation logic in one place (Python), not split across two layers.

---

## T-72.2 — Chat CRUD Service + Router

**Files:** `backend/app/services/chats.py`, `backend/app/routers/chats.py`

### Why this is safe to build before touching `/query/ask`
Nothing here is called by existing code. You can ship this entire step, deploy it, and the live app behaves identically to today — `/query/ask` still takes `document_ids` directly. This is the "build with zero blast radius" step.

### Service layer — what lives here vs. the router

Per the established thin-router pattern: the router parses the request, calls the service, returns the response. All logic lives in `services/chats.py`.

**`create_chat(user_id, document_ids, db) -> Chat`**
- Validates `document_ids` is non-empty.
- Validates every ID is owned by `user_id` AND has `status == READY`. This is the same check `/query/ask` already does today (T-37's query validation) — **extract it into a shared function** both `chats.py` and `query.py` call, rather than reimplementing it. Prevents the two checks drifting out of sync later.
- Inserts the row, returns it.
- Raises a typed exception (e.g. `InvalidDocumentSelectionError`) on failure — the router translates that to the right HTTP status. Never raise `HTTPException` directly from the service, matching the centralized exception handler pattern already in use.

**`list_chats(user_id, limit, offset, db) -> list[Chat]`**
- Paginated, owned-only filter baked into the query itself — no path where a user can list someone else's chats by manipulating pagination params.

**`get_chat_with_messages(chat_id, user_id, db) -> ChatDetail`**
- Ownership check first — if `chat.user_id != user_id`, raise a "not found" exception so the router returns `404`, not `403`. Same enumeration-prevention logic as document ownership (T-27): a user probing random chat UUIDs should learn nothing.
- Loads all messages, ordered by `created_at`.
- Computes `missing_document_ids` here — diff `chat.document_ids` against a live query of the `documents` table for ones that are owned, exist, and aren't deleted. **This is computed on every read, not stored** — storing it would mean updating chat rows whenever documents are deleted, which is more moving parts for no benefit, since document deletion happens independently of any chat.

**`rename_chat(chat_id, user_id, new_title, db)`**
- Ownership check, update `title`, bump `updated_at`.

**`delete_chat(chat_id, user_id, db)`**
- Ownership check, delete. Messages cascade via the FK — a single DELETE statement, no manual cleanup needed.

### Router — the rate limiter detail

`POST /chats` gets its own Redis sliding-window dependency at **10/min/user**, reusing the exact mechanism from T-42 but with a new key namespace: `ratelimit:chat_create:{user_id}`. This reuses the existing `RateLimiter` class/dependency with different params — not a new rate-limiting system. Worth double-checking the T-42 implementation supports per-*user* (not just per-IP) limiting, since login/register are IP-based but this one needs to key off the authenticated user.

### Testing shape

Integration tests against real Postgres (per existing pattern — not SQLite, to avoid the UUID/timezone quirks already documented in project learnings). Specifically test:
- Creating a chat with someone else's document ID → rejected.
- Creating a chat with a non-READY document → rejected.
- `GET /chats/{id}` for a chat you don't own → `404`, not `403`.
- `missing_document_ids` correctly reflects a deleted document without the chat row itself being updated.

---

## T-72.3 — Prompt Builder: History Budgeting

**Files:** `backend/app/services/prompt.py` (extend, don't rewrite)

### Why this is isolated from the DB and from query.py
It's a pure function — `list[Message-like objects]` in, `string` out. No async, no DB session, no OpenAI call. This makes it the cheapest thing to get exhaustively right with unit tests, and bugs caught here never reach production streaming.

### The algorithm

```
function build_history_block(messages, budget=1500):
    messages are already ordered oldest→newest from the DB
    reverse to walk newest→oldest
    accumulated_tokens = 0
    selected = []
    for message in reversed(messages):
        if accumulated_tokens + message.token_count <= budget:
            selected.insert(0, message)   # maintain chronological order in output
            accumulated_tokens += message.token_count
        elif selected is empty (this is the most recent message and it alone exceeds budget):
            truncate message.content to fit remaining budget, using tiktoken to cut at a token boundary
            selected.insert(0, truncated_message)
            break
        else:
            break   # older messages don't fit, stop here
    return format selected messages as the conversation block
```

### Why truncate the most recent message instead of dropping it

If you drop it, a follow-up like "what about the second point you mentioned" has nothing to anchor to — the LLM sees the question but not what it's referencing, and either hallucinates or asks the user to repeat themselves, defeating the entire purpose of stateful chat.

**Truncation direction is a real choice, not arbitrary:** keep the end of the most recent assistant message and the full user message — since the user's question is almost always short, and the assistant's prior answer is what tends to run long. Decide this explicitly when writing the function rather than picking by default.

### Where this plugs into the existing prompt builder

T-37's `services/prompt.py` already caps document context at 3,000 tokens. This is a **second, independent function** in the same file — `build_history_block()` — not a merge into one shared token pool. They're separate concerns:
- Document context answers "what does the source material say."
- History answers "what have we already discussed."

Keeping them as separate capped blocks means a long conversation never eats into the budget reserved for grounding the answer in actual PDF content — which is the whole point of RAG. You don't want the model losing document grounding just because the conversation got long.

### Testing

Construct fake message lists with known token counts (mock `token_count` directly, no real `tiktoken` calls needed for this layer), assert exactly which messages survive the budget cut at various total lengths, and specifically test the single-oversized-message truncation path since it's the trickiest branch.

---

## T-72.4 — `/query/ask` Rewrite

**Files:** `backend/app/routers/query.py`, `backend/app/services/query_validation.py` (modify)

### Why this is sequenced last among backend work

This is the only step touching code that's live in production today and working. Everything before it (T-72.1–72.3) is net-new and additive — if the project stopped here, nothing breaks. This step is where risk concentrates, so by the time it's reached, chats exist and are tested, and history-budgeting is tested. This step becomes "wire two known-good things together" rather than "build three new things and hope they compose correctly under streaming."

### 1. Schema change

Request body goes from `{document_ids, question}` to `{chat_id, question}`. This is a **breaking API change** — any existing frontend code or tests hitting the old shape need updating in lockstep. Not a backend-only change in practice, even though it's filed under backend work.

### 2. Validation rewrite — the real behavioral nuance

**Old behavior (T-37):** all `document_ids` in the request must be owned + READY, or the whole request fails.

**New behavior:** fetch `chat.document_ids`, then filter:
- Not owned anymore (shouldn't happen since ownership was checked at chat creation, but defensive check anyway)
- Doesn't exist anymore (deleted) — filter out
- Exists but not READY (shouldn't happen if READY is a genuinely terminal state — worth confirming this assumption holds before relying on it)

Then count what remains:
- **Zero remain** → `409 {"error": "ALL_DOCUMENTS_DELETED", ...}`. New error code — needs an entry in the centralized exception handler and a corresponding mapping in the frontend's error-code-to-message system (T-53's toast mapping).
- **One or more remain** → proceed, compute `missing_document_ids` as the diff between the original `chat.document_ids` and the filtered set, so the frontend can show *which* documents vanished.

### 3. Pre-stream message save

Before retrieval/embedding/LLM call starts, insert the user's `Message` row (`role=user, status=complete`). This means even if everything after this point fails — OpenAI is down, retrieval throws — the user's question is preserved in history. Small but real durability win: nobody wants to retype a question because the server 503'd on the same request.

### 4. SSE shape change — the meta event

Before any token streaming begins, emit one extra SSE event:

```
event: meta
data: {"missing_document_ids": ["..."]}

```

followed by the existing `data: {token}` stream and `data: [DONE]` terminator. This is additive to the existing SSE contract — old token/done events are unchanged, there's just one new event type the frontend needs to listen for.

### 5. The durability problem — the trickiest part of this task

**The core issue:** streaming responses terminate in three ways:
1. Clean completion (`[DONE]` sent)
2. Client disconnect (user closes tab mid-answer)
3. Server-side error mid-stream (OpenAI errors out after sending some tokens)

In all three cases, *some* text was already generated and sent to the client. If the `Message` row is only written in the happy path (after `[DONE]`), the other two cases lose that text entirely — the user saw an answer on screen, refreshes, and it's gone.

**The fix is structural:** wrap the token-generator consumption in a `try/finally`, where the `finally` block always writes whatever text was accumulated so far, with `status` set based on how it terminated:
- Reached `[DONE]` normally → `status=complete`
- Anything else (exception, detected disconnect) → `status=truncated`

This mirrors the existing pattern for `job_logs` — never let a failure path silently lose state, always write what you have.

**The mechanical challenge:** FastAPI's `StreamingResponse` consumes an async generator, and detecting "the client disconnected" inside that generator requires either periodically checking `request.is_disconnected()` or catching the specific exception Starlette raises on disconnect. This is the one part of this entire task worth prototyping carefully and testing with an actual simulated disconnect (a test that opens the stream and closes the connection after N tokens) rather than reasoning about it abstractly — async generator cleanup semantics in Python have sharp edges.

### 6. `updated_at` bump

Both the user-message save and the assistant-message save need to touch `chat.updated_at`, otherwise sidebar ordering (T-72.2's `list_chats`) goes stale the moment a chat is actively used. Easy to forget since it's a side effect on a different table than the one being directly written to.

### 7. Metrics

- `messages_total{role="user"}` — increments at the pre-stream save
- `messages_total{role="assistant"}` — increments at the post-stream save, regardless of `complete` vs. `truncated` (still want to count it)
- `chat_query_blocked_total{reason="all_documents_deleted"}` — increments on the 409 path
- `queries_total` (already existing) — stays exactly where it is today

### Testing — four distinct scenarios

1. **Normal flow:** chat with all documents intact, question asked, full streamed response, `Message` rows for both user and assistant exist with `status=complete`.
2. **Partial-missing flow:** one of two documents deleted, query still succeeds, `meta` event contains the missing ID, retrieval only used the remaining document.
3. **All-missing flow:** both documents deleted, `409` returned, decide whether the user's `Message` row still gets created or not, metric incremented.
4. **Simulated disconnect:** start the stream, forcibly close the connection partway through, then query the DB separately and assert a `Message` row exists with `status=truncated` and partial content matching what was sent before the cut.

---

## T-72.5 — Frontend: API Client + Chat State

**Files:** `frontend/src/lib/api.ts` (extend), new `frontend/src/lib/chats.api.ts`

### Why this comes after the backend is integration-tested, not in parallel

Building UI against an API contract that might still shift (because T-72.4 surfaced something unexpected) wastes rework. Once T-72.4's tests pass, the contract is stable and this step becomes mechanical.

### `chats.api.ts`

Five typed functions mirroring the five endpoints — `listChats()`, `createChat(documentIds)`, `getChat(chatId)`, `renameChat(chatId, title)`, `deleteChat(chatId)` — following the existing `ApiError` pattern from `lib/api.ts` (T-47), so a failed request throws a typed error the UI can branch on, not a raw fetch rejection.

### The more involved part: updating the existing `/query/ask` client call

Today, this function takes `document_ids` and `question`, opens the SSE stream, and parses `data:` lines. It now needs to:
- Take `chat_id` instead of `document_ids`.
- **Parse SSE event types, not just `data:` lines.** The existing parser (from T-39's frontend pattern) only looks for lines starting with `data:`. It needs extending to also recognize `event: meta` lines and route that payload to a different callback than the token-stream callback. This is a real parser change, not just a parameter rename — treat it as its own small unit of work with its own test (feed it a fake SSE byte stream containing a meta event + token events + `[DONE]`, assert both callbacks fire with the right payloads in the right order).

### Done-when

No visible UI yet at this step — purely the typed client layer. "Done" means it compiles, is typed against the real response shapes (no `any`), and has a unit test for the SSE parsing change specifically, since that's the part most likely to have an off-by-one bug in line-splitting logic.

---

## T-72.6 — Frontend: Sidebar + Chat Window Integration

**Files:** `frontend/src/components/chat/ChatSidebar.tsx`, modified dashboard/chat page

### Sidebar component

- Fetches `listChats()` on mount, renders title + relative timestamp (e.g. "2h ago") per row.
- Highlights whichever chat matches the currently-active `chat_id` in state.
- **"New Chat" button does not call `POST /chats`.** It only clears local state (`activeChatId = null`, message list = empty, document selection reset or kept, per UX preference). This avoids a real bug: if "New Chat" eagerly created a row, a user clicking it three times while deciding what to ask ends up with three empty "New Chat" rows cluttering the sidebar forever (since `DELETE` is hard-delete and nothing auto-cleans empty chats). Deferring creation until the first actual message is sent avoids this class of orphan entirely.

### Main chat view changes

- State needs an explicit `activeChatId: string | null`, separate from the message list and document selection — these were previously coupled (documents picked per-query) and now need to be three independent pieces of state, set together only at the moment a chat is created or loaded.
- **Send flow when `activeChatId` is null:** call `createChat(selectedDocumentIds)` first, get back a `chat_id`, then immediately start the SSE stream using that new ID. The send button's click handler now has two sequential async steps instead of one. Worth handling the case where chat creation succeeds but the immediately-following stream fails (rare, but the chat now exists with zero messages — the UI naturally recovers since `listChats()` will include it, letting the user click back in).
- **Send flow when `activeChatId` exists:** skip straight to streaming, no creation call.
- **On chat select from sidebar:** `getChat(chatId)` → populate message list, set `activeChatId`, render `missing_document_ids` (if any) as a small persistent banner/badge in the chat header — not a toast, since toasts disappear and this is a standing condition the user should see for as long as they're in that chat.
- **Handling the `409 ALL_DOCUMENTS_DELETED` case specifically:** must be caught before falling into the generic `ApiError`-to-toast mapping (T-53) — a generic "something went wrong" toast is the wrong UX here. The user needs to understand why (all documents gone) and what to do (delete the chat). This is a dedicated UI state: a full-width message in place of the chat window, with a "Delete this chat" button wired to `deleteChat()`.
- **Rename UI:** inline-editable title (click to edit, blur/enter to save) is the lowest-friction pattern and avoids a modal for something this small — wired to `renameChat()`.

### Manual verification checklist

1. Create new chat → send message → streams correctly → message appears in sidebar with truncated title.
2. Refresh page → chat history loads, correct messages in correct order.
3. Ask a follow-up referencing the previous answer → confirm the model actually has context (not just that it doesn't error).
4. Delete a document attached to an active chat → reload that chat → confirm the missing-doc badge appears and the chat still answers using the remaining document.
5. Delete *all* documents attached to a chat → confirm the dedicated error state renders, not a generic toast → delete the chat → confirms it's gone from sidebar.
6. Click "New Chat" multiple times without sending anything → confirm the sidebar doesn't accumulate empty entries.
7. Rename a chat → refresh → confirm the rename persisted and a new message doesn't overwrite it. (This is really testing T-72.4's "only auto-title if still `New Chat`" guard, which lives in the backend message-save path — worth noting which layer actually owns the behavior being verified, even though the test is run through the UI.)

---

## T-72.7 — Metrics + Alerting Wiring

**Files:** `backend/app/utils/metrics.py` (extend); no new Grafana dashboard required yet

### Why this is low-priority and parallelizable

Nothing depends on it, and nothing breaks without it — purely diagnostic visibility, not functionality. This is the kind of task that's easy to skip under time pressure, which is exactly why it's worth scheduling explicitly rather than leaving it as an implicit "do it whenever" — implicit low-priority tasks are the ones that silently never happen.

### The three metrics

| Metric | Labels | Why |
|---|---|---|
| `chats_created_total` | none | Simple counter — no per-user label, consistent with the existing cardinality warning already documented for `queries_total` |
| `messages_total` | `role` (`user`/`assistant`) | Small, fixed cardinality (2–3 values); operationally useful to see the ratio drift if, say, assistant saves silently start failing while user saves keep succeeding |
| `chat_query_blocked_total` | `reason` | Currently just `all_documents_deleted`, but structured so more reasons can be added later via the label, not a schema change |

### Registration

Module-level singletons in `app/utils/metrics.py`, imported and never instantiated inside a function — consistent with the existing rule about avoiding double-registration `ValueError`s.

### Dashboard/alerting — deferred, correctly

No new Grafana panel or Alertmanager rule in this task. At current scale, these are numbers to check occasionally, not numbers that need to page anyone at 2am. If `chat_query_blocked_total` starts climbing in a way that suggests a real problem (e.g. a bug deleting documents that shouldn't be deleted), that signal would show up on existing dashboards or the admin stats page first — a dedicated alert rule can be added later if it proves warranted, rather than speculatively now.

---

## Suggested Build Order

1. **T-72.1 → T-72.2** first, in isolation. Nothing else depends on `query.py` yet, so this delivers a fully working, testable chat CRUD layer with zero risk to the live `/query/ask` endpoint.
2. **T-72.3** next, also isolated. Pure function, no risk.
3. **T-72.4** last among backend work, deliberately — the only step touching already-working production code. By this point chats exist and history budgeting is tested, so this step is "wire two known-good things together," not "build three things at once under risk."
4. **Frontend (T-72.5 → T-72.6)** only after T-72.4 is integration-tested. Building UI against an unstable contract wastes time.
5. **T-72.7** can run in parallel with T-72.2 onward — low-risk, low-priority, slot in whenever convenient.

---

## Decisions Deferred to Build Time (Not Now)

- Exact truncation length for auto-titles (50 characters was a working suggestion, not yet confirmed).
- Whether `ChatSidebar` paginates or loads-all — depends on real usage volume once the feature ships; don't over-engineer ahead of data.
- Truncation direction for the single-oversized-message case in T-72.3 (keep start vs. end of content) — flagged as a real choice above, decide explicitly when writing the function.
