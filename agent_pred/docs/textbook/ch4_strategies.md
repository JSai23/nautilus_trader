# Chapter 4: Writing Strategies

How to write trading strategies on this framework — the base class, the two patterns, the exit lifecycle, and the things that trip people up.

## The Base Class

Every strategy extends `PolymarketStrategy` (from `src/strategy/base.py`). It provides:

1. **Orderbook subscription** — subscribes to all configured instruments on start
2. **Interval timer** — optional recurring callback for timer-based strategies
3. **Exit lifecycle** — automatic position closing on convergence, resolution, take-profit, stop-loss, and end-of-data
4. **Dynamic instruments** — auto-subscribes to new markets discovered at runtime (paper/live)

```python
from strategy.base import PolymarketStrategy, PolymarketStrategyConfig

class MyStrategyConfig(PolymarketStrategyConfig, frozen=True):
    trade_size: float = 5.0
    my_threshold: float = 0.3

class MyStrategy(PolymarketStrategy):
    def __init__(self, config: MyStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size
        self._my_threshold = config.my_threshold
```

Config must be `frozen=True` (NautilusTrader requirement — configs are immutable after construction).

### Config Fields You Get for Free

From `PolymarketStrategyConfig`:

| Field | Default | Purpose |
|-------|---------|---------|
| `instrument_ids` | `[]` | List of InstrumentId strings to trade (auto-injected by runner) |
| `check_interval_minutes` | `0` | If > 0, enables `on_interval()` timer |
| `convergence_threshold` | `0.95` | Exit when mid-price > this or < (1 - this) |
| `take_profit` | `None` | Exit on unrealized PnL above this |
| `stop_loss` | `None` | Exit on unrealized PnL below this |
| `exit_before_resolution_secs` | `300` | Exit N seconds before market resolution |
| `start_time_ns` | `0` | Data window start (auto-injected by runner) |
| `end_time_ns` | `0` | Data window end (auto-injected by runner) |
| `dynamic_instruments` | `False` | Enable dynamic instrument subscription (paper/live) |

You don't set `instrument_ids`, `start_time_ns`, or `end_time_ns` in your config YAML — the runner injects them automatically from universe resolution and data hour parsing.

## Two Strategy Patterns

### Pattern 1: Timer-Based (Preferred)

```python
class MyTimerStrategy(PolymarketStrategy):
    def __init__(self, config: MyTimerStrategyConfig) -> None:
        super().__init__(config)
        self._trade_size = config.trade_size

    def on_interval(self, event: TimeEvent) -> None:
        for iid in self._instrument_ids:
            if iid in self._closed or iid in self._exiting:
                continue

            book = self.cache.order_book(iid)
            if book is None:
                continue

            best_bid = book.best_bid_price()
            best_ask = book.best_ask_price()
            if best_bid is None or best_ask is None:
                continue

            mid = (float(best_bid) + float(best_ask)) / 2.0

            # Your logic here — decide whether to buy or sell
            if some_condition(mid):
                self._enter_long(iid, best_ask)
```

Timer fires every `check_interval_minutes`. The base class handles timer setup with proper time bounds — it won't fire before data starts or after data ends.

**Advantages**: simpler mental model, naturally holds positions across intervals, less sensitive to noise.

**Tradeoff**: blind between timer fires. If price spikes and drops back between two 1-minute intervals, you never see it.

### Pattern 2: Tick-Reactive

```python
class MyTickStrategy(PolymarketStrategy):
    def __init__(self, config: MyTickStrategyConfig) -> None:
        super().__init__(config)

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        super().on_order_book_deltas(deltas)  # MUST call for exit checks

        instrument_id = deltas.instrument_id
        if instrument_id in self._closed or instrument_id in self._exiting:
            return

        book = self.cache.order_book(instrument_id)
        # React to every orderbook update
```

Fires on every single orderbook update. You see everything.

**Critical**: you MUST call `super().on_order_book_deltas(deltas)` — the base class uses this for exit condition checks (convergence, take-profit, stop-loss). Without the super call, positions never exit.

**Advantages**: sees all price action, can react to fleeting opportunities.

**Tradeoff**: much noisier. Hundreds of updates happen per minute. Your logic needs to be robust to avoid churning.

## What a Strategy Can See

On each callback, you have access to:

```python
# Orderbook (always current — reflects all updates processed so far)
book = self.cache.order_book(instrument_id)
best_bid = book.best_bid_price()
best_ask = book.best_ask_price()
# Full depth: book.bids(), book.asks()

# Instruments
instrument = self.cache.instrument(instrument_id)
# instrument.expiration_ns — market end date as nanosecond timestamp

# Your positions and orders
positions = self.cache.positions_open(instrument_id=instrument_id)
orders = self.cache.orders_open(instrument_id=instrument_id)

# Portfolio
balance = self.portfolio.net_exposures(POLYMARKET_VENUE)

# Time
now_ns = self.clock.timestamp_ns()
```

### What You DON'T Get

