"""Tests for tearsheet computation.

PnL is computed from fills (BUY/SELL pairs per instrument), not from
positions_df.realized_pnl. These tests verify the fills-based pairing logic.
"""

import pandas as pd

from runner.tearsheet import Tearsheet, _compute_round_trip_pnls, compute_tearsheet


def _make_fills(trades: list[tuple[str, str, float, float, str]]) -> pd.DataFrame:
    """Build a fills DataFrame from (instrument_id, side, price, qty, time) tuples."""
    return pd.DataFrame(
        trades,
        columns=["instrument_id", "order_side", "last_px", "last_qty", "ts_event"],
    )


class TestComputeRoundTripPnls:
    def test_single_round_trip(self):
        fills = _make_fills([
            ("A", "BUY", 0.50, 10.0, "2026-01-01T00:00:00"),
            ("A", "SELL", 0.55, 10.0, "2026-01-01T00:01:00"),
        ])
        pnls = _compute_round_trip_pnls(fills)
        assert len(pnls) == 1
        assert pnls[0] == round((0.55 - 0.50) * 10.0, 6)

    def test_multiple_round_trips_same_instrument(self):
        fills = _make_fills([
            ("A", "BUY", 0.50, 5.0, "2026-01-01T00:00:00"),
            ("A", "SELL", 0.48, 5.0, "2026-01-01T00:01:00"),
            ("A", "BUY", 0.47, 5.0, "2026-01-01T00:02:00"),
            ("A", "SELL", 0.52, 5.0, "2026-01-01T00:03:00"),
        ])
        pnls = _compute_round_trip_pnls(fills)
        assert len(pnls) == 2
        assert pnls[0] == round((0.48 - 0.50) * 5.0, 6)  # Loss
        assert pnls[1] == round((0.52 - 0.47) * 5.0, 6)  # Win

    def test_multiple_instruments(self):
        fills = _make_fills([
            ("A", "BUY", 0.50, 1.0, "2026-01-01T00:00:00"),
            ("B", "BUY", 0.30, 1.0, "2026-01-01T00:00:01"),
            ("A", "SELL", 0.55, 1.0, "2026-01-01T00:01:00"),
            ("B", "SELL", 0.25, 1.0, "2026-01-01T00:01:01"),
        ])
        pnls = _compute_round_trip_pnls(fills)
        assert len(pnls) == 2
        total = sum(pnls)
        # A: +0.05, B: -0.05
        assert abs(total) < 1e-6

    def test_unpaired_buy_ignored(self):
        fills = _make_fills([
            ("A", "BUY", 0.50, 1.0, "2026-01-01T00:00:00"),
            ("A", "SELL", 0.55, 1.0, "2026-01-01T00:01:00"),
            ("A", "BUY", 0.52, 1.0, "2026-01-01T00:02:00"),
            # No matching SELL — this BUY is unpaired
        ])
        pnls = _compute_round_trip_pnls(fills)
        assert len(pnls) == 1  # Only the completed round trip

    def test_sell_without_buy_ignored(self):
        fills = _make_fills([
            ("A", "SELL", 0.55, 1.0, "2026-01-01T00:00:00"),  # No preceding BUY
            ("A", "BUY", 0.50, 1.0, "2026-01-01T00:01:00"),
            ("A", "SELL", 0.53, 1.0, "2026-01-01T00:02:00"),
        ])
        pnls = _compute_round_trip_pnls(fills)
        assert len(pnls) == 1
        assert pnls[0] == round((0.53 - 0.50) * 1.0, 6)

    def test_empty_fills(self):
        pnls = _compute_round_trip_pnls(pd.DataFrame())
        assert pnls == []

    def test_uses_min_qty_for_partial_fills(self):
        fills = _make_fills([
            ("A", "BUY", 0.50, 10.0, "2026-01-01T00:00:00"),
            ("A", "SELL", 0.55, 8.0, "2026-01-01T00:01:00"),
        ])
        pnls = _compute_round_trip_pnls(fills)
        assert len(pnls) == 1
        assert pnls[0] == round((0.55 - 0.50) * 8.0, 6)  # min(10, 8) = 8


