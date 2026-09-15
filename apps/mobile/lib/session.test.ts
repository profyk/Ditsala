/* eslint-disable import/first -- jest.mock must precede the import it mocks */
const mockStore = new Map<string, string>();

jest.mock("expo-secure-store", () => ({
  setItemAsync: jest.fn((key: string, value: string) => {
    mockStore.set(key, value);
    return Promise.resolve();
  }),
  getItemAsync: jest.fn((key: string) => Promise.resolve(mockStore.get(key) ?? null)),
  deleteItemAsync: jest.fn((key: string) => {
    mockStore.delete(key);
    return Promise.resolve();
  }),
}));

import {
  clearSession,
  getAccessToken,
  getRefreshToken,
  hasStoredSession,
  saveAccessToken,
  saveSession,
} from "./session";

beforeEach(() => {
  mockStore.clear();
});

describe("session storage", () => {
  it("has no session by default", async () => {
    expect(await hasStoredSession()).toBe(false);
    expect(await getAccessToken()).toBeNull();
    expect(await getRefreshToken()).toBeNull();
  });

  it("saveSession stores both tokens", async () => {
    await saveSession("access-1", "refresh-1");
    expect(await getAccessToken()).toBe("access-1");
    expect(await getRefreshToken()).toBe("refresh-1");
    expect(await hasStoredSession()).toBe(true);
  });

  it("saveAccessToken updates only the access token", async () => {
    await saveSession("access-1", "refresh-1");
    await saveAccessToken("access-2");
    expect(await getAccessToken()).toBe("access-2");
    expect(await getRefreshToken()).toBe("refresh-1");
  });

  it("clearSession removes both tokens", async () => {
    await saveSession("access-1", "refresh-1");
    await clearSession();
    expect(await getAccessToken()).toBeNull();
    expect(await getRefreshToken()).toBeNull();
    expect(await hasStoredSession()).toBe(false);
  });
});
