'use client';

import type { Metadata } from 'next';
import { useCallback, useState } from 'react';
import { useDropzone, type FileRejection } from 'react-dropzone';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { uploadDocument, getUploadErrorMessage, UploadApiError } from '@/lib/documents.api';
import { ApiError, ERROR_CODES } from '@/lib/api';
import { env } from '@/env';
import { Button, FormError, Spinner } from '@/components/ui';
import { useCountdown } from '@/hooks/useCountdown';

// ─── Constants ───────────────────────────────────────────────────────────────

const MAX_SIZE_BYTES = env.NEXT_PUBLIC_MAX_UPLOAD_MB * 1024 * 1024;
const MAX_SIZE_LABEL = `${env.NEXT_PUBLIC_MAX_UPLOAD_MB} MB`;

const ACCEPTED_MIME_TYPES: Record<string, string[]> = {
  'application/pdf': ['.pdf'],
  'text/plain': ['.txt'],
  'text/markdown': ['.md'],
};

// Extensions shown in UI (derived from the accept map)
const ACCEPTED_EXTENSIONS = Object.values(ACCEPTED_MIME_TYPES).flat().join(', ');

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function clientValidationError(file: File): string | null {
  if (file.size > MAX_SIZE_BYTES) {
    return `File is ${formatFileSize(file.size)} — must be under ${MAX_SIZE_LABEL}.`;
  }
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  const allowedExts = Object.values(ACCEPTED_MIME_TYPES).flat();
  if (!allowedExts.includes(ext)) {
    return `"${file.name}" is not a supported file type. Upload PDF, TXT, or MD files only.`;
  }
  return null;
}

// ─── File row shown in the dropzone after selection ──────────────────────────

