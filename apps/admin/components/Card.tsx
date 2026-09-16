import type { PropsWithChildren } from "react";

export function Card({
  title,
  action,
  children,
}: PropsWithChildren<{ title?: string; action?: React.ReactNode }>) {
  return (
    <div className="rounded border border-border bg-surface p-5">
      {title || action ? (
        <div className="mb-4 flex items-center justify-between">
          {title ? <h2 className="text-base font-semibold text-text-primary">{title}</h2> : <div />}
          {action}
        </div>
      ) : null}
      {children}
    </div>
  );
}

export function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded border border-border bg-surface p-5">
      <p className="mb-1 text-sm text-text-tertiary">{label}</p>
      <p className="font-display text-3xl font-semibold text-text-primary">{value}</p>
    </div>
  );
}
