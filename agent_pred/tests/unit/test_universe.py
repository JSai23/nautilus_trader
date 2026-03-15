"""Tests for instrument building."""

from nautilus_trader.model.instruments import BinaryOption

from universe.instruments import build_instrument_maps, build_instruments_from_metadata

MARKET_INFO = {
    "condition_id": "0xabc123def456",
    "question": "Will BTC be above 100K?",
    "minimum_tick_size": "0.01",
    "minimum_order_size": "5",
    "end_date_iso": "2027-12-31T00:00:00Z",
    "maker_base_fee": "0",
    "taker_base_fee": "0",
    "tokens": [
        {"token_id": "111222333", "outcome": "Yes"},
        {"token_id": "444555666", "outcome": "No"},
    ],
}


class TestInstrumentBuilding:
    def test_build_from_metadata(self):
        results = build_instruments_from_metadata(MARKET_INFO)
        assert len(results) == 2

        inst_yes, tid_yes = results[0]
        inst_no, tid_no = results[1]

        assert isinstance(inst_yes, BinaryOption)
        assert isinstance(inst_no, BinaryOption)
        assert inst_yes.outcome == "Yes"
        assert inst_no.outcome == "No"
        assert tid_yes == "111222333"
        assert tid_no == "444555666"

    def test_build_instrument_maps(self):
        instruments, instrument_ids, market_ids = build_instrument_maps([MARKET_INFO])

        assert len(instruments) == 2
        assert len(instrument_ids) == 2
        assert "0xabc123def456" in market_ids
        assert "111222333" in instruments
        assert "444555666" in instruments
