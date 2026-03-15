"""Shared test fixtures for agent_pred tests."""

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import fsspec
import pytest
import pyarrow.parquet as pq

from pmxt.reader import file_url
from universe.gamma import fetch_market_clob
from universe.instruments import build_instrument_maps

log = logging.getLogger(__name__)

TEST_HOUR = "2026-03-09T09"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Tier 2 fixtures — bundled data, no network
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def bundled_parquet_path():
    """Path to the bundled test parquet file (committed to repo)."""
    path = FIXTURES_DIR / "test_hour.parquet"
    assert path.exists(), f"Bundled test data missing: {path}"
    return path


@pytest.fixture(scope="session")
def bundled_market_infos():
    """Hardcoded market metadata for bundled test data."""
    with open(FIXTURES_DIR / "market_metadata.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def bundled_instruments(bundled_market_infos):
    """Instruments + IDs + market_ids built from bundled market metadata."""
    return build_instrument_maps(bundled_market_infos)


# ---------------------------------------------------------------------------
# Tier 3 fixtures — network required
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _pmxt_local_path():
    """Session-scoped: download the PMXT parquet once to a temp file."""
    url = file_url(TEST_HOUR)
    log.info("Downloading PMXT parquet: %s", url)
    fs = fsspec.filesystem("http")
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
        tmp_path = tmp.name
        with fs.open(url, "rb") as remote:
            tmp.write(remote.read())
    log.info("PMXT parquet cached locally: %s", tmp_path)
    yield Path(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)


@pytest.fixture(scope="session")
def pmxt_local_path(_pmxt_local_path):
    """Expose the local parquet path for test engine data reads."""
    return _pmxt_local_path


@pytest.fixture(scope="session")
def market_with_tokens(_pmxt_local_path):
    """Session-scoped: discover a market once, reuse across all tests."""
    pf = pq.ParquetFile(str(_pmxt_local_path))
    return _discover_market_with_tokens_from_pf(pf, TEST_HOUR)


@pytest.fixture(scope="session")
def volatile_market(_pmxt_local_path):
    """Session-scoped: discover a volatile market once, reuse across all tests."""
    pf = pq.ParquetFile(str(_pmxt_local_path))
    return _discover_volatile_market_from_pf(pf, TEST_HOUR)


def _adapt_metadata_for_testing(metadata: dict, hour: str) -> dict:
    """Adapt real API metadata for test use."""
    metadata = dict(metadata)
    end_date = metadata.get("end_date_iso", "")
    if end_date:
        try:
            hour_dt = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_dt <= hour_dt:
                extended = hour_dt.replace(hour=23, minute=59, second=59)
                metadata["end_date_iso"] = extended.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError):
            pass
    metadata["minimum_order_size"] = "1"
    return metadata


def _resolve_test_metadata(condition_id: str, tokens: set[str], hour: str) -> dict:
    """Resolve market metadata for tests: CLOB API -> fabricated fallback."""
    clob = fetch_market_clob(condition_id)
    if clob:
        return _adapt_metadata_for_testing(clob, hour)
    token_list = []
    for i, tid in enumerate(sorted(tokens)):
        outcome = "Yes" if i == 0 else "No"
        token_list.append({"token_id": tid, "outcome": outcome})
    return {
        "condition_id": condition_id,
        "question": f"Test market {condition_id[:16]}",
        "minimum_tick_size": "0.01",
        "minimum_order_size": "1",
        "end_date_iso": "2027-12-31T00:00:00Z",
        "maker_base_fee": "0",
        "taker_base_fee": "0",
        "tokens": token_list,
    }


def _discover_market_with_tokens_from_pf(pf: pq.ParquetFile, hour: str) -> dict:
    """Discover a market from a pre-loaded ParquetFile."""
    table = pf.read_row_group(0, columns=["market_id", "update_type", "data"])
    rows = table.to_pylist()
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
    best_market = max(market_rows, key=lambda mid: len(market_rows[mid]))
    tokens = market_tokens[best_market]
    return _resolve_test_metadata(best_market, tokens, hour)


def _discover_volatile_market_from_pf(pf: pq.ParquetFile, hour: str) -> dict:
    """Discover a volatile market from a pre-loaded ParquetFile."""
    token_stats: dict[str, dict] = {}
    market_tokens: dict[str, set[str]] = {}
    for rg_idx in range(pf.metadata.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=["market_id", "data"])
        for row in table.to_pylist():
            data = json.loads(row["data"])
            token_id = str(data.get("token_id", ""))
            if not token_id:
                continue
            best_bid = data.get("best_bid")
            best_ask = data.get("best_ask")
            if best_bid is None or best_ask is None:
                continue
            bid = float(best_bid)
            ask = float(best_ask)
            if bid <= 0 or ask <= 0:
                continue
            mid = row["market_id"]
            if mid not in market_tokens:
                market_tokens[mid] = set()
            market_tokens[mid].add(token_id)
            if token_id not in token_stats:
                token_stats[token_id] = {"min_ask": ask, "max_bid": bid, "market_id": mid}
            else:
                s = token_stats[token_id]
                s["min_ask"] = min(s["min_ask"], ask)
                s["max_bid"] = max(s["max_bid"], bid)
    best_mid = None
    best_gap = 0.0
    for tid, stats in token_stats.items():
        mid = stats["market_id"]
        if len(market_tokens.get(mid, set())) < 2:
            continue
        gap = stats["max_bid"] - stats["min_ask"]
        if gap > best_gap:
            best_gap = gap
            best_mid = mid
    if best_mid is None:
        raise RuntimeError("No volatile market found in data")
    tokens = market_tokens[best_mid]
    return _resolve_test_metadata(best_mid, tokens, hour)


def discover_market_with_tokens(hour: str) -> dict:
    """Discover a market from PMXT data and extract token_ids (HTTP download)."""
    url = file_url(hour)
    fs = fsspec.filesystem("http")
    f = fs.open(url)
    pf = pq.ParquetFile(f)
    result = _discover_market_with_tokens_from_pf(pf, hour)
    f.close()
    return result
