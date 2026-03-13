"""Visualization artifacts for backtest and paper trading results.

Generates PnL curves, position timelines, trade distributions,
and instrument lifecycle charts. All labels use slug + condition_id.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


def _slug_label(instrument_id: str, market_infos: list[dict] | None = None) -> str:
    """Convert instrument_id to slug + outcome + truncated condition_id label.

    Distinguishes Up/Down tokens of the same market by matching token_id
    against the market_info tokens array.
    """
    # instrument_id format: "{condition_id}-{token_id}.POLYMARKET"
    symbol = instrument_id.split(".")[0] if "." in instrument_id else instrument_id
    parts = symbol.split("-", 1)
    condition_id = parts[0] if parts else symbol
    token_id = parts[1] if len(parts) == 2 else ""

    if market_infos:
        for m in market_infos:
            if m.get("condition_id", "") == condition_id:
                slug = m.get("slug", "")
                # Find outcome for this specific token
                outcome = ""
                for t in m.get("tokens", []):
                    if str(t.get("token_id", "")) == token_id:
                        outcome = t.get("outcome", "")
                        break
                if slug:
                    suffix = f"-{outcome}" if outcome else ""
                    return f"{slug}{suffix} ({condition_id[:10]}...)"
                break

    return f"{condition_id[:16]}..."


def generate_pnl_curve(fills_df: pd.DataFrame, output_path: Path,
                       market_infos: list[dict] | None = None) -> bool:
    """Generate cumulative PnL curve as PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib not available — skipping PnL curve")
        return False

    if fills_df.empty:
        return False

    df = fills_df.copy()
    df["_px"] = pd.to_numeric(df["last_px"].astype(str), errors="coerce")
    df["_qty"] = pd.to_numeric(df["last_qty"].astype(str), errors="coerce")
    df = df.sort_values("ts_event")

    # Compute cumulative PnL from fill pairs per instrument
    pnl_events = []
    pending_buys: dict[str, dict] = {}

    for _, row in df.iterrows():
        side = str(row["order_side"])
        iid = str(row["instrument_id"])
        px = row["_px"]
        qty = row["_qty"]
        ts = row["ts_event"]

        if pd.isna(px) or pd.isna(qty):
            continue

        if side == "BUY":
            pending_buys[iid] = {"px": px, "qty": qty}
        elif side == "SELL" and iid in pending_buys:
            buy = pending_buys.pop(iid)
            trade_pnl = (px - buy["px"]) * min(qty, buy["qty"])
            pnl_events.append({"ts": ts, "pnl": trade_pnl})

    if not pnl_events:
        return False

    pnl_df = pd.DataFrame(pnl_events)
    pnl_df["cumulative_pnl"] = pnl_df["pnl"].cumsum()

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(range(len(pnl_df)), pnl_df["cumulative_pnl"], linewidth=1.5, color="#2196F3")
    ax.fill_between(range(len(pnl_df)), pnl_df["cumulative_pnl"], alpha=0.1, color="#2196F3")
    ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cumulative PnL (USDC)")
    ax.set_title("Cumulative PnL Curve")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved PnL curve to %s", output_path)
    return True


