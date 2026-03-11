"""Shared test fixtures and helpers for agent_pred tests."""

import json
import logging

import fsspec
import pyarrow.parquet as pq

from pmxt.reader import file_url

log = logging.getLogger(__name__)


def discover_market_with_tokens(hour: str) -> dict:
    """Discover a market from PMXT data and extract token_ids.

    Reads the first row group of the PMXT parquet file for the given hour,
    finds the market with the most activity, and builds a market_info dict
    suitable for instrument construction.
    """
    url = file_url(hour)
    fs = fsspec.filesystem("http")
    f = fs.open(url)
    pf = pq.ParquetFile(f)

    table = pf.read_row_group(0, columns=["market_id", "update_type", "data"])
    rows = table.to_pylist()
    f.close()

    market_tokens: dict[str, set[str]] = {}
    market_rows: dict[str, list[dict]] = {}

    for row in rows[:5000]:
        data = json.loads(row["data"])
        mid = row["market_id"]
        token_id = str(data.get("token_id", ""))
        if not token_id:
            continue
        if mid not in market_tokens:
            market_tokens[mid] = set()
            market_rows[mid] = []
        market_tokens[mid].add(token_id)
        market_rows[mid].append(row)

    # Pick market with most activity
    best_market = max(market_rows, key=lambda mid: len(market_rows[mid]))
    tokens = market_tokens[best_market]

    log.info(
        "Discovered market %s with %d tokens, %d rows",
        best_market[:16],
        len(tokens),
        len(market_rows[best_market]),
    )

    # KNOWN LIMITATION: Yes/No assignment is by lexicographic sort of token_id,
    # not from the Gamma API. The actual outcome label may be inverted. This
    # doesn't affect imbalance strategy correctness (trades on volume, not
    # direction) but makes analyst reasoning about market direction unreliable.
    token_list = []
    for i, tid in enumerate(sorted(tokens)):
        outcome = "Yes" if i == 0 else "No"
        token_list.append({"token_id": tid, "outcome": outcome})

    return {
        "condition_id": best_market,
        "question": f"Test market {best_market[:16]}",
        "minimum_tick_size": "0.01",
        "minimum_order_size": "1",
        "end_date_iso": "2027-12-31T00:00:00Z",
        "maker_base_fee": "0",
        "taker_base_fee": "0",
        "tokens": token_list,
    }
