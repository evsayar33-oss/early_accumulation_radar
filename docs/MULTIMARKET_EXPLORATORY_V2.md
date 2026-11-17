# BIST, US microcap and altcoin independent candidate experiment — V2

**Source design:** derived from the user's quant_superlab SENTEZ_RAPORU.md and VARLIK_STRATEJI_KITABI.md, which report large-scale price-pattern search instability, weak holdout selection persistence, and the importance of trading delay, costs, and independent selection. These reports do **not** demonstrate alpha on the EAR smallcap/altcoin universe.

## Frozen and visible before this PR's CI run

Six **fixed**, no-grid, long-only price/volume families applied identically to each of 3 markets; 18 market-family attempts, including every failure in the report:

1. compression_breakout: above prior SMA100, prior 20-bar range <=22%, RVOL >=1.7, close above previous 20-bar high and in top 30% of daily range
2. high_volume_trend: above prior SMA100, RVOL >=2.0, 20-bar return between 2–30%, bullish bar, close in top 30% of daily range
3. pullback_reclaim: above SMA100, 60-bar return >=8%, 5-bar dip -9% to +1.5%, RVOL >=1.2, bullish bar
4. range_base_break: prior 60-bar range <=35%, RVOL >=1.3, close above previous 60-bar high in top 35% of daily range
5. quiet_trend_acceleration: above SMA100, 60-bar return >=6%, median 60-bar daily range <=6.5%, RVOL >=1.6, 5-bar return 0–10%, bullish bar
6. capitulation_reversal: 5-bar drop 8–23%, RVOL >=2.5, bullish bar closing in top 30% of daily range

No historical bars after the **signal close** are used for the trigger; simulated observation uses next session OPEN and the fifth following CLOSE. Also records next-next OPEN (one more session delay) and 2x round-trip stress costs. Suppress overlapping five-session events per symbol and family. Require 30/15/15 nonoverlapping per-market event observations across chronological 60/20/20 partitions. Outputs include n, mean and median net, positive fraction, symbol count, 2x cost and delayed-entry returns. **Event averages are not investable NAV, independent trade samples, or a market benchmark.** All statuses explicitly block automatic PAPER/live promotion.

Exclude USD-pegged coins including FDUSDUSDT and TUSDUSDT, which were present in the earlier source artifact. The historical data pipeline itself is not changed, to preserve existing evidence; this study filters pegged assets from its research universe and names exclusions explicitly.

## Important prior exposure

The V1 historical discovery report has already disclosed the latest 20% holdout to researchers. Thus the same period is **NOT a new blind confirmation** for V2. The report labels it `previously_exposed_holdout` and `pristine_holdout=false`. New independent historical validation requires a previously unseen dataset, further forward observations, PIT/delisted inclusion and verified corporate actions; a positive V2 result is **exploratory only**.

Source original CSV: GitHub Action #44053703288, artifact historical-discovery-44053703288, 38,373 actual bars across 31 current-symbol series. This dataset includes known survivor selection and some pegged coins. The code does not manufacture missing data.

## Preliminary local exploratory scan (not CI verification)

On the previously downloaded artifact (run #44053703288), the six-family engine was executed offline before publishing this PR. The strongest *unconfirmed* pattern is CRYPTO high_volume_trend, with mean assumed-cost-adjusted event returns of +3.18% (train; n=55), +1.12% (validation; n=28), +1.74% (previously seen holdout; n=39). However its delayed-entry mean in the exposed holdout is -0.04%, and data are current-survivor biased. It **fails the robust gate**. BIST high_volume_trend has -5.35% in validation; US high_volume_trend has -11.80% in validation. No family is shown as fully verified profitable.

This exercise is **hypothesis exploration**, not post-hoc parameter tuning to force a winner. Old failures are preserved. The next technical priority after a clean CI/main run is broader historically verified smallcap/altcoin coverage and risk-aware independent portfolios and controls, NOT loosening the thresholds.

No existing PAPER, trading, ledger, V4 source or V3 decision files changed.
