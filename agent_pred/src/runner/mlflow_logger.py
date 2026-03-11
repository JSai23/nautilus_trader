"""MLflow logging with experiment/variant/child-run hierarchy.

Per IMPL_PLAN Section 5.3:
- Experiment = strategy idea (e.g., "orderbook-imbalance")
- Run = variant (e.g., "v1-simple-threshold")
- Child Run = individual execution (auto-tagged with git_sha, params, dates, mode)

Every child run MUST have git_sha. Non-negotiable.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()[:12] if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


class MLflowLogger:
    """Logs experiment results to MLflow with proper hierarchy."""

    def __init__(self, tracking_uri: str | None = None):
        self._enabled = False
        self._mlflow = None
        try:
            import mlflow

            self._mlflow = mlflow
            if tracking_uri:
                mlflow.set_tracking_uri(tracking_uri)
            self._enabled = True
            log.info("MLflow enabled: %s", mlflow.get_tracking_uri())
        except ImportError:
            log.warning("MLflow not available — logging disabled")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def log_child_run(
        self,
        experiment_name: str,
        variant_name: str,
        metrics: dict[str, float],
        params: dict[str, Any],
        tags: dict[str, str] | None = None,
        artifacts_dir: Path | None = None,
    ) -> str | None:
        """Log a child run under the experiment/variant hierarchy.

        Returns the child run ID, or None if MLflow is disabled.
        """
        if not self._enabled:
            log.info("MLflow disabled — skipping logging")
            return None

        mlflow = self._mlflow

        # Get or create experiment
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if experiment is None:
            experiment_id = mlflow.create_experiment(experiment_name)
        else:
            experiment_id = experiment.experiment_id

        # Find or create parent run (variant)
        parent_run_id = self._find_or_create_parent_run(
            experiment_id, variant_name,
        )

        # Create child run
        git_sha = _get_git_sha()
        all_tags = {
            "git_sha": git_sha,
            "mlflow.parentRunId": parent_run_id,
        }
        if tags:
            all_tags.update(tags)

        with mlflow.start_run(
            experiment_id=experiment_id,
            tags=all_tags,
            nested=True,
        ) as child_run:
            # Log params (stringify all values)
            str_params = {k: str(v) for k, v in params.items()}
            mlflow.log_params(str_params)

            # Log metrics
            mlflow.log_metrics(metrics)

            # Log artifacts
            if artifacts_dir and artifacts_dir.exists():
                mlflow.log_artifacts(str(artifacts_dir))

            child_run_id = child_run.info.run_id
            log.info(
                "Logged MLflow child run: experiment=%s, variant=%s, run_id=%s, git_sha=%s",
                experiment_name,
                variant_name,
                child_run_id[:8],
                git_sha,
            )

            return child_run_id

    def _find_or_create_parent_run(
        self,
        experiment_id: str,
        variant_name: str,
    ) -> str:
        """Find existing parent run by name, or create a new one."""
        mlflow = self._mlflow

        # Search for existing run with this name
        runs = mlflow.search_runs(
            experiment_ids=[experiment_id],
            filter_string=f'tags.mlflow.runName = "{variant_name}"',
            max_results=1,
        )

        if not runs.empty:
            return runs.iloc[0]["run_id"]

        # Create new parent run
        with mlflow.start_run(
            experiment_id=experiment_id,
            run_name=variant_name,
        ) as parent_run:
            return parent_run.info.run_id
