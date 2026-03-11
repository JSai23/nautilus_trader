"""Tests for orchestrator config parsing, convergence detection, and integration loop.

Unit tests cover deterministic helpers. Integration test uses a mock LLM client
with real PMXT data and real backtest engine.
"""

import tempfile
from pathlib import Path

import pytest

from agents.orchestrator import (
    Orchestrator,
    OrchestratorConfig,
    _check_convergence,
    _dict_to_experiment_config,
    _format_tearsheet,
    _parse_configs_from_yaml,
    result_dir_name,
)
from conftest import discover_market_with_tokens
from runner.engine import ExperimentConfig
from runner.tearsheet import Tearsheet

TEST_HOUR = "2026-03-09T09"

# Canned YAML the mock strategist returns — one experiment config
STRATEGIST_YAML = """\
```yaml
mode: backtest
strategy:
  path: strategy.imbalance:ImbalanceStrategy
  params:
    imbalance_threshold: 0.3
    trade_size: 5.0
    take_profit: null
    stop_loss: null
data:
  hours:
    - "2026-03-09T09"
mlflow:
  experiment: test-integration
  parent_run: v1-mock
```
"""

# Canned analysis the mock analyst returns — converges immediately
ANALYST_RESPONSE = """\
## Analysis

The strategy executed correctly. Positions were opened based on imbalance signals.
PnL is negative due to bid-ask spread on thin binary option books.

### Recommendation
No further iterations needed for this test.

CONVERGED: true
"""


class _MockMessage:
    def __init__(self, text: str):
        self.text = text


class _MockResponse:
    def __init__(self, text: str):
        self.content = [_MockMessage(text)]


class _MockMessages:
    """Tracks calls: returns strategist YAML first, analyst text second."""

    def __init__(self):
        self._call_count = 0

    def create(self, **kwargs):
        self._call_count += 1
        # Odd calls = strategist, even calls = analyst
        if self._call_count % 2 == 1:
            return _MockResponse(STRATEGIST_YAML)
        return _MockResponse(ANALYST_RESPONSE)


class _MockClient:
    def __init__(self):
        self.messages = _MockMessages()


class TestParseConfigsFromYaml:
    def test_single_config(self):
        yaml_text = """
mode: backtest
strategy:
  path: strategy.imbalance:ImbalanceStrategy
  params:
    imbalance_threshold: 0.3
data:
  hours:
    - "2026-03-09T09"
"""
        configs = _parse_configs_from_yaml(yaml_text)
        assert len(configs) == 1
        assert configs[0]["mode"] == "backtest"

    def test_multi_config_with_separator(self):
        yaml_text = """
mode: backtest
strategy:
  path: strategy.imbalance:ImbalanceStrategy
  params:
    imbalance_threshold: 0.2
data:
  hours: ["2026-03-09T09"]
mlflow:
  experiment: test
  parent_run: v1
---
mode: backtest
strategy:
  path: strategy.imbalance:ImbalanceStrategy
  params:
    imbalance_threshold: 0.5
data:
  hours: ["2026-03-09T09"]
mlflow:
  experiment: test
  parent_run: v2
"""
        configs = _parse_configs_from_yaml(yaml_text)
        assert len(configs) == 2
        assert configs[0]["strategy"]["params"]["imbalance_threshold"] == 0.2
        assert configs[1]["strategy"]["params"]["imbalance_threshold"] == 0.5

    def test_with_markdown_fences(self):
        yaml_text = """
```yaml
mode: backtest
strategy:
  path: strategy.imbalance:ImbalanceStrategy
data:
  hours: ["2026-03-09T09"]
```
"""
        configs = _parse_configs_from_yaml(yaml_text)
        assert len(configs) == 1

    def test_empty_input(self):
        assert _parse_configs_from_yaml("") == []
        assert _parse_configs_from_yaml("no yaml here") == []


