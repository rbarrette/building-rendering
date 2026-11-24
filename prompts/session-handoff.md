# End-of-session handoff

Tool-neutral prompt (Claude Code, Antigravity, others). Claude Code: `/handoff [short topic]`.
Run at the end of a session or before a long pause, so the next tool picks up from `.agents/` and not from chat history.
This is the procedure in `AGENTS.md` ("At the end of every session"), made concrete.

## 1. Gather what happened (from the repo, not memory)
- `git status --short` and `git diff --stat` (ignore `renders/` and `blend/` churn unless that was the work).
  Also check `git log` since the last `.agents/history/` entry: something may already be committed.
- Read the current `.agents/HANDOFF.md` and the newest `.agents/history/` file, so you know what was already recorded.
  Another tool may have worked in between: don't drop its open items.
- Run `make validate` and note the counts (errors, warnings by kind). Don't fix things now; just record them.

## 2. Write the history file (append-only)
Create `.agents/history/YYYY-MM-DD-<tool>-<short-topic>.md` (today's date, e.g. `claude-code`, `antigravity`; topic in
kebab-case, from the argument if given). If that name exists, add `-2`. Never edit or delete existing history files.
Under 40 lines, these sections:
- **Goal:** what the session set out to do (the owner's ask).
- **Done:** what changed, with the files touched (group them: data, layouts, scripts, prompts, assets, renders).
- **Decisions:** choices made and why, including the owner's answers that settled them (quote short phrases).
- **Open / next:** unfinished work, what wasn't verified, known issues, questions waiting on the owner.

## 3. Rewrite `.agents/HANDOFF.md` (under 30 lines)
- Header: `Last updated: YYYY-MM-DD (<tool>). Detail: <path of the history file you just wrote>.`
- **Current state:** what is true now (counts of items/rules/layouts, validate result, what's new), not a changelog.
- **Next 3 steps:** the most useful next actions, owner decisions first. Carry over still-open items from the old file.
- **Blockers:** or "None". Keep the Blender path line.
If HANDOFF disagreed with the code or data, trust the repo and fix it.

## 4. Update stable docs only if stable facts changed
- `CONTEXT.md`: conventions, measurements, layout of the repo, pipeline/Make targets, Known facts table. Bump its
  `Last updated` line. Don't put session news there.
- `AGENTS.md` "Reusable prompts" and `README.md`: only if a prompt or command was added or renamed.
- New field measurements must already be in `measurements/raw/` (verbatim); if they're only in chat, add them now.

## 5. Report and stop
Say which files you wrote, the validate counts, and the next 3 steps in one short paragraph. Don't commit unless the
owner asks; if they do, commit the `.agents/` files with the work they describe.
