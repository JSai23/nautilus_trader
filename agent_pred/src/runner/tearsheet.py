"""Tearsheet computation from backtest results.

Per IMPL_PLAN Section 5.2, computes 8 core metrics from
ReportProvider DataFrames.

PnL is computed from fills (BUY/SELL pairs per instrument), NOT from
Position.realized_pnl. In NETTING mode with re-entry, the positions
report only captures the last open/close cycle's PnL — fills are the
only reliable source across all round trips.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class Tearsheet:
    total_pnl: float = 0.0
    num_trades: int = 0  # Fill events (BUY + SELL)
    num_round_trips: int = 0  # Completed BUY→SELL pairs
    num_positions: int = 0  # Unique instruments with closed positions
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    avg_trade_pnl: float = 0.0
    profit_factor: float = 0.0

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _compute_round_trip_pnls(fills_df: pd.DataFrame) -> list[float]:
    """Pair BUY/SELL fills per instrument chronologically to compute per-trade PnL.

    In NETTING mode, each instrument has a sequence of BUY→SELL→BUY→SELL...
    Each BUY→SELL pair is one round trip with PnL = (sell_price - buy_price) * qty.
    """
    if fills_df.empty:
        return []

    # Parse numeric columns from string format
    df = fills_df.copy()
    df["_px"] = pd.to_numeric(df["last_px"].astype(str), errors="coerce")
    df["_qty"] = pd.to_numeric(df["last_qty"].astype(str), errors="coerce")

    # Sort by instrument then time
    df = df.sort_values("ts_event")

    pnls: list[float] = []

    # Group by instrument and pair sequential BUY/SELL fills
    for _instrument_id, group in df.groupby("instrument_id"):
        pending_buy: dict | None = None
        for _, row in group.iterrows():
            side = str(row["order_side"])
            px = row["_px"]
            qty = row["_qty"]

            if pd.isna(px) or pd.isna(qty):
                continue

            if side == "BUY":
                pending_buy = {"px": px, "qty": qty}
            elif side == "SELL" and pending_buy is not None:
                # Round trip: BUY at pending_buy price, SELL at current price
                trade_pnl = (px - pending_buy["px"]) * min(qty, pending_buy["qty"])
                pnls.append(round(trade_pnl, 6))
                pending_buy = None

    return pnls


def compute_tearsheet(
    positions_df: pd.DataFrame,
    fills_df: pd.DataFrame,
    account_df: pd.DataFrame | None = None,
) -> Tearsheet:
    """Compute tearsheet metrics from ReportProvider DataFrames.

    PnL metrics are derived from fills (BUY/SELL pairs), not from
    Position.realized_pnl, because the positions report under-reports
    PnL in NETTING mode with re-entry strategies.

    Parameters
    ----------
    positions_df : pd.DataFrame
        Output of ReportProvider.generate_positions_report().
        Used only for num_positions count.
    fills_df : pd.DataFrame
        Output of ReportProvider.generate_fills_report().
        Primary source for all PnL metrics.
    account_df : pd.DataFrame | None
        Output of ReportProvider.generate_account_report().
    """
    ts = Tearsheet()

    # Num positions from positions report (unique instruments, correct in NETTING)
    if not positions_df.empty:
        ts.num_positions = len(positions_df)

    # Num fills
    if not fills_df.empty:
        ts.num_trades = len(fills_df)

    # Compute all PnL metrics from fills
    pnls = _compute_round_trip_pnls(fills_df)
    if not pnls:
        return ts

    pnl_series = pd.Series(pnls)
    ts.num_round_trips = len(pnls)
    ts.total_pnl = round(float(pnl_series.sum()), 6)

    wins = pnl_series[pnl_series > 0]
    losses = pnl_series[pnl_series < 0]

    if len(pnls) > 0:
        ts.win_rate = round(float(len(wins) / len(pnls)), 4)
        ts.avg_trade_pnl = round(float(pnl_series.mean()), 6)

    # Profit factor
    total_wins = float(wins.sum()) if len(wins) > 0 else 0.0
    total_losses = abs(float(losses.sum())) if len(losses) > 0 else 0.0
    if total_losses > 0:
        ts.profit_factor = round(total_wins / total_losses, 4)
    elif total_wins > 0:
        ts.profit_factor = float("inf")

    # Sharpe ratio from per-trade PnL (annualized)
    if len(pnls) > 1:
        mean_pnl = float(pnl_series.mean())
        std_pnl = float(pnl_series.std())
        if std_pnl > 0:
            ts.sharpe_ratio = round(mean_pnl / std_pnl * math.sqrt(252), 4)

    # Max drawdown from cumulative PnL
    cum_pnl = pnl_series.cumsum()
    running_max = cum_pnl.cummax()
    drawdown = cum_pnl - running_max
    ts.max_drawdown = round(float(drawdown.min()), 6)

    return ts
