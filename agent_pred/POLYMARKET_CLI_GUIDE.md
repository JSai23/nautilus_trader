# Polymarket CLI Reference Guide

Practical reference for LLM agents using the `polymarket` CLI to discover markets, pull orderbook data, and understand Polymarket's data model.

CLI location: `/usr/local/bin/polymarket`

Always use `-o json` for machine-parseable output.

---

## 1. Quick Reference

### Health & Status

| Command | Purpose |
|---------|---------|
| `polymarket status -o json` | API health check (`{"status":"OK"}`) |
| `polymarket clob ok -o json` | CLOB API health check |
| `polymarket clob time -o json` | CLOB server time (unix timestamp) |

### Market Discovery

| Command | Purpose |
|---------|---------|
| `polymarket markets list -o json --limit N` | List markets (paginated) |
| `polymarket markets list -o json --active true --closed false` | Active open markets only |
| `polymarket markets list -o json --order volume --limit 10` | Sort by volume |
| `polymarket markets get <id-or-slug> -o json` | Get one market by numeric ID or slug |
| `polymarket markets search "<query>" -o json --limit N` | Full-text search |
| `polymarket markets tags <market_id> -o json` | Get tags assigned to a market |
| `polymarket events list -o json --tag <slug> --active true --closed false` | Filter events by tag |
| `polymarket events get <id-or-slug> -o json` | Get event with all its markets |
| `polymarket events tags <event_id> -o json` | Get tags for an event |
| `polymarket tags list -o json` | List all tags |
| `polymarket tags get <slug> -o json` | Get a single tag |
| `polymarket tags related-tags <slug> -o json` | Get related tag objects |

### CLOB / Orderbook (all require `<token_id>`)

| Command | Purpose |
|---------|---------|
| `polymarket clob book <token_id> -o json` | Full orderbook (bids + asks) |
| `polymarket clob price --side buy <token_id> -o json` | Best buy price |
| `polymarket clob price --side sell <token_id> -o json` | Best sell price |
| `polymarket clob midpoint <token_id> -o json` | Midpoint price |
| `polymarket clob spread <token_id> -o json` | Bid-ask spread |
| `polymarket clob last-trade <token_id> -o json` | Last trade price + side |
| `polymarket clob tick-size <token_id> -o json` | Minimum tick size |
| `polymarket clob neg-risk <token_id> -o json` | Neg-risk status |
| `polymarket clob fee-rate <token_id> -o json` | Base fee in bps |
| `polymarket clob price-history <token_id> --interval <I> -o json` | Price history (intervals: `1m`, `1h`, `6h`, `1d`, `1w`, `max`) |
| `polymarket clob market <condition_id> -o json` | Full CLOB market info by condition ID |
| `polymarket clob markets -o json` | List all CLOB markets (cursor-paginated) |

### Batch Operations (comma-separated token_ids)

| Command | Purpose |
|---------|---------|
| `polymarket clob books <t1>,<t2> -o json` | Multiple orderbooks |
| `polymarket clob midpoints <t1>,<t2> -o json` | Multiple midpoints |
| `polymarket clob spreads <t1>,<t2> -o json` | Multiple spreads |
| `polymarket clob last-trades <t1>,<t2> -o json` | Multiple last trades |
| `polymarket clob batch-prices --side buy <t1>,<t2> -o json` | Multiple prices |

### On-chain Data

| Command | Purpose |
|---------|---------|
| `polymarket data open-interest <condition_id> -o json` | Open interest for a market |
| `polymarket data volume <event_id> -o json` | Volume by market within an event |
| `polymarket data trades <wallet_address> --limit N -o json` | Trade history for a wallet |
| `polymarket data holders <condition_id> --limit N -o json` | Top token holders per outcome |
| `polymarket data leaderboard --period <P> --order-by <O> -o json` | Trader leaderboard (period: `day`/`week`/`month`/`all`, order-by: `pnl`/`vol`) |

---

## 2. Data Model

### Entity Hierarchy

```
Tag (category label)
 └── Event (a question or group of related questions)
      └── Market (a single Yes/No or multi-outcome contract)
           └── Token (one tradeable side: Yes token + No token)
```

### Key Identifiers

