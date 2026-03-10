# Session Objective: Review Corrections Applied to PLAN.md

You are reviewing `agents/PLAN.md` after a corrections pass. The corrections are in `agents/CORRECTIONS.md` (10 corrections). Your job is to verify every correction was applied correctly and completely.

## Tools Available

- `polymarket` CLI at `/usr/local/bin/polymarket` + guide at `agents/POLYMARKET_CLI_GUIDE.md`
- Full NautilusTrader codebase for verification
- `agents/CORRECTIONS.md` — the source of truth for what must change

## Review Checklist

### 1. Correction Completeness
Go through each of the 10 corrections in `agents/CORRECTIONS.md` and verify:
- Was it applied? (If not, flag as MUST FIX)
- Was it applied correctly? (Does the plan text match the correction's "Required fix"?)
- Was it integrated into the narrative flow? (Not just patched in awkwardly?)

### 2. Scope Cleanup
- Are ALL v2 and v3 references removed? Search for "v2", "v3", "tier 2", "tier 3" etc.
- Is the plan strictly v0 (exists) and v1 (we build)?
- Is the EXISTS/BUILD format used consistently?

### 3. Agent Model Consistency
- Does the Section 1 diagram show Strategist + Analyst?
- Are there any remaining references to "Researcher", "Writer", or "3 agents"?
- Is the runner script clearly positioned as deterministic (not an agent)?

### 4. Runner Automation
- Does the runner design include automated metrics, tearsheet, and MLflow logging?
- Is the Analyst agent's role limited to reading reports and proposing experiments?
- Is MLflow hosting listed as an infra prerequisite?

### 5. PMXT Focus
- Is StreamingConfig/record-replay reduced to a brief mention?
- Is the PMXT transformer clearly in v1?
- Does the PMXT pipeline use `add_data_iterator()` (not `add_data()`)?

### 6. Newcomer Clarity (carry forward from run 2)
- Are NautilusTrader features explained for newcomers?
- Spot-check 3 NT features: are they explained (what, how, code) or just name-dropped?

### 7. Factual Accuracy
- Spot-check at least 2 claims against source code
- Verify the event_slug_builder explanation matches what's in `providers.py`

## Output

Write `FEEDBACK.md` and `DONEXT.md`. For each correction, state: APPLIED / PARTIALLY APPLIED / NOT APPLIED. Be specific about what's missing.
