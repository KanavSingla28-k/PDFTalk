# T-52a · Markdown Rendering for Chat Messages

> **Type:** Frontend enhancement (sub-task of T-52 — Chat / Q&A UI)
> **Phase:** 10 — Frontend
> **Depends on:** T-52 (SSE streaming chat UI — confirmed live in `src/app/dashboard/chat/page.tsx` + `ChatContext.tsx`)
> **Blocks:** T-53 (error boundary / responsive polish should land after this)
> **Estimated effort:** 1.5–2 hours (smaller than originally scoped — see §2)

This revision replaces the first draft after reviewing the actual frontend source. The plan now targets real file paths, the real `ChatMessage` function, the real CSS variable names from `globals.css`, and the actual dependency set in `package.json` / `pnpm-lock.yaml`.

---

## 1. Why this task exists

`gpt-4o-mini` streams Markdown-structured text (`**bold**`, numbered lists, code fences) through `streamAnswer()` in `query.api.ts`, token by token, into `ChatContext.tsx`'s `activeChat.messages` state. The chat page currently renders that accumulated string as literal text inside a `whitespace-pre-wrap` div (`page.tsx`, `ChatMessage` function, lines ~140–160). Users see raw asterisks and hash marks instead of formatting.

This is a pure rendering change. Nothing in `query.api.ts`, `ChatContext.tsx`, or the backend SSE protocol changes.

---

## 2. What's different from the original draft, now that the real code is visible

| Item | Original assumption | Actual codebase | Plan adjustment |
|---|---|---|---|
| Component location | Separate `ChatMessage.tsx` file | `ChatMessage` is a local function *inside* `src/app/dashboard/chat/page.tsx` (not exported, not in its own file) | Edit in place; no new component directory needed |
| Tailwind version | Assumed v4, unconfirmed | Confirmed v4: `globals.css` starts with `@import "tailwindcss";`, `package.json` has `"tailwindcss": "^4"` and `"@tailwindcss/postcss": "^4"` | `@plugin` directive approach is correct, no fallback needed |
| Brand/surface CSS vars | Guessed names like `--surface-muted`, `--surface-code` | Real tokens in `globals.css`: `--brand-500`, `--gray-50`...`--gray-900`, `--error-50/300/500/700`, `--success-50/500/700`, `--warning-50/500`. **No `--surface-*` or `--text-*` tokens exist** | Rewrite every `prose-*` class and the code-block component to use the actual `--gray-*` / `--brand-*` scale |
| Icon library | Assumed `lucide-react` available | Not installed. Every icon in this codebase (`ui/index.tsx`, `UploadForm.tsx`, `dashboard/layout.tsx`) is **hand-written inline SVG**, zero icon-library dependency anywhere | Copy button uses inline SVG, matching the codebase's existing pattern exactly — don't introduce a new dependency for one icon |
| Citations | Assumed already rendered after the stream, needing isolation from Markdown | **Not implemented yet.** `query.api.ts` has a literal `// TODO: emit 'sources' event if UI needs to display citations` — the `sources` SSE payload is currently discarded | No isolation work needed today since there's nothing to isolate from. Note added in §6 so whoever implements citations later reads it first |
| pnpm version | Generic `pnpm add` | Repo pins pnpm to exactly `11.6.0` (`package.json` `packageManager` field, `Dockerfile`'s `npm install -g pnpm@11.6.0`) | Specify the exact pinned version in install instructions |
| Streaming source | Assumed a generic streaming hook | Real flow: `ChatContext.sendMessage()` mutates `activeChat.messages[last].content += event.content` on every `token` event, fully accumulated string lives in React state already | Confirms "render whatever string exists right now" approach in §5 — no extra buffering work needed |
| User message rendering | Generic | `ChatMessage` already branches on `isUser` with a different bubble style (`bg-[var(--brand-500)] text-white` vs `bg-white border`) | Keep that exact branch structure — only change what happens inside the non-user branch |

---

## 3. Security note (unchanged, still load-bearing)

`react-markdown` does not execute embedded HTML or scripts by default. That property must be preserved:

- Never add `rehype-raw` to the plugin list.
- Never pipe any part of `msg.content` through `dangerouslySetInnerHTML`.
- The streamed text originates from the backend's LLM call, grounded in user-uploaded PDF content — effectively untrusted text that happens to flow through your own API. Treat it accordingly.

---

## 4. Implementation steps

### Step 1 — Install dependencies

```bash
cd frontend
pnpm add react-markdown@9.0.1 remark-gfm@4.0.0
pnpm add -D @tailwindcss/typography@0.5.15
```

Exact pins, not `^` ranges — consistent with how `package.json` already pins exact versions for framework-critical packages (`"next": "15.5.19"`, `"react": "19.2.4"`, `"eslint-config-next": "15.5.19"`).

After this, `pnpm-lock.yaml` regenerates. Confirm `pnpm install --frozen-lockfile` (the exact command `Dockerfile`'s `deps` stage runs) still succeeds before committing the new lockfile — that's the real build gate, not just `pnpm add` exiting cleanly.

---

### Step 2 — Register the Tailwind v4 typography plugin

**File:** `frontend/src/app/globals.css`

```css
@import "tailwindcss";
@plugin "@tailwindcss/typography";

/* ─── Design tokens ──────────────────────────────────────────────────── */
:root {
  /* ... existing content, completely unchanged ... */
```

One line added, directly below the existing `@import "tailwindcss";`. Nothing else in this file changes — all the `--brand-*`, `--gray-*`, `--error-*`, `--success-*`, `--warning-*` tokens stay exactly as they are; Step 3 builds on top of them rather than inventing new ones.

---

### Step 3 — Edit `ChatMessage` in place (no new file needed)

**File:** `frontend/src/app/dashboard/chat/page.tsx`

Current code (for reference, lines ~140–162):

```tsx
function ChatMessage({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';

  return (
    <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-5 py-3.5 shadow-sm ${
          isUser
            ? 'bg-[var(--brand-500)] text-white rounded-br-none'
            : msg.isError
            ? 'bg-[var(--error-50)] text-[var(--error-700)] border border-[var(--error-200)] rounded-bl-none'
            : 'bg-white text-[var(--gray-900)] border border-[var(--gray-200)] rounded-bl-none'
        }`}
      >
        <div className="whitespace-pre-wrap text-sm leading-relaxed">
          {msg.content}
          {msg.isStreaming && (
            <span className="inline-block ml-1 h-3 w-1.5 animate-pulse bg-current opacity-60" />
          )}
        </div>
      </div>
    </div>
  );
}
```

Note in passing: `border-[var(--error-200)]` is referenced here but `--error-200` isn't defined in `globals.css` (only `--error-50/300/500/700` exist). Pre-existing gap, unrelated to this task — left as-is below rather than silently "fixed" as a drive-by change.

New code — only the inner content block changes; the outer bubble/role logic is untouched:

```tsx
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';

