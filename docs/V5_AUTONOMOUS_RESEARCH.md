# V5 one-merge autonomous research / source audit

This PR addresses repeated manual launches and blind secondary-source failures. **One merge is sufficient to enable weekly automatic research.** The first run may be triggered manually if immediate results are desired; it is not required for scheduling.

## What is automated
- Every **Wednesday at 06:23 UTC** (GitHub Actions cron; actual dispatch can be delayed), run the existing expanded 36 BIST / 36 US / 48 crypto current-universe historical collection, original baseline, V2/V3/V4 hypothesis families, and independent source checks.
- Preserve the previous manual `workflow_dispatch` option. A scheduled run now uses explicit default input values instead of empty strings.
- Produce one `research_triage/report.md` and machine-readable `report.json` combining coverage, secondary-source availability, and exploratory candidates. All underlying evidence and source attempts remain in the 90-day workflow artifact.
- Keep GitHub `contents: read`, no write credentials, no bot trading, no PAPER changes, no automatic strategy promotion.

## Secondary-source changes
- Binance altcoin closes are now checked against Bybit spot first, then **OKX public spot history** if Bybit is blocked, absent or has insufficient overlapping bars. The OKX request uses `instId=BASE-USDT`, `bar=1Dutc` to align UTC-day boundaries, and verifies positive finite closes.
- Stooq remains the optional US independent history provider. For every failed secondary-source attempt, retain provider, error category, and a truncated diagnostic string in the artifact. A failure never becomes a successful comparison.
- BIST second-source audit is explicitly blocked until a verified, licensed or auditable independent OHLCV source is available. KAP listing is not historical price validation.
- Bybit and OKX are **different trading venues**, and Stooq and Yahoo can use different corporate-action adjustment conventions. Differences are **review flags**, not definitive data corruption.

## Unified triage safeguards
- Fail-closed when no independent price comparison succeeded, when US or crypto comparison is absent, or if any market has fewer than 2 usable series / <65% coverage.
- The triage step reports blockers without hiding the underlying research outputs. These warnings do not claim that a GitHub workflow failure occurred.
- V2/V3/V4 candidates are always tagged `EXPLORATORY_ONLY_REQUIRES_NEW_BLIND_DATA`. Positive backtests cannot automatically start PAPER or live trading.
- All previous survivor selection, missing delisted history, missing as-of market cap/free float, corporate-action uncertainty and already exposed holdout caveats remain **unresolved**. This PR does not falsely claim PIT correction or profitability.

## After merge
No manual Actions run is required for weekly scheduling. To obtain **immediate** results, optionally run GitHub Actions → `Expanded BIST US altcoin historical discovery (RESEARCH ONLY)` → `main` → `Run workflow` with defaults. Inspect the job summary and `research_triage/` in the artifact.

Research continues at a fixed weekly cadence, but discovering a profitable strategy is not guaranteed. Production and PAPER workflows are unchanged.
