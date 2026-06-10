'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useState, Suspense } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';

import { register, resendVerification } from '@/lib/auth.api';
import { ApiError, ERROR_CODES } from '@/lib/api';
import { emailSchema, type EmailFormValues } from '@/lib/auth.schemas';
import { Button, Input, FormError } from '@/components/ui';
import { useCountdown } from '@/hooks/useCountdown';

// ─── Error messages for each ?error= param value ─────────────────────────────

const ERROR_PARAM_MESSAGES: Record<string, { title: string; body: string }> = {
  invalid_token: {
    title: 'Invalid verification link',
    body: 'This link is invalid or has already been used. Request a new one below.',
  },
  token_expired: {
    title: 'Link has expired',
    body: 'Verification links expire after 24 hours. Request a fresh one below.',
  },
};

// ─── Resend form ──────────────────────────────────────────────────────────────

function ResendForm({
  prefillEmail,
  cooldown,
  onCooldownStart,
}: {
  prefillEmail?: string;
  cooldown: ReturnType<typeof useCountdown>;
  onCooldownStart: (seconds: number) => void;
}) {
  const [sent, setSent] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register: formRegister,
    handleSubmit,
    formState: { errors },
  } = useForm<EmailFormValues>({
    resolver: zodResolver(emailSchema),
    defaultValues: { email: prefillEmail ?? '' },
    mode: 'onTouched',
  });

  const onSubmit = async (data: EmailFormValues) => {
    setSubmitError(null);
    setIsSubmitting(true);
    try {
      // Use the dedicated resend verification route
      await resendVerification({ email: data.email });
      setSent(true);
      toast.success('Verification email sent! Check your inbox.');
    } catch (err) {
      if (err instanceof ApiError && err.code === ERROR_CODES.RATE_LIMIT_EXCEEDED) {
        const seconds = err.retryAfter ?? 60;
        onCooldownStart(seconds);
        setSubmitError(`Too many attempts. Try again in ${seconds} seconds.`);
      } else {
        // Always show a neutral message — never reveal whether email exists
        setSent(true);
        toast.success('If that account exists, a verification link has been sent.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (sent) {
    return (
      <div
        className="rounded-lg border p-4 text-sm text-center"
        style={{
          background: 'var(--success-50)',
          borderColor: 'var(--success-500)',
          color: 'var(--success-700)',
        }}
        role="status"
      >
        <p className="font-medium">Email sent!</p>
        <p className="mt-1">Check your inbox and click the verification link.</p>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit(onSubmit)}
      className="flex flex-col gap-3"
      noValidate
      aria-label="Resend verification email form"
    >
      {submitError && !cooldown.isActive && <FormError message={submitError} />}
      {cooldown.isActive && (
        <div
          className="rounded-lg border px-3.5 py-3 text-sm"
          style={{
            background: 'var(--warning-50)',
            borderColor: 'var(--warning-500)',
            color: 'var(--gray-700)',
          }}
          role="alert"
        >
          Too many attempts. Try again in{' '}
          <span className="font-semibold">{cooldown.remaining}s</span>.
        </div>
      )}
      <Input
        id="verify-email-resend-email"
        label="Your email address"
        type="email"
        autoComplete="email"
        placeholder="you@example.com"
        error={errors.email?.message}
        {...formRegister('email')}
      />
      <Button
        type="submit"
        fullWidth
        isLoading={isSubmitting}
        disabled={cooldown.isActive}
        id="verify-email-resend-btn"
      >
        Send new verification link
      </Button>
    </form>
  );
}

// ─── Inner page (uses useSearchParams) ───────────────────────────────────────

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const countdown = useCountdown(undefined);

  const errorParam = searchParams.get('error'); // e.g. "invalid_token" | "token_expired"
  const hasQueryParams = errorParam !== null || searchParams.has('token');

  // ── Case 1: Error redirect from backend ─────────────────────────────────
  if (errorParam) {
    const errInfo = ERROR_PARAM_MESSAGES[errorParam] ?? {
      title: 'Verification failed',
      body: 'Something went wrong with your verification link. Please request a new one.',
    };

    return (
      <>
        <div className="flex flex-col items-center gap-2 text-center mb-6">
          {/* Error icon */}
          <div
            className="flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: 'var(--error-50)' }}
          >
            <svg
              width="28"
              height="28"
              viewBox="0 0 28 28"
              fill="none"
              aria-hidden="true"
            >
              <circle cx="14" cy="14" r="13" stroke="var(--error-500)" strokeWidth="2" />
              <path
                d="M14 8v7M14 18v1"
                stroke="var(--error-500)"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--gray-900)' }}>
            {errInfo.title}
          </h1>
          <p className="text-sm leading-relaxed" style={{ color: 'var(--gray-500)' }}>
            {errInfo.body}
          </p>
        </div>

        <ResendForm
          cooldown={countdown}
          onCooldownStart={(s) => countdown.start(s)}
        />

        <p className="mt-4 text-center text-sm" style={{ color: 'var(--gray-500)' }}>
          <Link
            href="/auth/login"
            className="font-medium hover:underline"
            style={{ color: 'var(--brand-600)' }}
          >
            Back to login
          </Link>
        </p>
      </>
    );
  }

  // ── Case 2: No query params at all (direct navigation) ──────────────────
  // Do NOT call the backend. Show neutral message + resend option.
  if (!hasQueryParams) {
    return (
      <>
        <div className="flex flex-col items-center gap-2 text-center mb-6">
          <div
            className="flex h-14 w-14 items-center justify-center rounded-full"
            style={{ background: 'var(--brand-50)' }}
          >
            <svg
              width="28"
              height="28"
              viewBox="0 0 32 32"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M4 8a2 2 0 012-2h20a2 2 0 012 2v16a2 2 0 01-2 2H6a2 2 0 01-2-2V8z"
                fill="var(--brand-100)"
                stroke="var(--brand-500)"
                strokeWidth="1.5"
              />
              <path
                d="M4 8l12 10L28 8"
                stroke="var(--brand-500)"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--gray-900)' }}>
            Verify your email
          </h1>
          <p className="text-sm leading-relaxed" style={{ color: 'var(--gray-500)' }}>
            Check your inbox for the verification link we sent when you registered. If you
            didn&apos;t receive it, enter your email to get a new one.
          </p>
        </div>

        <ResendForm
          cooldown={countdown}
          onCooldownStart={(s) => countdown.start(s)}
        />

        <p className="mt-4 text-center text-sm" style={{ color: 'var(--gray-500)' }}>
          <Link
            href="/auth/login"
            className="font-medium hover:underline"
            style={{ color: 'var(--brand-600)' }}
          >
            Back to login
          </Link>
        </p>
      </>
    );
  }

  // ── Case 3: ?token= is present (user clicking a link — backend handles this
  // via redirect. We should never render this state because the backend
  // redirects before the browser loads the Next.js page.
  // If it does render (e.g. the backend is down), show a neutral fallback.
  return (
    <>
      <div className="flex flex-col items-center gap-2 text-center mb-6">
        <div
          className="flex h-14 w-14 items-center justify-center rounded-full animate-pulse"
          style={{ background: 'var(--brand-50)' }}
          aria-hidden="true"
        />
        <h1 className="text-xl font-bold" style={{ color: 'var(--gray-900)' }}>
          Verifying…
        </h1>
        <p className="text-sm" style={{ color: 'var(--gray-500)' }}>
          If this page doesn&apos;t redirect automatically,{' '}
          <Link href="/auth/login" className="font-medium hover:underline" style={{ color: 'var(--brand-600)' }}>
            go to login
          </Link>
          .
        </p>
      </div>
    </>
  );
}

// ─── Page export ─────────────────────────────────────────────────────────────

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="h-64 animate-pulse rounded-lg bg-gray-100" />}>
      <VerifyEmailContent />
    </Suspense>
  );
}
