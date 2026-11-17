# V3 research: three new hypotheses and bias audit

This is **not** a claim that survivorship bias has been removed. The available dataset still consists of current survivors only, excludes delisted securities, has no historical market-cap or float evidence, lacks verified corporate-action adjustments and reuses a previously inspected holdout. No historical period is now pristine.

## New predeclared hypotheses (no parameter grid)
1. **Relative-strength rotation**: top 20% of contemporaneous 20-session returns among >=5 current-universe peers on the same date, positive trend versus prior SMA100, >=1.1 relative volume and 20-session gain between 0% and 50%. Rank uses only information available at signal close, but peer membership is survivor-biased.
2. **Downside exhaustion**: >=18% below prior 60-session high, 5-session decline of 5–20%, relative volume >=1.8, strong closing location and positive one-session return. Hypothesis: a selloff exhausts before reversal.
3. **Volume dry-up reclaim**: above prior SMA100, median volume of prior five sessions <=65% of preceding 20-session median, current relative volume >=1.3, close above prior five closes, and 20-session return -6% to +25%. Hypothesis: supply contracts before renewed demand.

The 3 families run on BIST, US and crypto (9 new cells) using next-open entry and fifth-following close, 2x round-trip costs, one additional session entry delay, chronological 60/20/20 partitions, non-overlapping per-symbol/family events, >=30/15/15 event minima, >=3 contributing symbols per period and **worst leave-one-symbol-out average** to reveal dependence on one winner. Results are research diagnostics, not executable portfolio NAV.

## Bias controls added
- Explicitly expose the prior holdout as `previously_exposed_holdout` and prohibit PAPER/live approval.
- Require >=5 contemporaneous peers for cross-sectional strength ranks; rank uses same-day closes, never future closes.
- Require at least three distinct symbols per time partition; report worst average after removing any one symbol. This **mitigates single-winner concentration**, not survivorship bias.
- Include negative findings in reports; no family selected based on earlier V2 holdout.
- Preserve original V1/V2 diagnostics and source manifests; no production, PAPER or evidence ledger edits.

## Follow-up needed for genuine bias correction
Acquire licensed or auditable historical constituent/market-cap snapshots and delisted prices; verify splits/dividends, historical symbol mappings and realistic execution costs. Until then all V3 outcomes are exploratory, including positive ones. The report does not fabricate PIT provenance.

## Manual step
After PR merge and green CI: GitHub Actions → **Expanded BIST US altcoin historical discovery (RESEARCH ONLY)** → branch **main** → **Run workflow** (default 36/36/48). The new V3 report is appended to the job summary and stored in `new_hypotheses_bias/report.json` and `report.md` inside the workflow artifact.
