# V6 both-direction event discovery (upside + downside)

The main goal is to detect **early expansion up and early expansion down**, rather than retrospectively treating extreme daily changes as easy profit. The independent research step has four predeclared signal families:

- `upside_expansion` — positive 20-day high breakout, range and volume expansion, strong closing location and an uptrend. **Long-only research**.
- `downside_expansion` — negative 20-day low breakdown, high volume, expanded daily range, weak closing location, downtrend. **Downside-risk alert** only, not an executable short.
- `capitulation_recovery` — strong five-day fall, a positive close, elevated volume and upper-range location. **Long-only reversal research**.
- `blowoff_exhaustion` — very strong prior five-day rally then high-volume, high-range lower-close location. **Downside-risk alert** only, not short execution.

The output is an event report for BIST, US and crypto with 60/20/20 chronology, next-open forward measurements and base/double costs + delayed-entry sensitivity. The previously examined holdout is not independent. A latest-closed-bar watchlist is diagnostic; it is not a realtime feed or guaranteed pre-move alert. No live orders or Telegram alerts are added.

## Critical integrity separation

- A **price discontinuity** (open >=2x / <=0.5x prior close) is merely a **suspected** scale change, rebase, split, venue event or bad price. Daily OHLC data cannot confirm the corporate action. That date and signals using its previous 20 bars or its holding period are excluded from event-PnL diagnostics.
- Exchange-specific Pre-IPO contracts, redenominated synthetic derivatives, unsupported quote assets, delisted instruments and short positions are **not imported** into the Binance spot universe. No claim to have captured the Anthropic pre-IPO screenshot's change.
- No short sale PnL is computed as investable performance: for bearish ideas the report stores only a signed *directional diagnostic*. Borrow/locate availability, short-sale restrictions, margin calls, derivatives contract multipliers, funding, liquidation and order fills have not been modeled.
- The prospective append-only registry from V5 is unchanged. New families are NOT registered into PAPER or prospective-ledger without separate scientific review; historical performance cannot self-authorize trading.

## Installation

One PR merge is enough to add the `V6 bidirectional breakout and crash event diagnostics (NO SHORT ORDERS)` step to the existing V5 scheduled workflow. Each run includes `out/v6_bidirectional/report.json` and `report.md` in the 90-day research artifact. No extra manual workflow run is necessary for regular execution.

## Research gaps still blocking an investable claim

Current-survivor selection, absent historical delistings and as-of market cap/float, unverified split/event metadata, daily rather than intraday alerts, portfolio risk for short positions, and independent untouched-forward confirmation. Realtime identification of a sudden move would require timestamped intraday trade/book and instrument metadata feeds plus execution evidence. An up or down spike visible in hindsight is not necessarily a tradeable opportunity.
