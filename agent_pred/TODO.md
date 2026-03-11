# TODO — Plan v3.2 (All Corrections + All Polish Applied)

## Corrections (from agents/CORRECTIONS.md)
- [x] C1: Explain instrument-data connection via instrument_id in Section 4.1
- [x] C2: Add `add_data_iterator()` for streaming/lazy loading of PMXT data
- [x] C3: Flatten to v0/v1 only — remove all v2/v3 sections
- [x] C4: Clarify two data paths (record-replay vs PMXT), focus only on PMXT
- [x] C5: Explain event_slug_builder clearly, address live/paper/backtest asymmetry
- [x] C6: State Python library freedom explicitly
- [x] C7: Add v0 position handling mechanisms (price threshold, time-based, no-quotes)
- [x] C8: Explain instruments without data are inert in backtest
- [x] C9: Automate metrics/tearsheet/MLflow in runner, not analyst agent
- [x] C10: Fix agent role inconsistency — use Strategist + Analyst everywhere

## Reviewer Fixes (from FEEDBACK.md / DONEXT.md)
- [x] Remove Section 5.4 (StreamingConfig subsection — violated C3c/C4)
- [x] Fix reduce_only=True in Section 4.5(a) code example
- [x] Rename imbalance_v2.py → imbalance_iter2.py in sequence diagram

## Final Polish (iteration 3)
- [x] Add missing `InstrumentId` import in Section 4.2 paper trading example (line 603)
- [x] Rename `imbalance_v1.py` / `spread_v1.py` → `imbalance_iter1.py` / `spread_iter1.py` in state contract (line 1540-1541)

## Remaining Work
- [ ] Human review of v3.2 plan
- [ ] Begin execution plan (if system plan is approved)
