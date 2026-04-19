---
name: gmail-triage
description: Walk through unread Gmail in priority order and decide what to do with each message.
---

# Gmail triage

Walk through unread Gmail in priority order and decide what to do with
each message. Use this when the user says "triage my inbox", "what
needs my attention?", or runs as part of the daily heartbeat.

## Inputs

- The user's primary Gmail connection (use ``gmail_list_messages`` with
  ``q="is:unread"`` and a small ``max_results`` like 25).
- Any "ignore" or "promote" rules already saved in agent memory under
  the ``triage_rules`` tag (recall with ``recall_memory``).

## Steps

1. List unread messages from the inbox: call ``gmail_list_messages``
   with ``q="is:unread in:inbox"``.
2. For each id, call ``gmail_get_message`` (format ``metadata`` is
   usually enough — pull the snippet + headers, body only when needed).
3. Classify the message in your head as:
   - ``urgent`` — blocking the user; surface it explicitly.
   - ``actionable`` — needs a reply or task within a day; summarise.
   - ``noise`` — newsletters, receipts, automated; recommend muting
     the sender (``gmail_modify_thread`` with the ``MUTED`` label or
     ``gmail_create_filter``).
4. After scanning, write a short summary back to the user with the
   urgent + actionable items first. Offer to draft replies (which
   creates an ``email_send`` / ``email_reply`` proposal that the user
   must approve before anything goes out).
5. For obvious noise senders, suggest a ``gmail_create_filter`` rule
   (``criteria.from`` → action ``addLabelIds=["TRASH"]`` or skip
   inbox). The user can accept or decline; filters are auto-applied
   so be conservative — confirm in chat before creating one.

## Things to remember

- Never mark messages read on the user's behalf without an explicit
  request — silent reads break the user's own triage habit.
- If you find a recurring pattern (same sender, same boilerplate),
  ``upsert_memory`` with key ``triage_rule:<sender>`` so future runs
  are faster.
