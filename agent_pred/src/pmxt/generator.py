"""PMXT data generator for BacktestEngine.add_data_iterator().

Yields list[Data] batches from PMXT parquet files, streaming one hour
at a time, one row group at a time. Memory-safe by design.

Usage:
    gen = pmxt_data_generator(market_ids, hours, instruments, instrument_ids, cache_dir)
    engine.add_data_iterator("pmxt", gen)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Generator

from pmxt.index import PMXTIndex
from pmxt.reader import read_local_filtered, read_remote_filtered
from pmxt.transformer import transform_row

if TYPE_CHECKING:
    from nautilus_trader.model.data import Data
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.instruments import BinaryOption

log = logging.getLogger(__name__)


def pmxt_data_generator(
    market_ids: set[str],
    hours: list[str],
    instruments: dict[str, BinaryOption],
    instrument_ids: dict[str, InstrumentId],
    cache_dir: Path | None = None,
    index: PMXTIndex | None = None,
) -> Generator[list[Data], None, None]:
    """Generate NautilusTrader data from PMXT parquet files.

    Processes hours in order, yielding sorted batches of OrderBookDelta
    and OrderBookDeltas objects suitable for BacktestEngine.add_data_iterator().

    Parameters
    ----------
    market_ids : set[str]
        Condition ID hashes to filter on.
    hours : list[str]
        Hour identifiers in chronological order (e.g., ["2026-03-09T14", "2026-03-09T15"]).
    instruments : dict[str, BinaryOption]
        Map from token_id to BinaryOption instrument.
    instrument_ids : dict[str, InstrumentId]
        Map from token_id to InstrumentId.
    cache_dir : Path | None
        Local cache directory. If None, always streams from remote.
    index : PMXTIndex | None
        Data index for cache lookups.
    """
    for hour in hours:
        log.info("Processing hour: %s", hour)

        # Determine data source: cache or remote
        use_cache = False
        if cache_dir and index:
            # Check if ALL requested markets are cached for this hour
            all_cached = all(index.has_data(mid, hour) for mid in market_ids)
            if all_cached:
                use_cache = True

        if use_cache:
            log.info("Reading from cache for hour %s", hour)
            batch_gen = _read_cached_markets(cache_dir, market_ids, hour, index)
        else:
            log.info("Streaming from remote for hour %s", hour)
            batch_gen = read_remote_filtered(hour, market_ids)

        for batch in batch_gen:
            transformed: list[Data] = []
            for row in batch:
                result = transform_row(row, instruments, instrument_ids)
                if result is not None:
                    transformed.append(result)

            if transformed:
                # Sort by ts_init for BacktestEngine
                transformed.sort(key=lambda d: d.ts_init)
                yield transformed


def _read_cached_markets(
    cache_dir: Path,
    market_ids: set[str],
    hour: str,
    index: PMXTIndex,
) -> Generator[list[dict], None, None]:
    """Read cached per-market parquet files and yield merged batches."""
    for mid in market_ids:
        cached_path = index.get_cached_path(mid, hour, cache_dir)
        if cached_path is None:
            continue
        yield from read_local_filtered(cached_path, {mid})
