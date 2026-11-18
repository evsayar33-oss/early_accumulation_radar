# V8 — Perpetual universe monitoring (early motion RESEARCH, not trading)

## Why PIPPIN was missed on 18 November 2026

User-provided screenshot: **PIPPINUSDT Perp** on a 1h chart, 24h approximately **+66%**, observed 0.01856 USDT, intraday low/high 0.01073/0.02197. Low-to-high is approximately +105%, but no strategy is allowed to claim it would have entered at the low or sold at the high.

EAR V2/BTC-ETH-SOL observed selected SPOT tokens, V5/V6/V7 use Binance *spot* current-survivor samples with DAILY OHLCV, and V7 DEX profiles are young on-chain pairs. None is a market-wide **linear USDT perpetual universe** observer. No PIPPIN pre-move time-stamped evidence existed; post-event reasoning is *not a valid backtest*.

## New isolated observation layer

- Discover **ALL active USDT-settled linear PERPETUAL** instruments from Binance USD-M Futures `exchangeInfo`, OKX linear USDT SWAP `public/instruments` and Bitget Classic USDT-FUTURES contract metadata, with no hardcoded PIPPIN whitelist or small fixed 36/48-asset sample. Poll all three venues' all-symbol 24-hour ticker snapshots. GitHub's live pre-merge smoke found **OKX 525 eligible USDT perpetuals including PIPPIN** but Binance futures was unavailable from that runner; Bitget was added as a third independent fallback, with its live accessibility still requiring verification. Each provider outage is visible; no fake second- or third-venue confirmation.
- Preserve strict venue/market identity: only `PIPPINUSDT` Binance USDT-M PERPETUAL corresponds to `PIPPIN-USDT-SWAP` OKX linear USDT swap. Never combine SPOT, inverse contracts, premarket instruments, settled contracts or stale/timing-invalid prices.
- Scan current public prices on a best-effort schedule twice an hour (UTC :09 and :39). GitHub Actions may skip/delay cron; THIS IS NOT realtime, guaranteed 5-minute discovery, early forecasting, or continuous tape.
- For each asset, require **a prior, real scan of that same venue**, at most 100 minutes earlier. Measure its actual price move since that prior scan and label `EARLY_UPWARD_MOTION_WATCH`, `EARLY_DOWNWARD_MOTION_WATCH`, or `IMPULSE_ALREADY_IN_PROGRESS`. Extreme >75% single-interval moves are retained as `EXTREME_PRICE_MOVE_SCALE_UNVERIFIED` and cannot create fictitious PnL. First scan has no synthetic prior or assumed trade entry.
- Historical 24h quote turnover is a MINIMUM DATA QUALITY/LIQUIDITY PROXY, **not** actual 30-minute trade volume, signed flow, open interest, borrow, float or fillability. At least 100,000 USDT quote turnover for a movement to be flagged, not a strategy-profit optimization. Binance and Bitget report native quote-currency `quoteVolume` (USDT in this USDT-M scope). OKX v5 linear SWAP `volCcy24h` is BASE units and `vol24h` is contract count. If `volCcyQuote24h` is absent, this research estimates 24h USDT turnover as `volCcy24h × last price`, marked `rolling_24h_turnover_estimated_from_base_units=true`; this is an **approximation** (not an exact 24h turnover) and must never be read as evidence of executed quote-currency volume.
- Cross-venue 4% price-dispersion tolerance across available independent venues is a consistency screen, not proof of trade opportunity. Divergent prices are recorded but never sent to Telegram. Single-venue alerts are explicitly `TEK BORSA — TEYİTSİZ`; they are not a multi-exchange vote.
- The movement category thresholds (0.8%, 6%, 20% 24h) only separate early observations from already-running moves. They are **not** validated entry parameters, alpha thresholds or final optimized strategy logic.
- Append time-ordered, SHA-linked, compressed full-universe snapshots to a **dedicated** `research/v8-perp-forward` branch; only observed future snapshots near 30/60/240-minute horizons produce underlying price-change diagnostics. Future missing snapshots remain PENDING. Neither a record's timestamp nor event is backfilled from historic candles.
- Optional capped (max three per run) Telegram messages clearly state a move was *already observed*, not predicted, and that perpetuals carry liquidation and funding risk. There are no BUY/SELL messages or orders. 90-minute same-asset/direction cooldown bounds duplicate observed alerts.
- Repo size warning: the persistent branch stores compressed snapshots **for all tracked contracts** per scan; monitor longitudinal growth, tune storage if this becomes a repo capacity risk. Artifact reports are separately retained for 30 days.

## Security and governance

This is a separate research workflow, no changes to V2 Telegram accumulation rules, V3 PAPER, V5/V6 backtests, V7 DEX first-seen, their historical ledgers or existing LIVE/DEMO services. It uses **only unauthenticated public market endpoints** and the existing optional Telegram bot secret. If all available Binance, OKX and Bitget APIs fail from GitHub's network, the job fails visibly and never writes a fabricated scan. No short funding/borrow/margin/book-depth/executable entry, no transaction cost or revenue proof, no recommendation to chase a 60%-100% move.

**After merge:** `V8 all-symbol perpetual early-motion evidence (RESEARCH ONLY)` executes once automatically on the workflow change, then at :09/:39 UTC (best-effort). On the first run there is a baseline only; a later successful run is essential for any *causal* price-motion alert. Check both provider success/coverage and followup evidence **before** calling the PIPPIN class covered.

## Remaining gap

This addresses **a missing perpetual asset class and the wrong daily-only observation cadence**, NOT the full original low-float/early accumulation problem. To catch an explosive rally before an initial 30-minute snapshot, real timestamped 1–5 minute market data, contract events, open interest, funding, signed order flow, cross-exchange depth, and an independent prospective signal-performance study would still be necessary. Any newly observed success must be weighed against all false positives and costs.
