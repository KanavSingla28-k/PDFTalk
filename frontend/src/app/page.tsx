import Link from "next/link";

export default function Home() {
  const features = [
    {
      title: 'Instant Citations',
      desc: 'Every answer is backed by direct citations to your original document so you can verify facts immediately.',
      icon: (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
      )
    },
    {
      title: 'Multiple File Types',
      desc: 'We support PDF, plain text, and Markdown files. Just drag and drop, and start chatting within seconds.',
      icon: (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
        </svg>
      )
    },
    {
      title: 'Privacy First',
      desc: 'Your documents are secure. We only process what you upload, and you can delete them permanently at any time.',
      icon: (
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      )
    }
  ];

  return (
    <div className="flex flex-col min-h-screen bg-[var(--surface-bg)]">
      {/* Navigation */}
      <header className="sticky top-0 z-50 w-full border-b border-[var(--gray-200)] bg-[var(--surface-bg)]/80 backdrop-blur-md">
        <div className="container mx-auto px-6 h-16 flex items-center justify-between max-w-6xl">
          <Link href="/" className="flex items-center gap-2 text-xl font-bold tracking-tight text-[var(--brand-600)]">
            <svg width="28" height="28" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <rect width="32" height="32" rx="8" fill="var(--brand-500)" />
              <path d="M9 8h9l5 5v11a1 1 0 01-1 1H9a1 1 0 01-1-1V9a1 1 0 011-1z" fill="white" fillOpacity="0.9" />
              <path d="M18 8l5 5h-4a1 1 0 01-1-1V8z" fill="white" fillOpacity="0.5" />
              <path d="M12 17h8M12 20h5" stroke="var(--brand-500)" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            PDFTalk
          </Link>
          <nav className="flex items-center gap-6">
            <Link href="/auth/login" className="text-sm font-medium text-[var(--gray-600)] hover:text-[var(--gray-900)] transition-colors">
              Sign in
            </Link>
            <Link href="/auth/register" className="text-sm font-semibold bg-[var(--brand-500)] text-white px-4 py-2 rounded-lg hover:bg-[var(--brand-600)] transition-all shadow-sm">
              Get Started Free
            </Link>
          </nav>
        </div>
      </header>

      <main className="flex-1 flex flex-col items-center">
        {/* Hero Section */}
        <section className="w-full pt-32 pb-24 px-6 relative overflow-hidden flex flex-col items-center text-center">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-[var(--brand-50)] rounded-full blur-[100px] -z-10 pointer-events-none" />
          
          <div className="max-w-4xl mx-auto flex flex-col items-center">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[var(--brand-50)] border border-[var(--brand-200)] text-[var(--brand-700)] text-sm font-medium mb-8 animate-slide-up" style={{ animationDelay: '0ms' }}>
              <span className="flex h-2 w-2 rounded-full bg-[var(--brand-500)]"></span>
              PDFTalk v2.0 is now live
            </div>
            
            <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight text-[var(--gray-900)] mb-6 animate-slide-up" style={{ animationDelay: '100ms' }}>
              Chat with your documents.<br/>
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-[var(--brand-500)] to-[var(--brand-700)]">
                Get answers instantly.
              </span>
            </h1>
            
            <p className="text-xl md:text-2xl text-[var(--gray-500)] mb-10 max-w-2xl leading-relaxed animate-slide-up" style={{ animationDelay: '200ms' }}>
              Upload PDFs, text files, and markdown. Ask questions, extract key points, and get reliable citations in seconds.
            </p>
            
            <div className="mt-10 flex flex-col sm:flex-row gap-4 items-center justify-center">
              <Link href="/auth/register" className="w-full sm:w-auto flex items-center justify-center gap-2 bg-[var(--brand-500)] text-white px-8 py-4 rounded-xl text-lg font-semibold hover:bg-[var(--brand-600)] active:scale-95 transition-all shadow-md">
                Get Started for Free
              </Link>
              <Link href="#how-it-works" className="w-full sm:w-auto flex items-center justify-center px-8 py-4 rounded-xl text-lg font-semibold text-[var(--gray-700)] bg-[var(--surface-card)] border border-[var(--gray-200)] hover:bg-[var(--gray-50)] active:scale-95 transition-all shadow-sm">
                How it Works
              </Link>
            </div>
            
            <div className="mt-12 flex items-center gap-4 text-sm text-[var(--gray-400)] animate-slide-up" style={{ animationDelay: '400ms' }}>
              <div className="flex -space-x-2">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="w-8 h-8 rounded-full border-2 border-[var(--surface-bg)] bg-[var(--gray-200)] flex items-center justify-center text-[10px] text-[var(--gray-500)] font-medium">
                    {String.fromCharCode(64 + i)}
                  </div>
                ))}
              </div>
              <p>Trusted by 1,000+ professionals and students</p>
            </div>
          </div>
        </section>

        {/* Features Section */}
        <section className="w-full py-24 bg-[var(--surface-card)] px-6">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-16">
              <h2 className="text-3xl font-bold text-[var(--gray-900)] mb-4">Everything you need to digest information faster</h2>
              <p className="text-lg text-[var(--gray-500)] max-w-2xl mx-auto">Built for researchers, students, and professionals who deal with long documents daily.</p>
            </div>
            
            <div className="grid md:grid-cols-3 gap-8">
              {features.map((feature, idx) => (
                <div key={idx} className="bg-[var(--surface-card)] p-8 rounded-2xl border border-[var(--gray-200)] shadow-sm hover:shadow-md transition-shadow hover:-translate-y-1 duration-200">
                  <div className="w-12 h-12 bg-[var(--brand-50)] text-[var(--brand-600)] rounded-xl flex items-center justify-center mb-6">
                    {feature.icon}
                  </div>
                  <h3 className="text-xl font-semibold text-[var(--gray-900)] mb-3">{feature.title}</h3>
                  <p className="text-[var(--gray-500)] leading-relaxed">{feature.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
        
        {/* CTA Section */}
        <section className="w-full py-24 px-6 bg-[var(--surface-bg)] border-t border-[var(--gray-200)]">
          <div className="max-w-4xl mx-auto text-center space-y-8">
            <h2 className="text-3xl md:text-4xl font-bold text-[var(--gray-900)] mb-6">Ready to work smarter?</h2>
            <p className="text-lg text-[var(--gray-600)] mb-10 max-w-xl mx-auto">
              Join thousands of users who are already saving hours every week by chatting with their documents.
            </p>
            <Link href="/auth/register" className="inline-flex items-center justify-center gap-2 bg-[var(--brand-500)] text-white px-8 py-4 rounded-xl text-lg font-semibold hover:bg-[var(--brand-600)] active:scale-95 transition-all shadow-sm">
              Create your free account
            </Link>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="w-full border-t border-[var(--gray-200)] bg-[var(--surface-bg)] py-12 px-6">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex items-center gap-2 text-lg font-bold text-[var(--gray-900)]">
            <svg width="24" height="24" viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="8" fill="var(--brand-500)" />
              <path d="M9 8h9l5 5v11a1 1 0 01-1 1H9a1 1 0 01-1-1V9a1 1 0 011-1z" fill="white" />
              <path d="M12 17h8M12 20h5" stroke="var(--brand-500)" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            PDFTalk
          </div>
          <div className="text-sm text-[var(--gray-500)]">
            © {new Date().getFullYear()} PDFTalk Inc. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  );
}