def generate_position_timeline(positions_df: pd.DataFrame, output_path: Path,
                               market_infos: list[dict] | None = None) -> bool:
    """Generate position timeline (Gantt-style) as PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        log.warning("matplotlib not available — skipping position timeline")
        return False

    if positions_df.empty:
        return False

    df = positions_df.copy()

    # Build labels with slugs
    labels = []
    for iid in df["instrument_id"]:
        labels.append(_slug_label(str(iid), market_infos))
    df["label"] = labels

    # Parse timestamps
    if "ts_opened" in df.columns:
        df["open_time"] = pd.to_datetime(df["ts_opened"], utc=True)
    if "ts_closed" in df.columns:
        df["close_time"] = pd.to_datetime(df["ts_closed"], utc=True)

    if "open_time" not in df.columns or "close_time" not in df.columns:
        return False

    fig, ax = plt.subplots(figsize=(14, max(3, len(df) * 0.3)))
    unique_labels = df["label"].unique()
    label_to_y = {label: i for i, label in enumerate(unique_labels)}

    for _, row in df.iterrows():
        y = label_to_y[row["label"]]
        start = row["open_time"]
        end = row["close_time"]
        duration = end - start
        ax.barh(y, duration, left=start, height=0.6, color="#4CAF50", alpha=0.7, edgecolor="black", linewidth=0.5)

    ax.set_yticks(range(len(unique_labels)))
    ax.set_yticklabels(unique_labels, fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_xlabel("Time (UTC)")
    ax.set_title("Position Timeline")
    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(output_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved position timeline to %s", output_path)
    return True


def generate_trade_distribution(fills_df: pd.DataFrame, output_path: Path) -> bool:
    """Generate histogram of PnL per trade as PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib not available — skipping trade distribution")
        return False

    if fills_df.empty:
        return False

    df = fills_df.copy()
    df["_px"] = pd.to_numeric(df["last_px"].astype(str), errors="coerce")
    df["_qty"] = pd.to_numeric(df["last_qty"].astype(str), errors="coerce")
    df = df.sort_values("ts_event")

    pnls = []
    pending_buys: dict[str, dict] = {}
    for _, row in df.iterrows():
        side = str(row["order_side"])
        iid = str(row["instrument_id"])
        px = row["_px"]
        qty = row["_qty"]
        if pd.isna(px) or pd.isna(qty):
            continue
        if side == "BUY":
            pending_buys[iid] = {"px": px, "qty": qty}
        elif side == "SELL" and iid in pending_buys:
            buy = pending_buys.pop(iid)
            pnls.append((px - buy["px"]) * min(qty, buy["qty"]))

    if not pnls:
        return False

    fig, ax = plt.subplots(figsize=(10, 5))
    colors = ["#4CAF50" if p > 0 else "#F44336" for p in pnls]
    ax.bar(range(len(pnls)), pnls, color=colors, alpha=0.7)
    ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)
    ax.set_xlabel("Trade #")
    ax.set_ylabel("PnL (USDC)")
    ax.set_title("Trade PnL Distribution")
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(output_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved trade distribution to %s", output_path)
    return True


def generate_instrument_lifecycle(fills_df: pd.DataFrame, output_path: Path,
                                  market_infos: list[dict] | None = None) -> bool:
    """Generate instrument lifecycle Gantt chart (first to last data point per instrument)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        log.warning("matplotlib not available — skipping instrument lifecycle")
        return False

    if fills_df.empty:
        return False

    df = fills_df.copy()
    df["_ts"] = pd.to_datetime(df["ts_event"], utc=True)

    # Group by instrument: first and last event timestamps
    lifecycle = df.groupby("instrument_id")["_ts"].agg(["min", "max"]).reset_index()
    lifecycle.columns = ["instrument_id", "first_seen", "last_seen"]

    if lifecycle.empty:
        return False

    # Build labels with slugs
    lifecycle["label"] = lifecycle["instrument_id"].apply(
        lambda iid: _slug_label(str(iid), market_infos)
    )

    fig, ax = plt.subplots(figsize=(14, max(3, len(lifecycle) * 0.5)))

    for i, row in lifecycle.iterrows():
        duration = row["last_seen"] - row["first_seen"]
        ax.barh(i, duration, left=row["first_seen"], height=0.6,
                color="#FF9800", alpha=0.7, edgecolor="black", linewidth=0.5)

    ax.set_yticks(range(len(lifecycle)))
    ax.set_yticklabels(lifecycle["label"], fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.set_xlabel("Time (UTC)")
    ax.set_title("Instrument Lifecycle (First to Last Data Point)")
    ax.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    fig.savefig(output_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved instrument lifecycle to %s", output_path)
    return True


def generate_all_artifacts(
    fills_df: pd.DataFrame,
    positions_df: pd.DataFrame,
    results_dir: Path,
    market_infos: list[dict] | None = None,
) -> list[Path]:
    """Generate all visualization artifacts. Returns list of created files."""
    created = []

    if generate_pnl_curve(fills_df, results_dir / "pnl_curve.png", market_infos):
        created.append(results_dir / "pnl_curve.png")

    if generate_position_timeline(positions_df, results_dir / "position_timeline.png", market_infos):
        created.append(results_dir / "position_timeline.png")

    if generate_trade_distribution(fills_df, results_dir / "trade_distribution.png"):
        created.append(results_dir / "trade_distribution.png")

    if generate_instrument_lifecycle(fills_df, results_dir / "instrument_lifecycle.png", market_infos):
        created.append(results_dir / "instrument_lifecycle.png")

    return created
