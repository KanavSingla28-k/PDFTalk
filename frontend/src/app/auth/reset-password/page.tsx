'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useState, Suspense } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { toast } from 'sonner';

import { resetPassword } from '@/lib/auth.api';
import { ApiError } from '@/lib/api';
import { resetPasswordSchema, type ResetPasswordFormValues } from '@/lib/auth.schemas';
import { Button, PasswordInput, FormError, Skeleton } from '@/components/ui';

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get('token');

  const [formError, setFormError] = useState<string | null>(null);

  const {
    register: formRegister,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ResetPasswordFormValues>({
    resolver: zodResolver(resetPasswordSchema),
    mode: 'onTouched',
  });

  if (!token) {
    return (
      <div className="flex flex-col items-center text-center">
        <h1 className="text-2xl font-bold tracking-tight mb-2" style={{ color: 'var(--gray-900)' }}>
          Missing Token
        </h1>
        <p className="mb-6 text-sm" style={{ color: 'var(--gray-500)' }}>
          No password reset token was found in the URL.
        </p>
        <Link href="/auth/forgot-password" style={{ color: 'var(--brand-600)' }} className="font-semibold hover:underline">
          Request a new reset link
        </Link>
      </div>
    );
  }

  const onSubmit = async (data: ResetPasswordFormValues) => {
    setFormError(null);

    try {
      await resetPassword(token, data.password);
      toast.success('Password updated successfully. Please log in.');
      router.push('/auth/login');
    } catch (err) {
      if (err instanceof ApiError && err.code === 'INVALID_OR_EXPIRED_TOKEN') {
        setFormError('This password reset link is invalid or has expired.');
      } else if (err instanceof ApiError && err.code === 'FILE_VALIDATION_FAILED') {
         // Should not happen, but fallback
        setFormError(err.message);
      } else {
        setFormError('Something went wrong. Please try again.');
      }
    }
  };

  return (
    <>
      <div className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--gray-900)' }}>
          Set new password
        </h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--gray-500)' }}>
          Please enter your new password below.
        </p>
      </div>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="flex flex-col gap-5"
        noValidate
        aria-label="Reset password form"
      >
        {formError && <FormError message={formError} />}

        {formError?.includes('expired') && (
          <div className="mt-1 text-center">
            <Link href="/auth/forgot-password" style={{ color: 'var(--brand-600)' }} className="text-sm font-semibold hover:underline">
              Request a new reset link
            </Link>
          </div>
        )}

        <PasswordInput
          id="reset-password-new"
          label="New password"
          autoComplete="new-password"
          placeholder="Must be at least 8 characters"
          error={errors.password?.message}
          {...formRegister('password')}
        />

        <PasswordInput
          id="reset-password-confirm"
          label="Confirm password"
          autoComplete="new-password"
          placeholder="Repeat your new password"
          error={errors.confirmPassword?.message}
          {...formRegister('confirmPassword')}
        />

        <Button
          type="submit"
          fullWidth
          isLoading={isSubmitting}
          id="reset-password-submit-btn"
        >
          Reset password
        </Button>
      </form>
    </>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={
      <div className="flex flex-col gap-5 w-full">
        <Skeleton className="h-8 w-40 mb-2" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-10 w-full mt-2" />
      </div>
    }>
      <ResetPasswordForm />
    </Suspense>
  );
}
