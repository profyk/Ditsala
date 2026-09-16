/**
 * Backend API client for the admin panel (docs/DITSALA_MASTER_SPEC.md
 * §28-29). Mirrors apps/mobile/lib/api.ts's shape (thin `request()` +
 * per-domain method objects) — a separate client, not a shared package,
 * since the two apps' auth models (bearer admin token vs. mobile session)
 * differ enough that sharing would mean threading token-type generics
 * through everything for no real benefit at this size.
 */

export const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number
  ) {
    super(message);
  }
}

export async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; token?: string | null; params?: Record<string, string | number | boolean | undefined> } = {}
): Promise<T> {
  const query = options.params
    ? "?" +
      Object.entries(options.params)
        .filter(([, v]) => v !== undefined)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join("&")
    : "";

  const response = await fetch(`${BASE_URL}/api/v1${path}${query}`, {
    method: options.method ?? (options.body === undefined ? "GET" : "POST"),
    headers: {
      "Content-Type": "application/json",
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body?.detail === "string" ? body.detail : "Something went wrong.";
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
