/**
 * IndexedDB persistence for local telemetry. English-only internal errors (console).
 */

import type { TelemetryEvent } from "./types";

const DB_NAME = "aquilat-telemetry-v1";
const STORE = "events";
const DB_VERSION = 1;
const MAX_EVENTS = 5000;

function wrapReq<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error ?? new Error("aborted"));
  });
}

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const st = db.createObjectStore(STORE, { keyPath: "id" });
        st.createIndex("ts", "ts", { unique: false });
        st.createIndex("groupKey", "groupKey", { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

async function pruneIfNeeded(db: IDBDatabase): Promise<void> {
  const tx = db.transaction(STORE, "readonly");
  const st = tx.objectStore(STORE);
  const all = (await wrapReq(st.getAll())) as TelemetryEvent[];
  await txDone(tx);
  if (all.length <= MAX_EVENTS) return;
  const sorted = [...all].sort(
    (a, b) => new Date(a.ts).getTime() - new Date(b.ts).getTime(),
  );
  const victims = sorted.slice(0, all.length - MAX_EVENTS + 100);
  const tx2 = db.transaction(STORE, "readwrite");
  const st2 = tx2.objectStore(STORE);
  for (const v of victims) {
    st2.delete(v.id);
  }
  await txDone(tx2);
}

export async function putTelemetryEvent(event: TelemetryEvent): Promise<void> {
  try {
    const db = await openDb();
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(event);
    await txDone(tx);
    await pruneIfNeeded(db);
  } catch (e) {
    console.warn("[telemetry] put failed", e);
  }
}

export async function getAllTelemetryEvents(): Promise<TelemetryEvent[]> {
  try {
    const db = await openDb();
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAll();
    const rows = (await wrapReq(req)) as TelemetryEvent[];
    await txDone(tx);
    return rows.sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
  } catch (e) {
    console.warn("[telemetry] getAll failed", e);
    return [];
  }
}

export async function clearAllTelemetryEvents(): Promise<void> {
  try {
    const db = await openDb();
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).clear();
    await txDone(tx);
  } catch (e) {
    console.warn("[telemetry] clear failed", e);
  }
}