// ─── Markdown code block (fenced ``` blocks only — inline `code` falls
// through to prose-code:* classes below and isn't touched by this) ──────────

function CodeBlock({ className, children }: { className?: string; children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const language = className?.replace('language-', '') ?? 'text';
  const code = String(children).replace(/\n$/, '');

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-[var(--gray-200)]">
      <div className="flex items-center justify-between bg-[var(--gray-50)] px-3 py-1.5 text-xs text-[var(--gray-500)]">
        <span className="font-mono">{language}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 transition-opacity hover:opacity-100"
          style={{ opacity: copied ? 1 : 0.6 }}
          aria-label="Copy code"
        >
          {copied ? (
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M3 7l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <rect x="9" y="9" width="13" height="13" rx="2" />
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
          )}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="m-0 overflow-x-auto bg-[var(--gray-25)] p-3 text-sm">
        <code className={className}>{code}</code>
      </pre>
    </div>
  );
}

const markdownComponents: Components = {
  code(props) {
    const { children, className, ...rest } = props;
    const isInline = !className?.includes('language-');
    if (isInline) {
      return <code className={className} {...rest}>{children}</code>;
    }
    return <CodeBlock className={className}>{children}</CodeBlock>;
  },
};

function ChatMessage({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user';

  return (
    <div className={`flex w-full ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-5 py-3.5 shadow-sm ${
          isUser
            ? 'bg-[var(--brand-500)] text-white rounded-br-none'
            : msg.isError
            ? 'bg-[var(--error-50)] text-[var(--error-700)] border border-[var(--error-300)] rounded-bl-none'
            : 'bg-white text-[var(--gray-900)] border border-[var(--gray-200)] rounded-bl-none'
        }`}
      >
        {isUser ? (
          // User input stays plain text — preserves whitespace exactly as
          // typed and never interprets typed *asterisks* or _underscores_
          // as Markdown.
          <div className="whitespace-pre-wrap text-sm leading-relaxed">
            {msg.content}
          </div>
        ) : msg.isError ? (
          // Error bubbles also stay plain text — these are short strings
          // from getSseErrorMessage(), not LLM output, and don't need
          // Markdown parsing.
          <div className="whitespace-pre-wrap text-sm leading-relaxed">
            {msg.content}
          </div>
        ) : (
          <div
            className="
              prose prose-sm max-w-none text-sm leading-relaxed
              prose-p:my-2 prose-headings:my-2 prose-headings:font-semibold
              prose-a:text-[var(--brand-600)] prose-a:no-underline hover:prose-a:underline
              prose-strong:text-[var(--gray-900)]
              prose-code:rounded prose-code:bg-[var(--gray-100)] prose-code:px-1 prose-code:py-0.5
              prose-code:text-[var(--brand-700)] prose-code:before:content-none prose-code:after:content-none
              prose-pre:bg-transparent prose-pre:p-0 prose-pre:m-0
              prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5
              prose-blockquote:border-l-[var(--brand-300)] prose-blockquote:text-[var(--gray-600)]
            "
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {msg.content}
            </ReactMarkdown>
          </div>
        )}
        {msg.isStreaming && (
          <span className="inline-block ml-1 h-3 w-1.5 animate-pulse bg-current opacity-60" />
        )}
      </div>
    </div>
  );
}
```

Two structural notes versus the original draft:

1. **Error bubbles (`msg.isError`) now get their own explicit plain-text branch**, rather than falling into the Markdown path. A stray `*` in an error string like *"AI service went down mid-response"* shouldn't ever be parsed as emphasis.
2. **The streaming cursor (`msg.isStreaming` span) stays outside all three branches**, exactly matching today's placement — it appears after whichever content rendered, regardless of which branch ran.

`useState` is already imported at the top of `page.tsx` (`import { Suspense, useState, useEffect, useRef, FormEvent } from 'react';`), so `CodeBlock`'s `useState` call needs no new import line.

---

### Step 4 — Verify the exact `prose-*` color choices against `globals.css`

Quick gut-check before merging — every var referenced above, checked against the real file:

| Class used | Token | Defined in `globals.css`? |
|---|---|---|
| `prose-a:text-[var(--brand-600)]` | `--brand-600: #444ce7;` | ✅ |
| `prose-strong:text-[var(--gray-900)]` | `--gray-900: #101828;` | ✅ |
| `prose-code:bg-[var(--gray-100)]` | `--gray-100: #f2f4f7;` | ✅ |
| `prose-code:text-[var(--brand-700)]` | `--brand-700: #3538cd;` | ✅ |
| `prose-blockquote:border-l-[var(--brand-300)]` | `--brand-300: #a4bcfd;` | ✅ |
| `bg-[var(--gray-25)]` (code block background) | `--gray-25: #fcfcfd;` | ✅ |
| `border-[var(--gray-200)]` | `--gray-200: #eaecf0;` | ✅ |

All real, all already defined — no new CSS variables introduced by this task.

---

### Step 5 — `package.json` / CI check

CI (`T-58`) runs `pnpm install --frozen-lockfile` then `pnpm type-check && pnpm lint && pnpm test`. Before pushing:

- `pnpm type-check` — `react-markdown@9` ships its own `.d.ts`, no `@types/react-markdown` needed. Importing `Components` (`import type { Components } from 'react-markdown'`) types the `code()` render-prop without resorting to `any`.
- `pnpm lint` — `eslint.config.mjs` extends `next/core-web-vitals` + `next/typescript`, plus `eslint-plugin-prettier`. The inline-SVG + template-literal style added here matches what's already throughout `page.tsx`, so it should pass without new exceptions.
- `pnpm test` — `frontend/src/app/page.test.tsx` is the only existing test, targets the unrelated root `page.tsx`. Not required to add a new test for this task, but a cheap regression guard would be: render `<ChatMessage msg={{ id: '1', role: 'assistant', content: '**bold** text' }} />` and assert the literal string `**bold**` is absent from the rendered output.

---

### Step 6 — Docker rebuild reminder

This change adds no new env vars, but it does change `frontend/package.json` and `pnpm-lock.yaml`. The `deps` stage in `frontend/Dockerfile` does `COPY package.json pnpm-lock.yaml* ... && pnpm install --frozen-lockfile`, cached as a layer keyed on those two files' content hash. Since both change here, Docker's own layer cache invalidates automatically on the next build — unlike `NEXT_PUBLIC_*` env-var changes, this doesn't require a manual `--no-cache` flag. Still worth one clean local build to be sure: `docker build -t pdftalk-frontend-test ./frontend`.

---

## 5. Streaming + partial Markdown — confirmed behavior, no extra code needed

The real flow in `ChatContext.tsx`:

```tsx
} else if (event.type === 'token') {
  setActiveChat(prev => {
    if (!prev) return prev;
    const newMessages = [...prev.messages];
    const lastMsg = newMessages[newMessages.length - 1];
    if (lastMsg.id === tempAssistantId) {
      lastMsg.content += event.content;
    }
    return { ...prev, messages: newMessages };
  });
}
```

Every token triggers a full `setActiveChat` re-render with the growing string. `ChatMessage` already re-renders on every token today (just showing raw text); adding `ReactMarkdown` means each re-render now re-parses the accumulated string instead of dumping it raw. For typical response lengths (a few hundred to low thousands of tokens), that parse cost per token isn't perceptible lag — no debouncing is being added preemptively.

The only visible effect: while `**bold` is mid-stream (closing `**` not yet arrived), it renders as literal `**bold` for a moment, then snaps to bold once the closing marker streams in. Same behavior any Markdown-streaming chat UI has (ChatGPT, Claude.ai itself) — treated as acceptable, not a bug to engineer around.

---

## 6. Note for whoever implements citations next (not part of this task)

`query.api.ts` currently discards the `sources` SSE event:

```tsx
if (parsed.type === 'sources') {
  // TODO: emit 'sources' event if UI needs to display citations
  continue;
}
```

When that TODO gets picked up: render citations as a **separate React element appended after** the `<ReactMarkdown>` block inside the assistant bubble, never concatenated into `msg.content` itself. A source filename like `Q3_2024_report.pdf` contains an underscore, which Markdown's emphasis parsing would silently corrupt if it were part of the string passed to `ReactMarkdown`. This task doesn't touch that flow since it isn't implemented yet, but the constraint is worth stating now so it isn't violated later.

---

## 7. File summary

| Action | Path | Change |
|---|---|---|
| Modify | `frontend/package.json` / `pnpm-lock.yaml` | Add `react-markdown@9.0.1`, `remark-gfm@4.0.0`, `@tailwindcss/typography@0.5.15` (dev) |
| Modify | `frontend/src/app/globals.css` | One line: `@plugin "@tailwindcss/typography";` below the existing `@import` |
| Modify | `frontend/src/app/dashboard/chat/page.tsx` | Add `CodeBlock` function + `markdownComponents` const + two new imports; rewrite the non-user/non-error branch of `ChatMessage` to use `<ReactMarkdown>` wrapped in `prose prose-sm` |

No other files change. No backend, no API contract, no new component directories.

---

## 8. Verification plan

### Manual
1. `pnpm dev` (or rebuild the Docker frontend image), open `/dashboard/chat`, select a `READY` document.
2. Ask: *"Give me a bulleted list of 3 points, bold one term and italicize another."* → confirm real `<ul>`/`<strong>`/`<em>` rendering, not literal markup characters.
3. Ask for a short Python snippet → confirm a bordered code block with a language label and a working Copy button (verify via actual clipboard paste, not just visually).
4. Type `**not bold**` as a *user* message → confirm it renders literally (user branch untouched).
5. Trigger a forced SSE error (e.g. disconnect network mid-stream) → confirm the red error bubble still renders as plain text, not through `ReactMarkdown`.
6. Resize to a 375px-wide viewport → confirm code blocks scroll horizontally (`overflow-x-auto` on `<pre>`) rather than breaking the `max-w-[85%]` bubble layout.
7. DevTools console: zero errors, zero React warnings, throughout.

### CI
- [ ] `pnpm install --frozen-lockfile` succeeds with the updated lockfile
- [ ] `pnpm type-check` passes
- [ ] `pnpm lint` passes
- [ ] `pnpm test` passes (unaffected, but confirm no accidental break)
- [ ] `docker build ./frontend` succeeds cleanly

### Explicit non-goals (unchanged from original, still out of scope)
- No syntax highlighting library (plain monospace + copy button only)
- No Markdown rendering of user-typed input
- No citation rendering (not implemented anywhere yet — see §6)
- No change to `query.api.ts`, `ChatContext.tsx`, or any backend code

---

## 9. Rollback

Single commit touching 3 source files plus the lockfile (`package.json`, `pnpm-lock.yaml`, `globals.css`, `page.tsx`). Revert the commit, redeploy via the normal CD pipeline (T-59). Nothing persisted differently in DB, Redis, or S3 — purely a frontend rendering change.
