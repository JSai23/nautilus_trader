"""Experiment runner — parses config, builds engine, runs strategy, reports results.

Per IMPL_PLAN Block 10a, this is the central integration point.
The LLM never touches this — agents write configs, the runner executes deterministically.
"""

from __future__ import annotations

import importlib
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.model.currencies import USDC_POS
from nautilus_trader.model.enums import AccountType, BookType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

from pmxt.generator import pmxt_data_generator
from runner.mlflow_logger import MLflowLogger
from runner.tearsheet import Tearsheet, compute_tearsheet
from universe.instruments import build_instrument_maps
from universe.resolver import UniverseResolver

log = logging.getLogger(__name__)

POLYMARKET_VENUE = Venue("POLYMARKET")


@dataclass
class ExperimentConfig:
    mode: str  # "backtest" or "paper"
    strategy_path: str  # e.g. "strategy.imbalance:ImbalanceStrategy"
    strategy_params: dict[str, Any] = field(default_factory=dict)
    universe_id: str = ""
    condition_ids: list[str] = field(default_factory=list)
    data_hours: list[str] = field(default_factory=list)
    fees: str = "zero"  # "polymarket", "zero", "custom"
    mlflow_experiment: str = ""
    mlflow_variant: str = ""
    mlflow_tags: dict[str, str] = field(default_factory=dict)
    starting_balance: float = 10_000.0
    paper_duration_seconds: int = 3600

    @classmethod
    def from_yaml(cls, path: Path) -> ExperimentConfig:
        with open(path) as f:
            raw = yaml.safe_load(f)

        strategy = raw.get("strategy", {})
        data = raw.get("data", {})
        mlflow = raw.get("mlflow", {})

        return cls(
            mode=raw["mode"],
            strategy_path=strategy.get("path", ""),
            strategy_params=strategy.get("params", {}),
            universe_id=raw.get("universe_id", ""),
            condition_ids=raw.get("condition_ids", []),
            data_hours=data.get("hours", []),
            fees=raw.get("fees", "zero"),
            mlflow_experiment=mlflow.get("experiment", ""),
            mlflow_variant=mlflow.get("parent_run", ""),
            mlflow_tags=mlflow.get("tags", {}),
            starting_balance=raw.get("starting_balance", 10_000.0),
            paper_duration_seconds=raw.get("paper", {}).get("duration_seconds", 3600),
        )


@dataclass
class RunResult:
    run_id: str
    config: ExperimentConfig
    tearsheet: Tearsheet
    orders_df: pd.DataFrame
    fills_df: pd.DataFrame
    positions_df: pd.DataFrame
    account_df: pd.DataFrame
    elapsed_seconds: float = 0.0
    success: bool = True
    error: str | None = None


