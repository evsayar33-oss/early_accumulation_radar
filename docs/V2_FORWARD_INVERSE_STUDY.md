# V2 accumulation versus inverse hypothesis: forward evidence

**Hypothesis:** Alerts labelled `BİRİKİM ADAYI` might be contrarian bearish/avoid-long events, while `DAĞITIM RİSKİ` could sometimes predict a recovery. This is an unverified hypothesis, **not** permission to flip the existing signals or start shorting.

We reuse the hash-chained `paper/early-radar-v2/observations/scan.jsonl` records. Current Telegram candles come only from Binance 1-minute **completed** spot bars, while the number of venues verifies quote/market accessibility and **does not** imply the taker-buy percentage is multi-venue.

For each non-overlapping asset/kind signal:
- Do **not** take the alert close as an executable fill. Require the **first subsequent** independently captured Binance closed-candle snapshot within 40 minutes as a theoretical entry.
- Compare 30, 60, and 240 minutes from that observed entry against a subsequently observed closed-candle price within an extra 40-minute observation window.
- Test original long-vs-bearish for accumulation; original bearish-vs-long for distribution. Both signed directions include a symmetric 30-bps round-trip cost estimate, but **bearish-direction results are not short execution PnL**. Actual shorting needs a derivatives instrument, funding, margin, liquidity and fills.
- Do not interpolate gaps, fabricate missing exit prices, update previously observed rows, or override the Telegram/PAPER signal. Reports explicitly mark incomplete horizons as PENDING.
- Require >=30 completed matched comparisons in a specific asset/horizon/signal-type group before even considering directional selection. Even then prospective independence and multiple-testing corrections are needed.

**Current verified example:** The 2026-11-17 18:29:55 UTC (21:29 Turkey) SHA-linked ETH 1801.05 and SOL 72.84 accumulation alerts are present as the ledger's latest record at time of analysis. The repo did not yet contain later validated observations to calculate what happened after the alert. It would be misleading to declare either original or inverse profitable.

**Automation:** This adds one offline research step to the existing every-30-minute `Research V2 sampled tape and immutable evidence` workflow **after** the original ledger is saved and integrity-checked. The machine-readable report and Markdown summary are uploaded with the existing 30-day workflow artifact and written to the GitHub job summary. No new workflow, scheduler, credential or auto-PR; no modification to the append-only ledger or production/PAPER trading.

Only completed observed outcomes, sample size, cost assumptions and differences between the normal and opposite hypothesis are reported. Negative results remain visible.
