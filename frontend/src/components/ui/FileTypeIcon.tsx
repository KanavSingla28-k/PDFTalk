import React from 'react';

interface FileTypeIconProps {
  filename: string;
  className?: string;
}

export function FileTypeIcon({ filename, className = '' }: FileTypeIconProps) {
  const safeFilename = filename || '';
  const ext = safeFilename.split('.').pop()?.toLowerCase();

  let bgColor = 'var(--gray-100)';
  let textColor = 'var(--gray-500)';
  let label = 'DOC';

  if (ext === 'pdf') {
    bgColor = 'var(--error-50)';
    textColor = 'var(--error-700)';
    label = 'PDF';
  } else if (ext === 'txt') {
    bgColor = 'var(--brand-50)';
    textColor = 'var(--brand-700)';
    label = 'TXT';
  } else if (ext === 'md') {
    bgColor = 'var(--success-50)';
    textColor = 'var(--success-700)';
    label = 'MD';
  } else if (ext === 'csv') {
    bgColor = 'var(--warning-50)';
    textColor = 'var(--warning-700)';
    label = 'CSV';
  }

  return (
    <div
      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-[10px] font-bold ${className}`}
      style={{ background: bgColor, color: textColor }}
      title={`${label} File`}
    >
      {label}
    </div>
  );
}