class TestComputeTearsheet:
    def test_empty_data(self):
        ts = compute_tearsheet(pd.DataFrame(), pd.DataFrame())
        assert ts.total_pnl == 0.0
        assert ts.num_trades == 0
        assert ts.num_round_trips == 0

    def test_basic_metrics(self):
        fills = _make_fills([
            ("A", "BUY", 0.50, 10.0, "2026-01-01T00:00:00"),
            ("A", "SELL", 0.55, 10.0, "2026-01-01T00:01:00"),
            ("A", "BUY", 0.52, 10.0, "2026-01-01T00:02:00"),
            ("A", "SELL", 0.48, 10.0, "2026-01-01T00:03:00"),
            ("B", "BUY", 0.30, 5.0, "2026-01-01T00:00:00"),
            ("B", "SELL", 0.35, 5.0, "2026-01-01T00:01:00"),
        ])
        positions_df = pd.DataFrame({"realized_pnl": ["1.0 USDC", "2.0 USDC"]})

        ts = compute_tearsheet(positions_df, fills)

        assert ts.num_trades == 6  # 6 fill events
        assert ts.num_round_trips == 3  # 3 BUY/SELL pairs
        assert ts.num_positions == 2  # From positions_df
        # Round trip PnLs: +0.50 (A1), -0.40 (A2), +0.25 (B1) = +0.35
        assert abs(ts.total_pnl - 0.35) < 0.01
        assert ts.win_rate == round(2 / 3, 4)  # 2 wins, 1 loss

    def test_all_wins(self):
        fills = _make_fills([
            ("A", "BUY", 0.40, 1.0, "2026-01-01T00:00:00"),
            ("A", "SELL", 0.50, 1.0, "2026-01-01T00:01:00"),
            ("B", "BUY", 0.20, 1.0, "2026-01-01T00:00:00"),
            ("B", "SELL", 0.30, 1.0, "2026-01-01T00:01:00"),
        ])

        ts = compute_tearsheet(pd.DataFrame(), fills)
        assert ts.win_rate == 1.0
        assert ts.profit_factor == float("inf")

    def test_sharpe_ratio(self):
        fills = _make_fills([
            ("A", "BUY", 0.50, 1.0, "2026-01-01T00:00:00"),
            ("A", "SELL", 0.55, 1.0, "2026-01-01T00:01:00"),
            ("A", "BUY", 0.52, 1.0, "2026-01-01T00:02:00"),
            ("A", "SELL", 0.48, 1.0, "2026-01-01T00:03:00"),
            ("A", "BUY", 0.47, 1.0, "2026-01-01T00:04:00"),
            ("A", "SELL", 0.53, 1.0, "2026-01-01T00:05:00"),
        ])

        ts = compute_tearsheet(pd.DataFrame(), fills)
        assert ts.sharpe_ratio != 0

    def test_max_drawdown(self):
        # Win then two losses — drawdown should be negative
        fills = _make_fills([
            ("A", "BUY", 0.50, 10.0, "2026-01-01T00:00:00"),
            ("A", "SELL", 0.60, 10.0, "2026-01-01T00:01:00"),
            ("A", "BUY", 0.55, 10.0, "2026-01-01T00:02:00"),
            ("A", "SELL", 0.45, 10.0, "2026-01-01T00:03:00"),
            ("A", "BUY", 0.44, 10.0, "2026-01-01T00:04:00"),
            ("A", "SELL", 0.40, 10.0, "2026-01-01T00:05:00"),
        ])

        ts = compute_tearsheet(pd.DataFrame(), fills)
        assert ts.max_drawdown < 0

    def test_positions_count_independent_of_fills(self):
        """num_positions comes from positions_df, not fills."""
        positions_df = pd.DataFrame({
            "realized_pnl": ["-1.0 USDC.e", "2.0 USDC.e", "0.5 USDC.e"]
        })
        ts = compute_tearsheet(positions_df, pd.DataFrame())
        assert ts.num_positions == 3
        assert ts.num_round_trips == 0  # No fills → no round trips
        assert ts.total_pnl == 0.0  # PnL comes from fills, not positions

    def test_to_dict(self):
        ts = Tearsheet(total_pnl=100.0, num_trades=5, num_round_trips=2)
        d = ts.to_dict()
        assert d["total_pnl"] == 100.0
        assert d["num_trades"] == 5
        assert d["num_round_trips"] == 2
        assert "sharpe_ratio" in d
