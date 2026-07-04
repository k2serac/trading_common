---
description: Restore Claude's memory across the 6 workspace repos — load each repo's MEMORY.md index, then pull detail files on relevance
---

Restore your persistent memory for the **trading workspace** (`/home/nicu/work/repos`). Memory is stored
**per project** under `~/.claude/projects/<key>/memory/`, so it does NOT auto-load when you're working in a
different repo. This command pulls it back into context across all 6 repos at once.

If an argument is given (`$ARGUMENTS`), restore only the repo whose name it matches; otherwise restore all 6.

**Ignore `sp500_index_bot`** — that strategy is declared sub-optimal for trading and is intentionally out of scope.

## The 6 repos and their memory dirs

| Repo | Memory dir | What it is |
|---|---|---|
| us_news_stock_bot | `/home/nicu/.claude/projects/-home-nicu-work-repos-us-news-stock-bot/memory` | News-driven US stock bot: Benzinga news + Claude sentiment + IBKR execution |
| soxl_index_bot | `/home/nicu/.claude/projects/-home-nicu-work-repos-soxl-index-bot/memory` | SOXL semiconductor bot: 200d-MA core regime + intraday-momentum satellite |
| commodity_breakout_bot | `/home/nicu/.claude/projects/-home-nicu-work-repos-commodity-breakout-1/memory` *(legacy `-1` project key)* | Commodity futures breakout bot |
| fx_macro_bot | `/home/nicu/.claude/projects/-home-nicu-work-repos-fx-macro-bot/memory` | FX macro bot on OANDA: intraday event-drift + Claude take/skip gate |
| trading_common | `/home/nicu/.claude/projects/-home-nicu-work-repos-trading-common/memory` | Shared library imported by all bots (see below) |
| bot_launcher_gui | `/home/nicu/.claude/projects/-home-nicu-work-repos-bot-launcher-gui/memory` | GUI to launch/manage any bot (see below) |

Four of the repos are trading bots. The other two are shared infrastructure:

- **trading_common** — shared library of common utilities used by all the bots (e.g. IBKR
  connection/execution helpers, `ClaudeSentiment`, the `/daily-check` tooling). It's a dependency
  every bot imports, not a strategy of its own; commit it like any other bot repo.
- **bot_launcher_gui** — a GUI front-end for launching and managing any of the bots from one place,
  rather than starting each bot's process by hand.

## What to do

1. For each repo in scope, read its `MEMORY.md` index. If the dir or `MEMORY.md` is missing/empty, note
   "no memory yet" and move on — don't treat it as an error.
2. The index lines are your map. **Read the individual detail files only when relevant** to what we're about
   to work on, or when I ask — don't dump every file's full contents by default.
3. After loading, give a **concise per-repo summary**: one or two lines each, led by a bottom line:
   **"Restored memory for <N>/6 repos."** Flag any repo with no memory yet.
4. Treat every restored fact as *background context reflecting what was true when written* — if a memory names
   a file, flag, or threshold, **verify it still exists** before acting on it.
5. **Enforce the tracked-symlink invariant** on every in-scope repo (see below). This is the one mutating
   step this command is allowed to take — do it every run.

Aside from step 5, this is a **read/restore** operation — do not otherwise modify, consolidate, or delete
memory files unless I explicitly ask.

## Enforce the tracked-symlink invariant (avoid the untracked default)

**Why:** the `~/.claude/projects/<key>/memory/` dir is NOT version-controlled. Any memory written there as a
plain file is one bad `rm`/reinstall away from being lost, and never gets code-reviewed or shared. So the rule
is: **every memory file must be a symlink pointing to a git-tracked file in a repo.** The memory system writes
new memories as *plain files by default*, so each restore must sweep them back under tracking.

**Tracked home for each file:**
- **Canonical strategy docs** — `strategyN_*.md` (the numbered strategies 1–9) → `trading_common/strategies/`.
  These are the shared, catalogued source of truth (see `strategies/README.md`); when relocating one, prepend
  memory frontmatter (`name` / `description` / `metadata: {type: project}`) if it lacks it, since the repo doc
  becomes both the strategy spec *and* the recalled memory.
- **Everything else** (indexes, findings, principles, project docs, feedback) → **`<that-repo>/memory/`** in the
  repo's own working tree (e.g. `us_news_stock_bot/memory/`). Includes `MEMORY.md` itself.

**Procedure — for each in-scope repo's memory dir:**
1. Find plain (non-symlink) `*.md` files: `find <memdir> -maxdepth 1 -type f`. If none, the invariant already
   holds — nothing to do.
2. For each plain file, pick its tracked home from the rule above, then **relocate verbatim and symlink back**:
   `mkdir -p <home>` · `mv <memdir>/<f> <home>/<f>` · `ln -s <home>/<f> <memdir>/<f>`. Use `mv` (not rewrite) so
   frontmatter/content is byte-preserved — the only exception is adding missing frontmatter to a strategy doc.
3. Verify no broken links: `find <memdir> -maxdepth 1 -type l ! -exec test -e {} \; -print` (must be empty).
4. In each repo that gained files, `git add memory/` (and/or `strategies/`), commit, and push — same as any
   other change. Report which files were newly tracked.

**Note:** `commodity_breakout_bot`'s memory key is the legacy `-1` path, but its tracked home is the normal
`commodity_breakout_bot/memory/`. `trading_common` and `bot_launcher_gui` have no memory yet — skip unless one
appears.
