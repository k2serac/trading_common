---
description: Restore Claude's memory across the 6 workspace repos — load each repo's MEMORY.md index, then pull detail files on relevance
---

Restore your persistent memory for the **trading workspace** (`/home/nicu/work/repos`). Memory is stored
**per project** under `~/.claude/projects/<key>/memory/`, so it does NOT auto-load when you're working in a
different repo. This command pulls it back into context across all 6 repos at once.

If an argument is given (`$ARGUMENTS`), restore only the repo whose name it matches; otherwise restore all 6.

**Ignore `sp500_index_bot`** — that strategy is declared sub-optimal for trading and is intentionally out of scope.

## The 6 repos and their memory dirs

| Repo | Memory dir |
|---|---|
| us_news_stock_bot | `/home/nicu/.claude/projects/-home-nicu-work-repos-us-news-stock-bot/memory` |
| soxl_index_bot | `/home/nicu/.claude/projects/-home-nicu-work-repos-soxl-index-bot/memory` |
| commodity_breakout_bot | `/home/nicu/.claude/projects/-home-nicu-work-repos-commodity-breakout-1/memory` *(legacy `-1` project key)* |
| fx_macro_bot | `/home/nicu/.claude/projects/-home-nicu-work-repos-fx-macro-bot/memory` |
| trading_common | `/home/nicu/.claude/projects/-home-nicu-work-repos-trading-common/memory` |
| bot_launcher_gui | `/home/nicu/.claude/projects/-home-nicu-work-repos-bot-launcher-gui/memory` |

## What to do

1. For each repo in scope, read its `MEMORY.md` index. If the dir or `MEMORY.md` is missing/empty, note
   "no memory yet" and move on — don't treat it as an error.
2. The index lines are your map. **Read the individual detail files only when relevant** to what we're about
   to work on, or when I ask — don't dump every file's full contents by default.
3. After loading, give a **concise per-repo summary**: one or two lines each, led by a bottom line:
   **"Restored memory for <N>/6 repos."** Flag any repo with no memory yet.
4. Treat every restored fact as *background context reflecting what was true when written* — if a memory names
   a file, flag, or threshold, **verify it still exists** before acting on it.

This is a **read/restore** operation only — do not modify, consolidate, or delete any memory files unless I
explicitly ask.
