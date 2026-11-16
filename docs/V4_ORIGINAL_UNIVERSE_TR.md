# V4 Original Universe — read-only discovery

This restores a distinct research track aligned to the original goal: low-float, concentrated-ownership, shallow-liquidity, anomalous-volume assets **before** a potential price expansion. These characteristics describe research risk flags, not proof of manipulation or future returns.

* DEX: twice-daily discovery samples from DexScreener public token profiles and token-pairs endpoints; unverified liquidity, volume, pair age, FDV and market-cap observations. This is **not** a comprehensive universe or a trading signal.
* Ownership concentration, real free float, token locks, contract risk and issuer fundamentals are **not observable from these endpoints**. The gate is deliberately not allowed to mark these fields as verified. No DEX price or trade strategy is approved.
* BIST and US small-cap equities are **NOT_CONNECTED**; they require point-in-time free-float, holder and financial data sources before any historical performance research. Never fabricate coverage.
* Legacy BTC/ETH/SOL V2/V3 and PAPER tasks are untouched and remain separately labeled legacy research; their failed historical screen cannot stand in for original-universe performance.
* Outputs: `discovery.json`, `report.md` as 90-day workflow artifacts. There are no orders, PAPER entries, state mutations, SHA branch writes or trading alerts.
* Sources can rate-limit or fail. Source outages produce `SOURCE_OUTAGE_NO_SIGNAL`, not a candidate.
* Screen parameters (USD): liquidity 15k–2m, 24h volume ≥10k, pair age 1–180 days. These are provisional discovery bounds, not optimized profitability thresholds.
* Next proof gate: independently verified float/concentration and survivorship-free historical candidate snapshots, followed by frozen prospective observation and out-of-sample tests.
