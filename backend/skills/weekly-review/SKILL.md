---
name: weekly-review
description: Structured weekly digest from Gmail + calendar + memory (heartbeat-friendly).
---

# Weekly review

A short, structured digest the agent can run on demand or from the
heartbeat (e.g. every Monday morning). Goal: surface what mattered
last week and what is on deck this week, in 5 bullets or fewer.

## Steps

1. Pull a **small** slice of recent Gmail with
   ``gmail_list_messages(q="newer_than:7d in:inbox", max_results=15)``.
   Group results by ``threadId`` and use ``gmail_get_thread`` with
   ``format="metadata"`` once per thread to skim subjects and snippets —
   avoid calling ``gmail_get_message`` per message. Fetch full bodies only
   when a subject line is ambiguous.
2. Pull next 7 days of calendar events with
   ``calendar_list_events(time_min=<now>, time_max=<now+7d>)``.
3. Recall any recent goals/preferences from agent memory:
   ``recall_memory(query="weekly review focus")``.
4. Synthesise:
   - "Last week" — at most 3 bullets, factual ("Closed 4 client
     emails", "2 calendar holds shifted").
   - "This week" — at most 3 bullets, forward-looking ("Tuesday: kick
     off X", "Friday: invoice Y").
   - "Watch" — 0–2 bullets where the agent noticed a risk
     (overdue reply, conflicting meetings).
5. Offer to draft anything (replies, calendar holds). Drafts always
   become proposals the user must approve before send.
6. ``upsert_memory`` with key ``weekly_review:last_run`` and content
   = today's ISO date so the next heartbeat doesn't repeat.

## Style

- Keep it short — the user reads this in 30 seconds, not 3 minutes.
- Use the user's working language (default Spanish, switch to English
  if the recent conversation is in English).
- Never invent metrics. If the data isn't there, say so and ask.