| ID | Format | Where Used | Example |
|----|--------|-----------|---------|
| **market id** | Numeric string | `markets get`, `markets tags` | `"531202"` |
| **slug** | Kebab-case string | `markets get`, `events get` | `"bitboy-convicted"` |
| **condition_id** | `0x` + 64 hex chars | CLOB market lookup, open-interest, holders | `"0xb48621f7..."` |
| **question_id** | `0x` + 64 hex chars | UMA oracle identifier | `"0x3bb85f5d..."` |
| **token_id** | `0x` + 63-64 hex chars | All CLOB price/book commands | `"0xa6d8e1b5..."` |
| **event id** | Numeric string | `events get`, `data volume` | `"16167"` |
| **tag slug** | Kebab-case string | `events list --tag`, `tags get` | `"crypto"` |

### How IDs Relate (Traced Example)

Starting from the market **"BitBoy convicted?"**:

```
Market ID:    531202
Slug:         bitboy-convicted
Condition ID: 0xb48621f7eba07b0a3eeabc6afb09ae42490239903997b9d412b0f69aeb040c8b
Question ID:  0x3bb85f5d1a96c576a57502626785d97ea78982592a1775764cefd236e930fd02

Outcomes:     ["Yes", "No"]
Token IDs:
  Yes: 0xa6d8e1b575e4a2c8610d036d5b3a969358a3334fb60ea6e8a0e22c1aba891b22
  No:  0x87f0a56ae4b8184d2db883055b7d99377185bd6edc3eeffcc0e6fea6fba079b

Tags:         Crypto, bitboy, Culture, Other, Courts
```

The **token_id** is what you pass to all CLOB commands (book, price, midpoint, etc.).
The **condition_id** is what you pass to `clob market`, `data open-interest`, `data holders`.
The **event id** (numeric) is what you pass to `data volume`.

### Events vs Markets

An **event** groups related markets. Example:

```
Event: "MicroStrategy sells any Bitcoin by ___ ?"  (event ID: 16167)
  ├── Market: "MicroStrategy sells any Bitcoin in 2025?"
  ├── Market: "MicroStrategy sells any Bitcoin by March 31, 2026?"
  ├── Market: "MicroStrategy sells any Bitcoin by June 30, 2026?"
  └── Market: "MicroStrategy sells any Bitcoin by December 31, 2026?"
```

Each market has its own condition_id and pair of token_ids.

Simple events have exactly 1 market. Multi-outcome events (like "Bitcoin price range on March 10") can have 10+ markets, each representing a price band.

### Neg-Risk Markets

Markets with `neg_risk: true` are **negative-risk** markets. These are grouped under a single neg-risk market ID and allow the CLOB to enforce that outcome prices across related markets sum correctly. Common for multi-outcome events like price bands.

---

## 3. Market Discovery Recipes

### Find Active Crypto Markets

```bash
# Events tagged "crypto", active and open
polymarket events list -o json --tag crypto --active true --closed false --limit 10
```

### Find Short-Duration Markets (1-Hour Crypto)

Polymarket has hourly crypto up/down markets. Use the `1h` tag:

```bash
polymarket events list -o json --tag 1h --active true --closed false --limit 10
```

Returns markets like:
- "Ethereum Up or Down - March 8, 2AM ET"
- "Solana Up or Down - March 8, 2AM ET"
- "XRP Up or Down - March 8, 2AM ET"

These have outcomes `["Up", "Down"]` and resolve based on Chainlink price feeds.

### Find Daily Crypto Markets

```bash
polymarket events list -o json --tag today --active true --closed false --limit 10
```

Returns markets like "Bitcoin Up or Down on March 9?"

### Find Hit-Price Markets (Will X Hit $Y?)

```bash
polymarket events list -o json --tag hit-price --active true --closed false --limit 10
```

Returns multi-market events like:
- "What price will Bitcoin hit in 2026?" (34 markets for different price levels)
- "What price will Ethereum hit in 2026?" (16 markets)

### Find High-Volume Markets

```bash
polymarket markets list -o json --order volume --active true --closed false --limit 10
```

Valid `--order` fields: `volume`, `liquidity` (and likely others; `volume_num` does NOT work).

### Search by Keyword

```bash
polymarket markets search "Bitcoin price" -o json --limit 10
```

Search returns markets directly (not events). Results include both open and closed markets.

### Find Markets by Tag on Events

The `--tag` flag only exists on `events list`, not on `markets list`. To find markets by category, use events:

```bash
polymarket events list -o json --tag <tag_slug> --active true --closed false --limit 25
```

Then extract markets from each event's `markets` array.

### Common Tag Slugs

Discovered via `polymarket tags related-tags crypto`:

