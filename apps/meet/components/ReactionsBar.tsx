"use client";

import { useState } from "react";

import { meetingsApi } from "@/lib/api";

/**
 * Quick reactions + raise hand — available to every participant, guests
 * included (public given a valid participant_id, no token — see
 * backend/app/api/v1/routers/meetings.py's send_reaction/raise_hand).
 * Fire-and-forget: a reaction failing silently is a better UX than an
 * error toast over something this low-stakes.
 */

const REACTIONS = ["👍", "👏", "❤️", "😂", "🎉"];

export function ReactionsBar({
  meetingId,
  participantId,
}: {
  meetingId: string;
  participantId: string;
}) {
  const [handRaised, setHandRaised] = useState(false);
  const [sentReaction, setSentReaction] = useState<string | null>(null);

  async function react(reaction: string) {
    setSentReaction(reaction);
    setTimeout(() => setSentReaction(null), 1200);
    try {
      await meetingsApi.sendReaction(meetingId, participantId, reaction);
    } catch {
      // Best-effort — see module docstring.
    }
  }

  async function toggleHand() {
    const next = !handRaised;
    setHandRaised(next);
    try {
      await meetingsApi.setHandRaised(meetingId, participantId, next);
    } catch {
      setHandRaised(!next);
    }
  }

  return (
    <div className="fixed bottom-24 left-1/2 z-50 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-surface px-2 py-1.5 shadow-lg">
      {REACTIONS.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => react(r)}
          className={`rounded-full px-2 py-1 text-lg transition-transform hover:scale-110 ${
            sentReaction === r ? "scale-125" : ""
          }`}
          title={`React with ${r}`}
        >
          {r}
        </button>
      ))}
      <button
        type="button"
        onClick={toggleHand}
        className={`ml-1 rounded-full px-2 py-1 text-lg transition-colors ${
          handRaised ? "bg-accent/20" : "hover:bg-surface-raised"
        }`}
        title={handRaised ? "Lower hand" : "Raise hand"}
      >
        ✋
      </button>
    </div>
  );
}
