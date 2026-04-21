"use client";

import { useEffect } from "react";

import {
  isTelemetryEnabled,
  recordTelemetryClientError,
} from "./record";

/**
 * Captures uncaught errors and unhandled promise rejections when telemetry is on.
 */
export function TelemetryGlobalHandlers() {
  useEffect(() => {
    const onError = (ev: ErrorEvent) => {
      if (!isTelemetryEnabled()) return;
      const msg = ev.message || "window error";
      const src = ev.filename ? `${ev.filename}:${ev.lineno}` : null;
      recordTelemetryClientError({ message: msg, source: src });
    };

    const onRejection = (ev: PromiseRejectionEvent) => {
      if (!isTelemetryEnabled()) return;
      const r = ev.reason;
      const msg =
        r instanceof Error
          ? r.message
          : typeof r === "string"
            ? r
            : "unhandled promise rejection";
      recordTelemetryClientError({ message: msg, source: "unhandledrejection" });
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return null;
}
