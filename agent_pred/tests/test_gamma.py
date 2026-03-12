"""Tests for Gamma API client and market discovery pipeline.

Uses real Gamma API requests — no mocking.
"""

import tempfile
from pathlib import Path

import pytest

from universe.gamma import (
    GammaMarketCache,
    MarketFilter,
    clob_to_metadata,
    discover_markets,
    fetch_all_markets,
    fetch_market_clob,
    fetch_markets,
    gamma_to_metadata,
)


class TestFetchMarkets:
    """Test raw Gamma API fetching with real requests."""

    @pytest.mark.timeout(30)
    def test_fetch_returns_list(self):
        results = fetch_markets(limit=3)
        assert isinstance(results, list)
        assert len(results) > 0

    @pytest.mark.timeout(30)
    def test_fetch_has_required_fields(self):
        results = fetch_markets(limit=1)
        market = results[0]
        assert "conditionId" in market
        assert "question" in market
        assert "outcomes" in market
        assert "clobTokenIds" in market

    @pytest.mark.timeout(30)
    def test_fetch_with_active_filter(self):
        mf = MarketFilter(active=True, closed=False, max_markets=5)
        results = fetch_markets(filter=mf, limit=5)
        assert len(results) > 0

    @pytest.mark.timeout(30)
    def test_fetch_respects_limit(self):
        results = fetch_markets(limit=2)
        assert len(results) <= 2


class TestFetchAllMarkets:
    """Test paginated fetching with client-side filters."""

    @pytest.mark.timeout(60)
    def test_fetch_all_with_volume_filter(self):
        mf = MarketFilter(
            active=True,
            closed=False,
            min_volume=10000,
            max_markets=5,
        )
        results = fetch_all_markets(mf)
        assert len(results) <= 5
        for market in results:
            vol = market.get("volumeNum", 0) or 0
            assert vol >= 10000, f"Volume {vol} below min_volume 10000"

    @pytest.mark.timeout(60)
    def test_fetch_all_respects_max_markets(self):
        mf = MarketFilter(max_markets=3)
        results = fetch_all_markets(mf)
        assert len(results) <= 3


class TestGammaToMetadata:
    """Test conversion from Gamma API format to internal metadata."""

    def test_basic_conversion(self):
        raw = {
            "conditionId": "0xabc123",
            "question": "Will BTC hit 100K?",
            "slug": "btc-100k",
            "category": "Crypto",
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["token_yes_123", "token_no_456"]',
            "orderPriceMinTickSize": 0.01,
            "orderMinSize": 5,
            "endDate": "2027-12-31T00:00:00Z",
            "volumeNum": 50000,
            "active": True,
            "closed": False,
            "feesEnabled": False,
        }

        metadata = gamma_to_metadata(raw)

        assert metadata["condition_id"] == "0xabc123"
        assert metadata["question"] == "Will BTC hit 100K?"
        assert metadata["slug"] == "btc-100k"
        assert metadata["minimum_tick_size"] == "0.01"
        assert metadata["minimum_order_size"] == "5"
        assert len(metadata["tokens"]) == 2

    def test_correct_yes_no_mapping(self):
        """The critical fix: outcomes[i] maps to clobTokenIds[i], not lexicographic."""
        raw = {
            "conditionId": "0xtest",
            "question": "Test",
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["zzz_token_first", "aaa_token_second"]',
            "endDate": "",
            "volumeNum": 0,
            "active": True,
        }

        metadata = gamma_to_metadata(raw)
        tokens = metadata["tokens"]

        # zzz_token_first is Yes (position 0), aaa_token_second is No (position 1)
        # Lexicographic sort would incorrectly assign aaa=Yes, zzz=No
        assert tokens[0]["token_id"] == "zzz_token_first"
        assert tokens[0]["outcome"] == "Yes"
        assert tokens[1]["token_id"] == "aaa_token_second"
        assert tokens[1]["outcome"] == "No"

    def test_handles_list_outcomes(self):
        """Gamma API sometimes returns lists instead of JSON strings."""
        raw = {
            "conditionId": "0xtest",
            "question": "Test",
            "outcomes": ["Yes", "No"],
            "clobTokenIds": ["token_a", "token_b"],
            "endDate": "",
            "volumeNum": 0,
            "active": True,
        }

        metadata = gamma_to_metadata(raw)
        assert metadata["tokens"][0]["outcome"] == "Yes"
        assert metadata["tokens"][0]["token_id"] == "token_a"


