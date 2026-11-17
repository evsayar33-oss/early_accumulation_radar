# V7 — Original target market, instrument-normalized hypotheses and first-seen evidence

## Diagnosis: previous 45 tests do not represent the target market

The original Early Accumulation Radar goal was **early accumulation in low-float, concentrated-ownership, shallow-liquidity instruments**, not conventional five-day momentum on large liquid stocks or Binance spot majors.

The old sample was deterministic current-survivor hashing: 36 KAP-listed BIST names without verified size/float, 36 present-day $10M–$500M US equities from a current TradingView screener, and 48 present-day $10M–$500M Binance CEX spot altcoins selected by current CoinGecko rank. **It did not contain the young DEX cohort** and historical float, orderbook depth, delistings, holder distributions and as-of market cap remain unverified. This PR makes these distinctions **first-class machine-readable failures** rather than claiming that current market cap proves original target fit.

## Changes — one PR, no production replacement

**A. Target-fit matrix** (`research_v4.v7_target_fit`):

- Compare expanded `manifest.json` metadata against the *actual* target: verified float, ownership distribution, historical point-in-time membership and executable liquidity/depth. Report BIST missing, US current-size-only proxy, crypto CEX-only proxy **separately**. Zero target-universe rows are marked as verified if essential evidence is missing.
- Keep raw OHLCV and screened OHLCV separate and never impute unknown float or cap. Do **not** turn turnover or current cap into a float proxy.
- A 36/36/48 sample limit remains a **research API/source constraint**, not evidence that it represents the intended universe.

**B. Early-stage candidates with instrument-relative statistics** (new, research-only families):

- `prebreakout_pressure`: price approaches but **has not exceeded** the previous 20-bar high, predominantly positive closes, ordinary-or-better relative volume and upper-range close.
- `quiet_base`: historical-relative narrow ten-day price base, five-day volume dry-up, near-but-not-beyond prior high and improved closing location.
- `absorption_probe`: relatively unusual volume within the symbol's preceding 60 bars, unusually small close-to-close movement versus own range, and a higher closing location. **Without multi-venue delta and full book, it cannot confirm real absorption.**
- `supply_absorption_risk`: similar large activity with weak closing location. This is bearish **risk research**, never an executable spot short.

Volumes are compared against the symbol's **preceding 60 bars**, rather than applying the same high absolute notional, $size or a universal 2x-volume gate. Price compression uses the symbol's own historical range and relative ATR. The pre-breakout hypothesis does not require an already completed breakout. Parameters are **frozen conceptual hypotheses**, not post-hoc optimized and not claimed to be correct.

**C. Measurement without signal leakage**:

- Hypothesis decision at day `t` depends only on bars up through `t`. A suspicious >2x or <0.5x price-scale jump in the *prior* feature window invalidates the signal. If a possible rebase/split occurs *after* the signal, it **censors the affected forward outcome**, never retroactively removes the earlier observed signal.
- Entry proxy is next-day open; outcomes are the 2nd, 5th and 10th subsequent daily close. Report raw/roundtrip-cost/2x-cost/delayed-entry return, historic exposure and non-executable maximum future high separately. Future highs are **not fill prices**.
- Evaluate 60/20/20 chronological portions; the final historical period is **already viewed**, not independent validation. Measure also a capital-constrained five-bar NAV through the frozen V6 simulator for LONG families only. Long-only hypothesis returns for bearish risk flags **are not presented as short-sale profit**.
- NO PAPER/live promotion, strategy substitution, new Telegram entry alerts or mutation of `research/auto-evidence` and `paper/early-radar-nav` records.

**D. Stop losing the young DEX cohorts** (`research_v4.dex_firstseen`):

- The existing 12-hour `V4 original-universe DEX discovery` now writes observed chain+pair+token identities, timestamp, snapshot price when available, USD liquidity and volume to a **dedicated SHA-linked branch** `research/dex-firstseen`, not main. It does not backfill a token's history at creation.
- Fix base/quote identity: **DexScreener `priceUsd` belongs to the BASE token**. If the scanned token appears only as quote, it must not inherit the other token's price.
- Follow up to 8 previously radar-observed candidate pairs per run, limited to 14 days after radar's first observation. Evaluate observed 24/72/168-hour snapshot-to-snapshot changes **only if** a later actual snapshot is available. No interpolation, "first launch" claims, trade fills or retrospective new winners.
- Existing workflow schedule and artifact path preserved; new report is saved as `out/dex_forward_evidence` and the isolated branch retains its hash-linked history. If GitHub token push rights are not allowed, the workflow fails visibly; uploaded artifacts remain separately available on successful discovery. This is a conditional GitHub permission requirement, not a promise of successful persistence before observing a run.
- These periodic profile snapshots are **not** a 1-minute trading feed or a survivorship-complete market history. Real early pump/short detection and execution require historical signed trades, L2 depth, holder/contract analysis, exchange-specific metadata, and more frequent timestamped observations.


**E. Independently record NEW early-stage candidates BEFORE their future outcomes** (`research_v4.v7_forward`):

- Once a trusted `main` V5 research workflow **finishes successfully**, a separate workflow downloads that exact run's already-collected historical artifact (no duplicate market-data requests and no historical "signal creation" backfill). This V7 job does not affect V5 or PAPER on failure.
- Take **only truly closed sessions** (daily bar date strictly prior to first observation UTC date). Freeze any latest V7 watchlist signals under their research code SHA + first-seen timestamp and source CSV SHA. The next possible simulated entry is a daily open strictly **after first observation UTC date**, not a historical signal-day close.
- Independently measure next available 2/5/10 CLOSED sessions with explicit fixed costs, pending/missing-symbol and future-scale-change states. Reject entries delayed beyond 3 calendar days for crypto or 7 for equities. No invented "fill", historical re-signal, or simulated short borrow.
- The sealed signal/settlement files live on **`research/v7-forward-evidence`**, isolated from both **`research/auto-evidence`** (old V5 hypotheses) and **`paper/early-radar-nav`** (frozen V3). Outcomes are first recorded once, not recomputed/overwritten. This provides a genuine future-only comparator, **but not verified PIT float/holder/depth**.
- The separate `V7 isolated forward validation from completed V5 research (NO TRADING)` workflow also uploads its own 90-day artifact. GitHub token must allow writing to its own evidence branch; failure is reported explicitly without modifying the original research stream.

## What this PR does NOT fix

It cannot conjure missing historical float, shareholder distribution, de-listed instruments, DEX trade history, book depth or independently frozen research periods. Real-time opportunities cannot be verified with twice-daily DEX sampling or five-year daily survivor bars alone. Free-source limitations are explicit, rather than silently substituted with large-cap proxy tests.

## Operations

After merge, the V7 diagnostics step is advisory-only, so faults in this new research cannot abort the frozen V5 ledger. The existing `V5 Autonomous three-market research and prospective evidence (NO TRADING)` regularly writes `out/v7_target_fit/report.json` and `report.md` to its existing 90-day artifact, and the already scheduled `V4 original-universe DEX discovery` appends separate first-seen snapshots. No new scheduling service or manual install is required. The current independent V2/V3 PAPER workflows remain frozen.

**Decision rule:** No candidate may be called "profitable" from survivor-only, currently sized samples. Publish concrete gaps, signal family × eligible cohort performance, raw-vs-screened sensitivity and eventually enough prospective outcomes before any new PAPER approval.
