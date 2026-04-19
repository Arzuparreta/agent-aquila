# Agent skills

A **skill** is a workflow recipe the agent can load on demand via `list_skills` /
`load_skill`. Layout follows **AgentSkills** / OpenClaw conventions: each skill is a
**directory** named after the skill slug, containing a single `SKILL.md` file.

## Where they live

| Layer       | Location                                                                 |
| ----------- | ------------------------------------------------------------------------ |
| Files       | [`backend/skills/<slug>/SKILL.md`](../backend/skills/)                   |
| Service     | `backend/app/services/skills_service.py`                                 |
| HTTP API    | `GET /skills`, `GET /skills/{name}`                                      |
| Agent tools | `list_skills`, `load_skill`                                              |
| Settings UI | **Settings → Habilidades del agente**                                  |

Override the root with `AQUILA_SKILLS_DIR` (see `backend/app/core/config.py`).

## SKILL.md format

Optional **YAML frontmatter** (single-line keys, OpenClaw-compatible subset):

```markdown
---
name: my-skill
description: One-line summary for the skill list.
---

# Title

Body markdown…
```

- **Slug** = directory name (e.g. `gmail-triage`).
- **Title** = frontmatter `name` or first `# Heading`.
- **Summary** = frontmatter `description` or first paragraph after the heading.
- **Body** = markdown after frontmatter (what `load_skill` returns).

Legacy flat `backend/skills/*.md` files are still discovered if present; new skills
should use folders.

## Seed skills

| Slug             | Purpose                                              |
| ---------------- | ---------------------------------------------------- |
| `gmail-triage`   | Unread triage, urgent vs noise.                      |
| `silence-sender` | Mute / spam a sender (filters + thread labels).      |
| `weekly-review`  | Weekly digest (Gmail + Calendar + memory).           |

## Authoring

1. Create `backend/skills/<slug>/SKILL.md` with frontmatter + markdown.
2. Answer: when to use it, which tools/connectors, numbered steps naming tools
   explicitly, and traps (no silent reads, etc.).
3. Restart not required — the service reads from disk on each call.

## How the agent picks a skill

The system prompt mentions skills. The model calls `list_skills`, then `load_skill`
with the slug when a workflow matches.
