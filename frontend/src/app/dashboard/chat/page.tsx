'use client';

import { Suspense, useState, useEffect, useRef, FormEvent } from 'react';
import { useSearchParams } from 'next/navigation';
import { toast } from 'sonner';
import { formatDistanceToNow, format } from 'date-fns';

import { listDocuments, type DocumentRecord } from '@/lib/documents.api';

import { Button, Spinner, Modal } from '@/components/ui';
import Link from 'next/link';
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
  created_at?: string;
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
    <div className="rounded-xl border border-[var(--gray-200)] bg-[var(--surface-card)] p-4 shadow-sm">
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
                  : 'border-[var(--gray-200)] bg-[var(--surface-card)] text-[var(--gray-700)] hover:bg-[var(--gray-50)] hover:border-[var(--gray-300)]'
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
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null);

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
    <div className={`group flex w-full ${isUser ? 'justify-end' : 'justify-start'} animate-in fade-in slide-in-from-bottom-2 duration-300`}>
      <div className={`flex flex-col max-w-[85%] sm:max-w-[75%] ${isUser ? 'items-end' : 'items-start'}`}>
        {/* Name and Timestamp Row */}
        <div className={`flex items-center gap-2 mb-1 px-1 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
          <span className="text-xs font-semibold text-[var(--gray-700)]">
            {isUser ? 'You' : 'Assistant'}
          </span>
          {msg.created_at && (
            <span 
              className="text-[10px] text-[var(--gray-400)] opacity-0 group-hover:opacity-100 transition-opacity"
              title={format(new Date(msg.created_at), 'PPpp')}
            >
              {formatDistanceToNow(new Date(msg.created_at), { addSuffix: true })}
            </span>
          )}
        </div>

        <div
          className={`
            relative rounded-2xl px-5 py-3.5 shadow-sm
            ${isUser
              ? 'bg-[var(--brand-600)] text-white rounded-br-sm'
              : msg.isError
              ? 'bg-[var(--error-50)] text-[var(--error-700)] border border-[var(--error-200)] rounded-bl-sm'
              : 'bg-[var(--surface-card)] text-[var(--gray-900)] border border-[var(--gray-200)] rounded-bl-sm'
            }
          `}
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
              prose prose-sm max-w-none text-sm leading-relaxed dark:prose-invert
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
          <span className="inline-block ml-1 h-4 w-1.5 align-middle cursor-blink bg-[var(--brand-500)]" />
        )}
        </div>
        {/* Actions Row */}
        <div className={`flex items-center gap-1.5 px-2 mt-1 opacity-50 hover:opacity-100 transition-opacity ${isUser ? '' : 'justify-end'}`}>
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
          
          {isUser ? (
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
          ) : (
            !msg.isStreaming && (
              <>
                <button
                  onClick={() => setFeedback('up')}
                  className={`flex items-center justify-center h-6 w-6 rounded hover:bg-[var(--gray-200)] transition-colors ${feedback === 'up' ? 'text-[var(--success-600)] bg-[var(--success-50)]' : 'text-[var(--gray-400)] hover:text-[var(--success-600)]'}`}
                  title="Helpful response"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path>
                  </svg>
                </button>
                <button
                  onClick={() => setFeedback('down')}
                  className={`flex items-center justify-center h-6 w-6 rounded hover:bg-[var(--gray-200)] transition-colors ${feedback === 'down' ? 'text-[var(--error-600)] bg-[var(--error-50)]' : 'text-[var(--gray-400)] hover:text-[var(--error-600)]'}`}
                  title="Unhelpful response"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"></path>
                  </svg>
                </button>
              </>
            )
          )}
        </div>
        {/* Suggestion chips — shown below fallback assistant messages once streaming ends */}
        {!isUser && msg.isFallback && !msg.isStreaming && onSuggestionSelect && (
          <SuggestionChips onSelect={onSuggestionSelect} />
        )}
      </div>

      {showRetryConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--gray-900)]/40 backdrop-blur-[2px] p-4">
          <div className="w-full max-w-md rounded-2xl bg-[var(--surface-card)] p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
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

  const { activeChat, sendMessage, isStreaming, abortStream, createNewChat } = useChat();

  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<Set<string>>(new Set());
  const [isLoadingDocs, setIsLoadingDocs] = useState(true);

  const [showDocModal, setShowDocModal] = useState(false);

  // ── Document Loading ──
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [showScrollFAB, setShowScrollFAB] = useState(false);

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
      } catch {
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
  }, [activeChat]);

  // ── Auto-scroll to bottom ──
  useEffect(() => {
    if (!showScrollFAB) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [activeChat?.messages, isStreaming, showScrollFAB]);

  const handleScroll = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    const { scrollTop, scrollHeight, clientHeight } = container;
    const isScrolledUp = scrollHeight - scrollTop - clientHeight > 100;
    setShowScrollFAB(isScrolledUp);
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    setShowScrollFAB(false);
  };

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
    <div className="flex h-[calc(100vh-4rem)] w-full bg-[var(--surface-bg)]">
      <ChatSidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="shrink-0 px-6 py-4 border-b border-[var(--gray-200)] flex items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight text-[var(--gray-900)] truncate">
            {activeChat ? activeChat.title : 'New Chat'}
          </h1>
          {activeChat?.missing_document_ids && activeChat.missing_document_ids.length > 0 && (
             <div className="rounded-lg border border-[var(--warning-200)] bg-[var(--warning-50)] px-3 py-1.5 text-sm text-[var(--warning-700)]">
                Some documents missing
             </div>
          )}
        </div>

        {/* Chat History Area */}
        <div 
          className="flex-1 overflow-y-auto p-4 md:p-6 relative bg-[var(--gray-50)]"
          ref={scrollContainerRef}
          onScroll={handleScroll}
        >
          <div className="mx-auto w-full max-w-4xl flex flex-col gap-6 pb-4">
            {!activeChat || activeChat.messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-center px-4 mt-20">
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
            <div className="flex flex-col gap-6 pb-4" role="log" aria-live="polite" aria-atomic="false">
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
                      created_at: msg.created_at,
                    }} 
                    isLatestUserMessage={isLatestUserMessage}
                    onSuggestionSelect={(text) => setInput(text)}
                  />
                );
              })}
              <div ref={messagesEndRef} />
            </div>
          )}

          {showScrollFAB && (
            <button
              onClick={scrollToBottom}
              className="sticky bottom-4 left-1/2 -translate-x-1/2 flex h-10 w-10 items-center justify-center rounded-full bg-[var(--surface-card)] text-[var(--gray-600)] shadow-lg border border-[var(--gray-200)] hover:bg-[var(--gray-50)] hover:text-[var(--gray-900)] transition-all z-10"
              aria-label="Scroll to bottom"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 5v14M19 12l-7 7-7-7" />
              </svg>
            </button>
          )}
          </div>
        </div>

        {/* Input Area */}
        <div className="shrink-0 px-4 pb-6 pt-2 bg-gradient-to-t from-[var(--surface-bg)] via-[var(--surface-bg)] to-transparent">
          <div className="mx-auto w-full max-w-4xl relative">
            <form 
              onSubmit={handleSubmit}
              className="flex items-center gap-2 rounded-full border border-[var(--gray-300)] bg-[var(--surface-card)] px-2 py-1.5 shadow-sm focus-within:border-[var(--brand-500)] focus-within:ring-1 focus-within:ring-[var(--brand-500)] transition-all overflow-hidden"
            >
              <button
                type="button"
                onClick={() => setShowDocModal(true)}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[var(--gray-500)] hover:bg-[var(--gray-100)] hover:text-[var(--gray-900)] transition-colors"
                aria-label="Add Documents"
                title="Add Documents"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
              </button>

              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  selectedDocs.size === 0
                    ? 'Select documents using the + button to chat...'
                    : 'Ask a question...'
                }
                disabled={selectedDocs.size === 0 || isStreaming}
                rows={1}
                maxLength={1000}
                className="w-full resize-none bg-transparent py-2 px-1 text-base text-[var(--gray-900)] placeholder:text-[var(--gray-400)] focus:outline-none disabled:opacity-50 h-[40px] flex items-center"
              />
              
              <div className="flex shrink-0 items-center gap-2 pr-1">
                {isStreaming ? (
                  <button
                    type="button"
                    onClick={handleStop}
                    className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--gray-100)] text-[var(--error-600)] hover:bg-[var(--error-50)] transition-colors"
                    aria-label="Stop generation"
                    title="Stop generation"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" ry="2"></rect></svg>
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={!input.trim() || selectedDocs.size === 0 || isStreaming}
                    className="flex h-10 w-10 items-center justify-center rounded-full bg-[var(--brand-500)] text-white hover:bg-[var(--brand-600)] disabled:opacity-50 disabled:bg-[var(--gray-300)] transition-colors"
                    aria-label="Send message"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      </div>

      <Modal
        isOpen={showDocModal}
        onClose={() => setShowDocModal(false)}
        title="Select Documents"
      >
        <div className="p-6 space-y-4">
          <p className="text-sm text-[var(--gray-600)]">
            Select up to 10 documents to include in your chat context.
          </p>
          {isLoadingDocs ? (
            <div className="flex justify-center p-4">
              <Spinner size={24} />
            </div>
          ) : documents.length === 0 ? (
            <div className="text-center py-6">
              <p className="text-sm text-[var(--gray-500)] mb-4">You don&apos;t have any ready documents.</p>
              <Link href="/dashboard/upload" onClick={() => setShowDocModal(false)}>
                <Button>Go to Upload</Button>
              </Link>
            </div>
          ) : (
            <div 
              className={activeChat ? 'opacity-50 cursor-not-allowed' : ''}
              title={activeChat ? "Documents cannot be changed in an existing chat." : undefined}
            >
              <div className={activeChat ? 'pointer-events-none' : ''}>
                <DocumentSelector
                  documents={documents}
                  selectedIds={selectedDocs}
                  onToggle={toggleDoc}
                />
              </div>
            </div>
          )}
          <div className="flex justify-between items-center pt-4 border-t border-[var(--gray-200)] mt-6">
            <Link href="/dashboard/upload" className="text-sm text-[var(--brand-600)] hover:underline font-medium" onClick={() => setShowDocModal(false)}>
              + Upload New Document
            </Link>
            <Button onClick={() => setShowDocModal(false)}>Done</Button>
          </div>
        </div>
      </Modal>
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
