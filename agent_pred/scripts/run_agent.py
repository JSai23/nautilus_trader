#!/usr/bin/env python3
"""Run the agentic orchestrator — strategist -> runner -> analyst loop.

Usage:
    # Full agent loop (requires ANTHROPIC_API_KEY)
    uv run python scripts/run_agent.py

    # With custom settings
    uv run python scripts/run_agent.py --iterations 3 --experiments 5 --model claude-sonnet-4-20250514

    # Single-cycle demo (1 iteration, 2 experiments)
    uv run python scripts/run_agent.py --iterations 1 --experiments 2

Prerequisites:
    1. Set ANTHROPIC_API_KEY environment variable
    2. Markets are discovered automatically via Gamma API at startup
"""

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run the agentic experiment loop")
    parser.add_argument("--iterations", type=int, default=5, help="Max iterations")
    parser.add_argument("--experiments", type=int, default=3, help="Experiments per iteration")
    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514", help="LLM model")
    parser.add_argument("--hours", nargs="+", default=["2026-03-09T09"], help="Data hours")
    parser.add_argument("--results-dir", type=Path, default=Path("results/agent"))
    parser.add_argument("--mlflow-uri", type=str, default="sqlite:///mlflow.db")
    parser.add_argument("--max-markets", type=int, default=50, help="Max markets to discover")
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.error(
            "ANTHROPIC_API_KEY not set. "
            "Export it: export ANTHROPIC_API_KEY=sk-ant-..."
        )
        sys.exit(1)

    # Import here to fail fast on missing deps
    try:
        import anthropic
    except ImportError:
        log.error("anthropic package not installed. Run: uv add anthropic")
        sys.exit(1)

    from agents.orchestrator import Orchestrator, OrchestratorConfig
    from universe.gamma import MarketFilter

    # Build orchestrator
    client = anthropic.Anthropic(api_key=api_key)
    config = OrchestratorConfig(
        max_iterations=args.iterations,
        num_experiments_per_iteration=args.experiments,
        data_hours=args.hours,
        universe_filter=MarketFilter(active=True, max_markets=args.max_markets),
        results_base_dir=args.results_dir,
        mlflow_tracking_uri=args.mlflow_uri,
        model=args.model,
    )

    orchestrator = Orchestrator(client=client, config=config)

    # Run the loop
    print(f"\n{'='*60}")
    print("  AGENT ORCHESTRATOR")
    print(f"  Max iterations: {args.iterations}")
    print(f"  Experiments/iter: {args.experiments}")
    print(f"  Model: {args.model}")
    print(f"  Data hours: {args.hours}")
    print(f"{'='*60}\n")

    history = orchestrator.run()

    # Summary
    print(f"\n{'='*60}")
    print("  ORCHESTRATOR COMPLETE")
    print(f"  Iterations: {len(history)}")
    total_runs = sum(len(h.run_results) for h in history)
    print(f"  Total runs: {total_runs}")

    if history:
        last = history[-1]
        print(f"  Converged: {last.converged}")
        best_pnl = max(
            (r.tearsheet.total_pnl for h in history for r in h.run_results if r.success),
            default=0.0,
        )
        print(f"  Best PnL: {best_pnl:.4f}")

    print(f"  Results: {args.results_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