**No price history.** NautilusTrader doesn't provide a "last N prices" buffer for orderbook delta subscriptions. `cache.quote_ticks()` and `cache.trade_ticks()` are empty when subscribed to orderbook deltas (different data type). Every strategy that needs lookback builds its own:

```python
from collections import deque

# In __init__:
self._mid_history: dict[InstrumentId, deque[float]] = defaultdict(
    lambda: deque(maxlen=100)
)

# In on_interval or on_order_book_deltas:
self._mid_history[instrument_id].append(mid)
```

This has a subtle consequence: timer strategies sample at interval frequency (1 price per minute with `check_interval_minutes=1`), while tick strategies sample at tick frequency (every orderbook update — could be hundreds per minute). A "100-period lookback" means very different things depending on the pattern.

**No market metadata.** Question text, category, slug, and end date are consumed during discovery and not stored on the instrument. `instrument.expiration_ns` IS populated from the metadata, so strategies can use it for time-to-expiry logic.

## Placing Orders

All orders go through `self.order_factory` and `self.submit_order()`:

```python
# Buy at best ask
instrument = self.cache.instrument(instrument_id)
qty = instrument.make_qty(self._trade_size)
order = self.order_factory.limit(
    instrument_id=instrument_id,
    order_side=OrderSide.BUY,
    quantity=qty,
    price=best_ask,
    time_in_force=TimeInForce.FOK,
)
self.submit_order(order)
```

**FOK (Fill-Or-Kill)** means the order fills completely or is cancelled — no partial fills. This is the standard for this framework. If the book moves between signal and submission, the order gets rejected. In backtest, the simulated exchange matches against the current book. In live, the Polymarket CLOB does.

**`instrument.make_qty()`** rounds the quantity to the instrument's lot size. Always use this — raw floats will fail validation.

**`minimum_order_size`** on Polymarket is typically $1. Strategies should ensure `trade_size` meets this minimum. The `make_qty()` call handles rounding but won't prevent zero-quantity orders if the trade size is below the minimum.

## The Exit Lifecycle

The base class handles exits automatically. You don't need to code these unless you want custom exit logic.

### Exit Triggers (in priority order)

1. **End-of-data** (`end_time_ns - 60s`): Exits all open positions 60 seconds before the data window ends. Prevents positions from being stuck with stale book prices. Sets `self._data_ended = True`, which blocks all new entries.

2. **Resolution timer** (`expiration_ns - exit_before_resolution_secs`): Exits positions before a market resolves. Resolution means the market decides Yes or No — holding through resolution means your position is worth either $1 or $0. Exiting early locks in current market-implied value.

3. **Convergence** (mid-price > `convergence_threshold` or < `1 - threshold`): When a binary outcome's price approaches 0 or 1, the market is nearly decided. Liquidity dries up and spreads widen. Exit early.

4. **Take-profit / Stop-loss**: Standard PnL-based exits. Only checked if the config values are set (not None).

### How Exits Work

All exits use FOK limit orders at the current best bid (for longs) or best ask (for shorts). The process:

1. Mark instrument as `_exiting`
2. Cancel all open orders for that instrument
3. Submit FOK exit order at best bid/ask
4. On fill: mark instrument as `_closed`

If the exit FOK order can't fill (book is empty or moved), `_exiting` is cleared and the exit will retry on the next tick/interval.

### Guarding New Entries

Always check `_closed` and `_exiting` before entering positions:

```python
def on_interval(self, event):
    for iid in self._instrument_ids:
        if iid in self._closed or iid in self._exiting:
            continue
        if self._data_ended:
            return
        # ... entry logic
```

## Dynamic Instruments (Paper/Live)

When `dynamic_instruments=True`, the strategy subscribes to venue-wide instrument updates. When `MarketDiscoveryActor` finds a new market:

1. Actor publishes the instrument through the DataEngine
2. Strategy's `on_instrument()` fires (base class handles subscription)
3. Base class appends to `_instrument_ids` and subscribes to orderbook data
4. Strategy's `on_new_instrument()` hook fires for any subclass-specific setup

```python
class MyLiveStrategy(PolymarketStrategy):
    def on_new_instrument(self, instrument: Instrument) -> None:
        # Called when a new market is dynamically discovered
        self.log.info(f"New market: {instrument.id}")
        # Initialize any per-instrument state
        self._mid_history[instrument.id] = deque(maxlen=100)
```

This means paper/live strategies can start with a seed universe and grow as new markets appear.

## Common Mistakes

**Forgetting `super().on_order_book_deltas()`** in tick strategies. Exit conditions never fire. Positions never close.

**Not checking `_closed` and `_exiting`**. Strategy re-enters a position that's being exited, creating confusion.

**Using raw floats for quantities**. Must use `instrument.make_qty()` for lot size rounding.

**Building price history without capping size**. Use `deque(maxlen=N)` — unbounded lists grow indefinitely in long backtests.

**Entering positions after `_data_ended`**. The end-of-data exit fires 60s before the window ends. New positions entered after this have no exit mechanism and no book updates.
