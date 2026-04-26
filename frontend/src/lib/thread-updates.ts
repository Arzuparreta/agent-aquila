import { useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";
import type { ChatThread } from "@/types/api";

type ThreadUpdateEvent = {
  t: "thread.updated";
  thread_id: number;
  title: string;
};

type ThreadUpdateHandler = (threadId: number, title: string) => void;

const WS_URL =
  typeof window !== "undefined"
    ? (() => {
        const fromEnv = (process.env.NEXT_PUBLIC_WS_URL || "").trim().replace(
          /\/$/,
          ""
        );
        if (fromEnv) {
          return `${fromEnv}/api/v1/realtime/ws`;
        }
        const { protocol, host } = window.location;
        const wsProto = protocol === "https:" ? "wss:" : "ws:";
        return `${wsProto}//${host}/api/v1/realtime/ws`;
      })()
    : null;

let globalWs: WebSocket | null = null;
let handlers: Set<ThreadUpdateHandler> = new Set();
let wsRefCount = 0;

function ensureWs(): WebSocket | null {
  if (typeof window === "undefined" || !WS_URL) return null;

  const token = window.localStorage.getItem("token");
  if (!token) return null;

  if (globalWs && globalWs.readyState === WebSocket.OPEN) {
    return globalWs;
  }

  globalWs = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`);

  globalWs.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data) as ThreadUpdateEvent;
      if (data.t === "thread.updated" && data.thread_id && data.title) {
        handlers.forEach((handler) => handler(data.thread_id, data.title));
      }
    } catch {
      // ignore parse errors
    }
  };

  globalWs.onclose = () => {
    globalWs = null;
  };

  return globalWs;
}

export function useThreadUpdates(onThreadUpdated: (threadId: number, title: string) => void) {
  const handlerRef = useRef(onThreadUpdated);
  handlerRef.current = onThreadUpdated;

  useEffect(() => {
    handlers.add(handlerRef.current);
    wsRefCount++;

    const ws = ensureWs();
    if (!ws) {
      return () => {
        handlers.delete(handlerRef.current);
        wsRefCount--;
      };
    }

    return () => {
      handlers.delete(handlerRef.current);
      wsRefCount--;
      if (wsRefCount === 0 && globalWs) {
        globalWs.close();
        globalWs = null;
      }
    };
  }, []);
}

export async function fetchThread<T extends { id: number; title: string }>(
  threadId: number
): Promise<T | null> {
  try {
    return await apiFetch<T>(`/threads/${threadId}`);
  } catch {
    return null;
  }
}