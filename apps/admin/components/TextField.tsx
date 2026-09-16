import type { InputHTMLAttributes } from "react";

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

export function TextField({ label, error, className = "", ...rest }: TextFieldProps) {
  return (
    <label className="mb-4 block">
      <span className="mb-1.5 block text-sm font-medium text-text-secondary">{label}</span>
      <input
        className={`w-full rounded border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent ${
          error ? "border-danger" : "border-border"
        } ${className}`}
        {...rest}
      />
      {error ? <span className="mt-1 block text-xs text-danger">{error}</span> : null}
    </label>
  );
}
