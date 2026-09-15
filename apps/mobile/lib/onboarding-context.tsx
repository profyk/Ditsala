import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";

import type { AccountState } from "./api";

interface OnboardingContextValue {
  token: string | null;
  accountState: AccountState | null;
  setSession: (token: string, accountState: AccountState) => void;
  setAccountState: (accountState: AccountState) => void;
  clear: () => void;
}

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

/**
 * Holds the onboarding JWT (docs/DITSALA_MASTER_SPEC.md §9, ADR 0002) for
 * the lifetime of the onboarding flow. Deliberately in-memory, not
 * SecureStore — this token is short-lived (2h) and scoped to onboarding
 * only; durable session storage (§16, real access/refresh tokens in
 * SecureStore) is Phase 3's concern, not this one's.
 */
export function OnboardingProvider({ children }: PropsWithChildren) {
  const [token, setToken] = useState<string | null>(null);
  const [accountState, setAccountStateValue] = useState<AccountState | null>(null);

  const setSession = useCallback((newToken: string, newAccountState: AccountState) => {
    setToken(newToken);
    setAccountStateValue(newAccountState);
  }, []);

  const setAccountState = useCallback((newAccountState: AccountState) => {
    setAccountStateValue(newAccountState);
  }, []);

  const clear = useCallback(() => {
    setToken(null);
    setAccountStateValue(null);
  }, []);

  const value = useMemo(
    () => ({ token, accountState, setSession, setAccountState, clear }),
    [token, accountState, setSession, setAccountState, clear]
  );

  return <OnboardingContext.Provider value={value}>{children}</OnboardingContext.Provider>;
}

export function useOnboarding(): OnboardingContextValue {
  const context = useContext(OnboardingContext);
  if (context === null) {
    throw new Error("useOnboarding must be used within an OnboardingProvider");
  }
  return context;
}
