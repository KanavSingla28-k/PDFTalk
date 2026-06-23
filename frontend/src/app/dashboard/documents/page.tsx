'use client';

import { Suspense, useCallback, useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { toast } from 'sonner';
import { apiToast } from '@/lib/toast';
import { formatDistanceToNow } from 'date-fns';

import {
  listDocuments,
  deleteDocument,
  pollDocumentStatus,
  type DocumentRecord,
  type DocumentStatus,
} from '@/lib/documents.api';
import { ApiError, ERROR_CODES } from '@/lib/api';
import { Button, Spinner, Skeleton, FileTypeIcon } from '@/components/ui';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Compile-time exhaustiveness check.
 * If a new DocumentStatus value is added to the union but not handled in a
 * switch, TypeScript will error here at the call site (assertNever(x) inside
 * the default branch) rather than silently rendering nothing.
 */
function assertNever(x: never): never {
  throw new Error(`Unhandled DocumentStatus: ${String(x)}`);
}

// ─── Status Badge ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: DocumentStatus }) {
  switch (status) {
    case 'PENDING_UPLOAD':
      // The file is currently being transferred to S3 by the browser.
      // This badge appears when the documents page is loaded while an upload
      // from another tab/session is still in progress, or if confirm-upload
      // has not yet been called.  The stale-cleanup job will transition this
      // to FAILED after ~15 minutes if the upload is abandoned.
      return (
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
          style={{ background: 'var(--warning-50)', color: 'var(--warning-500)' }}
        >
          <Spinner size={12} className="text-[var(--warning-500)]" />
          Uploading…
        </span>
      );
    case 'PENDING':
    case 'PROCESSING':
      return (
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
          style={{ background: 'var(--warning-50)', color: 'var(--warning-500)' }}
        >
          <Spinner size={12} className="text-[var(--warning-500)]" />
          {status === 'PENDING' ? 'Pending' : 'Processing'}
        </span>
      );
    case 'READY':
      return (
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
          style={{ background: 'var(--success-50)', color: 'var(--success-700)' }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <circle cx="6" cy="6" r="6" fill="var(--success-500)" />
            <path d="M3.5 6l1.5 1.5 3.5-3.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Ready
        </span>
      );
    case 'FAILED':
      return (
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
          style={{ background: 'var(--error-50)', color: 'var(--error-700)' }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M6 1a5 5 0 100 10A5 5 0 006 1zm-.75 2.5a.75.75 0 011.5 0v3a.75.75 0 01-1.5 0v-3zm.75 5.5a.75.75 0 110-1.5.75.75 0 010 1.5z" fill="currentColor" />
          </svg>
          Failed
        </span>
      );
    default:
      // TypeScript will error here if a new status is added to DocumentStatus
      // but not handled above — forcing the developer to add a case.
      return assertNever(status);
  }
}

// ─── Document Card ───────────────────────────────────────────────────────────

function DocumentCard({
  doc,
  isNew,
  onDelete,
  pollingError,
}: {
  doc: DocumentRecord;
  isNew: boolean;
  onDelete: (id: string) => void;
  pollingError?: string | null;
}) {
  const [isDeleting, setIsDeleting] = useState(false);

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await onDelete(doc.document_id);
    } finally {
      // If it fails, the parent will show a toast and keep the doc in the list,
      // so we need to reset the button state.
      setIsDeleting(false);
    }
  };

  const isTerminal = doc.status === 'READY' || doc.status === 'FAILED';

  return (
    <div
      className={`relative flex flex-col rounded-xl border p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-md ${
        isNew ? 'ring-2 ring-[var(--brand-400)] ring-offset-2' : ''
      }`}
      style={{
        background: 'var(--surface-card)',
        borderColor: 'var(--gray-200)',
      }}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <FileTypeIcon filename={doc.filename} />
          <div className="flex min-w-0 flex-col">
            <h3 className="truncate font-semibold text-[var(--gray-900)]" title={doc.filename}>
              {doc.filename}
            </h3>
            <p className="mt-1 text-xs text-[var(--gray-500)]">
              {formatFileSize(doc.file_size_bytes)} • Uploaded{' '}
              {formatDistanceToNow(new Date(doc.created_at), { addSuffix: true })}
            </p>
          </div>
        </div>
        <StatusBadge status={doc.status} />
      </div>

      {doc.status === 'FAILED' && doc.error_message && (
        <div className="mt-3 rounded-lg bg-[var(--error-50)] p-3 text-xs text-[var(--error-700)]">
          {doc.error_message}
        </div>
      )}

      {pollingError && doc.status !== 'FAILED' && (
        <div className="mt-3 rounded-lg bg-[var(--warning-50)] p-3 text-xs text-[var(--warning-700)]">
          {pollingError}
        </div>
      )}

      <div className="mt-auto pt-4 flex items-center justify-between border-t border-[var(--gray-100)]">
        <div className="flex gap-2">
          {doc.status === 'READY' && (
            <Link
              href={`/dashboard/chat?doc=${doc.document_id}`}
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold text-[var(--brand-700)] hover:bg-[var(--brand-50)] transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
              </svg>
              Chat
            </Link>
          )}
          {doc.status === 'FAILED' && (
            <Link
              href="/dashboard/upload"
              className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold text-[var(--gray-700)] hover:bg-[var(--gray-100)] transition-colors"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21.5 2v6h-6M2.13 15.57a9 9 0 1 0 3.84-10.36l-4.14-4.14"></path>
              </svg>
              Re-upload
            </Link>
          )}
        </div>

        <button
          onClick={handleDelete}
          disabled={isDeleting || (!isTerminal && doc.status !== 'FAILED')}
          className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-[var(--error-600)] hover:bg-[var(--error-50)] disabled:opacity-50 transition-colors"
          title="Delete document"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 6h18"></path>
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
          </svg>
          {isDeleting ? 'Deleting…' : 'Delete'}
        </button>
      </div>
    </div>
  );
}

