'use client';

import { useState } from 'react';
import { getDocumentDownloadUrl } from '@/lib/documents.api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';
import { Modal } from '@/components/ui';

interface CitationProps {
  filename: string;
  documentId: string;
}

export function Citation({ filename, documentId }: CitationProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [markdownContent, setMarkdownContent] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);

  const isMarkdown = filename.toLowerCase().endsWith('.md');


  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (isLoading) return;
    setIsLoading(true);

    try {
      const { url } = await getDocumentDownloadUrl(documentId);
      setDownloadUrl(url);

      if (isMarkdown) {
        // Fetch the markdown content to preview it
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch markdown content');
        const text = await res.text();
        setMarkdownContent(text);
        setIsModalOpen(true);
      } else {
        // For PDF/TXT, open directly in a new tab
        window.open(url, '_blank', 'noopener,noreferrer');
      }
    } catch (error) {
      console.error('Failed to open document:', error);
      toast.error('Could not open the document. It may have been deleted or expired.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      <button
        onClick={handleClick}
        disabled={isLoading}
        className="inline-flex items-center gap-1 mx-1 px-2 py-0.5 rounded-full bg-[var(--brand-50)] text-[var(--brand-700)] text-xs font-medium border border-[var(--brand-200)] hover:bg-[var(--brand-100)] transition-colors align-middle focus:outline-none focus:ring-2 focus:ring-[var(--brand-500)] focus:ring-offset-1 disabled:opacity-50"
        title={`View ${filename}`}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
        </svg>
        <span className="truncate max-w-[120px]">{filename}</span>
        {isLoading && (
          <span className="ml-1 h-2 w-2 animate-ping rounded-full bg-[var(--brand-500)] opacity-75" />
        )}
      </button>

      {/* Custom Markdown Preview Modal */}
      {isMarkdown && (
        <Modal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
          maxWidth="4xl"
        >
          <div className="flex-shrink-0 flex items-center justify-between bg-[var(--surface-card)] px-6 py-4 border-b border-[var(--gray-200)]">
            <h2 id="modal-title" className="text-lg font-semibold text-[var(--gray-900)] flex items-center gap-2">
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                className="text-[var(--gray-500)]"
              >
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
              </svg>
              {filename}
            </h2>
            
            <div className="flex items-center gap-3">
              {downloadUrl && (
                <a
                  href={downloadUrl}
                  download={filename}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium !text-white bg-[var(--brand-600)] hover:bg-[var(--brand-700)] rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--brand-500)] focus:ring-offset-2 !no-underline"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                  Download Original
                </a>
              )}
              <button 
                onClick={() => setIsModalOpen(false)}
                className="p-1.5 text-[var(--gray-400)] hover:text-[var(--gray-600)] hover:bg-[var(--gray-100)] rounded-md transition-colors"
                aria-label="Close modal"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-6 bg-[var(--gray-50)]">
            <div className="bg-[var(--surface-card)] border border-[var(--gray-200)] rounded-lg p-6 shadow-sm min-h-full">
              {markdownContent ? (
                <div className="prose prose-sm max-w-none dark:prose-invert text-[var(--gray-900)]">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {markdownContent}
                  </ReactMarkdown>
                </div>
              ) : (
                <div className="flex items-center justify-center h-40 text-[var(--gray-500)]">
                  Loading preview...
                </div>
              )}
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
