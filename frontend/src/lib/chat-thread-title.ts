/**
 * Default thread titles (must stay in sync with backend
 * ``chat_thread_title_service._THREAD_TITLE_PLACEHOLDERS_FOLDED``).
 */
const DEFAULT_THREAD_TITLES_FOLDED = new Set(
  ["new chat", "nuevo chat", "general"]
);

export function isDefaultChatThreadTitle(title: string | null | undefined): boolean {
  const t = (title ?? "").trim();
  if (!t) return true;
  return DEFAULT_THREAD_TITLES_FOLDED.has(t.toLowerCase());
}

const POLL_MS = 450;
const POLL_MAX_ATTEMPTS = 14;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/**
 * After an async agent run, the server marks the run terminal before the title LLM
 * finishes. Poll until the title is no longer a placeholder or attempts exhaust.
 */
export async function pollThreadUntilTitleReady<T extends { title: string }>(
  threadId: number,
  fetchThread: (id: number) => Promise<T>
): Promise<T | null> {
  let last: T | null = null;
  for (let i = 0; i < POLL_MAX_ATTEMPTS; i++) {
    try {
      last = await fetchThread(threadId);
      if (!isDefaultChatThreadTitle(last.title)) {
        return last;
      }
    } catch {
      return last;
    }
    if (i < POLL_MAX_ATTEMPTS - 1) {
      await sleep(POLL_MS);
    }
  }
  return last;
}
