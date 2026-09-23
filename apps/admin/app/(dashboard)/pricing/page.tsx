"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { TextField } from "@/components/TextField";
import {
  billingApi,
  type Entitlement,
  type Plan,
  type PlanPrice,
} from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { roleHasPermission } from "@/lib/rbac";

const PRODUCTS: Plan["product"][] = ["free", "vip", "business", "conference"];
const INTERVALS: PlanPrice["billing_interval"][] = ["month", "year", "one_time"];

function formatCents(cents: number, currency: string): string {
  return `${(cents / 100).toFixed(2)} ${currency}`;
}

export default function PricingPage() {
  const { token, role } = useAuth();
  const canAction = role ? roleHasPermission(role, "billing_plans:action") : false;

  const [plans, setPlans] = useState<Plan[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [newCode, setNewCode] = useState("");
  const [newProduct, setNewProduct] = useState<Plan["product"]>("vip");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setPlans(await billingApi.listPlans(token));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load plans.");
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreatePlan(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !newCode.trim() || !newName.trim()) return;
    setCreating(true);
    setError(null);
    try {
      await billingApi.createPlan(token, newCode.trim(), newProduct, newName.trim());
      setNewCode("");
      setNewName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create plan.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="max-w-3xl">
      <h1 className="mb-1 font-display text-2xl font-semibold text-text-primary">Pricing</h1>
      <p className="mb-8 text-sm text-text-tertiary">
        Plans, prices, and entitlements (§27-29) — nothing here is hardcoded in the app. Every
        change is audit-logged with before/after value.
      </p>

      {error ? <p className="mb-4 text-sm text-danger">{error}</p> : null}

      <div className="mb-6 space-y-4">
        {plans.map((plan) => (
          <PlanCard key={plan.id} plan={plan} token={token} canAction={canAction} onChanged={load} />
        ))}
        {plans.length === 0 ? (
          <p className="text-sm text-text-tertiary">No plans created yet.</p>
        ) : null}
      </div>

      {canAction ? (
        <Card title="Create a plan">
          <form onSubmit={handleCreatePlan}>
            <TextField
              label="Code"
              placeholder="e.g. vip, conference_starter"
              value={newCode}
              onChange={(e) => setNewCode(e.target.value)}
              required
            />
            <label className="mb-4 block">
              <span className="mb-1.5 block text-sm font-medium text-text-secondary">
                Product
              </span>
              <select
                className="w-full rounded border border-border bg-surface px-3 py-2 text-sm text-text-primary outline-none focus:border-accent"
                value={newProduct}
                onChange={(e) => setNewProduct(e.target.value as Plan["product"])}
              >
                {PRODUCTS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <TextField
              label="Display name"
              placeholder="e.g. Ditsala VIP"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              required
            />
            <Button type="submit" loading={creating} disabled={!newCode.trim() || !newName.trim()}>
              Create plan
            </Button>
          </form>
        </Card>
      ) : null}
    </div>
  );
}

function PlanCard({
  plan,
  token,
  canAction,
  onChanged,
}: {
  plan: Plan;
  token: string | null;
  canAction: boolean;
  onChanged: () => void;
}) {
  const [prices, setPrices] = useState<PlanPrice[] | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlement[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [priceCurrency, setPriceCurrency] = useState("ZAR");
  const [priceAmount, setPriceAmount] = useState("");
  const [priceInterval, setPriceInterval] = useState<PlanPrice["billing_interval"]>("month");
  const [priceReason, setPriceReason] = useState("");
  const [savingPrice, setSavingPrice] = useState(false);

  const [entKey, setEntKey] = useState("");
  const [entValue, setEntValue] = useState("true");
  const [entReason, setEntReason] = useState("");
  const [savingEnt, setSavingEnt] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [p, e] = await Promise.all([
        billingApi.listPlanPrices(token, plan.id),
        billingApi.listEntitlements(token, plan.id),
      ]);
      setPrices(p);
      setEntitlements(e);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load plan details.");
    }
  }, [token, plan.id]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSetPrice(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !priceAmount.trim() || !priceReason.trim()) return;
    const cents = Math.round(parseFloat(priceAmount) * 100);
    if (Number.isNaN(cents) || cents < 0) return;
    setSavingPrice(true);
    setError(null);
    try {
      await billingApi.setPlanPrice(token, plan.id, {
        currency: priceCurrency.trim().toUpperCase(),
        amount_cents: cents,
        billing_interval: priceInterval,
        reason: priceReason.trim(),
      });
      setPriceAmount("");
      setPriceReason("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not set price.");
    } finally {
      setSavingPrice(false);
    }
  }

  async function handleSetEntitlement(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !entKey.trim() || !entReason.trim()) return;
    let value: unknown;
    try {
      value = JSON.parse(entValue);
    } catch {
      value = entValue; // plain strings are valid entitlement values too
    }
    setSavingEnt(true);
    setError(null);
    try {
      await billingApi.setEntitlement(token, plan.id, entKey.trim(), value, entReason.trim());
      setEntKey("");
      setEntReason("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not set entitlement.");
    } finally {
      setSavingEnt(false);
    }
  }

  return (
    <Card
      title={`${plan.name} (${plan.code})`}
      action={
        <div className="flex items-center gap-2">
          <Badge label={plan.status} tone={plan.status === "active" ? "success" : "neutral"} />
          {canAction ? (
            <button
              type="button"
              onClick={async () => {
                if (!token) return;
                const next = plan.status === "active" ? "archived" : "active";
                const reason = window.prompt(
                  `Reason for ${next === "archived" ? "archiving" : "reactivating"} "${plan.name}"?`
                );
                if (!reason) return;
                try {
                  await billingApi.setPlanStatus(token, plan.id, next, reason);
                  onChanged();
                } catch (err) {
                  setError(err instanceof ApiError ? err.message : "Could not update status.");
                }
              }}
              className="text-xs font-medium text-text-secondary hover:text-danger"
            >
              {plan.status === "active" ? "Archive" : "Reactivate"}
            </button>
          ) : null}
        </div>
      }
    >
      {error ? <p className="mb-3 text-xs text-danger">{error}</p> : null}

      <p className="mb-1 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Prices
      </p>
      <div className="mb-4 space-y-1">
        {prices === null ? (
          <p className="text-xs text-text-tertiary">Loading…</p>
        ) : prices.length === 0 ? (
          <p className="text-xs text-text-tertiary">No price set yet.</p>
        ) : (
          prices.map((price) => (
            <div key={price.id} className="flex items-center justify-between text-sm">
              <span className="text-text-primary">
                {formatCents(price.amount_cents, price.currency)} / {price.billing_interval}
              </span>
              <Badge label={price.status} tone={price.status === "active" ? "success" : "neutral"} />
            </div>
          ))
        )}
      </div>

      <p className="mb-1 text-xs font-medium uppercase tracking-widest text-text-tertiary">
        Entitlements
      </p>
      <div className="mb-4 space-y-1">
        {entitlements === null ? (
          <p className="text-xs text-text-tertiary">Loading…</p>
        ) : entitlements.length === 0 ? (
          <p className="text-xs text-text-tertiary">No entitlements set yet.</p>
        ) : (
          entitlements.map((ent) => (
            <div key={ent.key} className="flex items-center justify-between text-sm">
              <span className="font-mono text-xs text-text-primary">{ent.key}</span>
              <span className="text-xs text-text-secondary">{JSON.stringify(ent.value)}</span>
            </div>
          ))
        )}
      </div>

      {canAction ? (
        <div className="grid gap-4 border-t border-border pt-4 sm:grid-cols-2">
          <form onSubmit={handleSetPrice} className="space-y-2">
            <p className="text-xs font-medium text-text-secondary">Set a price</p>
            <div className="flex gap-2">
              <input
                className="w-20 rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
                value={priceCurrency}
                onChange={(e) => setPriceCurrency(e.target.value)}
                placeholder="ZAR"
              />
              <input
                className="flex-1 rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
                value={priceAmount}
                onChange={(e) => setPriceAmount(e.target.value)}
                placeholder="99.00"
                inputMode="decimal"
              />
            </div>
            <select
              className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
              value={priceInterval}
              onChange={(e) =>
                setPriceInterval(e.target.value as PlanPrice["billing_interval"])
              }
            >
              {INTERVALS.map((i) => (
                <option key={i} value={i}>
                  {i}
                </option>
              ))}
            </select>
            <input
              className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
              value={priceReason}
              onChange={(e) => setPriceReason(e.target.value)}
              placeholder="Reason (audit-logged)"
            />
            <Button
              type="submit"
              variant="secondary"
              loading={savingPrice}
              disabled={!priceAmount.trim() || !priceReason.trim()}
              className="w-full"
            >
              Save price
            </Button>
          </form>

          <form onSubmit={handleSetEntitlement} className="space-y-2">
            <p className="text-xs font-medium text-text-secondary">Set an entitlement</p>
            <input
              className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
              value={entKey}
              onChange={(e) => setEntKey(e.target.value)}
              placeholder="e.g. conference.max_participants"
            />
            <input
              className="w-full rounded border border-border bg-surface px-2 py-1.5 font-mono text-sm text-text-primary outline-none focus:border-accent"
              value={entValue}
              onChange={(e) => setEntValue(e.target.value)}
              placeholder="true, 25, or a string"
            />
            <input
              className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text-primary outline-none focus:border-accent"
              value={entReason}
              onChange={(e) => setEntReason(e.target.value)}
              placeholder="Reason (audit-logged)"
            />
            <Button
              type="submit"
              variant="secondary"
              loading={savingEnt}
              disabled={!entKey.trim() || !entReason.trim()}
              className="w-full"
            >
              Save entitlement
            </Button>
          </form>
        </div>
      ) : null}
    </Card>
  );
}
