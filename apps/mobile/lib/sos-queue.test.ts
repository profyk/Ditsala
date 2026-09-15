/* eslint-disable import/first -- jest.mock must precede the import it mocks */
const mockTrigger = jest.fn();

jest.mock("./sos-api", () => ({
  sosApi: { trigger: (...args: unknown[]) => mockTrigger(...args) },
}));

import { triggerSosWithRetry } from "./sos-queue";

beforeEach(() => {
  mockTrigger.mockReset();
});

describe("triggerSosWithRetry", () => {
  it("resolves immediately on first success", async () => {
    mockTrigger.mockResolvedValueOnce({ id: "evt-1", status: "armed" });
    const statuses: string[] = [];

    const { promise } = triggerSosWithRetry("token", undefined, (s) => statuses.push(s));
    const event = await promise;

    expect(event).toEqual({ id: "evt-1", status: "armed" });
    expect(statuses).toEqual(["sending", "sent"]);
    expect(mockTrigger).toHaveBeenCalledTimes(1);
  });

  it("keeps retrying past a network blip and eventually succeeds", async () => {
    mockTrigger
      .mockRejectedValueOnce(new Error("offline"))
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ id: "evt-1", status: "armed" });
    const statuses: string[] = [];

    const { promise } = triggerSosWithRetry(
      "token",
      undefined,
      (s) => statuses.push(s),
      { retryDelayMs: 1 }
    );
    const event = await promise;

    expect(event.id).toBe("evt-1");
    expect(statuses).toEqual(["sending", "retrying", "retrying", "sent"]);
    expect(mockTrigger).toHaveBeenCalledTimes(3);
  });

  it("gives up after maxAttempts and reports failed", async () => {
    mockTrigger.mockRejectedValue(new Error("offline"));
    const statuses: string[] = [];

    const { promise } = triggerSosWithRetry(
      "token",
      undefined,
      (s) => statuses.push(s),
      { maxAttempts: 3, retryDelayMs: 1 }
    );

    await expect(promise).rejects.toThrow("offline");
    expect(statuses).toEqual(["sending", "retrying", "retrying", "failed"]);
    expect(mockTrigger).toHaveBeenCalledTimes(3);
  });

  it("stops retrying once cancelled", async () => {
    mockTrigger.mockRejectedValue(new Error("offline"));
    const statuses: string[] = [];

    const { promise, cancel } = triggerSosWithRetry(
      "token",
      undefined,
      (s) => statuses.push(s),
      { retryDelayMs: 20 }
    );
    // Let it fail once, then cancel before the next retry fires.
    await new Promise((resolve) => setTimeout(resolve, 5));
    cancel();

    await expect(promise).rejects.toThrow();
    expect(statuses[statuses.length - 1]).toBe("cancelled");
    const callsAtCancel = mockTrigger.mock.calls.length;

    // No further attempts should happen after cancellation.
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(mockTrigger.mock.calls.length).toBe(callsAtCancel);
  });

  it("passes the last known location ref through to the API", async () => {
    mockTrigger.mockResolvedValueOnce({ id: "evt-1", status: "armed" });
    await triggerSosWithRetry("token", "-26.2,28.0", () => undefined).promise;
    expect(mockTrigger).toHaveBeenCalledWith("token", "-26.2,28.0");
  });
});
