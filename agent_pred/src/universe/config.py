"""Universe definition parsing from YAML files.

Per IMPL_PLAN Section 4.2, universe YAML defines:
- selection: slugs, tags, condition_ids
- filters: active, min_volume, min_liquidity
- period: start, end dates
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class UniverseSelection:
    slugs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    condition_ids: list[str] = field(default_factory=list)


@dataclass
class UniverseFilters:
    active: bool | None = None
    min_volume: float | None = None
    min_liquidity: float | None = None


@dataclass
class UniversePeriod:
    start: str | None = None
    end: str | None = None


@dataclass
class UniverseConfig:
    universe_id: str
    description: str = ""
    selection: UniverseSelection = field(default_factory=UniverseSelection)
    filters: UniverseFilters = field(default_factory=UniverseFilters)
    period: UniversePeriod = field(default_factory=UniversePeriod)

    @classmethod
    def from_yaml(cls, path: Path) -> UniverseConfig:
        with open(path) as f:
            raw = yaml.safe_load(f)

        selection_raw = raw.get("selection", {})
        selection = UniverseSelection(
            slugs=selection_raw.get("slugs", []),
            tags=selection_raw.get("tags", []),
            condition_ids=selection_raw.get("condition_ids", []),
        )

        filters_raw = raw.get("filters", {})
        filters = UniverseFilters(
            active=filters_raw.get("active"),
            min_volume=filters_raw.get("min_volume"),
            min_liquidity=filters_raw.get("min_liquidity"),
        )

        period_raw = raw.get("period", {})
        period = UniversePeriod(
            start=period_raw.get("start"),
            end=period_raw.get("end"),
        )

        return cls(
            universe_id=raw["universe_id"],
            description=raw.get("description", ""),
            selection=selection,
            filters=filters,
            period=period,
        )
