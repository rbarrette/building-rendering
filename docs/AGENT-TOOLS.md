# Using different AI tools on one project

This repo is meant to be worked on by more than one AI coding tool, sometimes on the same day. Nothing depends on a
tool's own chat history or memory: **the repo is the memory**. Any tool that can read files, edit files and run shell
commands can pick up where another left off.

## How it fits together
| File | Role |
|---|---|
| `AGENTS.md` | The rules every tool follows: what to read at the start of a session, what to write at the end, project rules, the list of reusable prompts. |
| `CONTEXT.md` | Stable facts: units, frame, conventions, what each data file holds, a table of known facts with their confidence. |
| `.agents/HANDOFF.md` | Where things stand right now: current state, next 3 steps, blockers. Rewritten at the end of every session. |
| `.agents/history/` | One short, append-only note per session (Goal / Done / Decisions / Open). Template: `.agents/history-template.md`. |
| `prompts/*.md` | Tool-neutral, step-by-step procedures (ingest an item, placement rule, layout change, 3D asset, item scan, handoff). |
| `CLAUDE.md`, `GEMINI.md` | One-line pointers (`@AGENTS.md`) for tools that look for their own file name. |
| `.claude/commands/*.md` | Claude Code shortcuts (`/handoff`, `/layout`, ...). Each one just says "follow `prompts/X.md`". |

## Getting a tool to load the rules
| Tool | What it reads on its own | What to do |
|---|---|---|
| Claude Code | `CLAUDE.md` (which imports `AGENTS.md`) | Nothing. Slash commands in `.claude/commands/`. |
| Codex (CLI / IDE) | `AGENTS.md` | Nothing. |
| Cursor | `AGENTS.md` (and `.cursor/rules/`) | Nothing. |
| Gemini CLI | `GEMINI.md` (imports `AGENTS.md`) | Nothing. |
| Antigravity | its workspace rules; `GEMINI.md` / `AGENTS.md` depending on version | If it doesn't follow the start-of-session steps, start with the line below. |
| Anything else | varies | Start with the line below. |

Tool features change often. If you're not sure a tool loaded the rules, start the session with:

> Read AGENTS.md and do its "At the start of every session" steps, then tell me where we are.

A good sign it worked: the tool summarises `HANDOFF.md`'s current state and next steps without being asked.

## Running the reusable prompts without slash commands
Only Claude Code gets the `/` shortcuts. In any other tool, name the prompt file and give it the same arguments:

| Claude Code | Any tool |
|---|---|
| `/handoff lighting` | "Follow `prompts/session-handoff.md`. Tool name: `codex`. Topic: lighting." |
| `/layout move the bench to the east wall` | "Follow `prompts/layout-change.md` for: move the bench to the east wall." |
| `/ingest-item DeWalt table saw` | "Follow `prompts/inventory-ingest.md` for: DeWalt table saw." |
| `/placement-rule ...`, `/build-asset <id>`, `/scan-item <id> <file>` | same pattern with `placement-rules.md`, `item-asset.md`, `item-scan.md` |

The prompts are written for any tool, so the result is the same. If your tool has its own saved-prompt or workflow
feature, you can add a wrapper there the same way the Claude Code commands do: a few lines that say "follow
`prompts/<name>.md` exactly", never a copy of the steps (copies drift).

## The handoff, in any tool
End every session (or stop before a long break) with the handoff prompt. It:
1. checks `git status`, the log and `make validate` (from the repo, not from memory),
2. writes `.agents/history/YYYY-MM-DD-<tool>-<topic>.md`,
3. rewrites `.agents/HANDOFF.md` (under 30 lines), keeping open items from other tools,
4. updates `CONTEXT.md` only if stable facts changed.

Use a short, consistent tool name in the file name so you can see who did what: `claude-code`, `codex`, `cursor`,
`gemini`, `antigravity`, `copilot`.

Then **commit** (data, layouts, scripts, `.agents/`). The next tool, or the same tool next week, starts from that commit.

## Switching tools, or running two at once
- **One at a time is simplest.** Finish with a handoff and a commit, then open the other tool.
- **Two at once:** give them different files (for example one on `data/inventory.json` + assets, the other on a
  layout), or separate git branches/worktrees. Only one of them should rewrite `HANDOFF.md`; the other writes its
  history note and lists its open items there. The next handoff merges them (the prompt says not to drop another tool's
  open items).
- **Picking up after another tool:** pull, then the start-of-session steps. If `HANDOFF.md` disagrees with the code or
  data, the code and data win: fix `HANDOFF.md`.
- **Never** edit or delete old `.agents/history/` files, and never put renders, scans or `.blend` files in `.agents/`
  (reference them by path).

## When something goes wrong
- A tool "forgot" a decision: it's probably only in a chat. Put it in the history note's **Decisions**, or in
  `CONTEXT.md` if it's a lasting fact, so every tool sees it.
- Two tools disagree about a number: `data/space.json` and the other data files are the source of truth;
  `measurements/raw/` holds the verbatim field notes behind them.
