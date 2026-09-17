"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { TextField } from "@/components/TextField";
import { adminApi, type AdminUserSummary } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission, ROLE_PERMISSIONS } from "@/lib/rbac";

const ROLE_OPTIONS = Object.keys(ROLE_PERMISSIONS);

export default function AdminsPage() {
  const { token, email, role } = useAuth();
  const canAction = role ? roleHasPermission(role, "admin_users:action") : false;

  const [admins, setAdmins] = useState<AdminUserSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState(ROLE_OPTIONS[0] ?? "support_readonly");
  const [creating, setCreating] = useState(false);
  const [createdPassword, setCreatedPassword] = useState<string | null>(null);

  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setAdmins(await adminApi.listAdmins(token));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load admins.");
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreate() {
    if (!token || !newEmail.trim() || !newPassword) return;
    setCreating(true);
    setError(null);
    try {
      await adminApi.createAdmin(token, newEmail.trim(), newPassword, newRole);
      setCreatedPassword(newPassword);
      setNewEmail("");
      setNewPassword("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create admin.");
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(admin: AdminUserSummary) {
    if (!token) return;
    setBusyId(admin.id);
    setError(null);
    try {
      await adminApi.setAdminActive(token, admin.id, !admin.is_active);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update admin.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleRoleChange(admin: AdminUserSummary, nextRole: string) {
    if (!token || nextRole === admin.role) return;
    setBusyId(admin.id);
    setError(null);
    try {
      await adminApi.changeAdminRole(token, admin.id, nextRole);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not change role.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">Admins</h1>
      <p className="mb-8 text-sm text-text-tertiary">
        super_admin only. Admin accounts are never self-serve — creating one here sets its
        initial password directly; share it with the new admin out of band. MFA enrollment
        happens automatically on their first login.
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      {canAction ? (
        <Card title="Add an admin">
          {createdPassword ? (
            <div className="mb-4 rounded border border-accent/30 bg-accent-muted p-3 text-sm text-text-primary">
              Account created. Share this password with them once, out of band — it won&apos;t
              be shown again:{" "}
              <span className="font-mono font-semibold">{createdPassword}</span>
              <Button
                variant="secondary"
                className="ml-3"
                onClick={() => setCreatedPassword(null)}
              >
                Dismiss
              </Button>
            </div>
          ) : null}
          <TextField
            label="Email"
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
          />
          <TextField
            label="Initial password (12+ characters)"
            type="text"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <label className="mb-4 block">
            <span className="mb-1.5 block text-sm font-medium text-text-secondary">Role</span>
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value)}
              className="w-full rounded border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <Button
            loading={creating}
            disabled={!newEmail.trim() || newPassword.length < 12}
            onClick={handleCreate}
          >
            Create admin
          </Button>
        </Card>
      ) : null}

      <div className="h-4" />

      <Card title="All admins">
        <div className="space-y-2">
          {admins.map((admin) => {
            const isSelf = admin.email === email;
            return (
              <div
                key={admin.id}
                className="flex items-center justify-between gap-3 border-b border-border py-3 last:border-0"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm text-text-primary">
                    {admin.email}
                    {isSelf ? <span className="ml-2 text-xs text-text-tertiary">(you)</span> : null}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <Badge
                      label={admin.is_active ? "Active" : "Deactivated"}
                      tone={admin.is_active ? "success" : "neutral"}
                    />
                    <Badge
                      label={admin.mfa_enrolled ? "MFA enrolled" : "MFA pending"}
                      tone={admin.mfa_enrolled ? "success" : "warning"}
                    />
                    <span className="text-xs text-text-tertiary">
                      Last login:{" "}
                      {admin.last_login_at
                        ? new Date(admin.last_login_at).toLocaleString()
                        : "never"}
                    </span>
                  </div>
                </div>

                {canAction ? (
                  <div className="flex items-center gap-2">
                    <select
                      value={admin.role}
                      disabled={isSelf || busyId === admin.id}
                      onChange={(e) => handleRoleChange(admin, e.target.value)}
                      className="rounded border border-border bg-surface px-2 py-1.5 text-xs text-text-primary outline-none focus:border-accent disabled:opacity-50"
                    >
                      {ROLE_OPTIONS.map((r) => (
                        <option key={r} value={r}>
                          {r.replace(/_/g, " ")}
                        </option>
                      ))}
                    </select>
                    <Button
                      variant={admin.is_active ? "danger" : "secondary"}
                      disabled={isSelf}
                      loading={busyId === admin.id}
                      onClick={() => handleToggleActive(admin)}
                    >
                      {admin.is_active ? "Deactivate" : "Reactivate"}
                    </Button>
                  </div>
                ) : (
                  <Badge label={admin.role.replace(/_/g, " ")} tone="accent" />
                )}
              </div>
            );
          })}
          {admins.length === 0 ? (
            <p className="text-sm text-text-tertiary">No admins found.</p>
          ) : null}
        </div>
      </Card>
    </div>
  );
}
