"""Tier 1 unit tests: pure functions, no engine, no network.

Covers gaps identified in TEST_PLAN.md Section 4.1:
- MarketMeta: slug_timestamp(), is_active_at(), label
- ExperimentConfig.from_yaml(): parsing + defaults
- _slug_label(): artifact labeling
- file_url(): PMXT URL format (moved from test_pmxt_reader)
"""

from pmxt.reader import file_url
from runner.artifacts import _slug_label
from runner.engine import ExperimentConfig
from strategy.base import MarketMeta


class TestMarketMeta:
    def test_slug_timestamp(self):
        meta = MarketMeta(
            slug="btc-updown-15m-1773435600",
            condition_id="0xabc123",
            token_id="tok1",
            outcome="Up",
            question="BTC Up or Down?",
            start_date="",
            end_date="",
        )
        assert meta.slug_timestamp() == 1773435600

    def test_slug_timestamp_no_match(self):
        meta = MarketMeta(
            slug="some-other-market",
            condition_id="0xabc123",
            token_id="tok1",
            outcome="Yes",
            question="Q?",
            start_date="",
            end_date="",
        )
        assert meta.slug_timestamp() is None

    def test_is_active_at_in_window(self):
        meta = MarketMeta(
            slug="btc-updown-15m-1773435600",
            condition_id="0xabc123",
            token_id="tok1",
            outcome="Up",
            question="Q?",
            start_date="",
            end_date="",
        )
        # Midpoint of 15-min window
        assert meta.is_active_at(1773435600 + 450) is True

    def test_is_active_at_before_window(self):
        meta = MarketMeta(
            slug="btc-updown-15m-1773435600",
            condition_id="0xabc123",
            token_id="tok1",
            outcome="Up",
            question="Q?",
            start_date="",
            end_date="",
        )
        assert meta.is_active_at(1773435599) is False

    def test_is_active_at_after_window(self):
        meta = MarketMeta(
            slug="btc-updown-15m-1773435600",
            condition_id="0xabc123",
            token_id="tok1",
            outcome="Up",
            question="Q?",
            start_date="",
            end_date="",
        )
        # Window is [start, start+900) — at boundary should be False
        assert meta.is_active_at(1773435600 + 900) is False

    def test_is_active_at_start_boundary(self):
        meta = MarketMeta(
            slug="btc-updown-15m-1773435600",
            condition_id="0xabc123",
            token_id="tok1",
            outcome="Up",
            question="Q?",
            start_date="",
            end_date="",
        )
        # At exact start should be True (inclusive)
        assert meta.is_active_at(1773435600) is True

    def test_is_active_at_no_slug_timestamp(self):
        meta = MarketMeta(
            slug="regular-market",
            condition_id="0xabc123",
            token_id="tok1",
            outcome="Yes",
            question="Q?",
            start_date="",
            end_date="",
        )
        # No timestamp in slug → always returns False
        assert meta.is_active_at(1773435600) is False

    def test_label(self):
        meta = MarketMeta(
            slug="btc-updown-15m",
            condition_id="0xabc123def456",
            token_id="tok1",
            outcome="Up",
            question="Q?",
            start_date="",
            end_date="",
        )
        assert meta.label == "btc-updown-15m (0xabc123de...)"


class TestSlugLabel:
    def test_with_market_infos(self):
        instrument_id = "0xabc123def456-token111.POLYMARKET"
        market_infos = [
            {
                "condition_id": "0xabc123def456",
                "slug": "btc-updown-15m",
                "tokens": [
                    {"token_id": "token111", "outcome": "Up"},
                    {"token_id": "token222", "outcome": "Down"},
                ],
            }
        ]
        label = _slug_label(instrument_id, market_infos)
        assert label == "btc-updown-15m-Up (0xabc123de...)"

    def test_without_market_infos(self):
        instrument_id = "0xabc123def456789a-token111.POLYMARKET"
        label = _slug_label(instrument_id, None)
        # _slug_label truncates condition_id to 16 chars when no market_infos
        assert label == "0xabc123def45678..."

    def test_no_matching_condition(self):
        instrument_id = "0xNONEXISTENT-token111.POLYMARKET"
        market_infos = [
            {
                "condition_id": "0xabc123def456",
                "slug": "btc-updown",
                "tokens": [],
            }
        ]
        label = _slug_label(instrument_id, market_infos)
        assert "0xNONEXISTENT" in label


class TestExperimentConfig:
    def test_from_yaml_parses_all_fields(self, tmp_path):
        yaml_content = """\
mode: "backtest"
strategy:
  path: "experiments.strategies.tick_always:TickAlways"
  params:
    trade_size: 5.0
    buy_after_ticks: 3
condition_ids:
  - "0xabc123"
  - "0xdef456"
data:
  hours:
    - "2026-03-09T09"
    - "2026-03-09T10"
fees: "zero"
starting_balance: 5000.0
mlflow:
  experiment: "test-exp"
  parent_run: "v1"
  tags:
    env: "test"
universe:
  slug_contains: "btc-updown"
  volume_min: 10000
  max_markets: 25
"""
        config_file = tmp_path / "test_config.yml"
        config_file.write_text(yaml_content)

        config = ExperimentConfig.from_yaml(config_file)

        assert config.mode == "backtest"
        assert config.strategy_path == "experiments.strategies.tick_always:TickAlways"
        assert config.strategy_params == {"trade_size": 5.0, "buy_after_ticks": 3}
        assert config.condition_ids == ["0xabc123", "0xdef456"]
        assert config.data_hours == ["2026-03-09T09", "2026-03-09T10"]
        assert config.fees == "zero"
        assert config.starting_balance == 5000.0
        assert config.mlflow_experiment == "test-exp"
        assert config.mlflow_variant == "v1"
        assert config.mlflow_tags == {"env": "test"}
        assert config.universe.slug_contains == "btc-updown"
        assert config.universe.volume_min == 10000
        assert config.universe.max_markets == 25

    def test_from_yaml_defaults(self, tmp_path):
        yaml_content = """\
mode: "backtest"
strategy:
  path: "experiments.strategies.tick_always:TickAlways"
"""
        config_file = tmp_path / "minimal.yml"
        config_file.write_text(yaml_content)

        config = ExperimentConfig.from_yaml(config_file)

        assert config.mode == "backtest"
        assert config.strategy_path == "experiments.strategies.tick_always:TickAlways"
        assert config.starting_balance == 10_000.0
        assert config.fees == "zero"
        assert config.condition_ids == []
        assert config.data_hours == []
        assert config.mlflow_experiment == ""
        assert config.universe.active is True
        assert config.universe.max_markets == 50


class TestFileUrl:
    def test_file_url_format(self):
        url = file_url("2026-03-09T14")
        assert url == "https://r2.pmxt.dev/polymarket_orderbook_2026-03-09T14.parquet"
