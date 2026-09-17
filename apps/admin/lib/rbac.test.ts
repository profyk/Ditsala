import { describe, expect, it } from "vitest";

import { roleHasPermission } from "./rbac";

describe("roleHasPermission", () => {
  it("grants super_admin every permission", () => {
    expect(roleHasPermission("super_admin", "system_config:action")).toBe(true);
    expect(roleHasPermission("super_admin", "kyc:queue:action")).toBe(true);
  });

  it("restricts kyc_reviewer to KYC and dashboard only", () => {
    expect(roleHasPermission("kyc_reviewer", "kyc:queue:view")).toBe(true);
    expect(roleHasPermission("kyc_reviewer", "reports:view")).toBe(false);
    expect(roleHasPermission("kyc_reviewer", "system_config:view")).toBe(false);
  });

  it("restricts trust_safety away from KYC and system config", () => {
    expect(roleHasPermission("trust_safety", "reports:action")).toBe(true);
    expect(roleHasPermission("trust_safety", "users:action")).toBe(true);
    expect(roleHasPermission("trust_safety", "kyc:queue:view")).toBe(false);
    expect(roleHasPermission("trust_safety", "system_config:view")).toBe(false);
  });

  it("restricts support_readonly to view-only dashboard and users", () => {
    expect(roleHasPermission("support_readonly", "users:view")).toBe(true);
    expect(roleHasPermission("support_readonly", "users:action")).toBe(false);
    expect(roleHasPermission("support_readonly", "reports:view")).toBe(false);
  });

  it("returns false for an unknown role rather than throwing", () => {
    expect(roleHasPermission("nonexistent_role", "dashboard:view")).toBe(false);
  });

  it("restricts admin user management to super_admin only", () => {
    expect(roleHasPermission("super_admin", "admin_users:action")).toBe(true);
    expect(roleHasPermission("kyc_reviewer", "admin_users:view")).toBe(false);
    expect(roleHasPermission("trust_safety", "admin_users:view")).toBe(false);
    expect(roleHasPermission("support_readonly", "admin_users:view")).toBe(false);
  });
});
