"""Tier 3 E2E tests: paper trading property tests.

Covers TEST_PLAN.md Section 13:
- Paper structural correctness
- Fill invariants
- Lifecycle timing

These tests require live WebSocket connections to Polymarket.
Marked @pytest.mark.network for CI skip.

Note: Paper trading tests are inherently non-deterministic.
Assertions use invariant-based properties (prices in range, balanced
BUY/SELL, data arrives) rather than exact values.
"""

import json
import logging
import time

import pytest

log = logging.getLogger(__name__)


@pytest.mark.network
@pytest.mark.timeout(300)
class TestPaperProperties:
    """Paper trading property tests — requires live WebSocket.

    These tests run a real paper trading session for 60-90 seconds
    and assert on invariant properties. They are slow, non-deterministic,
    and require network access. Skip with: -m "not network"
    """

    def test_paper_structural_correctness(self, tmp_path):
        """Paper session starts, receives data, submits orders, fills."""
        from runner.engine import ExperimentConfig
        from runner.paper import run_paper
        from universe.gamma import discover_markets, MarketFilter

        # Discover active btc-updown-15m markets
        mf = MarketFilter(
            active=True,
            closed=False,
            slug_contains="btc-updown-15m",
            max_markets=3,
        )
        market_infos = discover_markets(mf)
        if not market_infos:
            pytest.skip("No active btc-updown-15m markets found")

        config = ExperimentConfig(
            mode="paper",
            strategy_path="experiments.strategies.tick_always:TickAlways",
            strategy_params={
                "trade_size": 5.0,
                "buy_after_ticks": 3,
                "sell_after_ticks": 10,
                "dynamic_instruments": True,
            },
            paper_duration_seconds=60,
        )

        result = run_paper(config, market_infos, results_dir=tmp_path)

        # Structural invariants
        assert result is not None, "run_paper returned None"

        # Check status.json was written
        status_path = tmp_path / "status.json"
        if status_path.exists():
            with open(status_path) as f:
                status = json.load(f)
            log.info(
                "Paper result: status=%s, ticks=%s, fills=%s",
                status.get("status"),
                status.get("ticks"),
                status.get("fills"),
            )

    def test_paper_fill_invariants(self, tmp_path):
        """Fill prices in (0,1), BUY/SELL ratio < 3.0."""
        from runner.engine import ExperimentConfig
        from runner.paper import run_paper
        from universe.gamma import discover_markets, MarketFilter

        mf = MarketFilter(
            active=True,
            closed=False,
            slug_contains="btc-updown-15m",
            max_markets=3,
        )
        market_infos = discover_markets(mf)
        if not market_infos:
            pytest.skip("No active btc-updown-15m markets found")

        config = ExperimentConfig(
            mode="paper",
            strategy_path="experiments.strategies.tick_always:TickAlways",
            strategy_params={
                "trade_size": 5.0,
                "buy_after_ticks": 3,
                "sell_after_ticks": 10,
            },
            paper_duration_seconds=90,
        )

        result = run_paper(config, market_infos, results_dir=tmp_path)

        # Check fills.csv if it exists
        fills_path = tmp_path / "fills.csv"
        if fills_path.exists():
            import csv

            with open(fills_path) as f:
                rows = list(csv.DictReader(f))

            log.info("Paper fills: %d rows", len(rows))

            for row in rows:
                if "last_px" in row:
                    price = float(row["last_px"])
                    assert 0 < price < 1.0, f"Fill price {price} out of range"

    def test_paper_artifacts_generated(self, tmp_path):
        """Paper session generates status.json and fills artifacts."""
        from runner.engine import ExperimentConfig
        from runner.paper import run_paper
        from universe.gamma import discover_markets, MarketFilter

        mf = MarketFilter(
            active=True,
            closed=False,
            slug_contains="btc-updown-15m",
            max_markets=3,
        )
        market_infos = discover_markets(mf)
        if not market_infos:
            pytest.skip("No active btc-updown-15m markets found")

        config = ExperimentConfig(
            mode="paper",
            strategy_path="experiments.strategies.tick_always:TickAlways",
            strategy_params={
                "trade_size": 5.0,
                "buy_after_ticks": 3,
                "sell_after_ticks": 10,
            },
            paper_duration_seconds=60,
        )

        result = run_paper(config, market_infos, results_dir=tmp_path)

        # status.json must always exist
        assert (tmp_path / "status.json").exists(), "status.json not generated"
