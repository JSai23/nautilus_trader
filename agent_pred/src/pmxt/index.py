"""PMXT data index — tracks what's cached locally and market coverage.

The index is a simple JSON file:
{
  "markets": {
    "0xbcf53c26...": {
      "hours_cached": ["2026-03-09T14", "2026-03-09T15"],
      "cache_size_mb": 12.3
    }
  },
  "total_cache_size_mb": 847
}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class PMXTIndex:
    def __init__(self, index_path: Path):
        self._path = index_path
        self._data: dict = {"markets": {}, "total_cache_size_mb": 0.0}
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        with open(self._path) as f:
            self._data = json.load(f)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    def has_data(self, market_id: str, hour: str) -> bool:
        market = self._data["markets"].get(market_id, {})
        return hour in market.get("hours_cached", [])

    def get_coverage(self, market_id: str) -> list[str]:
        market = self._data["markets"].get(market_id, {})
        return market.get("hours_cached", [])

    def register(self, market_id: str, hour: str, cache_path: Path) -> None:
        if market_id not in self._data["markets"]:
            self._data["markets"][market_id] = {"hours_cached": [], "cache_size_mb": 0.0}

        entry = self._data["markets"][market_id]
        if hour not in entry["hours_cached"]:
            entry["hours_cached"].append(hour)
            entry["hours_cached"].sort()

        size_mb = cache_path.stat().st_size / (1024 * 1024)
        entry["cache_size_mb"] = round(
            sum(
                (cache_path.parent / f"{h}.parquet").stat().st_size / (1024 * 1024)
                for h in entry["hours_cached"]
                if (cache_path.parent / f"{h}.parquet").exists()
            ),
            2,
        )

        self._data["total_cache_size_mb"] = round(
            sum(m["cache_size_mb"] for m in self._data["markets"].values()),
            2,
        )
        self.save()

    def get_cached_path(self, market_id: str, hour: str, cache_dir: Path) -> Path | None:
        if not self.has_data(market_id, hour):
            return None
        path = cache_dir / market_id / f"{hour}.parquet"
        return path if path.exists() else None
