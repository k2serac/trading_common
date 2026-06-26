# Claude Code Commands

Version-tracked **Claude Code slash commands** for the trading stack — the operational counterpart to
`strategies/`. Tracking them here means they survive, evolve with the bots, and aren't lost if local
config is wiped.

| Command | What it does |
|---|---|
| [`/daily-check`](daily-check.md) | Cross-bot daily review — what we ordered today + anomalies, **diagnosed** (state↔IBKR desync, skip floods, stalled bots, mega-cap non-reactions, fill-vs-limit). Optional arg focuses one bot. |

## Install (symlink so the tracked file *is* the live command — no copy drift)

```bash
mkdir -p ~/.claude/commands
ln -sf /home/nicu/work/repos/trading_common/commands/daily-check.md ~/.claude/commands/daily-check.md
```

Then type `/daily-check` in any Claude Code session (start a fresh session for a brand-new command to
appear). Editing the file here updates the live command immediately.

**Note:** detection is automated via the command; **remediation is not** — the command is instructed
never to change live trading code/config/state without explicit approval. Keep it that way until the
bots are stable and boring.
