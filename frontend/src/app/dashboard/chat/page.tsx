'use client';

import { Suspense, useState, useEffect, useRef, FormEvent } from 'react';
import { useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { listDocuments, type DocumentRecord } from '@/lib/documents.api';
import { streamAnswer, getSseErrorMessage, type StreamEvent } from '@/lib/query.api';
import { ERROR_CODES } from '@/lib/api';
import { Button, Spinner } from '@/components/ui';

// ─── Types ───────────────────────────────────────────────────────────────────

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  isError?: boolean;
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

// ─── Chat Message Bubble ─────────────────────────────────────────────────────

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

// ─── Inner Chat Component ────────────────────────────────────────────────────

function ChatContent() {
  const searchParams = useSearchParams();
  const initDocId = searchParams.get('doc');

  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [isLoadingDocs, setIsLoadingDocs] = useState(true);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  
  const abortControllerRef = useRef<AbortController | null>(null);
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
          // Pre-select the first document by default
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

  // ── Auto-scroll to bottom ──
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isStreaming]);

  // ── Toggle selection ──
  const toggleDoc = (id: string) => {
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
    setIsStreaming(true);


    // TODO: when shifting to https, remove down code and use only crypto.randomUUID
    // const userMsgId = crypto.randomUUID();
    // const assistantMsgId = crypto.randomUUID();

    const userMsgId = typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
    const assistantMsgId = typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36);

// -----------------------------------------------------------------------------
 
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: 'user', content: query },
      { id: assistantMsgId, role: 'assistant', content: '', isStreaming: true },
    ]);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    await streamAnswer(
      {
        document_ids: Array.from(selectedDocs),
        question: query,
      },
      (event: StreamEvent) => {
        if (event.type === 'token') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId ? { ...m, content: m.content + event.content } : m
            )
          );
        } else if (event.type === 'done') {
          setIsStreaming(false);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId ? { ...m, isStreaming: false } : m
            )
          );
        } else if (event.type === 'error') {
          setIsStreaming(false);
          const errorMsg = getSseErrorMessage(event.code);
          
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id === assistantMsgId) {
                // If we already had content, append the error inline
                // If it was empty, just show the error
                const prefix = m.content ? m.content + '\n\n[Error] ' : '';
                return { ...m, content: prefix + errorMsg, isStreaming: false, isError: true };
              }
              return m;
            })
          );
          
          // Show toast if it's a specific API error code
          if (event.code === ERROR_CODES.RATE_LIMIT_EXCEEDED || event.code === ERROR_CODES.DAILY_QUOTA_EXCEEDED) {
             toast.error(errorMsg);
          }
        }
      },
      controller.signal
    );

    abortControllerRef.current = null;
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsStreaming(false);
      setMessages((prev) =>
        prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m))
      );
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // ── Render ──
  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col gap-4 mx-auto max-w-3xl">
      {/* Header / Document Selector */}
      <div className="shrink-0">
        <h1 className="text-2xl font-bold tracking-tight text-[var(--gray-900)] mb-4">
          Chat with your documents
        </h1>
        {isLoadingDocs ? (
          <div className="flex items-center gap-2 text-sm text-[var(--gray-500)]">
            <Spinner size={16} /> Loading documents…
          </div>
        ) : (
          <DocumentSelector
            documents={documents}
            selectedIds={selectedDocs}
            onToggle={toggleDoc}
          />
        )}
      </div>

      {/* Chat History Area */}
      <div className="flex-1 overflow-y-auto rounded-xl border border-[var(--gray-200)] bg-[var(--gray-50)] p-4 shadow-inner relative">
        {messages.length === 0 ? (
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
            {messages.map((msg) => (
              <ChatMessage key={msg.id} msg={msg} />
            ))}
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
