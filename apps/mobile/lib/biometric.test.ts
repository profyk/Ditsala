/* eslint-disable import/first -- jest.mock must precede the import it mocks */
const mockHasHardwareAsync = jest.fn();
const mockIsEnrolledAsync = jest.fn();
const mockAuthenticateAsync = jest.fn();

jest.mock("expo-local-authentication", () => ({
  hasHardwareAsync: () => mockHasHardwareAsync(),
  isEnrolledAsync: () => mockIsEnrolledAsync(),
  authenticateAsync: (options: unknown) => mockAuthenticateAsync(options),
}));

import { authenticateWithBiometrics, isBiometricAvailable } from "./biometric";

beforeEach(() => {
  mockHasHardwareAsync.mockReset();
  mockIsEnrolledAsync.mockReset();
  mockAuthenticateAsync.mockReset();
});

describe("isBiometricAvailable", () => {
  it("is false when there's no hardware", async () => {
    mockHasHardwareAsync.mockResolvedValue(false);
    expect(await isBiometricAvailable()).toBe(false);
    expect(mockIsEnrolledAsync).not.toHaveBeenCalled();
  });

  it("is false when hardware exists but nothing is enrolled", async () => {
    mockHasHardwareAsync.mockResolvedValue(true);
    mockIsEnrolledAsync.mockResolvedValue(false);
    expect(await isBiometricAvailable()).toBe(false);
  });

  it("is true when hardware exists and biometrics are enrolled", async () => {
    mockHasHardwareAsync.mockResolvedValue(true);
    mockIsEnrolledAsync.mockResolvedValue(true);
    expect(await isBiometricAvailable()).toBe(true);
  });
});

describe("authenticateWithBiometrics", () => {
  it("returns true on success", async () => {
    mockAuthenticateAsync.mockResolvedValue({ success: true });
    expect(await authenticateWithBiometrics("Unlock")).toBe(true);
    expect(mockAuthenticateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ promptMessage: "Unlock" })
    );
  });

  it("returns false when the user cancels", async () => {
    mockAuthenticateAsync.mockResolvedValue({ success: false });
    expect(await authenticateWithBiometrics("Unlock")).toBe(false);
  });
});
