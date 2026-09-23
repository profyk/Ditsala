/**
 * Conference Room plan constants — mirrors
 * `backend/app/domain/billing/conference_plans.py` (entitlement keys and
 * tool ids) so the admin UI renders labeled fields/checkboxes instead of
 * asking someone to type `"conference.max_participants"` and a raw JSON
 * array into the generic entitlement editor on the Pricing page. Kept as
 * its own file (not inlined into the page component) so the plan/tool
 * vocabulary is one place to update if the backend's ever changes,
 * matching that module's own "one small vocabulary, everything else
 * reads from it" shape.
 */

export const CONFERENCE_PRODUCT = "conference" as const;

export const MAX_GUESTS_KEY = "conference.max_participants";
export const MAX_DURATION_MINUTES_KEY = "conference.max_duration_minutes";
export const MAX_MEETINGS_PER_MONTH_KEY = "conference.max_meetings_per_month";
export const TOOLS_KEY = "conference.tools";

export interface ConferenceTool {
  id: string;
  label: string;
  description: string;
  /** Whether MeetingService actually gates this tool today (vs.
   * informational-only — shown for admin/user comparison but not yet
   * enforced by any endpoint). See conference_plans.py's own
   * ENFORCED_TOOL_IDS for the source of truth this mirrors. */
  enforced: boolean;
}

export const CONFERENCE_TOOLS: ConferenceTool[] = [
  {
    id: "translation",
    label: "Multilingual translation",
    description: "Basic conference chat translation — always on, every tier (product decision).",
    enforced: false,
  },
  {
    id: "polls_qna",
    label: "Polls & Q&A",
    description: "Live polls and moderated Q&A during a meeting.",
    enforced: false,
  },
  {
    id: "recording",
    label: "Cloud recording",
    description: "Host/co-host can start and stop a cloud recording of the meeting.",
    enforced: true,
  },
  {
    id: "transcription",
    label: "Transcription",
    description: "Post-meeting transcript of a finished recording.",
    enforced: false,
  },
  {
    id: "ai_notes",
    label: "AI meeting notes",
    description: "AI-generated, editable summary/decisions/action items.",
    enforced: false,
  },
  {
    id: "breakout_rooms",
    label: "Breakout rooms",
    description: "Split participants into smaller sub-rooms.",
    enforced: true,
  },
  {
    id: "webinar_registration",
    label: "Webinar registration",
    description: "Public, no-account registration for webinar/town-hall meetings.",
    enforced: false,
  },
  {
    id: "analytics",
    label: "Attendance analytics",
    description: "Attendance duration, unique/guest counts, and peak concurrency per meeting.",
    enforced: true,
  },
  {
    id: "priority_support",
    label: "Priority support",
    description: "Marketing/informational flag — no support-ticket system reads this yet.",
    enforced: false,
  },
];

/** `null` in an entitlement value means "unlimited" — render it that way
 * instead of a bare empty/zero field. */
export function formatLimit(value: unknown, unit: string): string {
  if (value === null || value === undefined) return "Unlimited";
  return `${value} ${unit}`;
}

export function minutesToHoursLabel(minutes: number | null): string {
  if (minutes === null) return "Unlimited";
  if (minutes % 60 === 0) return `${minutes / 60}h`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
