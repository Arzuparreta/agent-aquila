# Manual UI QA checklist

Use this when verifying **chat thread actions** and **inbox row menus** after deploys or refactors. No automated suite covers these flows yet.

---

## Chat — thread list and top bar

Covers: rename, pin, archive, delete; kebab on sidebar rows and on the chat top bar (`/`).

1. **Kebab without selecting the thread** — Hover a thread in the sidebar → kebab (⋯) appears → open the menu → press **Esc** or click outside → the menu closes **without** switching the active thread.
2. **Rename** — Open **Renombrar** → modal opens with the title selected → save → a green confirmation banner appears; the new title shows in the list and top bar.
3. **Pin / unpin** — **Fijar arriba** / **Quitar fijación** — pinned threads sort to the top; unpinning restores chronological order (within pinned rules).
4. **Archive from Activas** — With **Activas** selected, **Archivar** on the current thread → the row disappears → the banner may offer **Ver archivadas**.
5. **Unarchive** — Switch to **Archivadas** → **Desarchivar** on a thread → it reappears under **Activas**.
6. **Delete** — **Eliminar conversación** → confirm → thread is removed; focus moves to another thread (not a blank chat).
7. **Mobile / narrow viewport** — Open the thread drawer from the hamburger → the **kebab in the top bar** exposes the same actions (no hover required).
8. **Persistence** — Hard refresh the page — pinned / archived / renamed state matches what you left (after the server round-trip).

---

## Inbox — row overflow menu and detail header

Covers: mark read/unread, promote, silence, start chat; kebab on list rows and in the detail header (`/inbox`).

1. **Kebab without opening the email** — Hover a row → kebab appears → open the menu → **Esc** or click outside → the menu closes **without** changing the selected email (if any).
2. **Mark read (unread row)** — On an unread row, **Marcar como leído** → the unread dot disappears → confirmation banner.
3. **Mark unread** — On a read row, **Marcar como no leído** → the dot returns; the **Inbox** badge in the chat top bar updates after its poll interval (or refresh).
4. **Promote** — From a row that is not already actionable (e.g. under **Info** or **Silenciados**), **Promover a accionable** → the row leaves the current filter; open **Accionables** and confirm the email is listed.
5. **Silence** — From **Accionables** (or another non-noise filter), **Silenciar remitente** → the row disappears from the current list → banner may offer **Ver silenciados**.
6. **Start chat** — **Iniciar chat sobre este correo** → navigates to the main chat with the entity-bound thread; the agent does **not** auto-run until you send a message.
7. **Mobile / detail** — On a narrow screen, open an email so the detail pane shows → use the **kebab in the detail header** (always visible; no hover on the row).

---

## Related

- Automated backend tests: [`docs/testing.md`](testing.md)
- AI provider smoke tests: [`docs/PROVIDERS.md`](PROVIDERS.md)
