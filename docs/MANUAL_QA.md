# Manual UI QA checklist

Use this when verifying **chat thread actions** and **inbox row menus** after
deploys or refactors. No automated suite covers these flows yet.

---

## Chat — thread list and top bar

Covers: rename, pin, archive, delete; kebab on sidebar rows and on the chat
top bar (`/`).

1. **Kebab without selecting the thread** — Hover a thread in the sidebar →
   kebab (⋯) appears → open the menu → press **Esc** or click outside → the
   menu closes **without** switching the active thread.
2. **Rename** — Open **Renombrar** → modal opens with the title selected →
   save → a green confirmation banner appears; the new title shows in the
   list and top bar.
3. **Pin / unpin** — **Fijar arriba** / **Quitar fijación** — pinned threads
   sort to the top; unpinning restores chronological order (within pinned
   rules).
4. **Archive from Activas** — With **Activas** selected, **Archivar** on the
   current thread → the row disappears → the banner may offer **Ver
   archivadas**.
5. **Unarchive** — Switch to **Archivadas** → **Desarchivar** on a thread →
   it reappears under **Activas**.
6. **Delete** — **Eliminar conversación** → confirm → thread is removed;
   focus moves to another thread (not a blank chat).
7. **Mobile / narrow viewport** — Open the thread drawer from the hamburger
   → the **kebab in the top bar** exposes the same actions (no hover
   required).
8. **Persistence** — Hard refresh the page — pinned / archived / renamed
   state matches what you left (after the server round-trip).
9. **Top-bar Inbox badge** — The unread counter in the top bar polls
   `/gmail/messages?detail=ids&max_results=1&q=is:unread in:inbox`. After
   marking a Gmail message read in the app or in Gmail itself, the badge
   updates after the next poll (or hard refresh).

---

## Inbox — single tab, live Gmail

Covers: search, pagination, mark read/unread, mute/spam, reply, start chat;
kebab on list rows and in the detail header (`/inbox`).

There are **no triage chips** any more — the inbox is a single chronological
list backed by `GET /gmail/messages?detail=metadata`. Email rows are not
mirrored locally.

1. **Initial load** — Open `/inbox`. The list shows recent Gmail messages
   ordered by `internalDate`; unread messages have a dot.
2. **Free-form search** — Type a Gmail query in the search bar (e.g.
   `is:unread`, `from:bob`, `has:attachment`, `subject:invoice`) and submit.
   The list refreshes with results from Gmail's own search.
3. **Pagination** — When more pages are available, **Siguiente** loads the
   next page using Gmail's `pageToken`; **Anterior** walks back through the
   stack you've visited.
4. **Open a message** — Click any row. The detail pane fetches the full
   message via `GET /gmail/messages/{id}?format=full` and renders the
   plain-text body extracted from the MIME parts.
5. **Mark read / unread** — In the detail pane or row kebab. The action
   calls `POST /gmail/messages/{id}/modify` (toggle `UNREAD` label) and
   updates Gmail itself; the row's unread dot updates immediately.
6. **Silenciar (mute)** — Per-row action or detail-pane button → modal opens
   with two options:
   - **Silenciar / Mute** → creates a Gmail filter for the sender that
     skips the inbox and marks future mail read; the current thread is also
     archived (`removeLabelIds=["INBOX","UNREAD"]`).
   - **Spam / Spam** → creates a Gmail filter that adds the `SPAM` label
     and removes `INBOX`; the current thread is moved to Gmail's Spam.
   Verify in Gmail web that the filter exists under **Settings → Filters
   and Blocked Addresses** and that the current thread has moved.
7. **Iniciar chat sobre este correo** — From the detail pane or row kebab.
   Creates a new chat thread titled with the email subject and navigates to
   `/?thread=<id>&gmail_msg=<msg_id>`. The agent does **not** auto-run; the
   first message you send is what kicks it off, and it can fetch the
   message live with `gmail_get_message`.
8. **Reconnect Gmail banner** — In **Settings → Connectors** the page shows
   a yellow banner if your Gmail connection is missing the new
   `gmail.settings.basic` scope. Clicking **Reconectar Gmail** restarts the
   Google OAuth flow and the banner disappears once the missing scope is
   granted.

---

## Settings — memory and skills

Covers: **Settings → Memoria del agente** and **Settings → Habilidades del
agente**.

1. **Memory list** — Open `/settings`. The Memory section lists every entry
   the agent has stored for you, newest first, with importance and tags.
   See [`MEMORY.md`](MEMORY.md) for what to expect.
2. **Delete a memory** — Click the trash icon on any row → the entry is
   removed via `DELETE /memory/{key}` and disappears from the list.
3. **Skills list** — The Skills section lists the markdown files in
   `backend/skills/` with their first H1 as the title. Three seed skills
   ship by default (`gmail-triage`, `silence-sender`, `weekly-review`).
4. **View a skill** — Click a skill → the full markdown body renders inline
   (the same content the agent loads when it calls `load_skill`).
5. **Add a skill** — Drop a new `.md` file in `backend/skills/`, refresh the
   page; the new skill should appear in the list and be loadable from the
   chat. See [`SKILLS.md`](SKILLS.md) for the file conventions.

---

## Approvals

Covers: the email send / reply approval gate. Other writes (label, archive,
trash, mute, spam, calendar, drive, Teams) auto-apply and do **not** show up
here.

1. From a chat, ask the agent to **send** or **reply** to an email. It
   should produce a proposal card in the chat (instead of sending).
2. Approve the card → the email is actually sent via Gmail or Outlook;
   reject → nothing leaves your machine.
3. Verify in Gmail/Outlook that the message appears in **Sent**.

---

## Related

- Automated backend tests: [`docs/testing.md`](testing.md)
- AI provider smoke tests: [`docs/PROVIDERS.md`](PROVIDERS.md)
- Agent persistent memory: [`docs/MEMORY.md`](MEMORY.md)
- Agent skills: [`docs/SKILLS.md`](SKILLS.md)
