"use client";

import {
  recordTelemetryApiError,
  recordTelemetryClientError,
  recordTelemetryNetworkError,
  recordTelemetrySlowRequest,
} from "@/lib/telemetry/record";
import { dictionaries, type TranslationKey } from "@/lib/i18n/dict";
import { DEFAULT_LOCALE, STORAGE_KEY, type Locale } from "@/lib/i18n/types";

/** Same-origin `/api/v1` is proxied by Next (see next.config.ts). Override with full URL only if needed. */
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(/\/$/, "");

const SLOW_REQUEST_MS = 4000;

// Module-level access token (synchronized with AuthContext)
let _accessToken: string | null = null;
let _isRefreshing = false;
let _refreshPromise: Promise<boolean> | null = null;

export function setApiAccessToken(token: string | null): void {
  _accessToken = token;
}

async function refreshAccessToken(): Promise<boolean> {
  // Prevent multiple simultaneous refresh attempts
  if (_isRefreshing && _refreshPromise) {
    return _refreshPromise;
  }

  _isRefreshing = true;
  _refreshPromise = (async () => {
    try {
      // Use relative URL since we're proxying through Next.js
      const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        credentials: "include",
      });

      if (response.ok) {
        const data = await response.json();
        _accessToken = data.access_token;
        // Notify auth context (if available globally)
        if (typeof window !== "undefined" && (window as any).__setAuthToken) {
          (window as any).__setAuthToken(data.access_token);
        }
        return true;
      }
      return false;
    } catch {
      return false;
    } finally {
      _isRefreshing = false;
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}

export class ApiError extends Error {
  readonly status: number;
  /**
   * The structured ``detail`` object FastAPI returned, when one is present.
   * Backend routes use this to ship machine-readable hints (e.g.
   * ``{kind:"gmail_rate_limited", retry_after_seconds:30, message:"…"}`` or
   * ``{kind:"needs_reauth", connection_id:1}``). Components branch on
   * ``detail?.kind`` to render a tailored UI.
   */
  readonly detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function looksLikeHtml(body: string): boolean {
  const t = body.trimStart();
  return t.startsWith("<") || body.includes("<!DOCTYPE") || body.includes("<html");
}

function detectLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === "en" || raw === "es" ? raw : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}

function t(key: TranslationKey, params?: Record<string, string | number>): string {
  const template = dictionaries[detectLocale()][key] ?? dictionaries[DEFAULT_LOCALE][key] ?? key;
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (m, p: string) => {
    const v = params[p];
    return v === undefined || v === null ? m : String(v);
  });
}

function fallbackMessage(status: number): { message: string; category: string } {
  if (status === 401) {
    return { message: "Unauthorized", category: "unauthorized" };
  }
  if (status >= 500) {
    return { message: t("api.error.server", { status }), category: "server_error" };
  }
  return { message: t("api.error.requestFailed", { status }), category: "request_failed" };
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
    // Backend convention: structured details always carry a human-friendly
    // ``message`` string. Pluck that out instead of dumping JSON at the user.
    const message = (detail as Record<string, unknown>).message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
    return null;
  }
  return null;
}

async function readErrorPayload(
  response: Response,
): Promise<{ message: string; detail: unknown }> {
  const raw = (await response.text()).trim();

  if (!raw || raw === "Internal Server Error" || looksLikeHtml(raw)) {
    const fallback = fallbackMessage(response.status);
    return {
      message: fallback.message,
      detail: { kind: "proxy_or_empty_error", status: response.status, category: fallback.category },
    };
  }

  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    const detail = parsed.detail;
    const fromDetail = detail !== undefined ? messageFromFastApiDetail(detail) : null;
    if (fromDetail) {
      return { message: fromDetail, detail };
    }
    if (detail !== undefined) {
      const fallback = fallbackMessage(response.status);
      return { message: fallback.message, detail };
    }
  } catch {
    // not JSON — fall through and use short text if reasonable
  }

  if (raw.length > 500) {
    const fallback = fallbackMessage(response.status);
    return {
      message: fallback.message,
      detail: { kind: "long_non_json_error", status: response.status, category: fallback.category },
    };
  }

  return { message: raw, detail: undefined };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  const t0 = typeof performance !== "undefined" ? performance.now() : 0;

  // Build headers with access token if available
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers || {}) as Record<string, string>,
  };
  
  if (_accessToken) {
    headers["Authorization"] = `Bearer ${_accessToken}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
      credentials: "include", // Include HTTP-only cookies (refresh token)
    });
  } catch (err) {
    recordTelemetryNetworkError({ path, method, error: err });
    throw err;
  }

  const durationMs =
    typeof performance !== "undefined" ? performance.now() - t0 : 0;

  if (response.status === 401) {
    // Try to refresh the token
    const refreshed = await refreshAccessToken();
    
    if (refreshed && _accessToken) {
      // Retry the request with new token
      const retryHeaders = {
        ...headers,
        "Authorization": `Bearer ${_accessToken}`,
      };
      response = await fetch(`${API_URL}${path}`, {
        ...init,
        headers: retryHeaders,
        credentials: "include",
      });
    } else {
      // Refresh failed - redirect to login
      if (typeof window !== "undefined") {
        // Clear token
        _accessToken = null;
        if ((window as any).__setAuthToken) {
          (window as any).__setAuthToken(null);
        }
        window.location.href = "/login";
      }
    }
  }

  if (!response.ok) {
    const { message, detail } = await readErrorPayload(response);
    recordTelemetryApiError({
      path,
      method,
      status: response.status,
      durationMs,
      message,
      detail
    });
    // 401s normally mean the *session* expired — log out and bounce to login.
    // But the backend also returns 401 with ``{kind:"needs_reauth"}`` when a
    // *connector* (e.g. Gmail) needs reauthorising; that should not log the
    // user out of the app, just let the caller render a "Reconnect" CTA.
    const isConnectorReauth =
      response.status === 401 &&
      detail !== undefined &&
      typeof detail === "object" &&
      detail !== null &&
      (detail as Record<string, unknown>).kind === "needs_reauth";

    if (response.status === 401 && !isConnectorReauth && typeof window !== "undefined") {
      _accessToken = null;
      if ((window as any).__setAuthToken) {
        (window as any).__setAuthToken(null);
      }
      window.location.href = "/login";
      throw new ApiError("Unauthorized", 401, detail);
    }
    throw new ApiError(message, response.status, detail);
  }

  if (response.status === 204) {
    return {} as T;
  }

  const rawBody = await response.text();

  if (durationMs >= SLOW_REQUEST_MS) {
    recordTelemetrySlowRequest({
      path,
      method,
      durationMs,
      status: response.status
    });
  }

  const trimmed = rawBody.trim();
  if (!trimmed) {
    recordTelemetryClientError({
      message: `Empty JSON body on ${method} ${path} (HTTP ${response.status})`,
      source: "apiFetch_empty_body",
    });
    throw new ApiError(t("api.error.emptyBody"), 502, { kind: "empty_body" });
  }
  try {
    return JSON.parse(trimmed) as T;
  } catch {
    recordTelemetryClientError({
      message: `Invalid JSON on ${method} ${path}: ${trimmed.slice(0, 240)}`,
      source: "apiFetch_json_parse",
    });
    throw new ApiError(t("api.error.badJson"), 502, { kind: "json_parse_error" });
  }
}
