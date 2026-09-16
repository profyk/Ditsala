"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AccountStateBadge } from "@/components/Badge";
import { TextField } from "@/components/TextField";
import { adminApi, type UserSummary } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const ACCOUNT_STATES = [
  "",
  "pending_email",
  "pending_phone",
  "pending_kyc_document",
  "pending_kyc_liveness",
  "pending_next_of_kin",
  "pending_code",
  "active",
  "manual_review",
  "suspended",
  "deactivated",
  "banned",
];

export default function UsersPage() {
  const { token } = useAuth();
  const [query, setQuery] = useState("");
  const [accountState, setAccountState] = useState("");
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    const handle = setTimeout(() => {
      adminApi
        .searchUsers(token, { q: query || undefined, account_state: accountState || undefined })
        .then(setUsers)
        .catch((err) => setError(err instanceof ApiError ? err.message : "Could not search."));
    }, 300);
    return () => clearTimeout(handle);
  }, [token, query, accountState]);

  return (
    <div>
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">Users</h1>
      <p className="mb-6 text-sm text-text-tertiary">
        Search by non-content metadata only — email, phone, name, account state (§28.3). There is
        no message content to search server-side.
      </p>

      <div className="mb-6 flex gap-4">
        <div className="w-72">
          <TextField
            label="Search"
            placeholder="Email, phone, or name"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="w-56">
          <label className="mb-4 block">
            <span className="mb-1.5 block text-sm font-medium text-text-secondary">
              Account state
            </span>
            <select
              className="w-full rounded border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
              value={accountState}
              onChange={(e) => setAccountState(e.target.value)}
            >
              {ACCOUNT_STATES.map((s) => (
                <option key={s} value={s}>
                  {s ? s.replace(/_/g, " ") : "Any state"}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {error ? <p className="text-sm text-danger">{error}</p> : null}

      <div className="overflow-hidden rounded border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface-raised text-left text-xs uppercase tracking-wide text-text-tertiary">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Email</th>
              <th className="px-4 py-3">State</th>
              <th className="px-4 py-3">Signed up</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {users.map((user) => (
              <tr key={user.id} className="bg-surface">
                <td className="px-4 py-3">
                  <Link href={`/users/${user.id}`} className="font-medium text-accent">
                    {user.display_name}
                  </Link>
                </td>
                <td className="px-4 py-3 text-text-secondary">{user.email}</td>
                <td className="px-4 py-3">
                  <AccountStateBadge state={user.account_state} />
                </td>
                <td className="px-4 py-3 text-text-tertiary">
                  {new Date(user.created_at).toLocaleDateString()}
                </td>
              </tr>
            ))}
            {users.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-text-tertiary">
                  No matches.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
