# V12 — BIST / US independent automatic early-pattern research

## Scope and source chain

This is a NEW non-trading research system in the same repository, not a
modification of V3 PAPER, V8–V11 crypto, V5 or V7 historical records.

* Source: a successful trusted-main V5 run's exact downloadable 90-day
  out/data_quality/screened_prices.csv and out/data_quality/report.json.
  V5 sources currently include a KAP current directory, a US current stock
  screener and unofficial Yahoo daily charts, all subject to failure.
* Only BIST and US quality-screened instruments are admitted to V12.
* Automated triggers: trusted successful V5 workflow completion (V5 is
  scheduled Tue–Sat, 03:47 UTC), or a manual dispatch providing the ID of
  a successful, main-branch, seven-days-or-newer V5 run. No new API keys.
* Every execution verifies source SHA and provenance, computes features only
  with bars whose dates are before the execution UTC date, and stores the
  first sighting for each market, symbol and session exactly once.
* Append-only SHA-verified observation, outcome, frozen-rule and decision
  registries are isolated on research/v12-equity-pattern-evidence, separately
  under research_archive/v12/BIST/ and /US/.
* On a failed source run, missing artifact, stale source, SHA corruption,
  vanished prior ledger, or code drift, V12 fails/pauses closed. Old evidence
  cannot be erased or transformed into fresh results.

## Ten same-asset and contemporaneous relative metrics

Relative volume, local-currency turnover ratio, daily quiet price, rolling
range compression, range/volatility expansion, close near high/low, 20-session
breakout, drawdown base, and 20-session strength relative to same-market peers.
The baseline consists of 60 strictly prior completed sessions, and
concurrent peers are known at the same as-of scan. No alleged open interest,
funding, float, share-holder concentration or intraday CVD is imputed.

There are 10 singleton motifs and 6 predeclared multi-metric combinations,
tested for both 5-session upside and downside terminal-return extremes:
BIST +/-12%, US +/-15%. These are fixed exploratory thresholds, not historically
optimized. Every future outcome uses the first future observed session
open following the actual V12 observation UTC date, and a subsequent
1/3/5/10th completed session close. Price scale gaps and missing entries are
quarantined or left pending, not filled backwards. Assumed long-only friction
is inherited from the pre-existing exploratory research (COST BIST 2%, US
1%); actual order execution and short borrow are NOT verified.

## Automatic discovery and prospective validation

Once 5-session outcomes actually mature, V12 compares each pre-move case
with same-observation-date, same-liquidity-band and same-prior-momentum-band
non-movers. It preserves all sampled controls, not only winners. Every
prespecified rule (both move directions) is evaluated with one-sided Fisher
association, and Benjamini–Hochberg multiple-testing correction.

To freeze a provisional hypothesis: >=15 matched cases, >=90 matched
non-movers, >=5 case symbols across >=4 days, >=5 exposed cases, control
FPR <=15%, sample lift >=1.6, and BH-FDR q <=0.05. One new trial per
market/direction may be frozen at the precommitted UTC Monday checkpoint, with
90-day cooldown. Trials start on the following UTC day, run for 60 calendar
days, and close exactly once after an 18-day outcome-maturation grace.
No training outcome may be relabelled as a prospective holdout; code drift
pauses active trials instead of silently modifying their rules.

Telegram (if already configured) is used only for a newly frozen
candidate or for a completed independent trial, after the branch push. Empty
daily research reports do not produce notifications. Daily reports appear
in Actions step summaries, 90-day artifacts and the dedicated archive.

## Important scientific limitations

* These equity candidates come from today's surviving stocks. Historical
  point-in-time universe, bankrupt/delisted instruments, true free float,
  corporate actions and executable order-book liquidity are unverified.
* They are daily OHLCV observations, NOT an intraday early-warning system;
  the V8 crypto 30-minute futures source is not an equity data source.
* Historical bars only initialize each stock's prior distribution; every
  association test is trained only on subsequently persisted first-seen
  events and their genuinely later observed 5-session outcomes.
* Same stocks observed on multiple days are statistically dependent. Fisher
  p-values and matched-control precision are exploratory indicators, not
  robust issuer-clustered inference or deployment approval.
* No strategies are promoted into V3, no new PAPER fills, live orders,
  guaranteed profitability, or verified downside short returns.

## How to inspect results

Actions workflow:
V12 Independent BIST US Equity Pattern Discovery (RESEARCH ONLY)

Evidence branch: research/v12-equity-pattern-evidence

File groups per market: observations.jsonl, outcomes.jsonl,
frozen.jsonl, decisions.jsonl, latest.json.

Review asof_observations_total, matured_primary_cohort,
primary_label_counts, all_rule_statistics, active_trials and
completed_holdout_decisions before any future strategy research.
A zero count in the initial weeks is expected and not a discovered strategy.