def _import_strategy_class(strategy_path: str):
    """Import a strategy class from a dotted path like 'module.submod:ClassName'."""
    module_path, class_name = strategy_path.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def run_backtest(
    config: ExperimentConfig,
    market_infos: list[dict[str, Any]],
    metadata_cache_dir: Path | None = None,
    data_cache_dir: Path | None = None,
    results_dir: Path | None = None,
    mlflow_tracking_uri: str | None = None,
) -> RunResult:
    """Run a backtest experiment from config and market metadata.

    Parameters
    ----------
    config : ExperimentConfig
        Parsed experiment configuration.
    market_infos : list[dict]
        Market metadata dicts (from Gamma API / CLI cache).
    metadata_cache_dir : Path | None
        Directory for market metadata cache.
    data_cache_dir : Path | None
        Directory for PMXT data cache.
    results_dir : Path | None
        Directory to save results. Default: ./results/{run_id}/
    mlflow_tracking_uri : str | None
        MLflow tracking URI.
    """
    from nautilus_trader.analysis.reporter import ReportProvider

    run_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    if results_dir is None:
        results_dir = Path("results") / run_id
    results_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Build instruments
        instruments, instrument_ids, market_ids = build_instrument_maps(market_infos)
        log.info("Built %d instruments for %d markets", len(instruments), len(market_ids))

        # Build engine
        engine_config = BacktestEngineConfig(
            logging=False,  # Reduce noise
        )
        engine = BacktestEngine(config=engine_config)

        # Add venue
        engine.add_venue(
            venue=POLYMARKET_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money(config.starting_balance, USDC_POS)],
            book_type=BookType.L2_MBP,
        )

        # Add instruments
        for instrument in instruments.values():
            engine.add_instrument(instrument)

        # Build data generator
        gen = pmxt_data_generator(
            market_ids=market_ids,
            hours=config.data_hours,
            instruments=instruments,
            instrument_ids=instrument_ids,
            cache_dir=data_cache_dir,
        )

        engine.add_data_iterator("pmxt", gen)

        # Inject resolved instrument IDs into strategy params
        instrument_id_strs = [str(iid) for iid in instrument_ids.values()]
        config.strategy_params["instrument_ids"] = instrument_id_strs

        # Import strategy and its config class (convention: StrategyConfig in same module)
        strategy_cls = _import_strategy_class(config.strategy_path)
        config_module_path = config.strategy_path.rsplit(":", 1)[0]
        config_class_name = strategy_cls.__name__ + "Config"
        config_cls = getattr(importlib.import_module(config_module_path), config_class_name)

        strategy_config = config_cls(**config.strategy_params)
        strategy = strategy_cls(strategy_config)
        engine.add_strategy(strategy)

        # Run
        log.info("Starting backtest: %d hours of data", len(config.data_hours))
        engine.run()
        elapsed = time.time() - start_time
        log.info("Backtest completed in %.1fs", elapsed)

        # Generate reports
        orders = engine.cache.orders()
        positions = engine.cache.positions()

        orders_df = ReportProvider.generate_order_fills_report(orders)
        fills_df = ReportProvider.generate_fills_report(orders)
        positions_df = ReportProvider.generate_positions_report(positions)
        account_df = pd.DataFrame()  # Account report needs Account object

        # Compute tearsheet
        tearsheet = compute_tearsheet(positions_df, fills_df, account_df)

        result = RunResult(
            run_id=run_id,
            config=config,
            tearsheet=tearsheet,
            orders_df=orders_df,
            fills_df=fills_df,
            positions_df=positions_df,
            account_df=account_df,
            elapsed_seconds=elapsed,
        )

        # Save artifacts
        _save_artifacts(result, results_dir)

        # Log to MLflow
        if config.mlflow_experiment:
            _log_to_mlflow(result, results_dir, mlflow_tracking_uri)

        engine.dispose()
        return result

    except Exception as e:
        elapsed = time.time() - start_time
        log.exception("Backtest failed: %s", e)

        result = RunResult(
            run_id=run_id,
            config=config,
            tearsheet=Tearsheet(),
            orders_df=pd.DataFrame(),
            fills_df=pd.DataFrame(),
            positions_df=pd.DataFrame(),
            account_df=pd.DataFrame(),
            elapsed_seconds=elapsed,
            success=False,
            error=str(e),
        )

        # Save error info
        error_path = results_dir / "error.json"
        with open(error_path, "w") as f:
            json.dump({"error": str(e), "run_id": run_id}, f, indent=2)

        return result


def _save_artifacts(result: RunResult, results_dir: Path) -> None:
    """Save backtest artifacts to disk."""
    # Tearsheet
    with open(results_dir / "tearsheet.json", "w") as f:
        json.dump(result.tearsheet.to_dict(), f, indent=2)

    # CSVs
    if not result.orders_df.empty:
        result.orders_df.to_csv(results_dir / "orders.csv")
    if not result.fills_df.empty:
        result.fills_df.to_csv(results_dir / "fills.csv")
    if not result.positions_df.empty:
        result.positions_df.to_csv(results_dir / "positions.csv")
    if not result.account_df.empty:
        result.account_df.to_csv(results_dir / "account.csv")

    # Metadata
    metadata = {
        "run_id": result.run_id,
        "mode": result.config.mode,
        "strategy_path": result.config.strategy_path,
        "strategy_params": result.config.strategy_params,
        "data_hours": result.config.data_hours,
        "elapsed_seconds": result.elapsed_seconds,
        "success": result.success,
    }
    with open(results_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    log.info("Saved artifacts to %s", results_dir)


def _log_to_mlflow(
    result: RunResult,
    results_dir: Path,
    tracking_uri: str | None,
) -> None:
    """Log results to MLflow."""
    try:
        logger = MLflowLogger(tracking_uri)
        if not logger.enabled:
            return

        tags = dict(result.config.mlflow_tags)
        tags["mode"] = result.config.mode
        tags["universe_id"] = result.config.universe_id
        tags["strategy_file"] = result.config.strategy_path
        if result.config.data_hours:
            tags["date_range"] = f"{result.config.data_hours[0]}..{result.config.data_hours[-1]}"

        logger.log_child_run(
            experiment_name=result.config.mlflow_experiment,
            variant_name=result.config.mlflow_variant or "default",
            metrics=result.tearsheet.to_dict(),
            params=result.config.strategy_params,
            tags=tags,
            artifacts_dir=results_dir,
        )
    except Exception:
        log.exception("MLflow logging failed — results saved locally")
