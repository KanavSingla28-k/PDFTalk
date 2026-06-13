import dynamic from 'next/dynamic';
import type { Metadata } from 'next';
import { Spinner } from '@/components/ui';

export const metadata: Metadata = {
  title: 'Upload Document | PDFTalk',
  description: 'Upload a PDF, text, or markdown file to start chatting with it.',
};

// Dynamically import the heavy UploadForm that contains react-dropzone
const UploadForm = dynamic(() => import('./UploadForm'), {
  loading: () => (
    <div className="flex h-64 items-center justify-center">
      <Spinner size={32} className="text-[var(--brand-500)]" />
    </div>
  ),
});

export default function UploadPage() {
  return <UploadForm />;
}
