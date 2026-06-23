'use client';


import Link from 'next/link';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';

import { register, resendVerification } from '@/lib/auth.api';
import { ApiError, ERROR_CODES } from '@/lib/api';
import { registerSchema, type RegisterFormValues } from '@/lib/auth.schemas';
import { Button, Input, PasswordInput, FormError } from '@/components/ui';
import { PasswordRulesList } from '@/hooks/usePasswordRules';
import { useCountdown } from '@/hooks/useCountdown';

// NOTE: metadata must be in a Server Component. Since this is 'use client',
// export it from a separate server wrapper if SEO is needed. For now, the
// auth/layout.tsx provides the title template.

// ─── Confirmation screen shown after 202 ─────────────────────────────────────

function ConfirmationScreen({
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
    <div className="flex flex-col items-center gap-6 text-center">
      {/* Icon */}
      <div
        className="flex h-16 w-16 items-center justify-center rounded-full"
        style={{ background: 'var(--brand-50)' }}
      >
        <svg
          width="32"
          height="32"
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

      <div>
        <h1 className="text-xl font-bold" style={{ color: 'var(--gray-900)' }}>
          Check your inbox
        </h1>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--gray-500)' }}>
          We sent a verification link to{' '}
          <span className="font-semibold" style={{ color: 'var(--gray-700)' }}>
            {email}
          </span>
          . Click the link to activate your account.
        </p>
      </div>

      <div
        className="w-full rounded-lg p-4 text-sm"
        style={{ background: 'var(--gray-50)', border: '1px solid var(--gray-200)' }}
      >
        <p style={{ color: 'var(--gray-600)' }}>
          Didn&apos;t receive the email? Check your spam folder, or:
        </p>
        <Button
          variant="ghost"
          onClick={onResend}
          isLoading={isResending}
          disabled={cooldown > 0 || isResending}
          className="mt-2 w-full"
          id="resend-verification-btn"
        >
          {cooldown > 0
            ? `Resend in ${cooldown}s`
            : isResending
              ? 'Sending…'
              : 'Resend verification email'}
        </Button>
      </div>

      <Link
        href="/auth/login"
        className="text-sm font-medium transition-colors hover:underline"
        style={{ color: 'var(--brand-600)' }}
      >
        Back to login
      </Link>
    </div>
  );
}

// ─── Register form ────────────────────────────────────────────────────────────

export default function RegisterPage() {
  const [confirmedEmail, setConfirmedEmail] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [isResending, setIsResending] = useState(false);
  const countdown = useCountdown(undefined);

  const {
    register: formRegister,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    mode: 'onTouched', // validate on blur, then live
  });

  const passwordValue = watch('password') ?? '';

  const onSubmit = async (data: RegisterFormValues) => {
    setFormError(null);
    try {
      await register(data);
      setConfirmedEmail(data.email);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === ERROR_CODES.RATE_LIMIT_EXCEEDED) {
          const seconds = err.retryAfter ?? 60;
          countdown.start(seconds);
          setFormError(`Too many attempts. Please wait ${seconds} seconds before trying again.`);
        } else {
          setFormError(err.message);
        }
      } else {
        setFormError('Something went wrong. Please try again.');
      }
    }
  };

  // Resend: call the dedicated resend endpoint
  const handleResend = async () => {
    if (!confirmedEmail || isResending) return;
    setIsResending(true);
    try {
      await resendVerification({ email: confirmedEmail });
      toast.success('Verification email sent! Check your inbox.');
    } catch (err) {
      if (err instanceof ApiError && err.code === ERROR_CODES.RATE_LIMIT_EXCEEDED) {
        const seconds = err.retryAfter ?? 60;
        countdown.start(seconds);
        toast.warning(`Slow down — resend blocked. Try again in ${seconds}s.`);
      } else {
        toast.success('If that email is registered, a new link has been sent.');
      }
    } finally {
      setIsResending(false);
    }
  };

  // Show confirmation screen after successful register
  if (confirmedEmail) {
    return (
      <ConfirmationScreen
        email={confirmedEmail}
        onResend={handleResend}
        isResending={isResending}
        cooldown={countdown.remaining}
      />
    );
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--gray-900)' }}>
          Create an account
        </h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--gray-500)' }}>
          Start chatting with your documents in seconds.
        </p>
      </div>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="flex flex-col gap-5"
        noValidate
        aria-label="Registration form"
      >
        {formError && !countdown.isActive && <FormError message={formError} />}

        {countdown.isActive && (
          <div
            className="rounded-lg border px-3.5 py-3 text-sm"
            style={{
              background: 'var(--warning-50)',
              borderColor: 'var(--warning-500)',
              color: 'var(--gray-700)',
            }}
          >
            Too many attempts. Try again in{' '}
            <span className="font-semibold">{countdown.remaining}s</span>.
          </div>
        )}

        <Input
          id="register-email"
          label="Email address"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          error={errors.email?.message}
          {...formRegister('email')}
        />

        <div>
          <PasswordInput
            id="register-password"
            label="Password"
            autoComplete="new-password"
            placeholder="Create a strong password"
            error={errors.password?.message}
            {...formRegister('password')}
          />
          <PasswordRulesList password={passwordValue} show={passwordValue.length > 0} />
        </div>

        <Button
          type="submit"
          fullWidth
          isLoading={isSubmitting}
          disabled={countdown.isActive}
          id="register-submit-btn"
        >
          Create account
        </Button>
      </form>

      <p className="mt-6 text-center text-sm" style={{ color: 'var(--gray-500)' }}>
        Already have an account?{' '}
        <Link
          href="/auth/login"
          className="font-semibold transition-colors hover:underline"
          style={{ color: 'var(--brand-600)' }}
        >
          Sign in
        </Link>
      </p>
    </>
  );
}
