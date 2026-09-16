"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { authApi } from "@/lib/admin-api";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

type Step =
  | { kind: "credentials" }
  | { kind: "mfa_enroll"; enrollToken: string; provisioningUri: string }
  | { kind: "mfa_code"; loginToken: string };

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [step, setStep] = useState<Step>({ kind: "credentials" });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleCredentialsSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = await authApi.loginStart(email, password);
      if (result.status === "mfa_enroll_required") {
        setStep({
          kind: "mfa_enroll",
          enrollToken: result.mfa_enroll_token!,
          provisioningUri: result.provisioning_uri!,
        });
      } else {
        setStep({ kind: "mfa_code", loginToken: result.login_token! });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleMfaSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const session =
        step.kind === "mfa_enroll"
          ? await authApi.enrollMfa(step.enrollToken, code)
          : step.kind === "mfa_code"
            ? await authApi.completeLogin(step.loginToken, code)
            : null;
      if (!session) return;
      login(session.access_token, session.email, session.role);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Incorrect code.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <p className="mb-1 font-display text-2xl font-semibold text-text-primary">DITSALA</p>
        <p className="mb-8 text-sm text-text-tertiary">Admin panel</p>

        {error ? (
          <p className="mb-4 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error}
          </p>
        ) : null}

        {step.kind === "credentials" ? (
          <form onSubmit={handleCredentialsSubmit}>
            <TextField
              label="Email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <TextField
              label="Password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <Button type="submit" loading={submitting} className="w-full">
              Continue
            </Button>
          </form>
        ) : (
          <form onSubmit={handleMfaSubmit}>
            {step.kind === "mfa_enroll" ? (
              <div className="mb-5 rounded border border-border bg-surface p-4">
                <p className="mb-2 text-sm text-text-secondary">
                  Set up MFA — this is required before first use. Scan this in an authenticator
                  app (Google Authenticator, 1Password, etc.):
                </p>
                <p className="break-all rounded bg-surface-raised p-2 font-mono text-xs text-text-tertiary">
                  {step.provisioningUri}
                </p>
              </div>
            ) : null}
            <TextField
              label="6-digit code"
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
              required
            />
            <Button type="submit" loading={submitting} className="w-full">
              {step.kind === "mfa_enroll" ? "Confirm & finish setup" : "Verify"}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