| Slug | Label | Notes |
|------|-------|-------|
| `crypto` | Crypto | Top-level crypto category |
| `1h` | 1H | Hourly crypto up/down markets |
| `today` | Today | Daily resolution markets |
| `hit-price` | Hit Price | Will-X-hit-$Y style markets |
| `politics` | Politics | Political prediction markets |
| `sports` | Sports | Sports betting markets |
| `pop-culture` | Culture | Entertainment/culture |
| `finance` | Finance | Financial markets |
| `business` | Business | Business events |
| `economy` | Economy | Economic indicators |

---

## 4. Orderbook & Price Data

### Orderbook Structure

Command: `polymarket clob book <token_id> -o json`

```json
{
  "asks": [
    {"price": "0.999", "size": "10055.7"},
    {"price": "0.998", "size": "2010.63"},
    {"price": "0.997", "size": "2000"}
  ],
  "asset_id": "69997398218388319357851891744495089105290992666643354882623212997310471983117",
  "bids": [
    {"price": "0.007", "size": "100"},
    {"price": "0.006", "size": "500"},
    {"price": "0.005", "size": "1005.64"}
  ],
  "hash": "abc123...",
  "market": "0xb48621f7...",
  "timestamp": "1773016557"
}
```

Notes:
- `price` and `size` are strings, not numbers
- `asset_id` is the token_id as a **decimal integer** (not hex)
- Asks are sorted descending (best ask first), bids ascending (best bid first)
- `market` is the condition_id

### Price

Command: `polymarket clob price --side buy <token_id> -o json`

```json
{"price": "0.031"}
```

The `--side` flag is **required**. `buy` = best ask (price to buy), `sell` = best bid (price to sell).

### Midpoint

Command: `polymarket clob midpoint <token_id> -o json`

```json
{"midpoint": "0.039"}
```

### Spread

Command: `polymarket clob spread <token_id> -o json`

```json
{"spread": "0.016"}
```

### Last Trade

Command: `polymarket clob last-trade <token_id> -o json`

```json
{"price": "0.047", "side": "BUY"}
```

### Tick Size

Command: `polymarket clob tick-size <token_id> -o json`

```json
{"minimum_tick_size": "0.001"}
```

Common tick sizes: `0.001` (most markets), `0.01` (older markets).

### Fee Rate

Command: `polymarket clob fee-rate <token_id> -o json`

```json
{"base_fee_bps": 0}
```

Note: Returns a number (not string). Many markets have 0 base fee.

### Neg-Risk

Command: `polymarket clob neg-risk <token_id> -o json`

```json
{"neg_risk": true}
```

### Price History

Command: `polymarket clob price-history <token_id> --interval <I> -o json`

Intervals: `1m`, `1h`, `6h`, `1d`, `1w`, `max`

```json
[
  {"price": "0.36", "timestamp": 1772930123},
  {"price": "0.3595", "timestamp": 1772930183},
  {"price": "0.3555", "timestamp": 1772930241}
]
```

Notes:
- Timestamps are unix seconds
- With `--interval 1d`, data points are spaced ~5 minutes apart (not daily candles -- the interval is the lookback window, not the candle size)
- `--fidelity N` controls how many data points are returned
- Returns `[]` (empty array) if the token has no recent trading history for the requested interval
- `1m` = last 1 minute, `1h` = last 1 hour, `1d` = last 1 day, etc.

### CLOB Market Info

Command: `polymarket clob market <condition_id> -o json`

```json
{
  "enable_order_book": true,
  "active": true,
  "closed": false,
  "archived": false,
  "accepting_orders": true,
  "accepting_order_timestamp": "2025-03-26T16:48:22Z",
  "minimum_order_size": "5",
  "minimum_tick_size": "0.001",
  "condition_id": "0xb48621f7...",
  "question_id": "0x3bb85f5d...",
  "question": "BitBoy convicted?",
  "description": "...",
  "market_slug": "bitboy-convicted",
  "end_date_iso": "2026-03-31T00:00:00Z",
  "game_start_time": null,
  "seconds_delay": 0,
  "fpmm": "",
  "maker_base_fee": "0",
  "taker_base_fee": "0",
  "neg_risk": false,
  "neg_risk_market_id": "",
  "rewards": {
    "rates": [{"asset_address": "0x2791bca...", "rewards_daily_rate": "5"}],
    "min_size": "20",
    "max_spread": "3.5"
  },
  "tokens": [
    {"token_id": "0xa6d8e1b5...", "outcome": "Yes", "price": "0.121", "winner": false},
    {"token_id": "0x87f0a56a...", "outcome": "No", "price": "0.879", "winner": false}
  ],
  "tags": ["Crypto", "bitboy", "Culture", "Other", "Courts"]
}
```

This is the richest single-market endpoint. It includes the `tokens` array with outcome labels mapped to token_ids, plus reward config and trading parameters.