// ─── Inner Component ─────────────────────────────────────────────────────────

function DocumentsContent() {
  const searchParams = useSearchParams();
  const newDocId = searchParams.get('new');

  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState('all');
  
  // Track polling controllers and timeout errors per document
  const pollingControllers = useRef<Record<string, AbortController>>({});
  const [pollingErrors, setPollingErrors] = useState<Record<string, string>>({});

  // ── Fetch Documents ──
  useEffect(() => {
    let mounted = true;

    async function fetchDocs() {
      try {
        const res = await listDocuments({ limit: 50 }); // Fetching up to 50 for MVP
        if (!mounted) return;
        setDocuments(res.items);
      } catch (err) {
        if (!mounted) return;
        if (err instanceof ApiError) {
          setError(err.message);
        } else {
          setError('Failed to load documents. Please try again.');
        }
      } finally {
        if (mounted) setIsLoading(false);
      }
    }

    fetchDocs();

    return () => {
      mounted = false;
      // Cleanup all active polling on unmount
      Object.values(pollingControllers.current).forEach((ctrl) => ctrl.abort());
    };
  }, []);

  // ── Start Polling ──
  const startPolling = useCallback((docId: string) => {
    // Prevent duplicate polling
    if (pollingControllers.current[docId]) return;

    const controller = new AbortController();
    pollingControllers.current[docId] = controller;

    // Remove any previous polling error for this doc
    setPollingErrors((prev) => {
      const copy = { ...prev };
      delete copy[docId];
      return copy;
    });

    pollDocumentStatus(
      docId,
      (updatedDoc) => {
        setDocuments((prev) =>
          prev.map((d) => (d.document_id === docId ? updatedDoc : d)),
        );
      },
      controller.signal,
    ).then((result) => {
      delete pollingControllers.current[docId];
      
      if (result.status === 'timeout') {
        setPollingErrors((prev) => ({
          ...prev,
          [docId]: 'Processing is taking longer than expected. Please check back later or try re-uploading.',
        }));
      } else if (result.status === 'failed') {
         // The onUpdate callback already set the doc status to FAILED and updated error_message
         // If it's a 404, we might want to handle it.
         if (result.error === 'Document not found.') {
           // Document was deleted while polling
           setDocuments((prev) => prev.filter((d) => d.document_id !== docId));
         }
      }
    }).catch(() => {
       delete pollingControllers.current[docId];
    });
  }, []);

  // Check for non-terminal documents to start polling.
  // PENDING_UPLOAD is included so that documents loaded from the list while
  // an upload from another tab/session is still in-progress will auto-update
  // to PENDING (after confirm-upload) or FAILED (after stale cleanup) without
  // requiring a manual page refresh.
  useEffect(() => {
    documents.forEach((doc) => {
      if (
        doc.status === 'PENDING_UPLOAD' ||
        doc.status === 'PENDING' ||
        doc.status === 'PROCESSING'
      ) {
        startPolling(doc.document_id);
      }
    });
  }, [documents, startPolling]);

  // ── Delete Handler ──
  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId);
      
      // Stop polling if active
      if (pollingControllers.current[docId]) {
        pollingControllers.current[docId].abort();
        delete pollingControllers.current[docId];
      }

      setDocuments((prev) => prev.filter((d) => d.document_id !== docId));
      toast.success('Document deleted successfully.');
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 404) {
          apiToast.error(new ApiError(err.code, 'Document not found.', 404));
          setDocuments((prev) => prev.filter((d) => d.document_id !== docId));
        } else if (err.status === 502) {
          apiToast.error(new ApiError(err.code, 'Deletion failed due to a storage error. Please try again.', 502));
        } else {
          apiToast.error(err);
        }
      } else {
        apiToast.error(err);
      }
      throw err; // Re-throw to reset button state in DocumentCard
    }
  };

  // ── Filter & Search ──
  const filteredDocuments = documents.filter(doc => {
    const filename = doc.filename || '';
    const matchesSearch = filename.toLowerCase().includes(searchQuery.toLowerCase());
    if (filterType === 'all') return matchesSearch;
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    return matchesSearch && ext === filterType;
  });

  const filterOptions = [
    { value: 'all', label: 'All Files' },
    { value: 'pdf', label: 'PDFs' },
    { value: 'txt', label: 'Text' },
    { value: 'md', label: 'Markdown' },
  ];

  // ── Render ──
  return (
    <div className="flex flex-col gap-6 h-full">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[var(--gray-900)]">
            My Documents
          </h1>
          <p className="mt-1 text-sm text-[var(--gray-500)]">
            Manage your uploaded files and check their processing status.
          </p>
        </div>
        <Link href="/dashboard/upload" tabIndex={-1} className="shrink-0">
          <Button>Upload new</Button>
        </Link>
      </div>

      {/* Search and Filters */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[var(--surface-card)] p-2 rounded-xl border border-[var(--gray-200)] shadow-sm">
        <div className="relative flex-1 max-w-sm">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--gray-400)]" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input
            type="text"
            placeholder="Search documents..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-[var(--gray-50)] text-sm rounded-lg pl-9 pr-3 py-2 text-[var(--gray-900)] placeholder:text-[var(--gray-400)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-500)] border border-transparent focus:bg-[var(--surface-bg)] transition-all"
          />
        </div>
        <div className="flex items-center gap-1 overflow-x-auto pb-1 sm:pb-0 hide-scrollbar">
          {filterOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilterType(opt.value)}
              className={`whitespace-nowrap px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                filterType === opt.value
                  ? 'bg-[var(--gray-900)] text-[var(--surface-bg)]'
                  : 'text-[var(--gray-600)] hover:bg-[var(--gray-100)]'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex flex-col justify-between rounded-xl border border-[var(--gray-200)] bg-[var(--surface-card)] p-5 shadow-sm h-48">
              <div>
                <div className="flex items-center gap-3">
                  <Skeleton className="h-10 w-10 rounded-lg" />
                  <div className="flex-1">
                    <Skeleton className="h-5 w-3/4 mb-2" />
                    <Skeleton className="h-4 w-1/2" />
                  </div>
                </div>
                <div className="mt-4">
                  <Skeleton className="h-6 w-20 rounded-full" />
                </div>
              </div>
              <div className="mt-auto pt-4 flex justify-between">
                <Skeleton className="h-8 w-16" />
                <Skeleton className="h-8 w-16" />
              </div>
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="rounded-xl border border-[var(--error-200)] bg-[var(--error-50)] p-6 text-center text-[var(--error-700)]">
          <p>{error}</p>
          <Button variant="secondary" onClick={() => window.location.reload()} className="mt-4">
            Retry
          </Button>
        </div>
      ) : documents.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-[var(--gray-200)] bg-[var(--surface-card)] p-12 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[var(--gray-50)]">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--gray-400)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          </div>
          <h2 className="mt-4 text-lg font-semibold text-[var(--gray-900)]">No documents yet</h2>
          <p className="mt-1 text-sm text-[var(--gray-500)] max-w-sm">
            You haven&apos;t uploaded any documents. Upload your first PDF, TXT, or MD file to start chatting.
          </p>
          <Link href="/dashboard/upload" className="mt-6">
            <Button>Upload your first document</Button>
          </Link>
        </div>
      ) : filteredDocuments.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-2xl border border-[var(--gray-200)] bg-[var(--surface-card)] p-12 text-center">
          <p className="text-sm text-[var(--gray-500)]">No documents match your search.</p>
          <Button variant="ghost" onClick={() => { setSearchQuery(''); setFilterType('all'); }} className="mt-4">
            Clear filters
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredDocuments.map((doc) => (
            <DocumentCard
              key={doc.document_id}
              doc={doc}
              isNew={doc.document_id === newDocId}
              onDelete={handleDelete}
              pollingError={pollingErrors[doc.document_id]}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Page Export ─────────────────────────────────────────────────────────────

export default function DocumentsPage() {
  return (
    <Suspense fallback={
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 w-full">
        <Skeleton className="h-48 w-full rounded-xl" />
        <Skeleton className="h-48 w-full rounded-xl hidden sm:block" />
        <Skeleton className="h-48 w-full rounded-xl hidden lg:block" />
      </div>
    }>
      <DocumentsContent />
    </Suspense>
  );
}