function SelectedFileRow({
  file,
  error,
  onRemove,
}: {
  file: File;
  error: string | null;
  onRemove: () => void;
}) {
  return (
    <div
      className="flex items-center gap-3 rounded-lg border px-4 py-3 text-sm"
      style={{
        borderColor: error ? 'var(--error-300)' : 'var(--gray-200)',
        background: error ? 'var(--error-50)' : 'var(--gray-25)',
      }}
    >
      {/* File icon */}
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
        style={{ background: error ? 'var(--error-100)' : 'var(--brand-50)' }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke={error ? 'var(--error-500)' : 'var(--brand-500)'}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
      </div>

      {/* Name + size / error */}
      <div className="flex min-w-0 flex-1 flex-col">
        <span
          className="truncate font-medium"
          style={{ color: error ? 'var(--error-700)' : 'var(--gray-800)' }}
        >
          {file.name}
        </span>
        <span className="text-xs" style={{ color: error ? 'var(--error-500)' : 'var(--gray-500)' }}>
          {error ?? formatFileSize(file.size)}
        </span>
      </div>

      {/* Remove */}
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Remove ${file.name}`}
        className="ml-2 rounded p-1 transition-colors hover:bg-[var(--gray-100)]"
        style={{ color: 'var(--gray-400)' }}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <line x1="1" y1="1" x2="13" y2="13" />
          <line x1="13" y1="1" x2="1" y2="13" />
        </svg>
      </button>
    </div>
  );
}

// ─── Upload progress overlay ──────────────────────────────────────────────────

function UploadingOverlay({ filename }: { filename: string }) {
  return (
    <div
      className="flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed p-12 text-center"
      style={{ borderColor: 'var(--brand-300)', background: 'var(--brand-50)' }}
      aria-live="polite"
      aria-label="Uploading file"
    >
      <Spinner size={36} className="text-[var(--brand-500)]" />
      <div>
        <p className="font-semibold" style={{ color: 'var(--brand-700)' }}>
          Uploading…
        </p>
        <p className="mt-1 text-sm" style={{ color: 'var(--brand-600)' }}>
          {filename}
        </p>
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function UploadPage() {
  const router = useRouter();
  const countdown = useCountdown(undefined);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  // ── Dropzone ──────────────────────────────────────────────────────────────

  const onDrop = useCallback(
    (accepted: File[], rejections: FileRejection[]) => {
      setUploadError(null);
      setClientError(null);

      // Dropzone's own rejection (wrong MIME before we even run our validation)
      if (rejections.length > 0) {
        const firstRejection = rejections[0];
        const firstError = firstRejection.errors[0];
        if (firstError.code === 'file-too-large') {
          setClientError(`File must be under ${MAX_SIZE_LABEL}.`);
        } else if (firstError.code === 'file-invalid-type') {
          setClientError(`Unsupported file type. Upload PDF, TXT, or MD files only.`);
        } else {
          setClientError(firstError.message);
        }
        setSelectedFile(firstRejection.file);
        return;
      }

      if (accepted.length === 0) return;

      const file = accepted[0]; // single-file upload
      const err = clientValidationError(file);
      setClientError(err);
      setSelectedFile(file);
    },
    [],
  );

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    accept: ACCEPTED_MIME_TYPES,
    maxSize: MAX_SIZE_BYTES,
    multiple: false,
    disabled: isUploading,
  });

  const handleRemove = () => {
    setSelectedFile(null);
    setClientError(null);
    setUploadError(null);
  };

  // ── Submit ────────────────────────────────────────────────────────────────

  const handleUpload = async () => {
    if (!selectedFile || clientError) return;
    setUploadError(null);
    setIsUploading(true);

    try {
      const result = await uploadDocument(selectedFile);

      toast.success('Upload successful! Processing your document…');

      // Navigate to documents list; polling is T-51's job — we just pass the new ID
      // via a query param so T-51 can highlight / auto-focus the new document.
      router.push(`/dashboard/documents?new=${result.document_id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.code) {
          case ERROR_CODES.FILE_VALIDATION_FAILED:
            setUploadError(getUploadErrorMessage(err));
            break;

          case ERROR_CODES.RATE_LIMIT_EXCEEDED: {
            const seconds = err.retryAfter ?? 60;
            countdown.start(seconds);
            setUploadError(`Too many uploads. Try again in ${seconds} seconds.`);
            break;
          }

          case ERROR_CODES.DAILY_QUOTA_EXCEEDED:
            setUploadError("You've reached your daily document limit. Try again tomorrow.");
            break;

          default:
            if (err.status === 503) {
              setUploadError('Upload queue is temporarily unavailable. Please try again shortly.');
            } else {
              setUploadError(err.message);
            }
        }
      } else {
        setUploadError('Something went wrong. Please try again.');
      }
    } finally {
      setIsUploading(false);
    }
  };

  // ── Dropzone border colour logic ──────────────────────────────────────────

  const dropzoneBorderColor = isDragReject
    ? 'var(--error-500)'
    : isDragActive
      ? 'var(--brand-500)'
      : selectedFile && !clientError
        ? 'var(--success-500)'
        : 'var(--gray-300)';

  const dropzoneBackground = isDragActive
    ? 'var(--brand-50)'
    : isDragReject
      ? 'var(--error-50)'
      : 'white';

  const canUpload = selectedFile !== null && clientError === null && !isUploading && !countdown.isActive;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-xl">
      {/* Page header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--gray-900)' }}>
          Upload a document
        </h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--gray-500)' }}>
          Upload a PDF, text, or markdown file to start chatting with it. Max {MAX_SIZE_LABEL}.
        </p>
      </div>

      {/* Uploading state overlay */}
      {isUploading && selectedFile ? (
        <UploadingOverlay filename={selectedFile.name} />
      ) : (
        <>
          {/* Dropzone */}
          <div
            {...getRootProps()}
            id="upload-dropzone"
            role="button"
            aria-label="File upload area. Drag and drop a file here, or click to browse."
            tabIndex={0}
            className="cursor-pointer rounded-2xl border-2 border-dashed p-10 text-center transition-colors duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-500)]"
            style={{
              borderColor: dropzoneBorderColor,
              background: dropzoneBackground,
              transition: 'border-color 0.15s, background 0.15s',
            }}
          >
            <input {...getInputProps()} id="upload-file-input" aria-label="File input" />

            <div className="flex flex-col items-center gap-3">
              {/* Upload cloud icon */}
              <div
                className="flex h-14 w-14 items-center justify-center rounded-full"
                style={{ background: isDragActive ? 'var(--brand-100)' : 'var(--gray-100)' }}
              >
                <svg
                  width="28"
                  height="28"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke={isDragActive ? 'var(--brand-500)' : 'var(--gray-400)'}
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <polyline points="16 16 12 12 8 16" />
                  <line x1="12" y1="12" x2="12" y2="21" />
                  <path d="M20.39 18.39A5 5 0 0018 9h-1.26A8 8 0 103 16.3" />
                </svg>
              </div>

              <div>
                <p className="font-semibold" style={{ color: isDragActive ? 'var(--brand-700)' : 'var(--gray-700)' }}>
                  {isDragActive ? 'Drop your file here' : 'Drag & drop your file here'}
                </p>
                <p className="mt-1 text-sm" style={{ color: 'var(--gray-400)' }}>
                  or{' '}
                  <span
                    className="font-medium"
                    style={{ color: 'var(--brand-600)', textDecoration: 'underline' }}
                  >
                    click to browse
                  </span>
                </p>
              </div>

              <p className="text-xs" style={{ color: 'var(--gray-400)' }}>
                {ACCEPTED_EXTENSIONS.toUpperCase()} · Max {MAX_SIZE_LABEL}
              </p>
            </div>
          </div>

          {/* Selected file preview */}
          {selectedFile && (
            <div className="mt-4">
              <SelectedFileRow
                file={selectedFile}
                error={clientError}
                onRemove={handleRemove}
              />
            </div>
          )}

          {/* Server-side error */}
          {uploadError && !countdown.isActive && (
            <div className="mt-4">
              <FormError message={uploadError} />
            </div>
          )}

          {/* Rate-limit cooldown */}
          {countdown.isActive && (
            <div
              className="mt-4 rounded-lg border px-3.5 py-3 text-sm"
              style={{
                background: 'var(--warning-50)',
                borderColor: 'var(--warning-500)',
                color: 'var(--gray-700)',
              }}
              role="alert"
            >
              Too many uploads. Try again in{' '}
              <span className="font-semibold">{countdown.remaining}s</span>.
            </div>
          )}

          {/* Submit button */}
          <div className="mt-6">
            <Button
              fullWidth
              onClick={handleUpload}
              disabled={!canUpload}
              isLoading={isUploading}
              id="upload-submit-btn"
            >
              Upload document
            </Button>
          </div>

          {/* Supported formats info */}
          <div
            className="mt-6 rounded-xl p-4 text-sm"
            style={{ background: 'var(--gray-50)', border: '1px solid var(--gray-200)' }}
          >
            <p className="font-medium mb-2" style={{ color: 'var(--gray-700)' }}>
              Supported file types
            </p>
            <ul className="flex flex-col gap-1" style={{ color: 'var(--gray-500)' }}>
              <li className="flex items-center gap-2">
                <span className="font-mono text-xs font-semibold px-1.5 py-0.5 rounded" style={{ background: 'var(--gray-200)', color: 'var(--gray-700)' }}>.pdf</span>
                PDF documents
              </li>
              <li className="flex items-center gap-2">
                <span className="font-mono text-xs font-semibold px-1.5 py-0.5 rounded" style={{ background: 'var(--gray-200)', color: 'var(--gray-700)' }}>.txt</span>
                Plain text files
              </li>
              <li className="flex items-center gap-2">
                <span className="font-mono text-xs font-semibold px-1.5 py-0.5 rounded" style={{ background: 'var(--gray-200)', color: 'var(--gray-700)' }}>.md</span>
                Markdown files
              </li>
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
