"""Build NautilusTrader BinaryOption instruments from cached market metadata.

Per IMPL_PLAN Section 4.3, backtest instruments are constructed from cached
JSON metadata (from Gamma API / CLI). This module handles that construction.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from nautilus_trader.adapters.polymarket.common.parsing import parse_polymarket_instrument
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import BinaryOption

log = logging.getLogger(__name__)


def load_market_metadata(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return json.load(f)


def build_instruments_from_metadata(
    market_info: dict[str, Any],
    ts_init: int = 0,
) -> list[tuple[BinaryOption, str]]:
    """Build BinaryOption instruments from market metadata JSON.

    Returns list of (instrument, token_id) tuples — one per outcome token
    (typically 2: Yes and No).
    """
    tokens = market_info.get("tokens", [])

    results = []
    for token_entry in tokens:
        token_id = str(token_entry["token_id"])
        outcome = token_entry.get("outcome", "Unknown")

        instrument = parse_polymarket_instrument(
            market_info=market_info,
            token_id=token_id,
            outcome=outcome,
            ts_init=ts_init,
        )
        results.append((instrument, token_id))

    return results


def build_instrument_maps(
    market_infos: list[dict[str, Any]],
    ts_init: int = 0,
) -> tuple[dict[str, BinaryOption], dict[str, InstrumentId], set[str]]:
    """Build instrument lookup maps from a list of market metadata dicts.

    Returns
    -------
    tuple of:
        instruments : dict[str, BinaryOption]
            Map from token_id to instrument.
        instrument_ids : dict[str, InstrumentId]
            Map from token_id to InstrumentId.
        market_ids : set[str]
            Set of condition_id hashes (for PMXT filtering).
    """
    instruments: dict[str, BinaryOption] = {}
    instrument_ids: dict[str, InstrumentId] = {}
    market_ids: set[str] = set()

    for market_info in market_infos:
        condition_id = str(market_info["condition_id"])
        market_ids.add(condition_id)

        for instrument, token_id in build_instruments_from_metadata(market_info, ts_init):
            instruments[token_id] = instrument
            instrument_ids[token_id] = instrument.id
            log.info(
                "Built instrument: %s (token=%s, outcome=%s)",
                instrument.id,
                token_id[:16],
                instrument.outcome,
            )

    return instruments, instrument_ids, market_ids
