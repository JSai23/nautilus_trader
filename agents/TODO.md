# TODO — Plan v2

## Completed
- [x] Read agents/archive/PLAN_run1.md (previous plan, 27 verified claims)
- [x] Read agents/POLYMARKET_CLI_GUIDE.md
- [x] Research BacktestEngine API (agent)
- [x] Research Sandbox/paper trading (agent)
- [x] Research Polymarket adapter (agent)
- [x] Research data catalog conversion pipeline (agent)
- [x] Write full PLAN.md v2.0
- [x] Fix reduce_only=True in resolution exit (MF-1, iter 1)
- [x] Fix StrategyClass.config_class in runner (MF-2, iter 1)
- [x] Fix orderbook JSON example with real CLI output (MF-3, iter 1)
- [x] Add ParquetDataCatalog explanation (MF-4, iter 1)
- [x] Complete runner script with build_backtest_engine/build_paper_node (SF-1, iter 1)
- [x] Remove dangling BacktestDataConfig import (SF-2, iter 1)
- [x] Add FeeModel example with PolymarketFeeModel (SF-3, iter 1)
- [x] Fix slug builder format in Sections 4.4 and 5.3 (MF-1, iter 2)
- [x] Fix runner paper trading timeout — signal.alarm → threading.Timer (MF-2, iter 2)
- [x] Standardize ReportProvider usage across Sections 4.1, 5.1, 6.3 (SF-1, iter 2)
- [x] Bump version references to v2.2 (SF-2, iter 2)
- [x] Fix runner config instantiation — StrategyFactory replaces ConfigClass(**params) (MF-1, iter 3)
- [x] Mention ImportableStrategyConfig / StrategyFactory in Section 4.6 (SF-1, iter 3)
- [x] Remove dead import asyncio from Sections 4.2 and 5.2 (SF-2, iter 3)
- [x] Note POLYMARKET_VENUE constant — import from adapter instead of manual Venue() (SF-3, iter 3)
- [x] Bump version to v2.3 (iter 3)
- [x] Update runner flowchart — replace importlib.import_module with StrategyFactory.create() (SF-1, iter 4)
- [x] Add account.csv to runner's export_reports() (SF-2, iter 4)
- [x] Fix sandbox/execution.py line reference 130 → 119 (N-1, iter 4)
- [x] Bump version to v2.4 final (iter 5)

## All Done
No remaining items. Plan is final.