class TestDictToExperimentConfig:
    def test_full_config(self):
        raw = {
            "mode": "backtest",
            "strategy": {
                "path": "strategy.imbalance:ImbalanceStrategy",
                "params": {"imbalance_threshold": 0.4, "trade_size": 15.0},
            },
            "data": {"hours": ["2026-03-09T09"]},
            "mlflow": {
                "experiment": "test-exp",
                "parent_run": "v1-threshold-0.4",
                "tags": {"iteration": "1"},
            },
            "fees": "zero",
            "starting_balance": 5000.0,
        }
        cfg = _dict_to_experiment_config(raw)
        assert cfg.mode == "backtest"
        assert cfg.strategy_path == "strategy.imbalance:ImbalanceStrategy"
        assert cfg.strategy_params["imbalance_threshold"] == 0.4
        assert cfg.mlflow_experiment == "test-exp"
        assert cfg.mlflow_variant == "v1-threshold-0.4"
        assert cfg.starting_balance == 5000.0

    def test_minimal_config(self):
        raw = {"mode": "backtest"}
        cfg = _dict_to_experiment_config(raw)
        assert cfg.mode == "backtest"
        assert cfg.strategy_path == "strategy.imbalance:ImbalanceStrategy"
        assert cfg.starting_balance == 10_000.0


class TestCheckConvergence:
    def test_converged_true(self):
        assert _check_convergence("Analysis text...\nCONVERGED: true") is True

    def test_converged_false(self):
        assert _check_convergence("Analysis text...\nCONVERGED: false") is False

    def test_no_convergence_line(self):
        assert _check_convergence("Just analysis, no decision") is False

    def test_case_insensitive(self):
        assert _check_convergence("converged: True") is True
        assert _check_convergence("CONVERGED: TRUE") is True

    def test_with_surrounding_whitespace(self):
        assert _check_convergence("  CONVERGED:  true  ") is True


class TestFormatTearsheet:
    def test_formats_all_fields(self):
        ts = Tearsheet(total_pnl=42.0, num_trades=5, win_rate=0.6)
        formatted = _format_tearsheet(ts)
        assert "total_pnl: 42.0" in formatted
        assert "num_trades: 5" in formatted
        assert "win_rate: 0.6" in formatted


class TestResultDirName:
    def test_uses_variant_name(self):
        cfg = ExperimentConfig(mode="backtest", strategy_path="x", mlflow_variant="v1-test")
        assert result_dir_name(cfg, 0) == "v1-test"

    def test_falls_back_to_index(self):
        cfg = ExperimentConfig(mode="backtest", strategy_path="x")
        assert result_dir_name(cfg, 3) == "run_3"

    def test_sanitizes_slashes(self):
        cfg = ExperimentConfig(mode="backtest", strategy_path="x", mlflow_variant="a/b c")
        assert result_dir_name(cfg, 0) == "a_b_c"


class TestOrchestratorLoop:
    """Integration test: runs the full strategist → runner → analyst loop.

    Uses a mock LLM client (canned responses) with real PMXT data and
    real backtest engine. Verifies the orchestrator drives one complete
    iteration and returns structured results.
    """

    @pytest.mark.timeout(300)
    def test_one_iteration_with_mock_llm(self):
        market_info = discover_market_with_tokens(TEST_HOUR)

        with tempfile.TemporaryDirectory() as tmpdir:
            results_dir = Path(tmpdir) / "results"

            orch_config = OrchestratorConfig(
                max_iterations=1,
                num_experiments_per_iteration=1,
                data_hours=[TEST_HOUR],
                results_base_dir=results_dir,
            )

            client = _MockClient()
            orch = Orchestrator(
                client=client,
                config=orch_config,
                market_infos=[market_info],
            )

            history = orch.run()

            # Should have exactly 1 iteration (converged on first)
            assert len(history) == 1

            iteration = history[0]
            assert iteration.iteration == 0
            assert iteration.converged is True

            # Strategist produced configs
            assert len(iteration.configs) >= 1
            cfg = iteration.configs[0]
            assert cfg.mode == "backtest"
            assert cfg.strategy_path == "strategy.imbalance:ImbalanceStrategy"

            # Runner produced results
            assert len(iteration.run_results) >= 1
            result = iteration.run_results[0]
            assert result.success is True
            assert result.run_id  # non-empty
            assert result.elapsed_seconds > 0

            # Tearsheet has real data (strategy ran against real PMXT)
            ts = result.tearsheet
            assert ts.num_positions > 0  # real PMXT data reliably produces positions

            # Analyst produced analysis text
            assert "CONVERGED" in iteration.analysis

            # Analysis was saved to disk
            analysis_path = results_dir / "iteration_0" / "analysis.md"
            assert analysis_path.exists()
            assert "CONVERGED" in analysis_path.read_text()
