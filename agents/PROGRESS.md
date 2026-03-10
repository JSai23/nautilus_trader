# PROGRESS — Polymarket Agentic Trading Framework Plan

## Current State

**Plan version:** v3.2
**Status:** All 10 corrections applied. All reviewer fixes applied. Final cosmetic polish complete. **Ready for human review.**

## What Changed (v3.1 → v3.2) — Final Polish

Two cosmetic fixes from reviewer's optional observations:

1. **Added missing `InstrumentId` import** in Section 4.2 paper trading example (line 603). The code example used `InstrumentId.from_str(...)` at line 640 but the import block didn't include it. Now imports `TraderId, InstrumentId` together.

2. **Renamed strategy filenames** in state contract directory listing (lines 1540-1541): `imbalance_v1.py` → `imbalance_iter1.py`, `spread_v1.py` → `spread_iter1.py`. Now consistent with the `_iter2` convention used in the sequence diagram at line 1809. Added clarifying comment: "Iteration suffix (_iter1, _iter2) — NOT scope tiers".

## Full Change Summary (v2.4 → v3.2)

### Structural
- Flattened from v0/v1/v2/v3 to **v0/v1 only** — two tiers, clean boundary
- Removed all "BLOCKED UNTIL (v2+)" sections
- Moved PMXT data pipeline from v2 to v1 (critical unblock)
- Moved MLflow integration from v2 to v1
- Moved Agentic Loop orchestration from v2 to v1
- Removed dedicated Record-and-Replay section (brief mention only)
- Removed Section 5.4 (StreamingConfig deep-dive)

### Agent Model
- Unified to **Strategist + Analyst** (2 agents) everywhere
- Removed Researcher/Writer/Analyzer (3 agents) model

### Runner Automation
- Runner script handles: backtest -> ReportProvider -> metrics -> tearsheet -> MLflow -> disk
- Analyst agent ONLY reads finished reports and interprets
- Added `compute_tearsheet()` and `log_to_mlflow()` functions
- Added MLflow infra prerequisite

### Technical Additions
- C1: Instrument-data connection via instrument_id
- C2: `add_data_iterator()` for streaming large datasets
- C5: event_slug_builder asymmetry (live/paper only)
- C6: Python library freedom
- C7: All v0 position handling mechanisms (with corrected code example)
- C8: Inert instruments in backtest

### Implementation Blocks (Section 7)
7 blocks, all v1:
1. PolymarketStrategy Base Class
2. Concrete Strategies
3. Universe Config & Slug Builders
4. PMXT Data Pipeline
5. Runner Script + Automated Tearsheet
6. Polymarket Fee Model
7. Agentic Loop Orchestration
