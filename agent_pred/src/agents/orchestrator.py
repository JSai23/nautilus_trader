"""Agentic orchestrator — strategist -> runner -> analyst loop.

Drives the experiment cycle:
1. Strategist (LLM) generates experiment config YAML from context
2. Runner executes each config deterministically via run_backtest()
3. Analyst (LLM) reads tearsheets + positions, produces insights
4. Loop until convergence or max iterations
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from runner.engine import ExperimentConfig, RunResult, run_backtest
from runner.tearsheet import Tearsheet
from universe.instruments import load_market_metadata

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class IterationResult:
    iteration: int
    configs: list[ExperimentConfig]
    run_results: list[RunResult]
    analysis: str
    converged: bool


@dataclass
class OrchestratorConfig:
    max_iterations: int = 5
    num_experiments_per_iteration: int = 3
    data_hours: list[str] = field(default_factory=lambda: ["2026-03-09T09"])
    metadata_dir: Path = field(default_factory=lambda: Path("data/markets"))
    results_base_dir: Path = field(default_factory=lambda: Path("results"))
    mlflow_tracking_uri: str | None = None
    model: str = "claude-sonnet-4-20250514"


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text()


def _format_tearsheet(ts: Tearsheet) -> str:
    d = ts.to_dict()
    lines = [f"  {k}: {v}" for k, v in d.items()]
    return "\n".join(lines)


def _format_run_results(results: list[RunResult]) -> str:
    sections = []
    for r in results:
        status = "SUCCESS" if r.success else f"FAILED: {r.error}"
        section = (
            f"### Run {r.run_id} [{status}]\n"
            f"Strategy: {r.config.strategy_path}\n"
            f"Params: {json.dumps(r.config.strategy_params, default=str)}\n"
            f"Hours: {r.config.data_hours}\n"
            f"Elapsed: {r.elapsed_seconds:.1f}s\n\n"
            f"Tearsheet:\n{_format_tearsheet(r.tearsheet)}\n"
        )
        if not r.positions_df.empty:
            section += f"\nPositions: {len(r.positions_df)} total\n"
        sections.append(section)
    return "\n---\n".join(sections)


def _call_llm(
    client: Any,
    system_prompt: str,
    user_message: str,
    model: str,
) -> str:
    """Call the Anthropic API and return the text response."""
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


def _parse_configs_from_yaml(text: str) -> list[dict]:
    """Extract YAML config dicts from LLM output.

    The LLM outputs YAML blocks separated by '---'. Some may be wrapped
    in ```yaml fences. We parse each block independently.
    """
    # Strip markdown fences
    cleaned = text.replace("```yaml", "").replace("```", "")

    configs = []
    for doc in yaml.safe_load_all(cleaned):
        if doc and isinstance(doc, dict) and "mode" in doc:
            configs.append(doc)

    return configs


def _dict_to_experiment_config(raw: dict) -> ExperimentConfig:
    """Convert a raw YAML dict to ExperimentConfig."""
    strategy = raw.get("strategy", {})
    data = raw.get("data", {})
    mlflow_cfg = raw.get("mlflow", {})

    return ExperimentConfig(
        mode=raw.get("mode", "backtest"),
        strategy_path=strategy.get("path", "strategy.imbalance:ImbalanceStrategy"),
        strategy_params=strategy.get("params", {}),
        condition_ids=raw.get("condition_ids", []),
        data_hours=data.get("hours", []),
        fees=raw.get("fees", "zero"),
        mlflow_experiment=mlflow_cfg.get("experiment", ""),
        mlflow_variant=mlflow_cfg.get("parent_run", ""),
        mlflow_tags=mlflow_cfg.get("tags", {}),
        starting_balance=raw.get("starting_balance", 10_000.0),
    )


def _check_convergence(analysis_text: str) -> bool:
    """Check if the analyst declared convergence."""
    for line in analysis_text.strip().splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("converged:"):
            val = stripped.split(":", 1)[1].strip()
            return val == "true"
    return False


class Orchestrator:
    """Drives the strategist -> runner -> analyst loop."""

    def __init__(
        self,
        client: Any,
        config: OrchestratorConfig,
        market_infos: list[dict[str, Any]] | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._market_infos = market_infos or self._load_all_markets()
        self._history: list[IterationResult] = []
        self._memory: list[str] = []

    def _load_all_markets(self) -> list[dict[str, Any]]:
        """Load all cached market metadata."""
        markets = []
        for f in sorted(self._config.metadata_dir.glob("*.json")):
            markets.append(load_market_metadata(f))
        if not markets:
            raise FileNotFoundError(
                f"No market metadata in {self._config.metadata_dir}. "
                "Run: uv run python scripts/run_backtest.py configs/example_backtest.yml --discover"
            )
        return markets

    def run(self) -> list[IterationResult]:
        """Execute the full orchestrator loop. Returns history of all iterations."""
        for i in range(self._config.max_iterations):
            log.info("=== Iteration %d/%d ===", i + 1, self._config.max_iterations)

            # 1. Strategist generates configs
            configs = self._run_strategist(iteration=i)
            if not configs:
                log.warning("Strategist produced no valid configs — stopping")
                break

            # 2. Runner executes all configs
            results = self._run_experiments(configs)

            # 3. Analyst evaluates results
            analysis, converged = self._run_analyst(results, iteration=i)

            # 4. Record iteration
            iteration_result = IterationResult(
                iteration=i,
                configs=configs,
                run_results=results,
                analysis=analysis,
                converged=converged,
            )
            self._history.append(iteration_result)

            # Save analysis to disk
            analysis_dir = self._config.results_base_dir / f"iteration_{i}"
            analysis_dir.mkdir(parents=True, exist_ok=True)
            (analysis_dir / "analysis.md").write_text(analysis)

            if converged:
                log.info("Analyst declared convergence at iteration %d", i)
                break

        return self._history

    def _run_strategist(self, iteration: int) -> list[ExperimentConfig]:
        """Call the strategist LLM to generate experiment configs."""
        prompt_template = _load_prompt("strategist")

        # Build context
        previous_results = "No previous results." if not self._history else ""
        for h in self._history:
            previous_results += f"\n## Iteration {h.iteration}\n"
            previous_results += _format_run_results(h.run_results)
            previous_results += f"\n### Analysis\n{h.analysis}\n"

        memory_text = "\n".join(self._memory) if self._memory else "No memory yet."

        system_prompt = prompt_template.format(
            previous_results=previous_results,
            memory=memory_text,
            num_experiments=self._config.num_experiments_per_iteration,
        )

        user_msg = (
            f"Iteration {iteration + 1}. "
            f"Available data hours: {self._config.data_hours}. "
            f"Generate {self._config.num_experiments_per_iteration} experiment configs."
        )

        log.info("Calling strategist LLM...")
        response = _call_llm(
            self._client, system_prompt, user_msg, self._config.model,
        )

        # Parse configs from response
        raw_configs = _parse_configs_from_yaml(response)
        log.info("Strategist produced %d configs", len(raw_configs))

        configs = []
        for raw in raw_configs:
            try:
                # Inject data hours if not specified
                if not raw.get("data", {}).get("hours"):
                    raw.setdefault("data", {})["hours"] = self._config.data_hours
                cfg = _dict_to_experiment_config(raw)
                configs.append(cfg)
            except Exception as e:
                log.warning("Failed to parse config: %s", e)

        return configs

    def _run_experiments(self, configs: list[ExperimentConfig]) -> list[RunResult]:
        """Execute all experiment configs. Runs sequentially (safe for memory)."""
        results = []
        for i, config in enumerate(configs):
            log.info("Running experiment %d/%d: %s", i + 1, len(configs), config.mlflow_variant or "unnamed")
            result = run_backtest(
                config=config,
                market_infos=self._market_infos,
                data_cache_dir=Path("data/pmxt/cache"),
                results_dir=self._config.results_base_dir / result_dir_name(config, i),
                mlflow_tracking_uri=self._config.mlflow_tracking_uri,
            )
            results.append(result)
            if result.success:
                log.info("  PnL=%.4f  Trades=%d  Sharpe=%.4f",
                         result.tearsheet.total_pnl,
                         result.tearsheet.num_trades,
                         result.tearsheet.sharpe_ratio)
            else:
                log.warning("  FAILED: %s", result.error)
        return results

    def _run_analyst(self, results: list[RunResult], iteration: int) -> tuple[str, bool]:
        """Call the analyst LLM to evaluate results."""
        prompt_template = _load_prompt("analyst")

        run_results_text = _format_run_results(results)

        previous_analyses = ""
        for h in self._history:
            previous_analyses += f"\n## Iteration {h.iteration}\n{h.analysis}\n"
        if not previous_analyses:
            previous_analyses = "No previous iterations."

        memory_text = "\n".join(self._memory) if self._memory else "No memory yet."

        system_prompt = prompt_template.format(
            run_results=run_results_text,
            previous_analyses=previous_analyses,
            memory=memory_text,
        )

        user_msg = (
            f"Iteration {iteration + 1} complete. "
            f"{len(results)} experiments ran. Analyze all results."
        )

        log.info("Calling analyst LLM...")
        analysis = _call_llm(
            self._client, system_prompt, user_msg, self._config.model,
        )

        converged = _check_convergence(analysis)
        self._memory.append(f"[Iteration {iteration}] {analysis[:500]}")

        return analysis, converged


def result_dir_name(config: ExperimentConfig, index: int) -> str:
    """Generate a descriptive results directory name."""
    variant = config.mlflow_variant or f"run_{index}"
    # Sanitize for filesystem
    return variant.replace("/", "_").replace(" ", "_")[:60]
