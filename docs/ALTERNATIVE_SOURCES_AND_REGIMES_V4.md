# V4 – Alternative price sources and new event-time regime research

This opt-in workflow extends historical exploration without changing any PAPER or live system. No returns are promoted to live authorization.

## New independent data checks
- **Crypto:** Compare the latest 200 Bybit V5 public **spot** daily closing prices for up to 12 Binance-listed altcoins against common-date Binance OHLCV from the existing expanded dataset. Venue basis and different trading conditions are not provider errors by themselves. The Bybit endpoint's public `/v5/market/kline` spot category, D interval, maximum 1000 bars is documented: https://bybit-exchange.github.io/docs/v5/market/kline.
- **US equities:** Compare Stooq public CSV history for up to 12 tickers with Yahoo's daily closing prices. Symbols with inaccessible Stooq data are marked unavailable. Split/dividend adjustment conventions may differ, so mismatches require review rather than blind price substitution.
- **BIST:** KAP current company directory identifies listed issuers, but it is **not** an independent audited daily OHLCV price source. BIST comparison explicitly marks `NO_VERIFIED_SECOND_PROVIDER`. No bogus vendor agreement or historical PIT claim.
- Reports include overlap counts, median and largest absolute difference, provider failures, and explicit sample limits. Secondary data cannot change strategies or create PAPER approval. Selection is alphabetical among existing selected symbols and not performance-selected.

## Three different market-event hypotheses
1. **Overnight gap continuation:** BIST/US only, +2.5%–12% open gap, trend-confirming positive candle and relative volume >=1.5.
2. **Overnight gap fade:** BIST/US only, -2.5% to -12% open gap followed by positive candle, relative volume >=1.5 and prior-close reclaim.
3. **Post-shock volatility cooldown:** all three markets; prior session range >=2.5x typical 20-bar daily range, next session range <=0.6x baseline, relative volume <=0.85, closes above prior close. No crypto-specific overnight-gap proxy is fabricated.

All three families use next daily open entry, five-bar hold, default and double costs, one extra session execution delay, 60/20/20 event-time chronological splits, >=30/15/15 events and >=3 symbols per split. Prior holdout remains **exposed**. Counts and returns are event-level, not portfolio NAV.

## Known bias and limits
This adds independent **price consistency** checks and new market behavior hypotheses, not historical membership verification. The universe remains current surviving assets. Missing delistings, as-of market cap, free float, corporate actions, realistic market impact and independent prospective results prevent any reliable claim of profitable executable strategy. No provider receives credentials and no trading endpoints are called.

## One manual run
After a green PR CI and merge: GitHub → Actions → **Expanded BIST US altcoin historical discovery (RESEARCH ONLY)** → branch `main` → **Run workflow** (defaults 36/36/48). Inspect the new `secondary_source_audit/` and `regime_events/` in the resulting artifact, as well as the step summary.
