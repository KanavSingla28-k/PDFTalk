import type { Metadata } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import { Toaster } from 'sonner';
import { AuthProvider } from '@/contexts/AuthContext';
import './globals.css';

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] });
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'PDFTalk — Chat with your documents',
  description:
    'Upload PDFs, text files, and markdown — then ask questions and get instant AI-powered answers.',
};

import { ChatProvider } from '@/contexts/ChatContext';
import { ThemeProvider } from '@/providers/ThemeProvider';

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col bg-[var(--surface-bg)] text-[var(--gray-900)] transition-colors duration-200">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <AuthProvider>
            <ChatProvider>
              {children}
              <Toaster
                position="top-right"
              richColors
              closeButton
              toastOptions={{ duration: 5000 }}
            />
          </ChatProvider>
        </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
