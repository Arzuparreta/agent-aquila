# Agent skills

A **skill** is a markdown file in [`backend/skills/`](../backend/skills/) that
describes a recipe the agent can follow: what it's for, what tools it needs,
and the step-by-step.

Skills are the OpenClaw-style answer to "how do I make the agent do X
consistently?" without baking X into the system prompt forever. The system
prompt mentions that skills exist; the agent decides on its own whether to
list and load one for the current request.

## Where they live

| Layer       | Location                                                              |
| ----------- | --------------------------------------------------------------------- |
| Files       | [`backend/skills/*.md`](../backend/skills/)                           |
| Service     | `backend/app/services/skills_service.py`                              |
| HTTP API    | `backend/app/routes/skills.py` — `GET /skills`, `GET /skills/{name}`  |
| Agent tools | `list_skills`, `load_skill`                                           |
| Settings UI | **Settings → Habilidades del agente** (`frontend/src/components/features/skills/skills-section.tsx`) |

The folder is configurable via the `skills_dir` setting in
`backend/app/core/config.py`. Default is `backend/skills/`.

## Seed skills shipped in the repo

| File                         | What it teaches the agent                                              |
| ---------------------------- | ---------------------------------------------------------------------- |
| `gmail-triage.md`            | Walk unread Gmail in priority order, summarise urgent vs noise.        |
| `silence-sender.md`          | Mute or move-to-spam a sender end-to-end (filter + apply to thread).   |
| `weekly-review.md`           | A short weekly digest combining Gmail + Calendar.                      |

## Authoring a new skill

A skill file is just markdown. There's no front-matter and no schema — the
filename (without `.md`) becomes the skill's name; the first H1 (or the file
name as a fallback) becomes the title; the rest is loaded verbatim into the
agent's context when it calls `load_skill`.

A useful skill answers four questions in plain prose:

1. **When to use it.** The agent only loads a skill when the user's request
   matches; phrase the opening so it's obvious.
2. **What it depends on.** Which tools (e.g. `gmail_list_messages`,
   `calendar_create_event`) and which connectors must be wired up.
3. **The steps.** A numbered list that names the tool calls explicitly. The
   agent will follow this verbatim, so be precise about arguments.
4. **The traps.** What the agent must *not* do (silent reads, marking as
   spam without confirmation, etc.).

Example template:

```markdown
# Skill name (one short H1)

One-paragraph intent: when the user says X / on heartbeat / etc, do Y.

## Inputs

- Connection: e.g. Gmail (`gmail_list_messages`).
- Memories: e.g. `triage_rules` tag (call `recall_memory`).

## Steps

1. Call `gmail_list_messages` with `q="..."`.
2. For each id, call `gmail_get_message` ...
3. ...

## Things to remember

- Never do X without confirmation.
- If the same pattern repeats, `upsert_memory` so future runs are faster.
```

Drop the file, restart the backend (or wait for the next request — the
service re-reads on every call), and it'll show up in **Settings →
Habilidades del agente** and via `list_skills`.

## How the agent picks a skill

The agent isn't routed to a skill — it *chooses*. The system prompt tells it
that skills exist and that `list_skills` returns the catalogue with one-line
descriptions; from there the model decides whether the current task warrants
loading one. When in doubt the model just answers without a skill, which is
the right behaviour for a one-off question.

## Rate-limit / heartbeat note

The background `agent_heartbeat` cron runs the agent with a tiny prompt every
N minutes (off by default — see `agent_heartbeat_enabled` in
`backend/app/core/config.py`). The heartbeat prompt is intentionally short
and *encourages* the agent to load `gmail-triage` or `weekly-review` when
appropriate, but does not force it. Per-user budget is controlled by
`agent_heartbeat_burst_per_hour`.
