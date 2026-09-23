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
  deleteMeetingSecret,
  getMeetingSecret,
  getMeetingSecrets,
  saveMeetingSecret,
} from "./meeting-secrets";

beforeEach(() => {
  mockStore.clear();
});

describe("meeting secrets local cache", () => {
  it("has nothing saved by default", async () => {
    expect(await getMeetingSecret("meeting-1")).toBeNull();
  });

  it("saves and retrieves a meeting's password and PIN", async () => {
    await saveMeetingSecret({
      meetingId: "meeting-1",
      title: "Standup",
      password: "hunter2",
      hostPin: "123456",
    });

    const saved = await getMeetingSecret("meeting-1");
    expect(saved?.password).toBe("hunter2");
    expect(saved?.hostPin).toBe("123456");
    expect(saved?.title).toBe("Standup");
    expect(saved?.savedAt).toBeTruthy();
  });

  it("keeps multiple meetings' secrets independent", async () => {
    await saveMeetingSecret({
      meetingId: "meeting-1",
      title: "Standup",
      password: "pw-1",
      hostPin: "111111",
    });
    await saveMeetingSecret({
      meetingId: "meeting-2",
      title: "Retro",
      password: "pw-2",
      hostPin: "222222",
    });

    expect((await getMeetingSecret("meeting-1"))?.password).toBe("pw-1");
    expect((await getMeetingSecret("meeting-2"))?.password).toBe("pw-2");
  });

  it("getMeetingSecrets returns only the requested, saved ones", async () => {
    await saveMeetingSecret({
      meetingId: "meeting-1",
      title: "Standup",
      password: "pw-1",
      hostPin: null,
    });

    const result = await getMeetingSecrets(["meeting-1", "meeting-unknown"]);
    expect(Object.keys(result)).toEqual(["meeting-1"]);
    expect(result["meeting-1"].password).toBe("pw-1");
  });

  it("overwriting a meeting's secret replaces it, not merges", async () => {
    await saveMeetingSecret({
      meetingId: "meeting-1",
      title: "Standup",
      password: "old-pw",
      hostPin: "111111",
    });
    await saveMeetingSecret({
      meetingId: "meeting-1",
      title: "Standup (renamed)",
      password: "new-pw",
      hostPin: null,
    });

    const saved = await getMeetingSecret("meeting-1");
    expect(saved?.password).toBe("new-pw");
    expect(saved?.hostPin).toBeNull();
    expect(saved?.title).toBe("Standup (renamed)");
  });

  it("deleteMeetingSecret removes only that meeting's entry", async () => {
    await saveMeetingSecret({
      meetingId: "meeting-1",
      title: "Standup",
      password: "pw-1",
      hostPin: "111111",
    });
    await saveMeetingSecret({
      meetingId: "meeting-2",
      title: "Retro",
      password: "pw-2",
      hostPin: "222222",
    });

    await deleteMeetingSecret("meeting-1");

    expect(await getMeetingSecret("meeting-1")).toBeNull();
    expect((await getMeetingSecret("meeting-2"))?.password).toBe("pw-2");
  });

  it("deleting a meeting with no saved secret is a harmless no-op", async () => {
    await expect(deleteMeetingSecret("never-saved")).resolves.toBeUndefined();
  });
});
