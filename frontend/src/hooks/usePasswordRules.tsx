'use client';

/**
 * usePasswordRules — evaluates password strength rules live as the user types.
 *
 * Rules mirror the backend exactly (see frontend_api_reference.md §9):
 *   - Min 8 characters
 *   - At least one uppercase letter
 *   - At least one lowercase letter
 *   - At least one digit
 *   - At least one special character
 */

import { useMemo } from 'react';

export interface PasswordRule {
  key: string;
  label: string;
  test: (value: string) => boolean;
}

export const PASSWORD_RULES: PasswordRule[] = [
  { key: 'minLength', label: 'At least 8 characters',   test: (p) => p.length >= 8 },
  { key: 'hasUpper',  label: 'One uppercase letter',     test: (p) => /[A-Z]/.test(p) },
  { key: 'hasLower',  label: 'One lowercase letter',     test: (p) => /[a-z]/.test(p) },
  { key: 'hasNumber', label: 'One number',               test: (p) => /\d/.test(p) },
  {
    key: 'hasSpecial',
    label: 'One special character',
    test: (p) => /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(p),
  },
];

export interface RuleResult {
  key: string;
  label: string;
  passed: boolean;
}

export function usePasswordRules(password: string): {
  rules: RuleResult[];
  allPassed: boolean;
} {
  return useMemo(() => {
    const rules = PASSWORD_RULES.map((rule) => ({
      key: rule.key,
      label: rule.label,
      passed: rule.test(password),
    }));
    return { rules, allPassed: rules.every((r) => r.passed) };
  }, [password]);
}

// ─── PasswordRulesList component ─────────────────────────────────────────────

interface PasswordRulesListProps {
  password: string;
  /** Only show the list once the user has started typing */
  show?: boolean;
}

export function PasswordRulesList({ password, show = true }: PasswordRulesListProps) {
  const { rules } = usePasswordRules(password);

  if (!show) return null;

  return (
    <ul className="mt-2 flex flex-col gap-1" aria-label="Password requirements">
      {rules.map((rule) => (
        <li
          key={rule.key}
          className="flex items-center gap-2 text-xs transition-colors duration-200"
          style={{ color: rule.passed ? 'var(--success-700)' : 'var(--gray-500)' }}
        >
          {rule.passed ? (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <circle cx="7" cy="7" r="7" fill="var(--success-500)" />
              <path d="M4 7l2 2 4-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <circle cx="7" cy="7" r="6.5" stroke="var(--gray-300)" />
            </svg>
          )}
          {rule.label}
        </li>
      ))}
    </ul>
  );
}
