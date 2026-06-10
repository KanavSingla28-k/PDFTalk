'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState, useEffect, Suspense } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';

import { login, register, resendVerification } from '@/lib/auth.api';
import { ApiError, ERROR_CODES } from '@/lib/api';
import { loginSchema, type LoginFormValues } from '@/lib/auth.schemas';
import { Button, Input, PasswordInput, FormError } from '@/components/ui';
import { useCountdown } from '@/hooks/useCountdown';

// ─── Resend-verification inline prompt ───────────────────────────────────────

function ResendPrompt({
  email,
  onResend,
  isResending,
  cooldown,
}: {
  email: string;
  onResend: () => void;
  isResending: boolean;
  cooldown: number;
}) {
  return (
    <div
      className="rounded-lg border p-4 text-sm"
      style={{
        background: 'var(--warning-50)',
        borderColor: 'var(--warning-500)',
        color: 'var(--gray-700)',
      }}
      role="alert"
    >
      <p className="font-medium" style={{ color: 'var(--gray-900)' }}>
        Email not verified
      </p>
      <p className="mt-1" style={{ color: 'var(--gray-600)' }}>
        Check your inbox for the verification link, or resend it below.
      </p>
      <Button
        variant="secondary"
        onClick={onResend}
        isLoading={isResending}
        disabled={cooldown > 0 || isResending}
        className="mt-3"
        id="login-resend-verification-btn"
      >
        {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend verification email'}
      </Button>
    </div>
  );
}

// ─── Inner component (uses useSearchParams — must be inside Suspense) ─────────

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [formError, setFormError] = useState<string | null>(null);
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);
  const [isResending, setIsResending] = useState(false);
  const countdown = useCountdown(undefined);

  const {
    register: formRegister,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    mode: 'onTouched',
  });

  // ── Show ?verified=true toast on mount ──────────────────────────────────
  useEffect(() => {
    if (searchParams.get('verified') === 'true') {
      toast.success('Email verified! You can now log in.');
    }
  }, [searchParams]);

  // ── Submit handler ──────────────────────────────────────────────────────
  const onSubmit = async (data: LoginFormValues) => {
    setFormError(null);
    setUnverifiedEmail(null);

    try {
      const response = await login(data);

      // Store user + token in sessionStorage for AuthContext to pick up (T-49).
      // Access token itself is NOT stored here — AuthContext owns that.
      sessionStorage.setItem(
        'pdftalk_user',
        JSON.stringify({ id: response.user.id, email: response.user.email }),
      );
      // Emit a custom event so AuthContext (once mounted) can hydrate from this
      window.dispatchEvent(new CustomEvent('pdftalk:login', { detail: response }));

      // Navigate to intended destination or dashboard
      const next = searchParams.get('next');
      const destination =
        next && next.startsWith('/') && !next.startsWith('/auth') ? next : '/dashboard/documents';
      router.push(destination);
    } catch (err) {
      if (err instanceof ApiError) {
        switch (err.code) {
          case ERROR_CODES.EMAIL_NOT_VERIFIED:
            setUnverifiedEmail(getValues('email'));
            break;
          case ERROR_CODES.RATE_LIMIT_EXCEEDED: {
            const seconds = err.retryAfter ?? 60;
            countdown.start(seconds);
            setFormError(`Too many attempts. Try again in ${seconds} seconds.`);
            break;
          }
          case ERROR_CODES.ACCOUNT_INACTIVE:
            setFormError('Your account has been deactivated. Contact support.');
            break;
          default:
            // INVALID_CREDENTIALS and everything else — always generic
            setFormError('Invalid email or password.');
        }
      } else {
        setFormError('Something went wrong. Please try again.');
      }
    }
  };

  // ── Resend verification (calls POST /auth/resend-verification) ──────────
  const handleResend = async () => {
    const email = unverifiedEmail ?? getValues('email');
    if (!email || isResending) return;
    setIsResending(true);
    try {
      await resendVerification({ email });
      toast.success('Verification email resent. Check your inbox.');
    } catch (err) {
      if (err instanceof ApiError && err.code === ERROR_CODES.RATE_LIMIT_EXCEEDED) {
        const seconds = err.retryAfter ?? 60;
        countdown.start(seconds);
        toast.warning(`Slow down — try again in ${seconds}s.`);
      } else {
        toast.info('If that account exists and is unverified, a new link has been sent.');
      }
    } finally {
      setIsResending(false);
    }
  };

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--gray-900)' }}>
          Welcome back
        </h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--gray-500)' }}>
          Sign in to your account to continue.
        </p>
      </div>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="flex flex-col gap-5"
        noValidate
        aria-label="Login form"
      >
        {/* Form-level error */}
        {formError && !countdown.isActive && <FormError message={formError} />}

        {/* Rate-limit cooldown */}
        {countdown.isActive && (
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
            <span className="font-semibold">{countdown.remaining}s</span>.
          </div>
        )}

        {/* Unverified email prompt */}
        {unverifiedEmail && (
          <ResendPrompt
            email={unverifiedEmail}
            onResend={handleResend}
            isResending={isResending}
            cooldown={countdown.remaining}
          />
        )}

        <Input
          id="login-email"
          label="Email address"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          error={errors.email?.message}
          {...formRegister('email')}
        />

        <div className="flex flex-col gap-1.5">
          <PasswordInput
            id="login-password"
            label="Password"
            autoComplete="current-password"
            placeholder="Enter your password"
            error={errors.password?.message}
            {...formRegister('password')}
          />
        </div>

        <Button
          type="submit"
          fullWidth
          isLoading={isSubmitting}
          disabled={countdown.isActive}
          id="login-submit-btn"
        >
          Sign in
        </Button>
      </form>

      <p className="mt-6 text-center text-sm" style={{ color: 'var(--gray-500)' }}>
        Don&apos;t have an account?{' '}
        <Link
          href="/auth/register"
          className="font-semibold transition-colors hover:underline"
          style={{ color: 'var(--brand-600)' }}
        >
          Create one
        </Link>
      </p>
    </>
  );
}

// ─── Page export — Suspense boundary required for useSearchParams ─────────────

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="h-80 animate-pulse rounded-lg bg-gray-100" />}>
      <LoginForm />
    </Suspense>
  );
}
