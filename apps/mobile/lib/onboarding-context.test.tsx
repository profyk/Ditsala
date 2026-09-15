import { act, renderHook } from "@testing-library/react-native";

import { OnboardingProvider, useOnboarding } from "./onboarding-context";

describe("useOnboarding", () => {
  it("throws when used outside a provider", () => {
    const { result } = renderHook(() => {
      try {
        return useOnboarding();
      } catch (error) {
        return error as Error;
      }
    });
    expect(result.current).toBeInstanceOf(Error);
  });

  it("starts with no session", () => {
    const { result } = renderHook(() => useOnboarding(), { wrapper: OnboardingProvider });
    expect(result.current.token).toBeNull();
    expect(result.current.accountState).toBeNull();
  });

  it("setSession stores the token and account state", () => {
    const { result } = renderHook(() => useOnboarding(), { wrapper: OnboardingProvider });

    act(() => {
      result.current.setSession("a.jwt.token", "pending_email");
    });

    expect(result.current.token).toBe("a.jwt.token");
    expect(result.current.accountState).toBe("pending_email");
  });

  it("setAccountState updates state without touching the token", () => {
    const { result } = renderHook(() => useOnboarding(), { wrapper: OnboardingProvider });

    act(() => {
      result.current.setSession("a.jwt.token", "pending_email");
    });
    act(() => {
      result.current.setAccountState("pending_phone");
    });

    expect(result.current.token).toBe("a.jwt.token");
    expect(result.current.accountState).toBe("pending_phone");
  });

  it("clear resets both token and account state", () => {
    const { result } = renderHook(() => useOnboarding(), { wrapper: OnboardingProvider });

    act(() => {
      result.current.setSession("a.jwt.token", "pending_email");
    });
    act(() => {
      result.current.clear();
    });

    expect(result.current.token).toBeNull();
    expect(result.current.accountState).toBeNull();
  });
});
