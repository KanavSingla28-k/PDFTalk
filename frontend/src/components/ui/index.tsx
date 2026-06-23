'use client';

/**
 * ui/index.tsx — Shared primitive components used across auth pages.
 *
 * Components:
 *   <Button>       — primary / secondary / ghost variants, loading state
 *   <Input>        — labelled input with inline error
 *   <FormError>    — standalone error message block
 *   <Spinner>      — inline loading spinner
 *   <PasswordInput> — Input with show/hide toggle
 */

import React, { forwardRef, useState } from 'react';

// ─── Spinner ─────────────────────────────────────────────────────────────────

export function Spinner({ size = 16, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={`animate-spin ${className}`}
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="3"
        strokeOpacity="0.25"
      />
      <path
        d="M12 2a10 10 0 0110 10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ─── Button ──────────────────────────────────────────────────────────────────

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  isLoading?: boolean;
  fullWidth?: boolean;
};

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-[var(--brand-500)] text-white hover:bg-[var(--brand-600)] active:bg-[var(--brand-700)] shadow-sm',
  secondary:
    'bg-white text-[var(--gray-700)] border border-[var(--gray-300)] hover:bg-[var(--gray-50)] active:bg-[var(--gray-100)] shadow-xs',
  ghost:
    'bg-transparent text-[var(--brand-600)] hover:bg-[var(--brand-50)] active:bg-[var(--brand-100)]',
  danger:
    'bg-[var(--error-500)] text-white hover:bg-[var(--error-700)] active:bg-[var(--error-700)] shadow-sm',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'primary',
    isLoading = false,
    fullWidth = false,
    disabled,
    children,
    className = '',
    ...props
  },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || isLoading}
      className={[
        'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all duration-150 active:scale-[0.98]',
        'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--brand-500)]',
        'disabled:cursor-not-allowed disabled:opacity-50',
        variantStyles[variant],
        fullWidth ? 'w-full' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...props}
    >
      {isLoading && <Spinner size={15} />}
      {children}
    </button>
  );
});

// ─── Input ───────────────────────────────────────────────────────────────────

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
  id: string; // required — enforced for a11y
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, hint, id, className = '', ...props },
  ref,
) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={id}
        className="text-sm font-medium"
        style={{ color: 'var(--gray-700)' }}
      >
        {label}
      </label>
      <input
        ref={ref}
        id={id}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        aria-invalid={!!error}
        className={[
          'block w-full rounded-lg border px-3.5 py-2.5 text-sm shadow-xs transition-colors',
          'placeholder:text-[var(--gray-400)]',
          'focus:outline-none focus:ring-2 focus:ring-[var(--brand-500)] focus:border-[var(--brand-500)]',
          error
            ? 'border-[var(--error-500)] ring-1 ring-[var(--error-500)] text-[var(--error-700)]'
            : 'border-[var(--gray-300)] text-[var(--gray-900)] hover:border-[var(--gray-400)]',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        {...props}
      />
      {error && (
        <p
          id={`${id}-error`}
          role="alert"
          className="flex items-center gap-1 text-xs"
          style={{ color: 'var(--error-500)' }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
            <path d="M6 1a5 5 0 100 10A5 5 0 006 1zm-.75 2.5a.75.75 0 011.5 0v3a.75.75 0 01-1.5 0v-3zm.75 5.5a.75.75 0 110-1.5.75.75 0 010 1.5z" />
          </svg>
          {error}
        </p>
      )}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs" style={{ color: 'var(--gray-500)' }}>
          {hint}
        </p>
      )}
    </div>
  );
});

// ─── PasswordInput ────────────────────────────────────────────────────────────

type PasswordInputProps = Omit<InputProps, 'type'>;

export const PasswordInput = forwardRef<HTMLInputElement, PasswordInputProps>(
  function PasswordInput({ id, ...props }, ref) {
    const [show, setShow] = useState(false);
    return (
      <div className="relative">
        <Input ref={ref} id={id} type={show ? 'text' : 'password'} {...props} />
        <button
          type="button"
          aria-label={show ? 'Hide password' : 'Show password'}
          onClick={() => setShow((s) => !s)}
          className="absolute right-3 top-[34px] text-[var(--gray-400)] hover:text-[var(--gray-600)] transition-colors"
          tabIndex={-1}
        >
          {show ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" />
              <line x1="1" y1="1" x2="23" y2="23" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          )}
        </button>
      </div>
    );
  },
);

// ─── FormError ────────────────────────────────────────────────────────────────

export function FormError({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border px-3.5 py-3 text-sm"
      style={{
        background: 'var(--error-50)',
        borderColor: 'var(--error-300)',
        color: 'var(--error-700)',
      }}
    >
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="currentColor"
        className="mt-0.5 shrink-0"
        aria-hidden="true"
      >
        <path d="M8 1a7 7 0 100 14A7 7 0 008 1zm-.75 3.25a.75.75 0 011.5 0v4a.75.75 0 01-1.5 0v-4zm.75 7a.75.75 0 110-1.5.75.75 0 010 1.5z" />
      </svg>
      {message}
    </div>
  );
}

// ─── Divider ──────────────────────────────────────────────────────────────────

export function Divider({ label }: { label?: string }) {
  return (
    <div className="relative flex items-center gap-3 py-1">
      <div className="h-px flex-1" style={{ background: 'var(--gray-200)' }} />
      {label && (
        <span className="text-xs font-medium" style={{ color: 'var(--gray-400)' }}>
          {label}
        </span>
      )}
      <div className="h-px flex-1" style={{ background: 'var(--gray-200)' }} />
    </div>
  );
}

export { Modal } from './Modal';
export { Skeleton } from './Skeleton';
export { FileTypeIcon } from './FileTypeIcon';