### Batch Operations

All batch commands take comma-separated token_ids (no spaces).

**Batch midpoints:**
```bash
polymarket clob midpoints "<token1>,<token2>" -o json
```
```json
{
  "108525676450...": "0.961",
  "69997398218...": "0.039"
}
```
Note: Keys are **decimal integer** token_ids (not hex).

**Batch prices:**
```bash
polymarket clob batch-prices --side buy "<token1>,<token2>" -o json
```
```json
{
  "108525676450...": {"BUY": "0.953"},
  "69997398218...": {"BUY": "0.031"}
}
```

**Batch last-trades:**
```bash
polymarket clob last-trades "<token1>,<token2>" -o json
```
```json
[
  {"price": "0.97", "side": "BUY", "token_id": "108525676450..."},
  {"price": "0.047", "side": "BUY", "token_id": "69997398218..."}
]
```

**Batch books:** returns array of full orderbook objects (same schema as single book).

**Batch spreads:** `polymarket clob spreads "<t1>,<t2>" -o json` -- returns `null` in testing. May require active two-sided books on both tokens.

---

## 5. On-chain Data

### Open Interest

Command: `polymarket data open-interest <condition_id> -o json`

```json
[
  {
    "market": "0xb48621f7...",
    "value": "14418.518777"
  }
]
```

Value is in USDC.

### Volume

Command: `polymarket data volume <event_id> -o json`

```json
[
  {
    "markets": [
      {"market": "0x19ee98e3...", "value": "17976157.529867"},
      {"market": "0x9a4db724...", "value": "1993286.039531"},
      {"market": "0x8e7a03cb...", "value": "704093.147702"},
      {"market": "0x8213d395...", "value": "371935.650345"}
    ],
    "total": "21045472.367445003"
  }
]
```

Breaks down volume per market within the event, plus total. Values in USDC.

### Trade History

Command: `polymarket data trades <wallet_address> --limit N -o json`

```json
[
  {
    "condition_id": "0x87b90fb1...",
    "outcome": "Magic",
    "outcome_index": 0,
    "price": "0.75",
    "proxy_wallet": "0x2a2C53bD...",
    "side": "BUY",
    "size": "6889.7",
    "slug": "nba-orl-mil-2026-03-08",
    "timestamp": 1773015877,
    "title": "Magic vs. Bucks",
    "transaction_hash": "0x915af758..."
  }
]
```

Requires a wallet address. Returns empty `[]` for addresses with no trades.

### Top Holders

Command: `polymarket data holders <condition_id> --limit N -o json`

```json
[
  {
    "holders": [
      {
        "amount": "1490.517925",
        "name": "0xE72Aea7a...-1771198262453",
        "outcome_index": 0,
        "proxy_wallet": "0xE72Aea7a...",
        "pseudonym": "Guilty-Congressman"
      }
    ],
    "token": "75467129615908319583031474642658885479135630431889036121812713428992454630178"
  }
]
```

Returns one entry per outcome token, each with a `holders` array. Token IDs are decimal integers.

### Leaderboard

Command: `polymarket data leaderboard --period week --order-by vol --limit 3 -o json`

```json
[
  {
    "pnl": "2306607.733",
    "proxy_wallet": "0x2a2C53bD...",
    "rank": 1,
    "user_name": "0x2a2C53bD...-1772479215461",
    "volume": "9148280.140243"
  }
]
```

---

## 6. Full Market JSON Schema

Every field returned by `polymarket markets get <id> -o json`:

```
id                      : string    - Numeric market ID
question                : string    - The market question
conditionId             : string    - 0x-prefixed condition ID for CLOB
slug                    : string    - URL-friendly slug
questionID              : string    - UMA oracle question identifier
description             : string    - Full description / resolution criteria
outcomes                : string    - JSON-encoded array, e.g. '["Yes","No"]'
outcomePrices           : string    - JSON-encoded array, e.g. '["0.121","0.879"]'
clobTokenIds            : string    - JSON-encoded array of 0x token IDs
                                      Index 0 = first outcome, Index 1 = second outcome

active                  : bool      - Whether market is active
closed                  : bool      - Whether market is closed
enableOrderBook         : bool      - Whether CLOB is enabled
acceptingOrders         : bool      - Whether orders are currently accepted

endDate                 : string    - ISO 8601 end date
startDate               : string    - ISO 8601 start date
closedTime              : string    - When market was closed (null if open)

volume                  : string    - Total volume (string)
volumeNum               : string    - Total volume (numeric string)
volume24hr              : string    - 24-hour volume
volume1wk               : string    - 1-week volume
volume1mo               : string    - 1-month volume
volume1yr               : string    - 1-year volume
liquidityNum            : string    - Current liquidity

orderPriceMinTickSize   : string    - Minimum tick size (e.g. "0.001")
orderMinSize            : string    - Minimum order size (e.g. "5")

bestBid                 : string    - Current best bid
bestAsk                 : string    - Current best ask
spread                  : string    - Current spread
lastTradePrice          : string    - Last trade price
competitive             : string    - Competitiveness score (0-1)

rewardsMinSize          : string    - Min size for rewards eligibility
rewardsMaxSpread        : string    - Max spread for rewards

image                   : string    - Market image URL
icon                    : string    - Market icon URL
resolvedBy              : string    - Address that resolved (or will resolve)
restricted              : bool      - Geoblocked in some jurisdictions
```