class TestGammaMarketCache:
    """Test the persistent JSON cache."""

    def test_put_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))

            metadata = {
                "condition_id": "0xabc",
                "question": "Test",
                "tokens": [{"token_id": "t1", "outcome": "Yes"}],
            }
            cache.put(metadata)

            result = cache.get("0xabc")
            assert result is not None
            assert result["condition_id"] == "0xabc"
            assert result["tokens"][0]["outcome"] == "Yes"

    def test_has(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            assert not cache.has("0xmissing")

            cache.put({"condition_id": "0xfound", "tokens": []})
            assert cache.has("0xfound")

    def test_list_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            cache.put({"condition_id": "0x1", "tokens": []})
            cache.put({"condition_id": "0x2", "tokens": []})

            all_items = cache.list_all()
            assert len(all_items) == 2
            ids = {m["condition_id"] for m in all_items}
            assert ids == {"0x1", "0x2"}

    def test_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            assert cache.count() == 0
            cache.put({"condition_id": "0x1", "tokens": []})
            assert cache.count() == 1

    def test_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            cache.put({"condition_id": "0x1", "question": "old", "tokens": []})
            cache.put({"condition_id": "0x1", "question": "new", "tokens": []})

            result = cache.get("0x1")
            assert result["question"] == "new"
            assert cache.count() == 1


class TestDiscoverMarkets:
    """Test end-to-end discovery pipeline with real Gamma API."""

    @pytest.mark.timeout(60)
    def test_discover_caches_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            mf = MarketFilter(active=True, closed=False, max_markets=3)

            results = discover_markets(mf, cache)

            assert len(results) > 0
            assert len(results) <= 3

            # Verify cached
            for m in results:
                assert cache.has(m["condition_id"])

            # Verify metadata format
            for m in results:
                assert "condition_id" in m
                assert "question" in m
                assert "tokens" in m
                assert len(m["tokens"]) >= 2
                # Verify correct outcome assignment
                outcomes = {t["outcome"] for t in m["tokens"]}
                assert "Yes" in outcomes
                assert "No" in outcomes

    @pytest.mark.timeout(60)
    def test_discover_uses_cache_when_not_refreshing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            mf = MarketFilter(active=True, closed=False, max_markets=2)

            # First discovery
            results1 = discover_markets(mf, cache)
            assert len(results1) > 0

            # Modify a cached entry
            cid = results1[0]["condition_id"]
            modified = cache.get(cid)
            modified["question"] = "MODIFIED_BY_TEST"
            cache.put(modified)

            # Second discovery without refresh should use cache
            results2 = discover_markets(mf, cache, refresh=False)
            for m in results2:
                if m["condition_id"] == cid:
                    assert m["question"] == "MODIFIED_BY_TEST"
                    break

    @pytest.mark.timeout(60)
    def test_discover_metadata_matches_api(self):
        """Verify that cached metadata has real data, not fabricated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            mf = MarketFilter(active=True, closed=False, min_volume=1000, max_markets=2)

            results = discover_markets(mf, cache, refresh=True)
            assert len(results) > 0

            for m in results:
                # Real question, not "Discovered market 0x..."
                assert not m["question"].startswith("Discovered market")
                # Real tick size from API
                assert m["minimum_tick_size"] in ("0.001", "0.01", "0.1", "1")
                # Has volume from API
                assert m.get("volume", 0) > 0


# Known condition_id from timer_momentum.yml for CLOB API tests
_KNOWN_CID = "0x884c293e9eeeda6065f05e75fca16fd4d67b5fb911ee854b1bed58c785d3b33d"


class TestFetchMarketClob:
    """Test CLOB API direct lookup with real requests."""

    @pytest.mark.timeout(30)
    def test_fetch_known_market(self):
        result = fetch_market_clob(_KNOWN_CID)
        assert result is not None
        assert result["condition_id"] == _KNOWN_CID
        assert result["question"] == "Counter-Strike: 100 Thieves vs FOKUS - Map 1 Winner"
        assert result["minimum_tick_size"] == "0.001"
        assert result["minimum_order_size"] == "5"
        assert len(result["tokens"]) == 2

    @pytest.mark.timeout(30)
    def test_fetch_returns_correct_token_outcomes(self):
        result = fetch_market_clob(_KNOWN_CID)
        outcomes = {t["outcome"] for t in result["tokens"]}
        assert "100 Thieves" in outcomes
        assert "FOKUS" in outcomes

    @pytest.mark.timeout(30)
    def test_fetch_nonexistent_returns_none(self):
        result = fetch_market_clob("0xdeadbeef_nonexistent_market_id")
        assert result is None

    @pytest.mark.timeout(30)
    def test_fetch_has_end_date(self):
        result = fetch_market_clob(_KNOWN_CID)
        assert result["end_date_iso"] != ""
        assert "2027-12-31" not in result["end_date_iso"]  # Not fabricated


class TestClobToMetadata:
    """Test CLOB API response normalization."""

    def test_normalizes_numeric_fields_to_strings(self):
        clob = {
            "condition_id": "0xabc",
            "question": "Test?",
            "market_slug": "test-slug",
            "minimum_tick_size": 0.001,
            "minimum_order_size": 5,
            "end_date_iso": "2026-03-09T00:00:00Z",
            "maker_base_fee": 0,
            "taker_base_fee": 0,
            "tokens": [
                {"token_id": "123", "outcome": "Yes", "price": 0.6, "winner": False},
                {"token_id": "456", "outcome": "No", "price": 0.4, "winner": False},
            ],
            "active": True,
            "closed": False,
        }
        metadata = clob_to_metadata(clob)
        assert metadata["minimum_tick_size"] == "0.001"
        assert metadata["minimum_order_size"] == "5"
        assert metadata["maker_base_fee"] == "0"
        assert metadata["taker_base_fee"] == "0"
        assert metadata["slug"] == "test-slug"

    def test_strips_extra_clob_fields(self):
        """Only our internal fields survive, not CLOB extras like price/winner."""
        clob = {
            "condition_id": "0xabc",
            "question": "Test?",
            "tokens": [{"token_id": "123", "outcome": "Yes", "price": 0.6, "winner": True}],
        }
        metadata = clob_to_metadata(clob)
        token = metadata["tokens"][0]
        assert "price" not in token
        assert "winner" not in token
        assert token["token_id"] == "123"
        assert token["outcome"] == "Yes"


class TestCachePurge:
    """Test cache purge and delete operations."""

    def test_delete_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            cache.put({"condition_id": "0x1", "question": "Real", "tokens": []})
            assert cache.has("0x1")
            assert cache.delete("0x1")
            assert not cache.has("0x1")

    def test_delete_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            assert not cache.delete("0xmissing")

    def test_purge_fabricated_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = GammaMarketCache(Path(tmpdir))
            # Fabricated entries (should be purged)
            cache.put({"condition_id": "0xfab1", "question": "Discovered market 0xfab1", "tokens": []})
            cache.put({"condition_id": "0xfab2", "question": "Test market 0xfab2", "tokens": []})
            cache.put({"condition_id": "0xfab3", "question": "Volatile market 0xfab3", "tokens": []})
            # Real entries (should survive)
            cache.put({"condition_id": "0xreal1", "question": "Will BTC hit 100K?", "tokens": []})
            cache.put({"condition_id": "0xreal2", "question": "CS2: Team A vs Team B", "tokens": []})

            assert cache.count() == 5
            purged = cache.purge_fabricated()
            assert purged == 3
            assert cache.count() == 2
            assert cache.has("0xreal1")
            assert cache.has("0xreal2")
            assert not cache.has("0xfab1")
