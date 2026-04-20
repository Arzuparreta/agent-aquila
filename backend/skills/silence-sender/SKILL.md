---
name: silence-sender
description: Mute or spam a Gmail sender using filters and thread labels.
---

# Silence a Gmail sender

Stop a sender from cluttering the inbox. The user can ask "silence
X", "mute this sender", or "send X to spam". Prefer
``gmail_silence_sender`` when you have the sender email (and optional
``thread_id`` / ``message_id`` for spam on the open thread).

## Mute (default — non-destructive)

Mute hides future threads from this sender from the inbox without
deleting anything. Use when the user says "silenciar" / "mute" /
"ignore for now".

1. Call ``gmail_silence_sender`` with ``email`` = sender address and
   ``mode="mute"`` (default), **or** ``gmail_create_filter`` with
   ``criteria.from`` and ``action.removeLabelIds`` = ``["INBOX","UNREAD"]``.
2. Confirm in chat which sender was silenced and how to undo it
   (Settings → Filters in Gmail).

## Spam (moves current mail to Spam; future mail skips inbox)

Use when the user says "spam", "block", or "report as spam".

Gmail **rejects** ``SPAM`` in filter ``addLabelIds`` (HTTP 400). You
cannot auto-route *future* incoming mail into the Spam folder via the
filters API.

1. Call ``gmail_silence_sender`` with ``email``, ``mode="spam"``, and
   ``thread_id`` or ``message_id`` for the mail in context so it moves
   to Spam immediately, **or** call ``gmail_modify_thread`` /
   ``gmail_modify_message`` with ``add_label_ids=["SPAM"]`` and
   ``remove_label_ids=["INBOX"]`` then ``gmail_silence_sender`` for the
   filter.
2. The tool creates a filter with only ``removeLabelIds`` (skip inbox,
   mark read) for future mail — same shape as mute.
3. Confirm to the user; actions auto-apply (no proposal).

## Remember

- Always read back which sender you targeted before applying — easy to
  silence the wrong address when the request is ambiguous.
- If the user asks to silence "everyone like this", consider a
  ``criteria.query`` filter (e.g. ``"unsubscribe newsletter"``)
  instead of a single ``from``. Confirm before creating.
