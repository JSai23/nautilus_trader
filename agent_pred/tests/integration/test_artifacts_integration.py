"""Tier 2 integration tests: artifact generation.

Covers TEST_PLAN.md Section 4.5:
- generate_all_artifacts creates PNGs
- generate_all_artifacts with empty data
- _save_artifacts creates CSVs + JSON
- tearsheet.json matches metrics
- metadata.json has required fields
"""

import json

import pandas as pd
import pytest

from runner.artifacts import generate_all_artifacts
from runner.engine import ExperimentConfig, RunResult, _save_artifacts
from runner.tearsheet import Tearsheet


def _make_fills_df():
    """Build a minimal fills DataFrame for artifact tests."""
    return pd.DataFrame({
        "instrument_id": ["0xabc-tok1.POLYMARKET"] * 4,
        "order_side": ["BUY", "SELL", "BUY", "SELL"],
        "last_qty": [1.0, 1.0, 1.0, 1.0],
        "last_px": [0.50, 0.55, 0.48, 0.52],
        "ts_event": pd.to_datetime([
            "2026-03-09T09:10:00Z",
            "2026-03-09T09:20:00Z",
            "2026-03-09T09:30:00Z",
            "2026-03-09T09:40:00Z",
        ]),
    })


def _make_positions_df():
    """Build a minimal positions DataFrame for artifact tests."""
    return pd.DataFrame({
        "instrument_id": ["0xabc-tok1.POLYMARKET", "0xabc-tok1.POLYMARKET"],
        "ts_opened": pd.to_datetime(["2026-03-09T09:10:00Z", "2026-03-09T09:30:00Z"]),
        "ts_closed": pd.to_datetime(["2026-03-09T09:20:00Z", "2026-03-09T09:40:00Z"]),
        "realized_pnl": [0.05, 0.04],
    })


def _make_run_result(tearsheet=None, fills_df=None, orders_df=None, positions_df=None):
    """Build a RunResult for artifact tests."""
    config = ExperimentConfig(
        mode="backtest",
        strategy_path="experiments.strategies.tick_always:TickAlways",
        data_hours=["2026-03-09T09"],
    )
    return RunResult(
        run_id="test1234",
        config=config,
        tearsheet=tearsheet or Tearsheet(),
        orders_df=orders_df if orders_df is not None else pd.DataFrame(),
        fills_df=fills_df if fills_df is not None else pd.DataFrame(),
        positions_df=positions_df if positions_df is not None else pd.DataFrame(),
        elapsed_seconds=1.5,
    )


class TestGenerateAllArtifacts:
    def test_creates_pngs(self, tmp_path):
        """PNGs are created when fills/positions data exists."""
        fills_df = _make_fills_df()
        positions_df = _make_positions_df()

        created = generate_all_artifacts(
            fills_df=fills_df,
            positions_df=positions_df,
            results_dir=tmp_path,
        )

        assert (tmp_path / "pnl_curve.png").exists()
        assert (tmp_path / "trade_distribution.png").exists()
        # PNGs should be non-trivial size
        for f in created:
            assert f.stat().st_size > 1000, f"{f.name} is too small ({f.stat().st_size} bytes)"

    def test_empty_data_returns_empty(self, tmp_path):
        """Empty DataFrames produce no artifacts and no exceptions."""
        created = generate_all_artifacts(
            fills_df=pd.DataFrame(),
            positions_df=pd.DataFrame(),
            results_dir=tmp_path,
        )
        assert created == []
        # No PNG files should be created
        pngs = list(tmp_path.glob("*.png"))
        assert len(pngs) == 0


class TestSaveArtifacts:
    def test_creates_csvs_and_json(self, tmp_path):
        """_save_artifacts creates tearsheet.json, fills.csv, metadata.json."""
        fills_df = _make_fills_df()
        positions_df = _make_positions_df()
        orders_df = pd.DataFrame({"col": [1, 2]})

        result = _make_run_result(
            fills_df=fills_df,
            orders_df=orders_df,
            positions_df=positions_df,
        )
        _save_artifacts(result, tmp_path)

        assert (tmp_path / "tearsheet.json").exists()
        assert (tmp_path / "fills.csv").exists()
        assert (tmp_path / "metadata.json").exists()

    def test_tearsheet_json_matches_metrics(self, tmp_path):
        """tearsheet.json values match tearsheet.to_dict()."""
        tearsheet = Tearsheet(
            total_pnl=5.0,
            num_trades=10,
            num_round_trips=5,
            num_positions=2,
            win_rate=0.6,
            sharpe_ratio=1.5,
            max_drawdown=-2.0,
            avg_trade_pnl=0.5,
            profit_factor=1.8,
        )
        result = _make_run_result(tearsheet=tearsheet)
        _save_artifacts(result, tmp_path)

        with open(tmp_path / "tearsheet.json") as f:
            data = json.load(f)

        expected = tearsheet.to_dict()
        for key, val in expected.items():
            assert data[key] == val, f"Mismatch for {key}: {data[key]} != {val}"

    def test_metadata_json_has_required_fields(self, tmp_path):
        """metadata.json contains all required fields."""
        result = _make_run_result()
        _save_artifacts(result, tmp_path)

        with open(tmp_path / "metadata.json") as f:
            data = json.load(f)

        required_fields = ["run_id", "mode", "strategy_path", "strategy_params",
                          "data_hours", "elapsed_seconds", "success"]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        assert data["run_id"] == "test1234"
        assert data["mode"] == "backtest"
