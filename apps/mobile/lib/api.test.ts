import { ApiError, NetworkError, request } from "./api";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("request", () => {
  let mockFetch: jest.Mock;

  beforeEach(() => {
    mockFetch = jest.fn();
    globalThis.fetch = mockFetch as unknown as typeof fetch;
  });

  it("returns parsed JSON on success", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    await expect(request<{ ok: boolean }>("/health")).resolves.toEqual({ ok: true });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("returns undefined for a 204", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(204, null));
    await expect(request("/logout")).resolves.toBeUndefined();
  });

  it("throws ApiError immediately on a 400 without retrying", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(400, { detail: "Bad input" }));
    await expect(request("/thing")).rejects.toMatchObject(
      new ApiError("Bad input", 400)
    );
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("retries a network failure and succeeds on the second attempt", async () => {
    mockFetch
      .mockRejectedValueOnce(new TypeError("Network request failed"))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await expect(request<{ ok: boolean }>("/thing")).resolves.toEqual({ ok: true });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("retries a 503 and succeeds", async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse(503, {}))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await expect(request<{ ok: boolean }>("/thing")).resolves.toEqual({ ok: true });
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("throws NetworkError after exhausting retries on persistent network failure", async () => {
    mockFetch.mockRejectedValue(new TypeError("Network request failed"));

    await expect(request("/thing")).rejects.toBeInstanceOf(NetworkError);
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  it("throws ApiError after exhausting retries on a persistent 503", async () => {
    mockFetch.mockResolvedValue(jsonResponse(503, {}));

    await expect(request("/thing")).rejects.toBeInstanceOf(ApiError);
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });
});
