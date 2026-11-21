# V15 — autonomous crypto strategy research continuity (NOT TRADING)

## What was wrong

The existing V8 USDT-perpetual source enumerates broad OKX/Bitget/Binance
contracts and records real first-seen snapshots, but observed GitHub run
intervals have sometimes been **several hours**, despite nominal twice-an-hour
cron. V9/11's four-hour future outcomes require at least four subsequent
observations and no >90-minute gap, which means V11 can report zero
matured evidence despite healthy `success` GitHub jobs.

V13's new-asof guard requires the newest V8 scan to be <=90m old; its former
independent 4h schedule frequently landed on stale data and reported zero
observations. Both 46 V11 two-direction tests and 92 V13 rule-direction-horizon
tests existed already; weakening thresholds or retrospectively picking
winning past coins would have been misleading.

## Changes

1. **V9 independent-venue continuity fallback**: Try OKX first, but when OKX
   lacks the required *actual previous 2h history* evaluate Bitget/Binance
   against their own earlier observations. Never join distinct venue tapes,
   rewrite the older archive or use future outcomes as features. If a viable
   first venue already shows a moving/illiquid instrument, retain its
   exclusion rather than selecting a more favourable second venue.
2. **V13 causal trigger**: Immediately after a successful and trusted main
   V8 workflow completion, launch the unchanged, costed V13 engine against
   the real committed V8 evidence. The old 4h schedule remains a secondary
   check; the SHA source and duplicate-4h-bucket registry prevent replay
   creating earlier signals.
3. **V15 observer/orchestrator**: Independently verify the V8 hash chain,
   provider coverage, two-venue population, and actual complete 4h sampling
   windows. Audit V11/V13 summaries. If the V8 evidence is stale, V11's daily
   research is missed, or a fresh V8 archive was not consumed by V13,
   dispatch only the affected workflow after bounded timeouts and backoff.
   Existing V8 watchdog remains in place; no unlimited rerun loop.
4. **Genuine negatives**: Preserve empty samples, failed provider requests,
   90-minute gaps, insufficient OI or execution-depth information as
   diagnostics. No additional optimistic PnL, modified V13 profitability
   thresholds or buy/sell orders. This change deliberately updates the V9
   and V11/V13 methodology fingerprints; old frozen hypotheses, if present,
   are paused rather than retroactively relabelled.

No GitHub secret, paid API, server or broker integration is required.
GitHub Actions cron is best effort, not a guaranteed 30-minute feed.

## How to verify

Actions -> `V15 Crypto autonomous evidence and strategy discovery health
(NO TRADING)`; inspect `v15-crypto-discovery-<run_id>` JSON/report.
Watch `V8 all-symbol perpetual early-motion evidence (RESEARCH ONLY)`,
`V11 Autonomous Pattern Discovery and Prospective Validation (RESEARCH)`,
and `V13 Crypto Perpetual Costed Alpha Discovery (RESEARCH ONLY)`.

A green Action alone doesn't mean usable evidence; monitor
`observed_cadence_viable_windows`, V11 `matured_case_control_samples`,
and V13 `asof_observations`, `modeled_outcomes`, `frozen_trials`.
Only independent future results may support an investable claim.
