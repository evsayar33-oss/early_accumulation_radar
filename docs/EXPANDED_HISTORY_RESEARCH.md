# Expanded three-market historical research — current-universe coverage experiment

## Why
Prior V1/V2 research on ~31 current survivors was too small to assess most BIST and US early-accumulation hypotheses. This PR is a separate, opt-in workflow; it does not modify V2/V3 PAPER, V4 evidence branches, or the production scanner.

## Real data selection and controls
- BIST: select up to 36 current symbols from public KAP company directory, sampled by deterministic SHA-256 order; **neither small market cap nor public float is verified**. Yahoo 5y OHLCV is then fetched. Current listing cannot show delisted historical firms.
- US: select up to 36 **currently** small/microcap stocks using the existing TradingView screener 10m–500m USD market cap, 25k+ daily share volume, 0.25–50 USD price. Yahoo 5y OHLCV. This excludes delisted symbols and other securities omitted by the screener.
- Crypto: select up to 48 **currently** trading spot USDT symbols by current CoinGecko $10m–$500m market cap, excluding USD-pegged tokens and ambiguous duplicate CoinGecko tickers across pages. Binance 5y daily klines. Current market caps/listings are not historical.
- At least 300 daily bars for equity; 180 for crypto. A source outage is recorded by symbol in manifest; require at least two usable series per market, otherwise fail. Price series and current snapshot metadata are stored as artifacts with CSV SHA-256.
- Full pre-existing 3-family baseline and 6-family V2 diagnostics execute on the expanded real-data CSV. 18 exploratory V2 family-market cells, with double-cost and delayed-entry sensitivities. No parameters are optimized to win this dataset.

## Critical research limits
This improves *coverage*, not historical point-in-time membership, historical free float, historical market caps, delisting inclusion, corporate-action adjustments, spread/market impact or independent holdout status. Previously viewed holdout is flagged as exposed in V2 diagnostics. Any positive outcome is **exploratory** and does not authorize PAPER/live. BIST results are **not** labeled smallcap-specific until contemporaneous size/float evidence exists. US and crypto also lack historical-cap proof. There is no independent prospective performance claim.

## One user action after green PR CI
Merge PR; in GitHub Actions select **Expanded BIST US altcoin historical discovery (RESEARCH ONLY)**, branch **main**, then **Run workflow**. Defaults 36 BIST / 36 US / 48 crypto; choose smaller limits only for diagnosing provider rate restrictions. The successful job summary reports candidate performance; artifact `expanded-history-research-<run_id>` contains CSV, selection manifest, baseline and six-family reports. Do not run existing production workflows manually for this PR.

No action is needed on any PAPER or evidence branch.
