"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

/**
 * Encapsulates the full Web Push lifecycle:
 *   1. Register `/sw.js` (idempotent; cheap on repeat calls).
 *   2. Fetch the VAPID public key from the backend.
 *   3. Ask the OS for notification permission.
 *   4. Subscribe via the PushManager and POST the subscription to the server.
 *
 * Exposes a single `enable()` action plus reactive state. Failures are caught
 * and surfaced via `error` so the UI can show a one-tap retry, never a crash.
 */

type PushPublicKeyResponse = { public_key: string | null; enabled: boolean };

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  const buf = new ArrayBuffer(raw.length);
  const out = new Uint8Array(buf);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

export type PushStatus = "idle" | "unsupported" | "denied" | "subscribed" | "error";

export function usePushNotifications() {
  const [status, setStatus] = useState<PushStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setStatus("unsupported");
      return;
    }
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("sw register failed", err);
    });
    if (Notification.permission === "denied") setStatus("denied");
  }, []);

  const enable = useCallback(async () => {
    setError(null);
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setStatus("unsupported");
      return;
    }
    try {
      const keyResp = await apiFetch<PushPublicKeyResponse>("/push/public-key");
      if (!keyResp.enabled || !keyResp.public_key) {
        setError("Las notificaciones push no están configuradas en el servidor.");
        setStatus("error");
        return;
      }
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setStatus("denied");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      let subscription = await reg.pushManager.getSubscription();
      if (!subscription) {
        subscription = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(keyResp.public_key)
        });
      }
      const json = subscription.toJSON();
      await apiFetch("/push/subscriptions", {
        method: "POST",
        body: JSON.stringify({
          endpoint: json.endpoint,
          keys: json.keys,
          user_agent: navigator.userAgent
        })
      });
      setStatus("subscribed");
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    }
  }, []);

  return { status, error, enable };
}
