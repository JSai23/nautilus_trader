# Session Objective: Review Polymarket Trading Framework System Plan v2

You are reviewing a **system plan** at `agents/PLAN.md`. The previous iteration (`agents/archive/PLAN_run1.md`) was technically accurate but failed on clarity — the reader couldn't distinguish what NautilusTrader provides today vs what needs building, and NautilusTrader features weren't explained for a newcomer.

## Tools Available

You have the `polymarket` CLI at `/usr/local/bin/polymarket` and a reference guide at `agents/POLYMARKET_CLI_GUIDE.md`. Use these to verify claims about Polymarket. You also have the full NautilusTrader codebase to verify code claims.

## The #1 Review Criterion: Can a NautilusTrader Newcomer Understand This?

The reader of this plan has NEVER used NautilusTrader. Your primary job is to catch every instance where the plan assumes NT knowledge. Specifically:

### Test 1: Feature Explanation
For every NautilusTrader feature referenced (BacktestEngine, StreamingConfig, SimulatedExchange, Sandbox mode, InstrumentProvider, StrategyConfig, LiveNode, etc.):
- Is it explained in plain English? (What it is, how it works, what it looks like in code)
- Or is it just name-dropped? ("Use StreamingConfig" without explaining what it is)

**If a feature is name-dropped without explanation, flag it as a MUST FIX.** This was the primary failure of run 1.

### Test 2: Exists vs Build Separation
For every capability (backtesting, paper trading, live trading, universe management, market resolution, etc.):
- Is there a clear "EXISTS TODAY" section showing what works right now?
- Is there a clear "WE MUST BUILD" section showing what needs to be written?
- Is there a clear "BLOCKED UNTIL" section for things that can't work yet?
- Or are exists/build mixed together in the same paragraphs?

**If exists and build are mixed, flag it as a MUST FIX.**

### Test 3: Actionability
Can the reader answer these questions after reading the plan?
1. "What can I do RIGHT NOW with zero code changes?" — Is the answer clear and specific?
2. "What do I need to build to backtest with PMXT data?" — Is there a step-by-step?
3. "What do I need to build for paper trading?" — Is there a step-by-step?
4. "How do I define a universe?" — Is the mechanism explained?
5. "How do strategies handle expiring markets?" — Is the lifecycle clear?

**If any of these questions can't be answered from the plan, flag it as a MUST FIX.**

### Test 4: PMXT Data Pipeline Depth
The PMXT backtesting pipeline is the most important section. Review it for:
- Is the PMXT data schema described? (What columns, what types, what the data looks like)
- Is the mapping from PMXT fields to NautilusTrader types explicit?
- Is the full pipeline described step-by-step? (download → filter → transform → load → run)
- Is the 12 GB/day size problem addressed?
- Is the alternative path (record live data via StreamingConfig → replay) also described?
- Are both paths compared honestly?

**If the PMXT pipeline is hand-wavy or skips steps, flag it as a MUST FIX.**

### Test 5: Code Examples
The plan should include real Python code (not pseudocode) for:
- Setting up a backtest with loaded data
- Setting up paper trading
- A minimal strategy that subscribes to orderbook data
- The runner script that the agentic loop uses

**If these are missing or use pseudocode, flag it as a SHOULD FIX.**

## Secondary Review Criteria

These matter but are secondary to the clarity issues above:

### Factual Accuracy
- Spot-check at least 3 NautilusTrader claims by reading source code
- Spot-check at least 1 Polymarket claim using the CLI
- Run 1 verified 27 claims — don't re-verify those unless the plan contradicts them

### Structural Balance
- Are sections proportional to importance?
- The PMXT pipeline and backtesting sections should be the deepest
- The agentic loop section should be concrete but not dominate

### Honest Gaps
- Does the plan say "we don't know" where it genuinely doesn't know?
- Does it avoid speculation about PMXT data format (which we can't inspect from this host)?

## Output

Write `FEEDBACK.md` and `DONEXT.md` as usual. Prioritize MUST FIX issues. Be specific — quote the problematic text and say exactly what's wrong with it.
