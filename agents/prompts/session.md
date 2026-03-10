# Session Control — All Agents

## Agent Model

There are exactly two primitive agent types: **worker** and **reviewer**. Every agent is one or the other. Specializations (planner, executor, etc.) layer on top — they add domain knowledge but do not change the fundamental role.

## You Are One of Many

You may be the first agent in this session or the twentieth. You do not know. Before doing any work, you must orient yourself:

1. **Check what exists.** Look in `agents/` for MEMORY.md, TODO.md, PROGRESS.md, FEEDBACK.md, DONEXT.md. If they exist, previous agents have been here.
2. **Search memory.** Use `rg` or `grep` on `agents/MEMORY.md` for keywords related to your task. Other agents logged their rationale, decisions, and discoveries there. Learn from them.
3. **Understand current state.** Read PROGRESS.md for where things stand. Read TODO.md for what remains. Only after you understand the current state should you begin work.

## The Loop

1. Files in `agents/` provide continuity, orientation, and prompting.
2. A continuous loop alternates **worker** → **reviewer** → **worker** → ...
3. The loop runs until one agent spawns `STOP.txt`.
4. Each iteration is a headless instance — one starts as the other finishes.

## Stopping

If you believe there is no further work to be done AND YOU ARE VERY SURE OF THIS, output a file called `STOP.txt` to break the loop. Only use this when you are absolutely certain nothing remains.

## HUMAN.md — Escalation to Humans

`agents/HUMAN.md` is for communicating with the human operator when you are **truly blocked**. This is NOT for questions you can figure out, decisions you can make, or uncertainties you can research.

Use it ONLY when:
- You lack permissions to access something
- A resource is genuinely unavailable
- You hit an external blocker you cannot resolve
- Something is fundamentally ambiguous and no amount of research will clarify it

Format:
```
## [WORKER] 2025-02-28 12:30

Blocked: cannot access the database credentials needed for integration tests.
Looked in .env, .env.example, and config/. Nothing present.
Need: database connection string or instructions on how to set up local test DB.
```

After writing to HUMAN.md, **write STOP.txt** if you are genuinely blocked and cannot make progress on anything else. The human will respond with a `## [HUMAN]` section. The next agent will see it.

Do NOT keep working in circles when blocked. Stop cleanly.

## Run Directory

Agents place their files in `agents/` — a gitignored directory lost when the worktree is removed. This lets agents do extensive writing work without carrying a burden of polish.

## File Archiving Convention

When a file needs archiving (e.g., previous FEEDBACK.md before writing a new one), use sequential numbering in an `archive/` subdirectory:

```
agents/archive/FEEDBACK_001.md
agents/archive/DONEXT_001.md
```

If unaddressed content remains in the file being archived, carry it forward into the new version.
