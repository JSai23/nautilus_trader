"""Tests for PMXT transformer — price_change and book_snapshot transformations."""

import json

from nautilus_trader.adapters.polymarket.common.parsing import parse_polymarket_instrument
from nautilus_trader.adapters.polymarket.common.symbol import get_polymarket_instrument_id
from nautilus_trader.model.data import OrderBookDelta, OrderBookDeltas
from nautilus_trader.model.enums import BookAction, OrderSide, RecordFlag

from pmxt.transformer import (
    transform_book_snapshot,
    transform_price_change,
    transform_row,
)

# Realistic test fixtures based on PMXT_REFERENCE.md
CONDITION_ID = "0xbcf53c26f5aee0e37afab4e3cf6df4f814e1b5dd1c9b4bca7c4099eff0795e8f"
TOKEN_ID = "26106976340921874615818677828184535836563305697919583768164459546872238738504"

MARKET_INFO = {
    "condition_id": CONDITION_ID,
    "question": "Will Bitcoin be above 100K?",
    "minimum_tick_size": "0.001",
    "minimum_order_size": "5",
    "end_date_iso": "2027-12-31T00:00:00Z",
    "maker_base_fee": "0",
    "taker_base_fee": "0",
    "neg_risk": False,
}


def _make_instrument():
    return parse_polymarket_instrument(
        market_info=MARKET_INFO,
        token_id=TOKEN_ID,
        outcome="Yes",
        ts_init=0,
    )


def _make_instrument_id():
    return get_polymarket_instrument_id(CONDITION_ID, TOKEN_ID)


