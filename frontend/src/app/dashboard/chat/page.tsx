'use client';

import { Suspense, useState, useEffect, useRef, FormEvent } from 'react';
import { useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { listDocuments, type DocumentRecord } from '@/lib/documents.api';
import { streamAnswer, getSseErrorMessage, type StreamEvent } from '@/lib/query.api';
import { ERROR_CODES } from '@/lib/api';
import { Button, Spinner } from '@/components/ui';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';
import { Citation } from '@/components/Citation';
import { useChat } from '@/contexts/ChatContext';
import { ChatSidebar } from '@/components/ChatSidebar';

// ─── Types ───────────────────────────────────────────────────────────────────

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isError?: boolean;
  /** Set to true when the backend emitted a fallback SSE event for this message */
  isFallback?: boolean;
};

// ─── Document Selector Component ──────────────────────────────────────────────

function DocumentSelector({
  documents,
  selectedIds,
  onToggle,
}: {
  documents: DocumentRecord[];
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
}) {
  if (documents.length === 0) {
    return (
      <div className="rounded-lg border border-[var(--warning-200)] bg-[var(--warning-50)] p-4 text-sm text-[var(--warning-700)]">
        You don&apos;t have any ready documents. Upload a document first.
      </div>
    );
  }

  const atLimit = selectedIds.size >= 10;

  return (
    <div className="rounded-xl border border-[var(--gray-200)] bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--gray-900)]">
          Select documents to chat with
        </h2>
        <span
          className={`text-xs font-medium ${
            atLimit ? 'text-[var(--error-500)]' : 'text-[var(--gray-500)]'
          }`}
        >
          {selectedIds.size} / 10 selected
        </span>
      </div>
      <div className="flex max-h-40 flex-wrap gap-2 overflow-y-auto pr-2">
        {documents.map((doc) => {
          const isSelected = selectedIds.has(doc.document_id);
          const isDisabled = !isSelected && atLimit;
          return (
            <label
              key={doc.document_id}
              className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                isSelected
                  ? 'border-[var(--brand-500)] bg-[var(--brand-50)] text-[var(--brand-700)]'
                  : isDisabled
                  ? 'cursor-not-allowed border-[var(--gray-200)] bg-[var(--gray-50)] text-[var(--gray-400)] opacity-60'
                  : 'border-[var(--gray-200)] bg-white text-[var(--gray-700)] hover:bg-[var(--gray-50)] hover:border-[var(--gray-300)]'
              }`}
            >
              <input
                type="checkbox"
                className="hidden"
                checked={isSelected}
                disabled={isDisabled}
                onChange={() => onToggle(doc.document_id)}
              />
              <span className="truncate max-w-[150px]" title={doc.filename}>{doc.filename}</span>
              {isSelected && (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true" className="shrink-0">
                  <path d="M11.667 3.5L5.25 9.917 2.333 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </label>
          );
        })}
      </div>
      {atLimit && (
        <p className="mt-2 text-xs text-[var(--error-500)]">
          You can only select up to 10 documents at a time.
        </p>
      )}
    </div>
  );
}

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
  a(props) {
    const { href, children, ...rest } = props;
    
    // Intercept our custom citation links format: [filename](citation:document_id)
    if (href?.startsWith('citation:')) {
      const documentId = href.replace('citation:', '');
      // Extract filename from the children array if it's text
      let filename = 'Document';
      if (Array.isArray(children) && typeof children[0] === 'string') {
        filename = children[0];
      } else if (typeof children === 'string') {
        filename = children;
      }
      
      // The LLM generates [[filename]](citation:uuid), so react-markdown captures "filename]".
      filename = filename.replace(/^\[|\]$/g, '');
      
      return <Citation filename={filename} documentId={documentId} />;
    }
    
    // Normal links
    return <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>{children}</a>;
  },
};

// ─── Suggestion Chips (shown after fallback responses) ───────────────────────

const SUGGESTION_CHIPS = [
  'Summarise this document',
  'What are the key topics covered?',
  'List the main points',
  'What conclusions does this document reach?',
];

function SuggestionChips({ onSelect }: { onSelect: (text: string) => void }) {
  return (
    <div className="mt-3 flex flex-col gap-2">
      <span className="text-xs font-medium text-[var(--gray-400)] tracking-wide uppercase">Try asking</span>
      <div className="flex flex-wrap gap-2">
        {SUGGESTION_CHIPS.map((chip) => (
          <button
            key={chip}
            type="button"
            onClick={() => onSelect(chip)}
            className="
              rounded-full border border-[var(--brand-200)] bg-[var(--brand-50)]
              px-3 py-1 text-xs font-medium text-[var(--brand-700)]
              transition-all duration-150
              hover:bg-[var(--brand-100)] hover:border-[var(--brand-400)] hover:shadow-sm
              active:scale-95
            "
          >
            {chip}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── Chat Message Bubble ─────────────────────────────────────────────────────

function ChatMessage({
  msg,
  isLatestUserMessage,
  onSuggestionSelect,
}: {
  msg: Message;
  isLatestUserMessage?: boolean;
  onSuggestionSelect?: (text: string) => void;
}) {
  const isUser = msg.role === 'user';
  const { retryMessage, isStreaming, activeChat } = useChat();
  const [copied, setCopied] = useState(false);
  const [hasRetried, setHasRetried] = useState(false);

  const [showRetryConfirm, setShowRetryConfirm] = useState(false);

  useEffect(() => {
    if (isUser && activeChat) {
      const key = `retried_v2_${activeChat.id}`;
      const existing = JSON.parse(localStorage.getItem(key) || '[]');
      if (existing.includes(msg.content)) {
        setHasRetried(true);
      } else {
        setHasRetried(false);
      }
    }
  }, [isUser, activeChat, msg.content]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(msg.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handleRetryClick = () => {
    if (isStreaming || hasRetried) return;
    
    if (!isLatestUserMessage) {
      setShowRetryConfirm(true);
      return;
    }
    
    retryMessage(msg.id, msg.content);
  };

  const confirmRetry = () => {
    setShowRetryConfirm(false);
    retryMessage(msg.id, msg.content);
  };

  return (
    <div className={`flex w-full group ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`flex flex-col gap-1 max-w-[85%] ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`w-full rounded-2xl px-5 py-3.5 shadow-sm ${
            isUser
              ? 'bg-[var(--brand-500)] text-white rounded-br-none'
              : msg.isError
              ? 'bg-[var(--error-50)] text-[var(--error-700)] border border-[var(--error-200)] rounded-bl-none'
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
            <ReactMarkdown 
              remarkPlugins={[remarkGfm]} 
              components={markdownComponents}
              urlTransform={(value: string) => {
                if (value.startsWith('citation:')) return value;
                return defaultUrlTransform(value);
              }}
            >
              {msg.content}
            </ReactMarkdown>
          </div>
        )}
        {msg.isStreaming && (
          <span className="inline-block ml-1 h-3 w-1.5 animate-pulse bg-current opacity-60" />
        )}
        </div>
        
        {isUser && (
          <div className="flex items-center gap-1.5 px-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={handleCopy}
              className="flex items-center justify-center h-6 w-6 rounded hover:bg-[var(--gray-200)] text-[var(--gray-400)] hover:text-[var(--gray-700)] transition-colors"
              title="Copy message"
            >
              {copied ? (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                  <path d="M3 7l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <rect x="9" y="9" width="13" height="13" rx="2" />
                  <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                </svg>
              )}
            </button>
            <button
              onClick={handleRetryClick}
              disabled={isStreaming || hasRetried}
              className="flex items-center justify-center h-6 w-6 rounded hover:bg-[var(--gray-200)] text-[var(--gray-400)] hover:text-[var(--brand-600)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title={hasRetried ? "Already retried" : "Retry question"}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
              </svg>
            </button>
          </div>
        )}
        {/* Suggestion chips — shown below fallback assistant messages once streaming ends */}
        {!isUser && msg.isFallback && !msg.isStreaming && onSuggestionSelect && (
          <SuggestionChips onSelect={onSuggestionSelect} />
        )}
      </div>

      {showRetryConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--gray-900)]/40 backdrop-blur-[2px] p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <h3 className="text-lg font-semibold text-[var(--gray-900)] mb-2">Retry Question?</h3>
            <p className="text-sm text-[var(--gray-600)] mb-6 leading-relaxed">
              Are you sure you want to retry this question? This will <strong className="text-[var(--gray-900)] font-medium">delete the previous response and any subsequent messages</strong> in the chat.
            </p>
            <div className="flex justify-end gap-3">
              <Button type="button" variant="ghost" onClick={() => setShowRetryConfirm(false)}>
                Cancel
              </Button>
              <Button type="button" variant="danger" onClick={confirmRetry}>
                Delete & Retry
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Inner Chat Component ────────────────────────────────────────────────────

function ChatContent() {
  const searchParams = useSearchParams();
  const initDocId = searchParams.get('doc');

  const { activeChat, sendMessage, isStreaming, abortStream, createNewChat, loadChat } = useChat();

  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [isLoadingDocs, setIsLoadingDocs] = useState(true);

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── Load READY documents ──
  useEffect(() => {
    let mounted = true;
    async function loadDocs() {
      try {
        const res = await listDocuments({ status: 'READY', limit: 100 });
        if (!mounted) return;
        setDocuments(res.items);

        // Pre-select document from URL if it exists
        if (initDocId && res.items.some(d => d.document_id === initDocId)) {
          setSelectedDocs(new Set([initDocId]));
        } else if (res.items.length > 0 && !initDocId) {
          setSelectedDocs(new Set([res.items[0].document_id]));
        }
      } catch (err) {
        if (mounted) toast.error('Failed to load documents.');
      } finally {
        if (mounted) setIsLoadingDocs(false);
      }
    }
    loadDocs();
    return () => { mounted = false; };
  }, [initDocId]);

  // Sync selected docs from activeChat if it exists
  useEffect(() => {
    if (activeChat && activeChat.document_ids) {
      setSelectedDocs(new Set(activeChat.document_ids));
    }
  }, [activeChat?.id]);

  // ── Auto-scroll to bottom ──
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeChat?.messages, isStreaming]);

  // ── Toggle selection ──
  const toggleDoc = (id: string) => {
    if (activeChat) return; // Cannot change docs for an existing chat
    setSelectedDocs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        if (next.size < 10) next.add(id);
      }
      return next;
    });
  };

  // ── Handle Submit ──
  const handleSubmit = async (e?: FormEvent) => {
    e?.preventDefault();

    const query = input.trim();
    if (!query || selectedDocs.size === 0 || isStreaming) return;
    if (query.length > 1000) return;

    setInput('');

    if (!activeChat) {
      // Create new chat first
      try {
        const chat_id = await createNewChat(Array.from(selectedDocs));
        sendMessage(query, chat_id);
      } catch (e) {
        console.error(e);
      }
    } else {
      sendMessage(query);
    }
  };

  const handleStop = () => {
    abortStream();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // ── Render ──
  return (
    <div className="flex h-[calc(100vh-4rem)] fixed left-0 right-0 top-16 bg-[var(--gray-50)] z-10">
      <ChatSidebar />
      <div className="flex-1 flex flex-col gap-4 p-6 mx-auto max-w-3xl">
        {/* Header / Document Selector */}
        <div className="shrink-0">
          <h1 className="text-2xl font-bold tracking-tight text-[var(--gray-900)] mb-4">
            {activeChat ? activeChat.title : 'New Chat'}
          </h1>
          {isLoadingDocs ? (
            <div className="flex items-center gap-2 text-sm text-[var(--gray-500)]">
              <Spinner size={16} /> Loading documents…
            </div>
          ) : (
            <div className={activeChat ? 'opacity-50 pointer-events-none' : ''}>
              <DocumentSelector
                documents={documents}
                selectedIds={selectedDocs}
                onToggle={toggleDoc}
              />
            </div>
          )}
          {activeChat?.missing_document_ids && activeChat.missing_document_ids.length > 0 && (
             <div className="mt-2 rounded-lg border border-[var(--warning-200)] bg-[var(--warning-50)] p-3 text-sm text-[var(--warning-700)]">
                Some documents in this chat are no longer available.
             </div>
          )}
        </div>

        {/* Chat History Area */}
        <div className="flex-1 overflow-y-auto rounded-xl border border-[var(--gray-200)] bg-[var(--gray-50)] p-4 shadow-inner relative">
          {!activeChat || activeChat.messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center px-4">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--brand-100)] text-[var(--brand-600)] mb-3">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
                </svg>
              </div>
              <p className="font-medium text-[var(--gray-900)]">How can I help you today?</p>
              <p className="mt-1 text-sm text-[var(--gray-500)]">
                Select one or more documents above and ask a question.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-6 pb-4">
              {activeChat.messages.map((msg, index, arr) => {
                const hasLaterUserMessages = arr.slice(index + 1).some(m => m.role.toLowerCase() === 'user');
                const isLatestUserMessage = !hasLaterUserMessages && msg.role.toLowerCase() === 'user';
                return (
                  <ChatMessage 
                    key={msg.id} 
                    msg={{
                      id: msg.id,
                      role: msg.role.toLowerCase() as 'user'|'assistant',
                      content: msg.content,
                      isStreaming: isStreaming && msg.role === 'ASSISTANT' && msg === activeChat.messages[activeChat.messages.length - 1],
                      isError: msg.status === 'TRUNCATED',
                      // isFallback is set by ChatContext on the temp message; after
                      // reload it won't exist on server messages, so we cast safely.
                      isFallback: (msg as { isFallback?: boolean }).isFallback,
                    }} 
                    isLatestUserMessage={isLatestUserMessage}
                    onSuggestionSelect={(text) => setInput(text)}
                  />
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input Area */}
        <div className="shrink-0 rounded-xl border border-[var(--gray-200)] bg-white p-3 shadow-sm focus-within:border-[var(--brand-500)] focus-within:ring-1 focus-within:ring-[var(--brand-500)] transition-colors relative">
          <form onSubmit={handleSubmit} className="flex flex-col gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                selectedDocs.size === 0
                  ? 'Select a document first...'
                  : 'Ask a question... (Press Enter to submit, Shift+Enter for new line)'
              }
              disabled={selectedDocs.size === 0 || isStreaming}
              rows={3}
              maxLength={1000}
              className="w-full resize-none bg-transparent p-2 text-sm text-[var(--gray-900)] placeholder:text-[var(--gray-400)] focus:outline-none disabled:opacity-50"
            />
            <div className="flex items-center justify-between px-2">
              <span
                className={`text-xs font-medium ${
                  input.length > 1000 ? 'text-[var(--error-500)]' : 'text-[var(--gray-400)]'
                }`}
              >
                {input.length} / 1000
              </span>

              {isStreaming ? (
                <Button type="button" variant="danger" onClick={handleStop}>
                  Stop generating
                </Button>
              ) : (
                <Button
                  type="submit"
                  disabled={selectedDocs.size === 0 || input.trim().length === 0 || input.length > 1000}
                >
                  Send
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="ml-1" aria-hidden="true">
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                </Button>
              )}
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}

// ─── Page Export ─────────────────────────────────────────────────────────────

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="flex h-[calc(100vh-6rem)] items-center justify-center"><Spinner size={32} className="text-[var(--brand-500)]" /></div>}>
      <ChatContent />
    </Suspense>
  );
}
