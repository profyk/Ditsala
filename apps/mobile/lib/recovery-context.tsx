import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";

interface RecoveryContextValue {
  recoveryRequestId: string | null;
  setRecoveryRequestId: (id: string) => void;
  clear: () => void;
}

const RecoveryContext = createContext<RecoveryContextValue | null>(null);

/**
 * Holds the in-flight recovery request id (docs/DITSALA_MASTER_SPEC.md
 * §33) for the lifetime of the recovery flow — same in-memory-only
 * pattern as OnboardingProvider, since this id is only meaningful while
 * the flow is active and carries no long-lived secret.
 */
export function RecoveryProvider({ children }: PropsWithChildren) {
  const [recoveryRequestId, setId] = useState<string | null>(null);

  const setRecoveryRequestId = useCallback((id: string) => setId(id), []);
  const clear = useCallback(() => setId(null), []);

  const value = useMemo(
    () => ({ recoveryRequestId, setRecoveryRequestId, clear }),
    [recoveryRequestId, setRecoveryRequestId, clear]
  );

  return <RecoveryContext.Provider value={value}>{children}</RecoveryContext.Provider>;
}

export function useRecovery(): RecoveryContextValue {
  const context = useContext(RecoveryContext);
  if (context === null) {
    throw new Error("useRecovery must be used within a RecoveryProvider");
  }
  return context;
}
