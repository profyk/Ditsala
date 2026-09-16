"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { kycApi, type UserSummary } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function KycQueuePage() {
  const { token } = useAuth();
  const [queue, setQueue] = useState<UserSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    kycApi
      .listQueue(token)
      .then(setQueue)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load queue."));
  }, [token]);

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">
        KYC Review Queue
      </h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Accounts in <code>manual_review</code> awaiting a decision. Opening a record requires a
        reason for access, logged before any detail is shown (§5).
      </p>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <div className="overflow-hidden rounded border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface-raised text-left text-xs uppercase tracking-wide text-text-tertiary">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">Phone</th>
              <th className="px-4 py-3">Signed up</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {queue.map((user) => (
              <tr key={user.id} className="bg-surface">
                <td className="px-4 py-3 text-text-primary">{user.display_name}</td>
                <td className="px-4 py-3 text-text-secondary">{user.email}</td>
                <td className="px-4 py-3 text-text-secondary">{user.phone}</td>
                <td className="px-4 py-3 text-text-tertiary">
                  {new Date(user.created_at).toLocaleDateString()}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link href={`/kyc/${user.id}`} className="text-sm font-medium text-accent">
                    Review
                  </Link>
                </td>
              </tr>
            ))}
            {queue.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-text-tertiary">
                  Nothing in the queue.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
