"""Experiment runner — parses config, builds engine, runs strategy, reports results.

Agents write configs, the runner executes deterministically.
"""

from __future__ import annotations

import importlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.backtest.models import FixedFeeModel
from nautilus_trader.model.currencies import USDC_POS
from nautilus_trader.model.enums import AccountType, BookType, OmsType
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.objects import Money

from pmxt.generator import pmxt_data_generator
from pmxt.index import PMXTIndex
from runner.artifacts import generate_all_artifacts
from runner.mlflow_logger import MLflowLogger
from runner.tearsheet import Tearsheet, compute_tearsheet
from runner.utils import import_strategy_class
from universe.instruments import build_instrument_maps

log = logging.getLogger(__name__)

POLYMARKET_VENUE = Venue("POLYMARKET")


@dataclass
class UniverseConfig:
    """Filter criteria for Gamma API market discovery.

    Maps directly to MarketFilter fields. Server-side filters are pushed
    to the Gamma API; client-side filters (slug_contains, categories)
    are applied after fetching.
    """

    # Server-side filters
    active: bool | None = True
    closed: bool | None = False
    end_date_min: str | None = None  # ISO date, e.g. "2026-04-01"
    end_date_max: str | None = None
    start_date_min: str | None = None
    volume_min: float = 0.0
    order_by: str | None = None  # camelCase field name, e.g. "volumeNum"
    ascending: bool | None = None

    # Client-side filters
    slug_contains: str | None = None
    categories: list[str] = field(default_factory=list)

    # Pagination cap
    max_markets: int = 50


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
    discovery_poll_minutes: int = 5  # How often to poll for new markets (paper/live)
    universe: UniverseConfig = field(default_factory=UniverseConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> ExperimentConfig:
        with open(path) as f:
            raw = yaml.safe_load(f)

        strategy = raw.get("strategy", {})
        data = raw.get("data", {})
        mlflow = raw.get("mlflow", {})
        uni_raw = raw.get("universe", {})

        universe = UniverseConfig(
            active=uni_raw.get("active", True),
            closed=uni_raw.get("closed", False),
            end_date_min=uni_raw.get("end_date_min"),
            end_date_max=uni_raw.get("end_date_max"),
            start_date_min=uni_raw.get("start_date_min"),
            volume_min=uni_raw.get("volume_min", 0.0),
            order_by=uni_raw.get("order_by"),
            ascending=uni_raw.get("ascending"),
            slug_contains=uni_raw.get("slug_contains"),
            categories=uni_raw.get("categories", []),
            max_markets=uni_raw.get("max_markets", raw.get("max_markets", 50)),
        )

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
            discovery_poll_minutes=raw.get("discovery", {}).get("poll_minutes", 5),
            universe=universe,
        )


@dataclass
class RunResult:
    run_id: str
    config: ExperimentConfig
    tearsheet: Tearsheet
    orders_df: pd.DataFrame
    fills_df: pd.DataFrame
    positions_df: pd.DataFrame
    elapsed_seconds: float = 0.0
    success: bool = True
    error: str | None = None
    strategy: Any = None  # For test access to _fill_records, _log_buffer, etc.
    engine: Any = None  # For cross-validation via engine.cache.positions()



