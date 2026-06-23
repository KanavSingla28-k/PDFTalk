import { ImageResponse } from 'next/og';

export const runtime = 'edge';
export const alt = 'PDFTalk - Chat with your documents';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: 'linear-gradient(135deg, #f0f4ff 0%, #fafafa 60%, #f0f4ff 100%)',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'sans-serif',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px', marginBottom: '40px' }}>
          <svg width="64" height="64" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="32" height="32" rx="8" fill="#6172f3" />
            <path d="M9 8h9l5 5v11a1 1 0 01-1 1H9a1 1 0 01-1-1V9a1 1 0 011-1z" fill="white" fillOpacity="0.9" />
            <path d="M18 8l5 5h-4a1 1 0 01-1-1V8z" fill="white" fillOpacity="0.5" />
            <path d="M12 17h8M12 20h5" stroke="#6172f3" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <h1 style={{ fontSize: '72px', fontWeight: 'bold', color: '#444ce7', margin: 0, letterSpacing: '-0.05em' }}>
            PDFTalk
          </h1>
        </div>
        <p style={{ fontSize: '32px', color: '#475467', textAlign: 'center', maxWidth: '800px', lineHeight: '1.5' }}>
          Upload PDFs, text files, and markdown — then ask questions and get instant AI-powered answers.
        </p>
      </div>
    ),
    { ...size }
  );
}
