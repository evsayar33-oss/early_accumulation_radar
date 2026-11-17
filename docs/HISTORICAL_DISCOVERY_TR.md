# Historical candidate discovery — research-only

This PR adds an **offline research engine**, not a claim that profitable strategies have been found. It deliberately **does not** repurpose the V4 first-seen six-symbol probe as a point-in-time historical universe.

## Inputs and scope
Run the manually triggered **Historical strategy discovery (research only)** workflow after committing a genuine historical CSV to a research data path, or run locally:

```sh
python -m research_v4.historical_discovery --csv data/historical/prices.csv --out out/historical_discovery
```

CSV columns: `market,symbol,date,open,high,low,close,volume,pit_universe_verified,corporate_actions_verified`. Markets: `BIST`, `US`, `CRYPTO`. Dates must be unique per symbol and ISO-formatted; prices must be positive, finite and OHLC-consistent. Source/provenance flags must only be set `true` with independent documentation; otherwise leave false. **No historical data is bundled, downloaded, invented, or backfilled by this PR.** The workflow explicitly fails if the CSV is absent.

## Predeclared candidates
- `volume_breakout`: relative volume >=2, new 20-session high, 5-session return <=20%.
- `quiet_accumulation`: relative volume >=1.5, absolute 5-session return <=4%, 20-session range <=16%.
- `pullback_rebound`: relative volume >=1.8, 5-session return between -12% and -2.5%, bullish daily candle.

Signals are known only at daily close; diagnostic entry is the **next session open**, exit the **fifth subsequent session close**. Overlapping events of the same symbol/family are suppressed. Round-trip stress costs are BIST 2%, US 1%, crypto 0.6%, **assumptions**, not observed spreads or fills.

## Historical selection and no-approval gates
Chronological 60/20/20 train/validation/holdout split by market session; boundary-straddling events are purged. Minimum independent non-overlapping events: 30/15/15 per candidate. A candidate must show positive **mean cost-adjusted return in all three partitions** and verified PIT membership and corporate actions even to be labeled `HISTORICAL_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW`. No status authorizes PAPER or trading. Failed and underpowered candidates remain visible; no cherry-picked top-line profits.

**Remaining research work before any reliable claim:** obtain sufficiently broad historical point-in-time universes (including delisted instruments), independently verified adjustments, bid/ask and depth history, benchmark and risk-adjusted comparisons, bootstrap uncertainty and regime/parameter stability, walk-forward model selection and untouched independent final test. This version does not implement those requirements or claim institutional-grade proof. Real-data inputs are the blocking prerequisite. V4 first-seen evidence, V2/V3 PAPER, existing scheduled workflows, and live permissions remain untouched.
