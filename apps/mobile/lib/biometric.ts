import * as LocalAuthentication from "expo-local-authentication";

/**
 * Routine unlock (§17) — a local biometric prompt gating access to the
 * refresh token already sitting in SecureStore. This never talks to the
 * server on its own; the caller still has to call the real /auth/refresh
 * endpoint afterward. Not a substitute for the DITSALA Code + liveness
 * flow (lib/api.ts's login functions) for a genuinely new authentication.
 */

export async function isBiometricAvailable(): Promise<boolean> {
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  if (!hasHardware) return false;
  return LocalAuthentication.isEnrolledAsync();
}

export async function authenticateWithBiometrics(reason: string): Promise<boolean> {
  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: reason,
    disableDeviceFallback: false,
  });
  return result.success;
}
