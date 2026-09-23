"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { ThemeToggle } from "@/components/ThemeToggle";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission, type Permission } from "@/lib/rbac";

const NAV_ITEMS: { href: string; label: string; permission: Permission }[] = [
  { href: "/dashboard", label: "Dashboard", permission: "dashboard:view" },
  { href: "/kyc", label: "KYC Review Queue", permission: "kyc:queue:view" },
  { href: "/users", label: "Users", permission: "users:view" },
  { href: "/reports", label: "Reports & Moderation", permission: "reports:view" },
  { href: "/security", label: "Security Dashboard", permission: "security:view" },
  { href: "/invitations", label: "Invitations", permission: "invitations:view" },
  { href: "/audit-log", label: "Audit Log", permission: "audit:view" },
  { href: "/system-config", label: "System Configuration", permission: "system_config:view" },
  { href: "/admins", label: "Admins", permission: "admin_users:view" },
  { href: "/pricing", label: "Pricing", permission: "billing_plans:view" },
  {
    href: "/conference-plans",
    label: "Conference Plans",
    permission: "billing_plans:view",
  },
  {
    href: "/live-meetings",
    label: "Live Meetings",
    permission: "meetings_governance:view",
  },
  { href: "/revenue", label: "Revenue", permission: "revenue:view" },
  {
    href: "/data-requests",
    label: "Data Subject Requests",
    permission: "data_subject_requests:view",
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const { role, email, logout } = useAuth();

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-border bg-surface">
      <div className="shrink-0 border-b border-border px-5 py-5">
        <p className="font-display text-lg font-semibold tracking-wide text-text-primary">
          DITSALA
        </p>
        <p className="text-xs text-text-tertiary">Admin</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <nav className="flex flex-col gap-0.5 p-3">
          {NAV_ITEMS.filter((item) => role && roleHasPermission(role, item.permission)).map(
            (item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded px-3 py-2 text-sm transition-colors ${
                    active
                      ? "bg-accent-muted text-accent"
                      : "text-text-secondary hover:bg-surface-raised hover:text-text-primary"
                  }`}
                >
                  {item.label}
                </Link>
              );
            }
          )}
        </nav>
      </div>
      <div className="shrink-0 border-t border-border p-2">
        <ThemeToggle />
      </div>
      <div className="shrink-0 border-t border-border p-4">
        <p className="mb-1 truncate text-sm text-text-primary">{email}</p>
        <p className="mb-3 text-xs capitalize text-text-tertiary">{role?.replace(/_/g, " ")}</p>
        <button
          onClick={() => logout()}
          className="text-xs font-medium text-text-secondary hover:text-danger"
        >
          Log out
        </button>
      </div>
    </aside>
  );
}
