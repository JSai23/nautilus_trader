"""Tearsheet computation from backtest results.

Per IMPL_PLAN Section 5.2, computes 8 core metrics from
ReportProvider DataFrames.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class Tearsheet:
    total_pnl: float = 0.0
    num_trades: int = 0
    num_positions: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    avg_trade_pnl: float = 0.0
    profit_factor: float = 0.0

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def compute_tearsheet(
    positions_df: pd.DataFrame,
    fills_df: pd.DataFrame,
    account_df: pd.DataFrame | None = None,
) -> Tearsheet:
    """Compute tearsheet metrics from ReportProvider DataFrames.

    Parameters
    ----------
    positions_df : pd.DataFrame
        Output of ReportProvider.generate_positions_report().
    fills_df : pd.DataFrame
        Output of ReportProvider.generate_order_fills_report().
    account_df : pd.DataFrame | None
        Output of ReportProvider.generate_account_report().
    """
    ts = Tearsheet()

    # Total PnL from positions
    if not positions_df.empty and "realized_pnl" in positions_df.columns:
        pnl_str = positions_df["realized_pnl"].astype(str).str.split().str[0]
        pnl_values = pd.to_numeric(pnl_str, errors="coerce").fillna(0)
        ts.total_pnl = round(float(pnl_values.sum()), 6)
        ts.num_positions = len(positions_df)

        wins = pnl_values[pnl_values > 0]
        losses = pnl_values[pnl_values < 0]

        if ts.num_positions > 0:
            ts.win_rate = round(float(len(wins) / ts.num_positions), 4)
            ts.avg_trade_pnl = round(float(pnl_values.mean()), 6)

        # Profit factor
        total_wins = float(wins.sum()) if len(wins) > 0 else 0.0
        total_losses = abs(float(losses.sum())) if len(losses) > 0 else 0.0
        if total_losses > 0:
            ts.profit_factor = round(total_wins / total_losses, 4)
        elif total_wins > 0:
            ts.profit_factor = float("inf")

        # Sharpe ratio from PnL series (annualized)
        if len(pnl_values) > 1:
            mean_pnl = float(pnl_values.mean())
            std_pnl = float(pnl_values.std())
            if std_pnl > 0:
                ts.sharpe_ratio = round(mean_pnl / std_pnl * math.sqrt(252), 4)

        # Max drawdown from cumulative PnL
        cum_pnl = pnl_values.cumsum()
        running_max = cum_pnl.cummax()
        drawdown = cum_pnl - running_max
        ts.max_drawdown = round(float(drawdown.min()), 6)

    # Num trades from fills
    if not fills_df.empty:
        ts.num_trades = len(fills_df)

    return ts