def run_backtest(
    config: ExperimentConfig,
    market_infos: list[dict[str, Any]],
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
        Market metadata dicts (from Gamma API or CLOB API).
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

    # Register run as "running"
    _write_status(results_dir, {
        "run_id": run_id,
        "status": "running",
        "strategy": config.strategy_path,
        "start_time": datetime.now(tz=timezone.utc).isoformat(),
        "markets": len(market_infos),
        "hours": len(config.data_hours),
    })

    try:
        # Filter markets by condition_ids when specified
        if config.condition_ids:
            market_infos = [m for m in market_infos if m.get("condition_id") in config.condition_ids]
            if not market_infos:
                raise ValueError(
                    f"No markets match condition_ids: {config.condition_ids[:3]}..."
                )

        # Build instruments
        instruments, instrument_ids, market_ids = build_instrument_maps(market_infos)
        log.info("Built %d instruments for %d markets", len(instruments), len(market_ids))

        # Build engine
        engine_config = BacktestEngineConfig(
            logging=False,  # Reduce noise
        )
        engine = BacktestEngine(config=engine_config)

        # Add venue with near-zero fixed fee (Polymarket fees are 0-2%, handled separately)
        fee_model = FixedFeeModel(commission=Money(0.001, USDC_POS))
        engine.add_venue(
            venue=POLYMARKET_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            starting_balances=[Money(config.starting_balance, USDC_POS)],
            book_type=BookType.L2_MBP,
            fee_model=fee_model,
        )

        # Add instruments
        for instrument in instruments.values():
            engine.add_instrument(instrument)

        # Build data index for cache lookups
        index = None
        if data_cache_dir:
            index = PMXTIndex(data_cache_dir / "index.json")

        # Build data generator
        gen = pmxt_data_generator(
            market_ids=market_ids,
            hours=config.data_hours,
            instruments=instruments,
            instrument_ids=instrument_ids,
            cache_dir=data_cache_dir,
            index=index,
        )

        engine.add_data_iterator("pmxt", gen)

        # Inject resolved instrument IDs into strategy params
        instrument_id_strs = [str(iid) for iid in instrument_ids.values()]
        config.strategy_params["instrument_ids"] = instrument_id_strs

        # Compute data time range for engine clock initialization.
        # Note: add_data_iterator() doesn't populate self._data, so we must
        # provide explicit start/end. Without them the engine defaults
        # start_ns=0 (epoch), causing set_timer() to spin millions of ticks.
        sorted_hours = sorted(config.data_hours)
        first_hour = sorted_hours[0]
        last_hour = sorted_hours[-1]
        start_dt = datetime.strptime(first_hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        end_dt = (
            datetime.strptime(last_hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
            + timedelta(hours=1)
        )

        # Tell strategies the data window so timers are bounded correctly.
        # start_time_ns prevents set_timer() from firing before data arrives
        # (defense against add_data_iterator epoch bug).
        # end_time_ns triggers position exit before book goes stale.
        config.strategy_params["start_time_ns"] = int(start_dt.timestamp() * 1_000_000_000)
        config.strategy_params["end_time_ns"] = int(end_dt.timestamp() * 1_000_000_000)

        # Import strategy and its config class (convention: StrategyConfig in same module)
        strategy_cls = import_strategy_class(config.strategy_path)
        config_module_path = config.strategy_path.rsplit(":", 1)[0]
        config_class_name = strategy_cls.__name__ + "Config"
        config_cls = getattr(importlib.import_module(config_module_path), config_class_name)

        strategy_config = config_cls(**config.strategy_params)
        strategy = strategy_cls(strategy_config)
        engine.add_strategy(strategy)

        # Inject heartbeat directory for periodic status updates (Block 5)
        strategy._heartbeat_dir = results_dir
        strategy._heartbeat_run_id = run_id

        # Run with explicit time range to initialize clocks correctly
        log.info("Starting backtest: %d hours of data", len(config.data_hours))
        engine.run(start=start_dt, end=end_dt)
        elapsed = time.time() - start_time
        log.info("Backtest completed in %.1fs", elapsed)

        # Generate reports
        orders = engine.cache.orders()
        positions = engine.cache.positions()
        closed_positions = [p for p in positions if p.is_closed]

        orders_df = ReportProvider.generate_order_fills_report(orders)
        fills_df = ReportProvider.generate_fills_report(orders)
        positions_df = ReportProvider.generate_positions_report(positions)

        # Compute tearsheet from closed positions only — open positions
        # have no realized PnL and dilute win_rate/avg_trade_pnl.
        closed_df = (
            ReportProvider.generate_positions_report(closed_positions)
            if closed_positions
            else pd.DataFrame()
        )
        tearsheet = compute_tearsheet(closed_df, fills_df)

        result = RunResult(
            run_id=run_id,
            config=config,
            tearsheet=tearsheet,
            orders_df=orders_df,
            fills_df=fills_df,
            positions_df=positions_df,
            elapsed_seconds=elapsed,
            strategy=strategy,
            engine=engine,
        )

        # Save artifacts
        _save_artifacts(result, results_dir, market_infos=market_infos)

        # Save top-of-book data if recorded (Block 6)
        if hasattr(strategy, "get_top_of_book_df"):
            tob_df = strategy.get_top_of_book_df()
            if not tob_df.empty:
                tob_path = results_dir / "top_of_book.csv"
                tob_df.to_csv(tob_path, index=False)
                log.info("Saved %d top-of-book records to %s", len(tob_df), tob_path)

        # Log to MLflow
        if config.mlflow_experiment:
            _log_to_mlflow(result, results_dir, mlflow_tracking_uri)

        # Mark run as completed
        _write_status(results_dir, {
            "run_id": run_id,
            "status": "completed",
            "strategy": config.strategy_path,
            "start_time": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            "end_time": datetime.now(tz=timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "total_pnl": tearsheet.total_pnl,
            "num_trades": tearsheet.num_trades,
        })

        engine.dispose()
        return result

    except Exception as e:
        elapsed = time.time() - start_time
        log.exception("Backtest failed: %s", e)

        # Mark run as failed
        _write_status(results_dir, {
            "run_id": run_id,
            "status": "failed",
            "strategy": config.strategy_path,
            "start_time": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            "end_time": datetime.now(tz=timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "error": str(e),
        })

        result = RunResult(
            run_id=run_id,
            config=config,
            tearsheet=Tearsheet(),
            orders_df=pd.DataFrame(),
            fills_df=pd.DataFrame(),
            positions_df=pd.DataFrame(),
            elapsed_seconds=elapsed,
            success=False,
            error=str(e),
        )

        # Save error info
        error_path = results_dir / "error.json"
        with open(error_path, "w") as f:
            json.dump({"error": str(e), "run_id": run_id}, f, indent=2)

        return result


def _write_status(results_dir: Path, status: dict[str, Any]) -> None:
    """Write run status to a JSON file for observability."""
    with open(results_dir / "status.json", "w") as f:
        json.dump(status, f, indent=2)


def _save_artifacts(
    result: RunResult,
    results_dir: Path,
    market_infos: list[dict[str, Any]] | None = None,
) -> None:
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

    # Visualization artifacts (Block 5)
    generated = generate_all_artifacts(
        fills_df=result.fills_df,
        positions_df=result.positions_df,
        results_dir=results_dir,
        market_infos=market_infos,
    )
    if generated:
        log.info("Generated %d visualization artifacts", len(generated))

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
