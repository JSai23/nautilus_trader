"""Tests for tearsheet computation."""

import pandas as pd

from runner.tearsheet import Tearsheet, compute_tearsheet


class TestTearsheet:
    def test_empty_data(self):
        ts = compute_tearsheet(pd.DataFrame(), pd.DataFrame())
        assert ts.total_pnl == 0.0
        assert ts.num_trades == 0

    def test_with_positions(self):
        positions_df = pd.DataFrame({
            "realized_pnl": [100.0, -50.0, 200.0, -30.0, 80.0],
        })
        fills_df = pd.DataFrame({"fill_id": range(10)})

        ts = compute_tearsheet(positions_df, fills_df)

        assert ts.total_pnl == 300.0
        assert ts.num_positions == 5
        assert ts.num_trades == 10
        assert ts.win_rate == 0.6  # 3 wins out of 5
        assert ts.avg_trade_pnl == 60.0  # 300 / 5
        assert ts.profit_factor > 0

    def test_all_wins(self):
        positions_df = pd.DataFrame({
            "realized_pnl": [100.0, 200.0, 50.0],
        })
        fills_df = pd.DataFrame()

        ts = compute_tearsheet(positions_df, fills_df)
        assert ts.win_rate == 1.0
        assert ts.profit_factor == float("inf")

    def test_sharpe_ratio(self):
        positions_df = pd.DataFrame({
            "realized_pnl": [10.0, -5.0, 15.0, -3.0, 8.0, 12.0, -2.0, 20.0],
        })
        fills_df = pd.DataFrame()

        ts = compute_tearsheet(positions_df, fills_df)
        assert ts.sharpe_ratio != 0  # Should compute a value

    def test_max_drawdown(self):
        positions_df = pd.DataFrame({
            "realized_pnl": [100.0, -200.0, 50.0],
        })
        fills_df = pd.DataFrame()

        ts = compute_tearsheet(positions_df, fills_df)
        assert ts.max_drawdown < 0  # Should be negative (drawdown)

    def test_money_string_format(self):
        """ReportProvider emits Money strings like '-1.100000 USDC.e'.
        compute_tearsheet must parse these correctly via .str.split().str[0].
        """
        positions_df = pd.DataFrame({
            "realized_pnl": [
                "-1.100000 USDC.e",
                "-7.400000 USDC.e",
                "3.500000 USDC.e",
                "-2.000000 USDC.e",
                "0.000000 USDC.e",
            ],
        })
        fills_df = pd.DataFrame({"fill_id": range(8)})

        ts = compute_tearsheet(positions_df, fills_df)

        assert ts.total_pnl == -7.0  # -1.1 + -7.4 + 3.5 + -2.0 + 0.0
        assert ts.num_positions == 5
        assert ts.num_trades == 8
        assert ts.win_rate == 0.2  # 1 win out of 5
        assert ts.avg_trade_pnl == -1.4  # -7.0 / 5

    def test_to_dict(self):
        ts = Tearsheet(total_pnl=100.0, num_trades=5)
        d = ts.to_dict()
        assert d["total_pnl"] == 100.0
        assert d["num_trades"] == 5
        assert "sharpe_ratio" in d
