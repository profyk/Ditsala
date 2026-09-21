"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Public marketing landing (business-model kickoff prompt, Feature 2) —
 * browsable by anyone, no login required. "Register" / "Create account"
 * never happens here: it routes to /get-app, which hands off to the
 * mobile app instead of collecting anything on the web. The existing
 * "join a meeting" utility (for someone who already has a meeting link)
 * stays a distinct section below, not the page's main purpose anymore.
 */

const FEATURES = [
  {
    title: "Speak your language, be understood in theirs",
    body: "Chat and conference messages translate automatically — a Setswana speaker and a French speaker can have a real conversation.",
  },
  {
    title: "Multilingual conferences",
    body: "Everyone in the room picks the language they speak and the language they want to receive — simultaneously, not one language at a time.",
  },
  {
    title: "Identity-verified, end-to-end encrypted",
    body: "Real KYC-backed accounts and end-to-end encrypted messaging, not an anonymous chat app.",
  },
  {
    title: "Built for real meetings",
    body: "Scheduling, waiting rooms, host controls, recording, and transcripts — a professional conferencing product, not a bolted-on video call.",
  },
];

export default function Home() {
  const router = useRouter();
  const [meetingId, setMeetingId] = useState("");

  return (
    <main className="flex min-h-screen flex-col items-center px-4 py-16">
      <section className="flex max-w-xl flex-col items-center gap-6 text-center">
        <h1 className="font-display text-4xl text-text-primary">Ditsala Conference</h1>
        <p className="text-lg text-text-secondary">Meet the world without language barriers.</p>
        <Link
          href="/get-app"
          className="rounded bg-accent px-6 py-3 font-medium text-background hover:bg-accent-pressed"
        >
          Create your DITSALA account
        </Link>
      </section>

      <section className="mt-16 grid w-full max-w-3xl gap-6 sm:grid-cols-2">
        {FEATURES.map((feature) => (
          <div
            key={feature.title}
            className="rounded border border-border bg-surface p-5 text-left"
          >
            <h2 className="font-display text-lg text-text-primary">{feature.title}</h2>
            <p className="mt-2 text-sm text-text-secondary">{feature.body}</p>
          </div>
        ))}
      </section>

      <section className="mt-16 flex w-full max-w-sm flex-col items-center gap-4 border-t border-border pt-10">
        <p className="text-center text-text-secondary">
          Already have a meeting link or ID? Join here.
        </p>
        <form
          className="flex w-full gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (meetingId.trim()) router.push(`/${meetingId.trim()}`);
          }}
        >
          <input
            value={meetingId}
            onChange={(e) => setMeetingId(e.target.value)}
            placeholder="Meeting ID"
            className="flex-1 rounded border border-border bg-surface px-4 py-2 text-text-primary outline-none focus:border-accent"
          />
          <button
            type="submit"
            className="rounded bg-surface-raised px-4 py-2 font-medium text-text-primary border border-border hover:bg-surface"
          >
            Join
          </button>
        </form>
      </section>
    </main>
  );
}
