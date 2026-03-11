"""Tests for universe config parsing and instrument building."""

import json
import tempfile
from pathlib import Path

from nautilus_trader.model.instruments import BinaryOption

from universe.config import UniverseConfig
from universe.instruments import build_instrument_maps, build_instruments_from_metadata
from universe.resolver import UniverseResolver

MARKET_INFO = {
    "condition_id": "0xabc123def456",
    "question": "Will BTC be above 100K?",
    "minimum_tick_size": "0.01",
    "minimum_order_size": "5",
    "end_date_iso": "2027-12-31T00:00:00Z",
    "maker_base_fee": "0",
    "taker_base_fee": "0",
    "tokens": [
        {"token_id": "111222333", "outcome": "Yes"},
        {"token_id": "444555666", "outcome": "No"},
    ],
}


class TestUniverseConfig:
    def test_from_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("""
universe_id: "test-universe"
description: "Test universe"
selection:
  slugs:
    - "bitcoin-*"
  tags: ["crypto"]
  condition_ids:
    - "0xabc123"
filters:
  active: true
  min_volume: 10000
period:
  start: "2026-03-01"
  end: "2026-03-31"
""")
            f.flush()

            config = UniverseConfig.from_yaml(Path(f.name))

        assert config.universe_id == "test-universe"
        assert "bitcoin-*" in config.selection.slugs
        assert "crypto" in config.selection.tags
        assert "0xabc123" in config.selection.condition_ids
        assert config.filters.active is True
        assert config.filters.min_volume == 10000
        assert config.period.start == "2026-03-01"


class TestInstrumentBuilding:
    def test_build_from_metadata(self):
        results = build_instruments_from_metadata(MARKET_INFO)
        assert len(results) == 2

        inst_yes, tid_yes = results[0]
        inst_no, tid_no = results[1]

        assert isinstance(inst_yes, BinaryOption)
        assert isinstance(inst_no, BinaryOption)
        assert inst_yes.outcome == "Yes"
        assert inst_no.outcome == "No"
        assert tid_yes == "111222333"
        assert tid_no == "444555666"

    def test_build_instrument_maps(self):
        instruments, instrument_ids, market_ids = build_instrument_maps([MARKET_INFO])

        assert len(instruments) == 2
        assert len(instrument_ids) == 2
        assert "0xabc123def456" in market_ids
        assert "111222333" in instruments
        assert "444555666" in instruments


class TestUniverseResolver:
    def test_resolve_from_condition_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            resolver = UniverseResolver(cache_dir)

            # Save market metadata
            resolver.save_metadata("0xabc123def456", MARKET_INFO)

            # Resolve
            instruments, instrument_ids, market_ids = resolver.resolve_from_condition_ids(
                ["0xabc123def456"]
            )

            assert len(instruments) == 2
            assert "0xabc123def456" in market_ids

    def test_list_cached_markets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            resolver = UniverseResolver(cache_dir)

            resolver.save_metadata("0xabc123def456", MARKET_INFO)
            markets = resolver.list_cached_markets()

            assert len(markets) == 1
            assert markets[0]["condition_id"] == "0xabc123def456"
