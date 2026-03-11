"""Universe resolver — resolves universe definitions to instruments and data.

Two resolution modes per IMPL_PLAN Section 4.3:
1. Forward: slug patterns -> condition_ids -> instruments -> PMXT data
2. Reverse: PMXT data -> market_ids -> metadata -> instruments

For backtest, we use cached market metadata JSON files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption

from universe.config import UniverseConfig
from universe.instruments import build_instrument_maps, load_market_metadata

log = logging.getLogger(__name__)


class UniverseResolver:
    """Resolves universe definitions to instruments and market IDs."""

    def __init__(self, metadata_cache_dir: Path):
        self._cache_dir = metadata_cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cached_metadata(self, condition_id: str) -> dict[str, Any] | None:
        path = self._cache_dir / f"{condition_id}.json"
        if path.exists():
            return load_market_metadata(path)
        return None

    def save_metadata(self, condition_id: str, metadata: dict[str, Any]) -> Path:
        path = self._cache_dir / f"{condition_id}.json"
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2)
        return path

    def resolve_from_condition_ids(
        self,
        condition_ids: list[str],
        ts_init: int = 0,
    ) -> tuple[dict[str, BinaryOption], dict[str, InstrumentId], set[str]]:
        """Resolve specific condition_ids to instruments.

        Loads cached metadata for each condition_id and builds instruments.
        """
        market_infos = []
        missing = []

        for cid in condition_ids:
            metadata = self.get_cached_metadata(cid)
            if metadata is None:
                missing.append(cid)
            else:
                market_infos.append(metadata)

        if missing:
            log.warning(
                "Missing cached metadata for %d markets: %s",
                len(missing),
                [m[:16] for m in missing],
            )

        return build_instrument_maps(market_infos, ts_init)

    def resolve_from_config(
        self,
        config: UniverseConfig,
        ts_init: int = 0,
    ) -> tuple[dict[str, BinaryOption], dict[str, InstrumentId], set[str]]:
        """Resolve a universe config to instruments.

        Uses condition_ids from the config's selection. Slug-based
        resolution requires CLI access (not implemented here —
        the orchestrator/agent handles discovery).
        """
        condition_ids = config.selection.condition_ids
        if not condition_ids:
            # Try loading all cached metadata and filtering
            return self._resolve_all_cached(config, ts_init)

        return self.resolve_from_condition_ids(condition_ids, ts_init)

    def _resolve_all_cached(
        self,
        config: UniverseConfig,
        ts_init: int = 0,
    ) -> tuple[dict[str, BinaryOption], dict[str, InstrumentId], set[str]]:
        """Resolve using all cached metadata files (for slug/tag matching)."""
        market_infos = []

        for path in sorted(self._cache_dir.glob("*.json")):
            metadata = load_market_metadata(path)
            market_infos.append(metadata)

        log.info("Loaded %d cached market metadata files", len(market_infos))
        return build_instrument_maps(market_infos, ts_init)

    def list_cached_markets(self) -> list[dict[str, str]]:
        """List all cached market metadata."""
        results = []
        for path in sorted(self._cache_dir.glob("*.json")):
            metadata = load_market_metadata(path)
            results.append({
                "condition_id": metadata.get("condition_id", ""),
                "slug": metadata.get("market_slug", metadata.get("slug", "")),
                "question": metadata.get("question", ""),
            })
        return results
