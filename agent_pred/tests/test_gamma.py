"""Tests for Gamma API client and market discovery pipeline.

Uses real Gamma API requests — no mocking.
"""

import pytest

from universe.gamma import (
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


class TestServerSideFilters:
    """Test that server-side filters are pushed to the Gamma API."""

    @pytest.mark.timeout(30)
    def test_end_date_min_filter(self):
        mf = MarketFilter(
            active=True,
            end_date_min="2027-01-01",
            max_markets=5,
        )
        results = fetch_all_markets(mf)
        assert len(results) > 0
        for market in results:
            end_date = market.get("endDate", "")
            assert end_date >= "2027-01-01", f"endDate {end_date} before min"

    @pytest.mark.timeout(30)
    def test_volume_num_min_filter(self):
        mf = MarketFilter(
            active=True,
            volume_num_min=100_000,
            max_markets=5,
        )
        results = fetch_all_markets(mf)
        assert len(results) > 0
        for market in results:
            vol = market.get("volumeNum", 0) or 0
            assert vol >= 100_000, f"Volume {vol} below min 100000"

    @pytest.mark.timeout(30)
    def test_order_by_volume_descending(self):
        mf = MarketFilter(
            active=True,
            order="volumeNum",
            ascending=False,
            max_markets=5,
        )
        results = fetch_all_markets(mf)
        assert len(results) > 0
        volumes = [m.get("volumeNum", 0) or 0 for m in results]
        assert volumes == sorted(volumes, reverse=True), "Results not sorted by volume desc"


class TestFetchAllMarkets:
    """Test paginated fetching with client-side filters."""

    @pytest.mark.timeout(60)
    def test_fetch_all_with_volume_filter(self):
        mf = MarketFilter(
            active=True,
            closed=False,
            volume_num_min=10000,
            max_markets=5,
        )
        results = fetch_all_markets(mf)
        assert len(results) <= 5
        for market in results:
            vol = market.get("volumeNum", 0) or 0
            assert vol >= 10000, f"Volume {vol} below volume_num_min 10000"

    @pytest.mark.timeout(60)
    def test_fetch_all_respects_max_markets(self):
        mf = MarketFilter(max_markets=3)
        results = fetch_all_markets(mf)
        assert len(results) <= 3

    @pytest.mark.timeout(60)
    def test_slug_contains_client_filter(self):
        """slug_contains is client-side; verify it filters results."""
        mf = MarketFilter(
            active=True,
            slug_contains="will",
            max_markets=5,
        )
        results = fetch_all_markets(mf)
        assert len(results) > 0
        for market in results:
            slug = market.get("slug", "")
            assert "will" in slug.lower(), f"Slug '{slug}' doesn't contain 'will'"


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


class TestDiscoverMarkets:
    """Test end-to-end discovery pipeline with real Gamma API."""

    @pytest.mark.timeout(60)
    def test_discover_returns_metadata(self):
        mf = MarketFilter(active=True, closed=False, max_markets=3)
        results = discover_markets(mf)

        assert len(results) > 0
        assert len(results) <= 3

        for m in results:
            assert "condition_id" in m
            assert "question" in m
            assert "tokens" in m
            assert len(m["tokens"]) >= 2
            outcomes = {t["outcome"] for t in m["tokens"]}
            assert "Yes" in outcomes or len(outcomes) >= 2

    @pytest.mark.timeout(60)
    def test_discover_metadata_is_real(self):
        """Verify metadata has real data, not fabricated."""
        mf = MarketFilter(
            active=True,
            closed=False,
            volume_num_min=1000,
            max_markets=2,
        )
        results = discover_markets(mf)
        assert len(results) > 0

        for m in results:
            assert not m["question"].startswith("Discovered market")
            assert m["minimum_tick_size"] in ("0.001", "0.01", "0.1", "1")
            assert m.get("volume", 0) > 0

    @pytest.mark.timeout(60)
    def test_discover_with_slug_filter(self):
        mf = MarketFilter(
            active=True,
            slug_contains="will",
            max_markets=3,
        )
        results = discover_markets(mf)
        assert len(results) > 0
        for m in results:
            assert "will" in m["slug"].lower()


# Known condition_id from momentum_drift.yml for CLOB API tests
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
