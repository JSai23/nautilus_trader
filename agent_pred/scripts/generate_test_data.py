"""One-time script to generate bundled test data for Tier 2 tests.

Downloads a small slice of PMXT data, filters to 1-2 markets with
price movement, and saves as a compact parquet + market metadata JSON.

Usage:
    uv run python scripts/generate_test_data.py
"""

import json
import logging
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pmxt.reader import file_url, read_remote_filtered
from universe.gamma import fetch_market_clob

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

HOUR = "2026-03-09T09"
OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def find_best_markets(hour: str, min_rows: int = 200) -> dict[str, set[str]]:
    """Scan PMXT data to find markets with the most activity."""
    import fsspec

    url = file_url(hour)
    log.info("Opening PMXT parquet: %s", url)
    fs = fsspec.filesystem("http")
    f = fs.open(url)
    pf = pq.ParquetFile(f)

    market_tokens: dict[str, set[str]] = {}
    market_row_count: dict[str, int] = {}
    market_has_snapshots: dict[str, bool] = {}

    # Scan first few row groups
    for rg_idx in range(min(pf.metadata.num_row_groups, 5)):
        table = pf.read_row_group(rg_idx, columns=["market_id", "update_type", "data"])
        for row in table.to_pylist():
            data = json.loads(row["data"])
            mid = row["market_id"]
            token_id = str(data.get("token_id", ""))
            if not token_id:
                continue
            if mid not in market_tokens:
                market_tokens[mid] = set()
                market_row_count[mid] = 0
                market_has_snapshots[mid] = False
            market_tokens[mid].add(token_id)
            market_row_count[mid] += 1
            if row["update_type"] == "book_snapshot":
                market_has_snapshots[mid] = True

    f.close()

    # Filter: need 2+ tokens, enough rows, and book_snapshots
    candidates = {
        mid: tokens
        for mid, tokens in market_tokens.items()
        if len(tokens) >= 2
        and market_row_count[mid] >= min_rows
        and market_has_snapshots[mid]
    }

    # Sort by row count, pick top 2
    sorted_markets = sorted(candidates.keys(), key=lambda m: market_row_count[m], reverse=True)
    log.info("Found %d candidate markets. Top 5 by row count:", len(sorted_markets))
    for mid in sorted_markets[:5]:
        log.info(
            "  %s: %d rows, %d tokens, snapshots=%s",
            mid[:16], market_row_count[mid], len(market_tokens[mid]),
            market_has_snapshots[mid],
        )

    selected = sorted_markets[:2]
    return {mid: market_tokens[mid] for mid in selected}


def download_filtered_data(hour: str, market_ids: set[str], max_rows: int = 2000) -> list[dict]:
    """Download PMXT rows for selected markets."""
    rows = []
    for batch in read_remote_filtered(hour, market_ids):
        rows.extend(batch)
        if len(rows) >= max_rows:
            break
    log.info("Downloaded %d rows for %d markets", len(rows), len(market_ids))
    return rows[:max_rows]


def fetch_metadata(market_ids_with_tokens: dict[str, set[str]], hour: str) -> list[dict]:
    """Fetch or fabricate market metadata for each market."""
    from datetime import datetime, timezone

    hour_dt = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    metadatas = []

    for condition_id, tokens in market_ids_with_tokens.items():
        clob = fetch_market_clob(condition_id)
        if clob:
            # Adapt for test use
            metadata = dict(clob)
            # Extend end_date past test hour
            metadata["end_date_iso"] = "2027-12-31T00:00:00Z"
            metadata["minimum_order_size"] = "1"
            log.info("Fetched CLOB metadata for %s: %s", condition_id[:16], metadata.get("question", "")[:60])
        else:
            # Fabricate
            token_list = []
            for i, tid in enumerate(sorted(tokens)):
                outcome = "Yes" if i == 0 else "No"
                token_list.append({"token_id": tid, "outcome": outcome})
            metadata = {
                "condition_id": condition_id,
                "question": f"Test market {condition_id[:16]}",
                "minimum_tick_size": "0.01",
                "minimum_order_size": "1",
                "end_date_iso": "2027-12-31T00:00:00Z",
                "maker_base_fee": "0",
                "taker_base_fee": "0",
                "tokens": token_list,
            }
            log.info("Fabricated metadata for %s", condition_id[:16])

        metadatas.append(metadata)

    return metadatas


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Find markets
    log.info("=== Step 1: Finding best markets in %s ===", HOUR)
    market_ids_with_tokens = find_best_markets(HOUR)
    if not market_ids_with_tokens:
        log.error("No suitable markets found!")
        sys.exit(1)

    market_ids = set(market_ids_with_tokens.keys())
    log.info("Selected %d markets: %s", len(market_ids), [m[:16] for m in market_ids])

    # Step 2: Download filtered data
    log.info("=== Step 2: Downloading filtered data ===")
    rows = download_filtered_data(HOUR, market_ids, max_rows=2000)

    # Step 3: Save parquet
    parquet_path = OUTPUT_DIR / "test_hour.parquet"
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, str(parquet_path))
    file_size = parquet_path.stat().st_size
    log.info("Saved %d rows to %s (%.1f KB)", len(rows), parquet_path, file_size / 1024)

    # Step 4: Fetch metadata
    log.info("=== Step 3: Fetching market metadata ===")
    metadatas = fetch_metadata(market_ids_with_tokens, HOUR)

    # Step 5: Save metadata JSON
    json_path = OUTPUT_DIR / "market_metadata.json"
    with open(json_path, "w") as f:
        json.dump(metadatas, f, indent=2)
    log.info("Saved metadata for %d markets to %s", len(metadatas), json_path)

    # Summary
    log.info("=== Done ===")
    log.info("Parquet: %s (%d rows, %.1f KB)", parquet_path, len(rows), file_size / 1024)
    log.info("Metadata: %s (%d markets)", json_path, len(metadatas))

    # Verify: check data has both update types
    update_types = set()
    for row in rows:
        update_types.add(row.get("update_type", "unknown"))
    log.info("Update types in data: %s", update_types)

    # Verify: check price range
    prices = []
    for row in rows:
        data = json.loads(row["data"]) if isinstance(row["data"], str) else row["data"]
        bid = data.get("best_bid")
        ask = data.get("best_ask")
        if bid:
            prices.append(float(bid))
        if ask:
            prices.append(float(ask))
    if prices:
        log.info("Price range: %.3f - %.3f", min(prices), max(prices))


if __name__ == "__main__":
    main()
