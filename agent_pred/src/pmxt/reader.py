"""Read PMXT parquet data from remote (via fsspec HTTP range) or local cache.

Design per IMPL_PLAN Section 3.6:
- Stream raw files via HTTP range requests (never download full raw file)
- Filter rows to target market_ids using PyArrow predicate pushdown
- Process one row group at a time (~1M rows, ~50MB) for memory safety
- Cache filtered subsets as small per-market parquet files
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Generator

import fsspec
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger(__name__)

DOWNLOAD_BASE_URL = "https://r2.pmxt.dev"
COLUMNS = ["market_id", "update_type", "data", "timestamp_received"]


def file_url(hour: str) -> str:
    """Build download URL for a PMXT hourly file.

    Parameters
    ----------
    hour : str
        Hour identifier like "2026-03-09T14".
    """
    return f"{DOWNLOAD_BASE_URL}/polymarket_orderbook_{hour}.parquet"


def read_remote_filtered(
    hour: str,
    market_ids: set[str],
    batch_size: int = 50_000,
) -> Generator[list[dict], None, None]:
    """Stream rows from a remote PMXT parquet file, filtered by market_id.

    Reads one row group at a time via HTTP range requests. Never downloads
    the full file. Yields batches of row dicts for the transformer.

    Parameters
    ----------
    hour : str
        Hour identifier like "2026-03-09T14".
    market_ids : set[str]
        Set of condition_id hashes to filter on.
    batch_size : int
        Max rows per yielded batch.
    """
    url = file_url(hour)
    log.info("Streaming remote PMXT file: %s (filtering %d markets)", url, len(market_ids))

    fs = fsspec.filesystem("http")
    try:
        f = fs.open(url)
        pf = pq.ParquetFile(f)
    except Exception:
        log.exception("Failed to open remote PMXT file: %s", url)
        raise

    num_row_groups = pf.metadata.num_row_groups
    log.info("File has %d row groups", num_row_groups)

    for rg_idx in range(num_row_groups):
        table = pf.read_row_group(rg_idx, columns=COLUMNS)

        # Filter by market_id using PyArrow compute
        market_id_col = table.column("market_id")
        mask = pa.compute.is_in(market_id_col, value_set=pa.array(list(market_ids)))
        filtered = table.filter(mask)

        if filtered.num_rows == 0:
            continue

        log.debug(
            "Row group %d/%d: %d/%d rows match",
            rg_idx + 1,
            num_row_groups,
            filtered.num_rows,
            table.num_rows,
        )

        # Yield in batches
        rows = filtered.to_pylist()
        for i in range(0, len(rows), batch_size):
            yield rows[i : i + batch_size]

    f.close()


def read_local_filtered(
    path: Path,
    market_ids: set[str],
    batch_size: int = 50_000,
) -> Generator[list[dict], None, None]:
    """Read rows from a local parquet file, filtered by market_id.

    Parameters
    ----------
    path : Path
        Path to local parquet file.
    market_ids : set[str]
        Set of condition_id hashes to filter on.
    batch_size : int
        Max rows per yielded batch.
    """
    pf = pq.ParquetFile(str(path))

    for rg_idx in range(pf.metadata.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=COLUMNS)

        market_id_col = table.column("market_id")
        mask = pa.compute.is_in(market_id_col, value_set=pa.array(list(market_ids)))
        filtered = table.filter(mask)

        if filtered.num_rows == 0:
            continue

        rows = filtered.to_pylist()
        for i in range(0, len(rows), batch_size):
            yield rows[i : i + batch_size]


def cache_filtered_data(
    hour: str,
    market_ids: set[str],
    cache_dir: Path,
) -> dict[str, Path]:
    """Download and cache filtered data for specific markets.

    Streams the remote file, filters by market_id, and writes small
    per-market parquet files to cache_dir.

    Returns
    -------
    dict[str, Path]
        Map from market_id to cached file path.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached: dict[str, Path] = {}

    # Collect all rows per market
    market_rows: dict[str, list[dict]] = {mid: [] for mid in market_ids}

    for batch in read_remote_filtered(hour, market_ids):
        for row in batch:
            mid = row["market_id"]
            if mid in market_rows:
                market_rows[mid].append(row)

    for mid, rows in market_rows.items():
        if not rows:
            continue

        market_cache_dir = cache_dir / mid
        market_cache_dir.mkdir(parents=True, exist_ok=True)
        out_path = market_cache_dir / f"{hour}.parquet"

        table = pa.Table.from_pylist(rows)
        pq.write_table(table, str(out_path))

        cached[mid] = out_path
        log.info("Cached %d rows for market %s -> %s", len(rows), mid[:16], out_path)

    return cached
