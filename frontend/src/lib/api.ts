"use client";

/** Same-origin `/api/v1` is proxied by Next (see next.config.ts). Override with full URL only if needed. */
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function looksLikeHtml(body: string): boolean {
  const t = body.trimStart();
  return t.startsWith("<") || body.includes("<!DOCTYPE") || body.includes("<html");
}

function fallbackMessage(status: number): string {
  if (status === 401) {
    return "Unauthorized";
  }
  if (status >= 500) {
    return `Server error (${status}). The API or Next.js proxy failed—check Docker logs for \`backend\` and \`frontend\`, and that BACKEND_INTERNAL_URL reaches the API.`;
  }
  return `Request failed (${status})`;
}

function messageFromFastApiDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return "";
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  if (detail && typeof detail === "object") {
    return JSON.stringify(detail);
  }
  return null;
}

async function readErrorMessage(response: Response): Promise<string> {
  const raw = (await response.text()).trim();

  if (!raw || raw === "Internal Server Error" || looksLikeHtml(raw)) {
    return fallbackMessage(response.status);
  }

  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    const fromDetail = parsed.detail !== undefined ? messageFromFastApiDetail(parsed.detail) : null;
    if (fromDetail) {
      return fromDetail;
    }
  } catch {
    // not JSON — use short text if reasonable
  }

  if (raw.length > 500) {
    return fallbackMessage(response.status);
  }

  return raw;
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;

  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {})
    }
  });

  if (response.status === 401 && typeof window !== "undefined") {
    localStorage.removeItem("token");
    window.location.href = "/login";
    throw new ApiError("Unauthorized", 401);
  }

  if (!response.ok) {
    const message = await readErrorMessage(response);
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return (await response.json()) as T;
}
