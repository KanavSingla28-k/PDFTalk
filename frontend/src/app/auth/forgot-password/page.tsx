'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';

import { forgotPassword } from '@/lib/auth.api';
import { ApiError, ERROR_CODES } from '@/lib/api';
import { emailSchema, type EmailFormValues } from '@/lib/auth.schemas';
import { Button, Input, FormError } from '@/components/ui';
import { useCountdown } from '@/hooks/useCountdown';

export default function ForgotPasswordPage() {
  const [formError, setFormError] = useState<string | null>(null);
  const [isSuccess, setIsSuccess] = useState(false);
  const countdown = useCountdown(undefined);

  const {
    register: formRegister,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<EmailFormValues>({
    resolver: zodResolver(emailSchema),
    mode: 'onTouched',
  });

  const onSubmit = async (data: EmailFormValues) => {
    setFormError(null);

    try {
      await forgotPassword(data.email);
      setIsSuccess(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === ERROR_CODES.RATE_LIMIT_EXCEEDED) {
        const seconds = err.retryAfter ?? 60;
        countdown.start(seconds);
        setFormError(`Too many attempts. Try again in ${seconds} seconds.`);
      } else {
        setFormError('Something went wrong. Please try again.');
      }
    }
  };

  if (isSuccess) {
    return (
      <div className="flex flex-col items-center text-center">
        <div
          className="mb-6 flex h-12 w-12 items-center justify-center rounded-full"
          style={{ background: 'var(--success-50)' }}
        >
          <svg
            className="h-6 w-6"
            style={{ color: 'var(--success-500)' }}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--gray-900)' }}>
          Check your email
        </h1>
        <p className="mt-2 text-sm" style={{ color: 'var(--gray-500)' }}>
          If an account with that email exists, you&apos;ll receive an email shortly with instructions to reset your password.
        </p>
        <Link
          href="/auth/login"
          className="mt-6 w-full rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:bg-gray-50 text-center"
          style={{ borderColor: 'var(--gray-300)', color: 'var(--gray-700)' }}
        >
          Return to login
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--gray-900)' }}>
          Reset your password
        </h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--gray-500)' }}>
          Enter your email address and we&apos;ll send you a link to reset your password.
        </p>
      </div>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="flex flex-col gap-5"
        noValidate
        aria-label="Forgot password form"
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
            role="alert"
          >
            Too many attempts. Try again in{' '}
            <span className="font-semibold">{countdown.remaining}s</span>.
          </div>
        )}

        <Input
          id="forgot-password-email"
          label="Email address"
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
          disabled={countdown.isActive}
          id="forgot-password-submit-btn"
        >
          Send reset link
        </Button>
      </form>

      <p className="mt-6 text-center text-sm" style={{ color: 'var(--gray-500)' }}>
        Remember your password?{' '}
        <Link
          href="/auth/login"
          className="font-semibold transition-colors hover:underline"
          style={{ color: 'var(--brand-600)' }}
        >
          Back to login
        </Link>
      </p>
    </>
  );
}
