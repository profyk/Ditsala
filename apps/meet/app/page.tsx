"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Home() {
  const router = useRouter();
  const [meetingId, setMeetingId] = useState("");

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <h1 className="font-display text-4xl text-text-primary">Ditsala Meet</h1>
      <p className="max-w-sm text-center text-text-secondary">
        Enter a meeting ID to join. Ask your host for the link they shared.
      </p>
      <form
        className="flex w-full max-w-sm gap-2"
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
          className="rounded bg-accent px-4 py-2 font-medium text-background hover:bg-accent-pressed"
        >
          Join
        </button>
      </form>
    </main>
  );
}
