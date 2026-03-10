# Session Objective: Apply Corrections to PLAN.md v2.4

You are revising `agents/PLAN.md` based on human-reviewed corrections in `agents/CORRECTIONS.md`.

## Your Job

1. **Read `agents/CORRECTIONS.md` first.** There are 10 corrections. Each one is verified against source code and includes the exact fix required.
2. **Read the current `agents/PLAN.md`.** Understand its structure before modifying.
3. **Apply every correction.** Do not skip any. Do not half-apply. Each correction has a "Required fix" section — follow it precisely.
4. **Maintain the plan's quality.** The plan must still read as a coherent narrative top-to-bottom. Don't just patch — integrate corrections into the flow.

## Key Structural Changes (from corrections)

### Scope: v0 and v1 ONLY
Remove all v2 and v3 content. The plan has exactly two tiers:
- **v0**: What NautilusTrader provides today with zero changes
- **v1**: Everything we build (all Python-side)

Delete v2/v3 sections, tier table rows, and references. If something from v2/v3 is actually needed for the research playground, move it to v1. Otherwise cut it.

### Agent Model: Strategist + Analyst
The plan currently has two conflicting agent models. Use **Strategist + Analyst** (2 agents) everywhere. Update the Section 1 ASCII diagram. Remove references to "Researcher" and "Writer" as separate roles.

### Runner Automation
The runner script (deterministic, not LLM) handles:
- Running backtests/paper trades via NautilusTrader
- Computing metrics via ReportProvider
- Generating standardized tearsheet
- Logging to MLflow (hyperparams, metrics, artifacts)
- Writing structured results to disk

The Analyst agent only reads finished reports and proposes next experiments. It never computes metrics.

### PMXT as the Only Data Path
Remove StreamingConfig/record-replay as a focus area. Brief mention only ("NT supports this natively, but it's not our path"). The PMXT transformer is v1 — this is how we backtest.

### Add MLflow Infra Prerequisite
The infra repo (separate from this codebase) needs to host an MLflow tracking server. Note this as a prerequisite in implementation blocks.

## Rules (same as previous runs)

- **Explain every NautilusTrader feature for a newcomer.** No name-dropping. What it is, how it works, what the code looks like.
- **Use EXISTS/BUILD format** for every capability.
- **Cite file paths** for all NautilusTrader claims.
- **Use the `polymarket` CLI** (`/usr/local/bin/polymarket`) to verify Polymarket claims. Read `agents/POLYMARKET_CLI_GUIDE.md`.
- **NEVER GUESS.** Read the code. Run the CLI.

## Previous Research

The previous plan (`agents/PLAN.md`) already has 27 code-verified claims. The corrections file has additional verified findings. Build on this — don't redo verified research.

## Output

Revised `agents/PLAN.md`. Same structure (Problem & Scope → Design → Blocks) but with all 10 corrections applied, v2/v3 removed, agent model fixed, runner automation added.
