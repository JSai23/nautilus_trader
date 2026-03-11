"""MLflow logger tests — verifies experiment/variant/child-run hierarchy.

Uses local file-backed MLflow (default ./mlruns/ tracking URI). No server required.
"""

import shutil
import tempfile
from pathlib import Path

import mlflow
import pytest

from runner.mlflow_logger import MLflowLogger, _get_git_sha


@pytest.fixture
def mlflow_tmp_dir():
    """Create a temp directory for MLflow tracking and clean up after."""
    tmp = tempfile.mkdtemp(prefix="mlflow_test_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def logger(mlflow_tmp_dir):
    """Create an MLflowLogger pointing to a temp tracking URI."""
    uri = f"file://{mlflow_tmp_dir}"
    return MLflowLogger(tracking_uri=uri)


class TestGetGitSha:
    def test_returns_nonempty_string(self):
        sha = _get_git_sha()
        assert isinstance(sha, str)
        assert len(sha) > 0
        assert sha != "unknown", "git_sha should not be 'unknown' in a git repo"
        assert len(sha) == 12, f"Expected 12-char truncated sha, got {len(sha)}"


class TestMLflowLogger:
    def test_logger_enabled(self, logger):
        assert logger.enabled is True

    def test_log_child_run_creates_experiment(self, logger, mlflow_tmp_dir):
        """Verify experiment is created and child run is logged."""
        experiment_name = "test-experiment"

        # Create temp artifacts
        artifacts_dir = Path(mlflow_tmp_dir) / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "tearsheet.json").write_text('{"pnl": 42.0}')

        child_run_id = logger.log_child_run(
            experiment_name=experiment_name,
            variant_name="v1-test",
            metrics={"total_pnl": 42.0, "num_trades": 5, "win_rate": 0.6},
            params={"threshold": 0.3, "trade_size": 10.0},
            tags={"mode": "backtest", "universe_id": "test-universe"},
            artifacts_dir=artifacts_dir,
        )

        assert child_run_id is not None

        # Verify experiment exists
        mlflow.set_tracking_uri(f"file://{mlflow_tmp_dir}")
        experiment = mlflow.get_experiment_by_name(experiment_name)
        assert experiment is not None, f"Experiment '{experiment_name}' not found"

    def test_child_run_has_git_sha(self, logger, mlflow_tmp_dir):
        """Every child run MUST have git_sha tag — non-negotiable per IMPL_PLAN."""
        child_run_id = logger.log_child_run(
            experiment_name="sha-test",
            variant_name="v1",
            metrics={"total_pnl": 0.0},
            params={},
        )

        assert child_run_id is not None

        mlflow.set_tracking_uri(f"file://{mlflow_tmp_dir}")
        run = mlflow.get_run(child_run_id)
        tags = run.data.tags

        assert "git_sha" in tags, "git_sha tag missing from child run"
        assert tags["git_sha"] != "unknown", "git_sha should not be 'unknown'"
        assert len(tags["git_sha"]) == 12

    def test_parent_child_relationship(self, logger, mlflow_tmp_dir):
        """Verify parent-child hierarchy: variant run is parent of child run."""
        child_run_id = logger.log_child_run(
            experiment_name="hierarchy-test",
            variant_name="v2-improved",
            metrics={"total_pnl": 10.0},
            params={"x": 1},
        )

        assert child_run_id is not None

        mlflow.set_tracking_uri(f"file://{mlflow_tmp_dir}")
        child_run = mlflow.get_run(child_run_id)
        tags = child_run.data.tags

        assert "mlflow.parentRunId" in tags, "parentRunId tag missing"
        parent_run_id = tags["mlflow.parentRunId"]

        # Verify parent run exists and has correct name
        parent_run = mlflow.get_run(parent_run_id)
        assert parent_run is not None, "Parent run not found"
        assert parent_run.data.tags.get("mlflow.runName") == "v2-improved"

    def test_metrics_logged(self, logger, mlflow_tmp_dir):
        """Verify metrics are logged on child run."""
        child_run_id = logger.log_child_run(
            experiment_name="metrics-test",
            variant_name="v1",
            metrics={"total_pnl": 123.45, "num_trades": 7, "sharpe_ratio": 1.5},
            params={"threshold": 0.5},
        )

        mlflow.set_tracking_uri(f"file://{mlflow_tmp_dir}")
        run = mlflow.get_run(child_run_id)

        assert run.data.metrics["total_pnl"] == 123.45
        assert run.data.metrics["num_trades"] == 7
        assert run.data.metrics["sharpe_ratio"] == 1.5

    def test_params_logged(self, logger, mlflow_tmp_dir):
        """Verify params are logged as strings."""
        child_run_id = logger.log_child_run(
            experiment_name="params-test",
            variant_name="v1",
            metrics={"total_pnl": 0.0},
            params={"threshold": 0.3, "trade_size": 10},
        )

        mlflow.set_tracking_uri(f"file://{mlflow_tmp_dir}")
        run = mlflow.get_run(child_run_id)

        assert run.data.params["threshold"] == "0.3"
        assert run.data.params["trade_size"] == "10"

    def test_artifacts_logged(self, logger, mlflow_tmp_dir):
        """Verify artifacts directory is logged."""
        # Artifacts dir must be OUTSIDE the tracking URI to avoid MLflow confusion
        artifacts_tmp = tempfile.mkdtemp(prefix="mlflow_artifacts_")
        artifacts_dir = Path(artifacts_tmp)
        (artifacts_dir / "result.txt").write_text("test data")

        try:
            child_run_id = logger.log_child_run(
                experiment_name="artifacts-test",
                variant_name="v1",
                metrics={"total_pnl": 0.0},
                params={},
                artifacts_dir=artifacts_dir,
            )

            mlflow.set_tracking_uri(f"file://{mlflow_tmp_dir}")
            client = mlflow.MlflowClient()
            artifacts = client.list_artifacts(child_run_id)
            artifact_names = [a.path for a in artifacts]
            assert "result.txt" in artifact_names, f"Artifacts: {artifact_names}"
        finally:
            shutil.rmtree(artifacts_tmp, ignore_errors=True)

    def test_second_child_reuses_parent(self, logger, mlflow_tmp_dir):
        """Two child runs under the same variant should share the same parent."""
        run1_id = logger.log_child_run(
            experiment_name="reuse-test",
            variant_name="v1-shared",
            metrics={"total_pnl": 1.0},
            params={},
        )
        run2_id = logger.log_child_run(
            experiment_name="reuse-test",
            variant_name="v1-shared",
            metrics={"total_pnl": 2.0},
            params={},
        )

        mlflow.set_tracking_uri(f"file://{mlflow_tmp_dir}")
        run1 = mlflow.get_run(run1_id)
        run2 = mlflow.get_run(run2_id)

        parent1 = run1.data.tags["mlflow.parentRunId"]
        parent2 = run2.data.tags["mlflow.parentRunId"]
        assert parent1 == parent2, (
            f"Expected same parent, got {parent1} vs {parent2}"
        )

    def test_custom_tags_preserved(self, logger, mlflow_tmp_dir):
        """Custom tags from config should be preserved alongside system tags."""
        child_run_id = logger.log_child_run(
            experiment_name="tags-test",
            variant_name="v1",
            metrics={"total_pnl": 0.0},
            params={},
            tags={"mode": "backtest", "universe_id": "crypto-hourly", "custom_key": "custom_val"},
        )

        mlflow.set_tracking_uri(f"file://{mlflow_tmp_dir}")
        run = mlflow.get_run(child_run_id)

        assert run.data.tags["mode"] == "backtest"
        assert run.data.tags["universe_id"] == "crypto-hourly"
        assert run.data.tags["custom_key"] == "custom_val"
        assert "git_sha" in run.data.tags  # System tag still present
