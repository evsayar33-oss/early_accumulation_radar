# V14 — BIST / US autonomous continuity and honest early-accumulation monitoring

Research only. **No orders, no new PAPER positions, no retroactive backtest winners.**

## What was actually broken

V5 collected market data, V12 independently froze BIST and US first-seen
observations and 1/3/5/10-session outcomes, V13 checked cost-aware strategy
candidates. They already had on-success workflow chaining, but no independent
orchestrator to recover an unexpectedly delayed/missing chain.

V12 formerly settled only symbols present in the *current* V5 sample. If a
previously observed stock vanished from the latest sample, its outcome could
remain pending forever, even though subsequent real daily candles remained
publicly accessible.

## V14 architecture

- Existing V5 is the only source of **new first-seen** stock observations.
  Existing V12 independently studies 16 frozen research rules per direction
  and V13 screens hypothetical after-cost performance. These are exploratory;
  issuer float, historical PIT membership and executable liquidity remain
  unverified. No proprietary data source or paid service is added.
- The V12 amendment may fetch up to 20 previously first-seen **off-sample**
  symbols per market from Yahoo's public daily chart on each V12 run,
  **for settlement only**. Symbols are drawn exclusively from SHA-verified
  prior V12 observations. There is no new signal created by recovered bars.
  Every missing/failed symbol remains explicit. Recovered outcome metadata
  states that prices were from a later unofficial data request, not the
  V5 artifact or a verified executable fill.
- A V12 methodology/code SHA change is deliberate: old signals can still
  receive factual later settlement observations, but their features are not
  silently relabelled as newly frozen rules when determining new strategies.
- V14 runs independently twice daily Tue-Sat and after the V13 workflow.
  It checks GitHub's **actual workflow runs** and both market's evidence reports.
  After allowing V5 up to **9 hours** of scheduler delay, it dispatches V5 if
  today's mature scheduled run did not complete. Once V5 succeeds, if its V12
  child is missing, it dispatches V12 using the **exact successful V5 run ID**.
  If V12 succeeds and V13 is absent, it dispatches V13. No job claims that
  dispatch means execution succeeded.
- It never skips SHA-integrity errors in the original workflows, and does not
  reset, overwrite, or retcon any V2/V3/PAPER, V5, V8 or V11 ledger.
  Attempts have a 12-hour backoff for manually dispatched runs; active jobs
  are not double-dispatched.
- Each run publishes a visible GitHub job summary plus 90-day JSON artifact.
  Existing V12/V13 dedicated branches retain historical immutable-ish
  SHA-linked source evidence; the V14 reporter **does not** push into them.

## Current scientific gates

V12 first-seen and V13 cost-only hypothetical performance are not proof of a
predictive or tradeable strategy. No BIST/US PAPER portfolio will be created
merely because a rule passes association or sample-profit filters. Separate
independent prospective validation and fillability requirements still apply.

Free daily OHLCV cannot establish true intraday absorption, real float,
market-making activity, historical delisted cohorts or L2 order-book liquidity.
GitHub Actions is best-effort scheduling, not a guaranteed market-data server.

## Inspect

Actions > **V14 Autonomous BIST US research continuity (NO TRADING)**.
Artifact: `v14-equity-continuity-<run_id>`.
Sources: V12 `research/v12-equity-pattern-evidence`;
V13 `research/v13-alpha-evidence`; historical V5 Actions artifacts.

Do not treat an empty 5-session cohort after two or three days as a failure.
A true failure is a missed eligible producer, broken SHA history, invalid
market data, persistent symbol loss or an attempted dispatch that failed.
