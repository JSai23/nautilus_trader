"""Tests for PMXT reader — real HTTP range requests against PMXT archive.

These tests hit the real PMXT endpoint. They use a single row group
from a recent hour to minimize data transfer.
"""

import json
import tempfile
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from pmxt.reader import cache_filtered_data, file_url, read_remote_filtered


# Use a known recent hour — if this fails, the hour may no longer exist
TEST_HOUR = "2026-03-09T09"


class TestFileUrl:
    def test_url_format(self):
        url = file_url("2026-03-09T14")
        assert url == "https://r2.pmxt.dev/polymarket_orderbook_2026-03-09T14.parquet"


class TestReadRemoteFiltered:
    @pytest.mark.timeout(120)
    def test_can_stream_and_filter(self):
        """Stream one row group from PMXT, filter to a specific market."""
        # First, discover a market_id from the data
        # Read a small batch unfiltered to find market_ids
        import fsspec

        url = file_url(TEST_HOUR)
        fs = fsspec.filesystem("http")
        f = fs.open(url)
        pf = pq.ParquetFile(f)

        # Read just market_id column from first row group to find a valid market
        table = pf.read_row_group(0, columns=["market_id"])
        market_ids_in_data = set(table.column("market_id").to_pylist()[:100])
        f.close()

        assert len(market_ids_in_data) > 0, "No market_ids found in PMXT data"

        # Pick one market and filter
        target_market = next(iter(market_ids_in_data))
        batches = list(read_remote_filtered(TEST_HOUR, {target_market}))

        # Should get at least some rows
        total_rows = sum(len(b) for b in batches)
        assert total_rows > 0, f"No rows found for market {target_market[:16]}"

        # Verify all rows have correct market_id
        for batch in batches:
            for row in batch:
                assert row["market_id"] == target_market

        # Verify row structure
        first_row = batches[0][0]
        assert "market_id" in first_row
        assert "update_type" in first_row
        assert "data" in first_row
        assert first_row["update_type"] in ("price_change", "book_snapshot")

        # Verify JSON data is parseable
        data = json.loads(first_row["data"])
        assert "token_id" in data
        assert "timestamp" in data

    @pytest.mark.timeout(120)
    def test_nonexistent_market_yields_nothing(self):
        """Filtering for a market not in the data yields no rows."""
        fake_market = "0x" + "0" * 64
        batches = list(read_remote_filtered(TEST_HOUR, {fake_market}))
        total_rows = sum(len(b) for b in batches)
        assert total_rows == 0


class TestCacheFilteredData:
    @pytest.mark.timeout(180)
    def test_cache_creates_per_market_parquet(self):
        """Cache filtered data creates small per-market parquet files."""
        import fsspec

        # Discover a market_id
        url = file_url(TEST_HOUR)
        fs = fsspec.filesystem("http")
        f = fs.open(url)
        pf = pq.ParquetFile(f)
        table = pf.read_row_group(0, columns=["market_id"])
        market_ids = set(table.column("market_id").to_pylist()[:50])
        target_market = next(iter(market_ids))
        f.close()

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cached = cache_filtered_data(TEST_HOUR, {target_market}, cache_dir)

            assert target_market in cached
            cached_path = cached[target_market]
            assert cached_path.exists()
            assert cached_path.suffix == ".parquet"

            # Verify the cached file is valid parquet with correct data
            cached_table = pq.read_table(str(cached_path))
            assert cached_table.num_rows > 0
            for mid in cached_table.column("market_id").to_pylist():
                assert mid == target_market
