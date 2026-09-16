const TONE_CLASSES: Record<string, string> = {
  neutral: "bg-surface-raised text-text-secondary border-border",
  success: "bg-success/10 text-success border-success/30",
  warning: "bg-warning/10 text-warning border-warning/30",
  danger: "bg-danger/10 text-danger border-danger/30",
  info: "bg-info/10 text-info border-info/30",
  accent: "bg-accent-muted text-accent border-accent/30",
};

const ACCOUNT_STATE_TONE: Record<string, keyof typeof TONE_CLASSES> = {
  active: "success",
  pending_email: "neutral",
  pending_phone: "neutral",
  pending_kyc_document: "warning",
  pending_kyc_liveness: "warning",
  pending_next_of_kin: "neutral",
  pending_code: "neutral",
  manual_review: "warning",
  suspended: "danger",
  deactivated: "neutral",
  banned: "danger",
};

export function Badge({ label, tone = "neutral" }: { label: string; tone?: keyof typeof TONE_CLASSES }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  );
}

export function AccountStateBadge({ state }: { state: string }) {
  return <Badge label={state.replace(/_/g, " ")} tone={ACCOUNT_STATE_TONE[state] ?? "neutral"} />;
}