class TestPriceChange:
    def test_buy_update(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()

        data = {
            "update_type": "price_change",
            "market_id": CONDITION_ID,
            "token_id": TOKEN_ID,
            "side": "YES",
            "best_bid": "0.18",
            "best_ask": "0.89",
            "timestamp": 1773046869.0186121,
            "change_price": "0.18",
            "change_size": "100",
            "change_side": "BUY",
        }

        delta = transform_price_change(
            data=data,
            instrument_id=instrument_id,
            instrument=instrument,
            ts_event=int(1773046869.0186121 * 1e9),
            ts_init=int(1773046869.0186121 * 1e9),
        )

        assert isinstance(delta, OrderBookDelta)
        assert delta.action == BookAction.UPDATE
        assert delta.order.side == OrderSide.BUY
        assert float(delta.order.price) == 0.18
        assert float(delta.order.size) == 100.0
        assert delta.order.order_id == 0
        assert delta.flags == RecordFlag.F_LAST
        assert delta.instrument_id == instrument_id

    def test_sell_update(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()

        data = {
            "change_price": "0.55",
            "change_size": "200",
            "change_side": "SELL",
            "timestamp": 1773046870.0,
        }

        delta = transform_price_change(
            data=data,
            instrument_id=instrument_id,
            instrument=instrument,
            ts_event=int(1773046870.0 * 1e9),
            ts_init=int(1773046870.0 * 1e9),
        )

        assert delta.action == BookAction.UPDATE
        assert delta.order.side == OrderSide.SELL

    def test_delete_when_size_zero(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()

        data = {
            "change_price": "0.18",
            "change_size": "0",
            "change_side": "BUY",
            "timestamp": 1773046871.0,
        }

        delta = transform_price_change(
            data=data,
            instrument_id=instrument_id,
            instrument=instrument,
            ts_event=int(1773046871.0 * 1e9),
            ts_init=int(1773046871.0 * 1e9),
        )

        assert delta.action == BookAction.DELETE

    def test_timestamp_conversion(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()
        ts = 1773046869.0186121

        data = {
            "change_price": "0.50",
            "change_size": "10",
            "change_side": "BUY",
            "timestamp": ts,
        }

        delta = transform_price_change(
            data=data,
            instrument_id=instrument_id,
            instrument=instrument,
            ts_event=int(ts * 1e9),
            ts_init=int(ts * 1e9),
        )

        assert delta.ts_event == int(ts * 1_000_000_000)
        assert delta.ts_init == delta.ts_event


class TestBookSnapshot:
    def test_snapshot_with_bids_and_asks(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()

        data = {
            "update_type": "book_snapshot",
            "market_id": CONDITION_ID,
            "token_id": TOKEN_ID,
            "side": "YES",
            "best_bid": "0.053",
            "best_ask": "0.054",
            "timestamp": 1773049042.054261,
            "bids": [["0.001", "2063745.76"], ["0.002", "4688"]],
            "asks": [["0.999", "5001257.96"], ["0.998", "2000000"]],
        }

        result = transform_book_snapshot(
            data=data,
            instrument_id=instrument_id,
            instrument=instrument,
            ts_event=int(1773049042.054261 * 1e9),
            ts_init=int(1773049042.054261 * 1e9),
        )

        assert isinstance(result, OrderBookDeltas)

        deltas = result.deltas
        # 1 CLEAR + 2 bids + 2 asks = 5 deltas
        assert len(deltas) == 5

        # First is CLEAR
        assert deltas[0].action == BookAction.CLEAR

        # Bids
        assert deltas[1].action == BookAction.ADD
        assert deltas[1].order.side == OrderSide.BUY
        assert deltas[2].action == BookAction.ADD
        assert deltas[2].order.side == OrderSide.BUY

        # Asks
        assert deltas[3].action == BookAction.ADD
        assert deltas[3].order.side == OrderSide.SELL
        assert deltas[4].action == BookAction.ADD
        assert deltas[4].order.side == OrderSide.SELL

        # Last delta has F_LAST
        assert deltas[4].flags == RecordFlag.F_LAST
        # Others don't
        for d in deltas[:4]:
            assert d.flags == 0

    def test_empty_snapshot(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()

        data = {
            "bids": [],
            "asks": [],
            "timestamp": 1773049042.0,
        }

        result = transform_book_snapshot(
            data=data,
            instrument_id=instrument_id,
            instrument=instrument,
            ts_event=int(1773049042.0 * 1e9),
            ts_init=int(1773049042.0 * 1e9),
        )

        assert isinstance(result, OrderBookDeltas)
        # Just the CLEAR delta
        assert len(result.deltas) == 1
        assert result.deltas[0].action == BookAction.CLEAR


class TestTransformRow:
    def test_price_change_row(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()
        instruments = {TOKEN_ID: instrument}
        instrument_ids = {TOKEN_ID: instrument_id}

        row = {
            "market_id": CONDITION_ID,
            "update_type": "price_change",
            "data": json.dumps({
                "update_type": "price_change",
                "market_id": CONDITION_ID,
                "token_id": TOKEN_ID,
                "side": "YES",
                "best_bid": "0.18",
                "best_ask": "0.89",
                "timestamp": 1773046869.0186121,
                "change_price": "0.18",
                "change_size": "100",
                "change_side": "BUY",
            }),
            "timestamp_received": None,
        }

        result = transform_row(row, instruments, instrument_ids)
        assert isinstance(result, OrderBookDelta)
        assert result.action == BookAction.UPDATE

    def test_book_snapshot_row(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()
        instruments = {TOKEN_ID: instrument}
        instrument_ids = {TOKEN_ID: instrument_id}

        row = {
            "market_id": CONDITION_ID,
            "update_type": "book_snapshot",
            "data": json.dumps({
                "update_type": "book_snapshot",
                "market_id": CONDITION_ID,
                "token_id": TOKEN_ID,
                "side": "YES",
                "best_bid": "0.053",
                "best_ask": "0.054",
                "timestamp": 1773049042.054261,
                "bids": [["0.001", "100"]],
                "asks": [["0.999", "200"]],
            }),
            "timestamp_received": None,
        }

        result = transform_row(row, instruments, instrument_ids)
        assert isinstance(result, OrderBookDeltas)

    def test_unknown_token_id_returns_none(self):
        instrument = _make_instrument()
        instrument_id = _make_instrument_id()
        instruments = {TOKEN_ID: instrument}
        instrument_ids = {TOKEN_ID: instrument_id}

        row = {
            "market_id": CONDITION_ID,
            "update_type": "price_change",
            "data": json.dumps({
                "token_id": "99999999999",
                "change_price": "0.50",
                "change_size": "10",
                "change_side": "BUY",
                "timestamp": 1773046869.0,
            }),
            "timestamp_received": None,
        }

        result = transform_row(row, instruments, instrument_ids)
        assert result is None
