# notes/

Local-only working notes — **gitignored by default** (see `.gitignore`).

This is the cross-session scratchpad for whoever is hacking on this repo
(typically: David + Claude Code). Use it for:

- Per-workshop status / progress trackers (`autocon5-status.md` is here today)
- Design sketches you're not ready to commit
- Reproduction steps for tricky bugs
- One-off TODO lists for a working session
- Anything that helps the next session pick up where this one left off

## What's tracked vs ignored

The `.gitignore` rule keeps `notes/` out of the repo, except for two files
that *are* tracked so the convention persists across clones:

- `notes/README.md` — this file
- `notes/.gitkeep` — placeholder so the empty folder exists after `git clone`

Anything else you put here stays on your machine.

## Why this lives in the repo at all

Two reasons:

1. **Persistence across Claude Code sessions.** Claude Code reads files from
   the repo. Having the notes here means a fresh session can pick up the
   thread by reading `notes/`. The MEMORY system in `~/.claude/` is for
   user-level facts that persist across *all* projects; `notes/` is for
   *this project's* in-flight state.

2. **One source of truth per workshop.** Per-workshop status notes live next
   to the workshop they describe (named `<workshop>-status.md`), so it's
   obvious which notes belong to which workshop without folder-hopping.

## Naming convention

- `<workshop>-status.md` — long-running status / open-item tracker for that
  workshop (e.g. `autocon5-status.md`).
- `session-YYYY-MM-DD.md` — optional per-session notes when you want to
  capture context for "what we did today / what's next."
- `decisions.md` — running log of architectural choices and the reasoning,
  in case it'd be useful to revisit later.

None of those are required — invent whatever helps. They just shouldn't
end up on GitHub.
