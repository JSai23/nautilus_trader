"""Transform PMXT parquet rows into NautilusTrader OrderBookDelta/OrderBookDeltas.

Field mapping:
- price_change -> OrderBookDelta (UPDATE or DELETE based on change_size)
- book_snapshot -> OrderBookDeltas (CLEAR + ADD for each level)

Timestamp: PMXT JSON 'timestamp' is unix seconds (float) -> nanos via int(v * 1e9).
order_id: Always 0 (L2 data, matches live adapter behavior).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nautilus_trader.model.data import BookOrder
from nautilus_trader.model.data import OrderBookDelta
from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.enums import BookAction
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.enums import RecordFlag

if TYPE_CHECKING:
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.instruments import BinaryOption


def _ts_seconds_to_nanos(ts: float) -> int:
    return int(ts * 1_000_000_000)


def transform_price_change(
    data: dict,
    instrument_id: InstrumentId,
    instrument: BinaryOption,
    ts_event: int,
    ts_init: int,
    flags: int = RecordFlag.F_LAST,
) -> OrderBookDelta:
    """Transform a PMXT price_change JSON blob into an OrderBookDelta.

    Mapping:
    - change_size == "0" -> BookAction.DELETE
    - change_side "BUY" -> OrderSide.BUY, "SELL" -> OrderSide.SELL
    - price/size via instrument.make_price/make_qty
    """
    change_size_str = data["change_size"]
    change_size = float(change_size_str)

    if change_size == 0:
        action = BookAction.DELETE
        size = instrument.make_qty(0)
    else:
        action = BookAction.UPDATE
        size = instrument.make_qty(change_size)

    side = OrderSide.BUY if data["change_side"] == "BUY" else OrderSide.SELL
    price = instrument.make_price(float(data["change_price"]))

    order = BookOrder(
        side=side,
        price=price,
        size=size,
        order_id=0,
    )

    return OrderBookDelta(
        instrument_id=instrument_id,
        action=action,
        order=order,
        flags=flags,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_init,
    )


def transform_book_snapshot(
    data: dict,
    instrument_id: InstrumentId,
    instrument: BinaryOption,
    ts_event: int,
    ts_init: int,
) -> OrderBookDeltas:
    """Transform a PMXT book_snapshot JSON blob into OrderBookDeltas.

    Mapping:
    - First delta: CLEAR action
    - Then ADD for each bid (BUY side) and ask (SELL side)
    - F_LAST flag on the final delta
    """
    deltas: list[OrderBookDelta] = []

    # CLEAR delta (no order needed — matches adapter pattern)
    deltas.append(
        OrderBookDelta(
            instrument_id=instrument_id,
            action=BookAction.CLEAR,
            order=None,
            flags=0,
            sequence=0,
            ts_event=ts_event,
            ts_init=ts_init,
        ),
    )

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    for price_str, size_str in bids:
        order = BookOrder(
            side=OrderSide.BUY,
            price=instrument.make_price(float(price_str)),
            size=instrument.make_qty(float(size_str)),
            order_id=0,
        )
        deltas.append(
            OrderBookDelta(
                instrument_id=instrument_id,
                action=BookAction.ADD,
                order=order,
                flags=0,
                sequence=0,
                ts_event=ts_event,
                ts_init=ts_init,
            ),
        )

    for price_str, size_str in asks:
        order = BookOrder(
            side=OrderSide.SELL,
            price=instrument.make_price(float(price_str)),
            size=instrument.make_qty(float(size_str)),
            order_id=0,
        )
        deltas.append(
            OrderBookDelta(
                instrument_id=instrument_id,
                action=BookAction.ADD,
                order=order,
                flags=0,
                sequence=0,
                ts_event=ts_event,
                ts_init=ts_init,
            ),
        )

    if not deltas:
        return OrderBookDeltas(instrument_id=instrument_id, deltas=deltas)

    # Mark last delta with F_LAST
    last = deltas[-1]
    deltas[-1] = OrderBookDelta(
        instrument_id=last.instrument_id,
        action=last.action,
        order=last.order,
        flags=RecordFlag.F_LAST,
        sequence=0,
        ts_event=ts_event,
        ts_init=ts_init,
    )

    return OrderBookDeltas(instrument_id=instrument_id, deltas=deltas)


def transform_row(
    row: dict,
    instruments: dict[str, BinaryOption],
    instrument_ids: dict[str, InstrumentId],
) -> OrderBookDelta | OrderBookDeltas | None:
    """Transform a single PMXT parquet row into NautilusTrader data.

    Parameters
    ----------
    row : dict
        Parquet row with keys: market_id, update_type, data, timestamp_received.
    instruments : dict[str, BinaryOption]
        Map from token_id (string) to BinaryOption instrument.
    instrument_ids : dict[str, InstrumentId]
        Map from token_id (string) to InstrumentId.

    Returns
    -------
    OrderBookDelta | OrderBookDeltas | None
        Transformed data, or None if token_id not in instruments.
    """
    data_str = row["data"]
    data = json.loads(data_str) if isinstance(data_str, str) else data_str

    token_id = str(data.get("token_id", ""))
    if token_id not in instruments:
        return None

    instrument = instruments[token_id]
    instrument_id = instrument_ids[token_id]

    # Timestamp: JSON data.timestamp is unix seconds (float)
    ts_raw = data.get("timestamp")
    if ts_raw is not None:
        ts_event = _ts_seconds_to_nanos(float(ts_raw))
    else:
        # Fallback to parquet column (already ms)
        ts_received = row.get("timestamp_received")
        if ts_received is not None:
            ts_event = int(ts_received.timestamp() * 1_000_000_000)
        else:
            return None

    ts_init = ts_event  # Historical data: ts_init == ts_event

    update_type = row["update_type"] if "update_type" in row else data.get("update_type", "")

    if update_type == "price_change":
        return transform_price_change(data, instrument_id, instrument, ts_event, ts_init)
    elif update_type == "book_snapshot":
        return transform_book_snapshot(data, instrument_id, instrument, ts_event, ts_init)

    return None