---

## 7. Gotchas & Limitations

### Token ID Format Inconsistency

The biggest gotcha: **token_ids have two formats** depending on the API.

| Context | Format | Example |
|---------|--------|---------|
| `markets get`, `clobTokenIds` field | Hex (`0x...`) | `0xa6d8e1b575e4a2c8610d...` |
| CLOB batch response keys | Decimal integer | `75467129615908319583...` |
| `data holders`, `token` field | Decimal integer | `75467129615908319583...` |
| CLOB command input | Hex (`0x...`) | Pass the hex form |

To convert: `int(hex_token_id, 16)` gives the decimal form.

### `clob price` Requires `--side`

Unlike midpoint, the `price` command requires `--side buy` or `--side sell`. Omitting it gives an error.

### `price-history` Interval Is a Lookback Window

The `--interval` parameter (`1m`, `1h`, `1d`, etc.) is a **lookback window**, not a candle size. With `--interval 1d`, you get data points roughly every 60 seconds over the last 24 hours. Use `--fidelity N` to control point count.

Returns `[]` for tokens with no trading activity in the window.

### `clob market` vs `markets get`

Two different endpoints with different schemas:
- `polymarket markets get <id-or-slug>` returns the **Gamma API** market (rich metadata, event nesting, volume breakdowns)
- `polymarket clob market <condition_id>` returns the **CLOB API** market (trading parameters, token array with outcomes, rewards config)

Use `clob market` when you need: tokens-to-outcomes mapping, reward rates, accepting_orders status, minimum_order_size.
Use `markets get` when you need: volume stats, dates, images, event context.

### `markets list` Order Fields

Valid: `volume`, `liquidity`. Invalid: `volume_num`, `liquidityNum` (returns 422 error).

### `events list --tag` Is the Only Tag Filter

There is no `--tag` flag on `markets list`. You must filter by tag via `events list --tag <slug>`, then extract markets from each event.

### `clob markets` Pagination

`polymarket clob markets -o json` returns ALL CLOB markets, paginated by cursor. The response includes very old/closed markets. Use `--cursor` for pagination. Response structure:

```json
{
  "data": [...],
  "next_cursor": "..."
}
```

### Batch Spreads May Return `null`

`polymarket clob spreads` returned `null` in testing. Individual `clob spread` works fine.

### `data trades` Requires Wallet Address

Trade history is per-wallet, not per-market. To find trades for a market, you need a wallet address. You can discover active traders via `data holders` or `data leaderboard`.

### `data volume` Takes Event ID, Not Condition ID

Unlike `data open-interest` (which takes condition_id), `data volume` takes the numeric event ID.

### `outcomes` and `clobTokenIds` Are JSON-Encoded Strings

These fields are strings containing JSON arrays, not actual arrays. You need to parse them:

```python
import json
outcomes = json.loads(market["outcomes"])        # ["Yes", "No"]
token_ids = json.loads(market["clobTokenIds"])    # ["0xabc...", "0xdef..."]
# outcomes[i] corresponds to token_ids[i]
```

### Authenticated Commands

Commands marked `(authenticated)` in `clob --help` require a private key via `--private-key` or env/config. These include: `orders`, `create-order`, `cancel`, `balance`, `trades` (CLOB trades, not data trades), `api-keys`.

### Rate Limits

No explicit rate limit documentation in the CLI. In practice, rapid sequential calls work fine. For bulk data gathering, prefer batch commands (`midpoints`, `books`, `batch-prices`, `last-trades`) over individual calls.

### All Prices Are Strings

Every price, volume, size, and amount value is a **string**, not a number. Always parse to float/Decimal for calculations. The only exception is `fee-rate` which returns `base_fee_bps` as a number.
