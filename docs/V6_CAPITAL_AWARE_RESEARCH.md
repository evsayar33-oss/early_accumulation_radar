# V6: Capital-aware discovery — minimum viable portfolio evidence

## Why V5 is not enough

The first V5 workflow succeeded, but its prospective registry contained 3 new signals and **0 matured settlements**. Eleven crypto secondary-history references succeeded; US independent historical price audit had 0 successful references. The historical results were event averages and matched-survivor comparisons: neither was executable portfolio NAV. V6 addresses **portfolio simulation**, not a claim that real alpha has already been discovered.

## Scope of V6

- Reuse the **same frozen** 3 baseline, 6 V2, 3 V3 and 3 V4 families. Do not retune or optimize on the already-exposed validation/holdout.
- Produce a separate capital-aware simulation **per market and family** on quarantined historical prices, starting with $10,000 notional units, at most five concurrent positions, at most 20% of starting capital per position, and 0.5% participation in the daily reported base-volume.
- Enter at **next session open**, never at signal close; exit after five bars at the modeled daily close. Do not rank entries using future returns: deterministic hash ordering enforces contention independent of outcome.
- Include the already configured market-specific round-trip trading costs and add **15 basis points of entry and exit slippage each**. Track cost, rejected trades, utilization, cash, marked-to-market NAV, closed trade win fraction and max drawdown.
- Chronological partitions (60/20/20) are independently reinitialized, with overlapping trades across boundaries excluded. Therefore per-partition performance cannot be compounded into a single continuous investment NAV.
- Any *positive* screen is only an exploration lead awaiting **independent prospective evidence**. This module never starts PAPER, never trades, and never promotes a strategy.

## Still missing

- Survivor-only current symbols, missing delisted instruments, historical PIT market-cap/free-float and split/dividend verification remain unresolved. Quarantine can itself induce selection bias.
- Candle OHLCV is not an intraday execution/order book. Daily reported volume as base quantity may be wrong for some vendors; a fixed participation cap and 15bps/side slippage are research assumptions, not measured order fills.
- Peer-matched comparisons and actual prospective trade results are still separate. There is not yet a complete risk model or trustworthy price-impact model.
- The previously viewed historical holdout is **not independent validation**. Multiple-hypothesis testing and statistical uncertainty must precede any positive efficacy claim.
- A positive modeled NAV is **not** an investable result. No historical or prospective profitability is certified.

## After merge

The existing automatic V5 workflow `V5 Autonomous three-market research and prospective evidence (NO TRADING)` incorporates the V6 portfolio screen in subsequent scheduled runs. It writes `out/v6_portfolio/report.json` and `report.md` to its existing 90-day run artifact, in addition to the normal append-only prospective evidence on the **unchanged** `research/auto-evidence` branch. No new scheduled task or recurring manual trigger required.

To inspect immediately, optionally run the existing workflow on `main` once after merge. This is optional, not a prerequisite for future scheduling.
