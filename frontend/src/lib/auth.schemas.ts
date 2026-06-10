/**
 * auth.schemas.ts — Zod validation schemas for all auth forms.
 *
 * Mirrors the backend rules exactly (frontend_api_reference.md §9).
 * Import these into react-hook-form via zodResolver.
 */

import { z } from 'zod';

// ─── Password schema ──────────────────────────────────────────────────────────

const passwordSchema = z
  .string()
  .min(8, 'Password must be at least 8 characters')
  .regex(/[A-Z]/, 'Must contain at least one uppercase letter')
  .regex(/[a-z]/, 'Must contain at least one lowercase letter')
  .regex(/\d/, 'Must contain at least one number')
  .regex(
    /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/,
    'Must contain at least one special character',
  );

// ─── Register schema ──────────────────────────────────────────────────────────

export const registerSchema = z.object({
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
  password: passwordSchema,
});

export type RegisterFormValues = z.infer<typeof registerSchema>;

// ─── Login schema ─────────────────────────────────────────────────────────────

export const loginSchema = z.object({
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

// ─── Email-only schema (for resend flows) ────────────────────────────────────

export const emailSchema = z.object({
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
});

export type EmailFormValues = z.infer<typeof emailSchema>;

// ─── Reset Password schema ────────────────────────────────────────────────────

export const resetPasswordSchema = z
  .object({
    password: passwordSchema,
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: "Passwords don't match",
    path: ['confirmPassword'],
  });

export type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;
