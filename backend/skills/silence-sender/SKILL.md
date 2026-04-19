---
name: silence-sender
description: Mute or spam a Gmail sender using filters and thread labels.
---

# Silence a Gmail sender

Stop a sender from cluttering the inbox. The user can ask "silence
X", "mute this sender", or "send X to spam". Pick the right tool
based on the verb they used.

## Mute (default — non-destructive)

Mute hides future threads from this sender from the inbox without
deleting anything. Use when the user says "silenciar" / "mute" /
"ignore for now".

1. Call ``gmail_create_filter`` with:
   - ``criteria.from`` = the sender's email address.
   - ``action.removeLabelIds`` = ``["INBOX"]``.
   - Optionally also ``action.addLabelIds`` = ``["MUTED"]`` if the
     ``MUTED`` label exists (check via ``gmail_list_labels``).
2. Confirm in chat which sender was silenced and how to undo it
   (Settings → Filters in Gmail).

## Spam (destructive — sender goes to spam)

Use when the user says "spam", "block", or "report as spam".

1. For the *current* thread, call ``gmail_modify_thread`` with
   ``addLabelIds=["SPAM"]`` and ``removeLabelIds=["INBOX"]`` so the
   visible message moves immediately.
2. Create a filter so future messages skip the inbox and go straight
   to spam:
   ``gmail_create_filter`` with ``criteria.from`` = sender,
   ``action.addLabelIds`` = ``["SPAM"]``,
   ``action.removeLabelIds`` = ``["INBOX"]``.
3. Confirm to the user; both actions auto-apply (no proposal).

## Remember

- Always read back which sender you targeted before applying — easy to
  silence the wrong address when the request is ambiguous.
- If the user asks to silence "everyone like this", consider a
  ``criteria.query`` filter (e.g. ``"unsubscribe newsletter"``)
  instead of a single ``from``. Confirm before creating.
