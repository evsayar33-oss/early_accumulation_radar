# Early Accumulation Radar — V1 research foundation

[![CI](https://github.com/evsayar33-oss/early_accumulation_radar/actions/workflows/ci.yml/badge.svg)](https://github.com/evsayar33-oss/early_accumulation_radar/actions/workflows/ci.yml)

**Research-only / NO REAL TRADES.** Free public **spot** top-of-book observations from Binance, OKX, Bybit, Bitget, Gate, Kraken and Coinbase for BTC / ETH / SOL. Strict quote age, schema, crossed-book, bid/ask and two-venue agreement checks. Missing or blocked providers are reported and never silently fabricated.

### Run
```sh
python -m unittest discover -s tests -v
python -m radar.scan --output out/latest.json
```

On GitHub: Actions > **Public spot multi-venue research scan** > **Run workflow**. The workflow is also scheduled at 17 and 47 minutes UTC every hour after merging. It uploads a per-run JSON artifact (30-day retention). GitHub timing is not real-time or guaranteed.

### What V1 does not do
No person/manipulator identification; no accumulation prediction; no continuous signed trade tape or CVD; no full depth or verified fills; no real or simulated trades; no backtest-based performance claims; no paid APIs. Top-book imbalance is a *snapshot observation*, not a predictive entry signal. Exchange outages and response incompatibilities remain visible.

### Roadmap (requires separate measured evidence)
V2: true trade tape + event timestamps + historical snapshots + immutable forward ledger and cost-envelope model.
V3: freeze and independently test accumulation/distribution signal families versus controls; paper fills and prospective NAV; DEX/security and US stocks/BIST added only after provider verification.

Setup/API documentation: [docs/API_KEYS_TR.md](docs/API_KEYS_TR.md). Secrets listed there are **reserved only**, not used by V1.

## V2 research extension (proposed in PR #2)

The V2 module adds independently timestamped public Binance/OKX/Bybit recent-trade *samples*, completed Binance 1m quote-volume and taker-buy-volume features, and strictly labeled OKX volume-only fallback. All accumulation and distribution flags remain **HYPOTHESIS_ONLY**, not actionable BUY/SELL signals. The branch smoke diagnostic executes real public API calls and writes JSON workflow artifacts.

Once merged, the new `Research V2 sampled tape and immutable evidence` Action runs on first main push, on demand and twice per hour (scheduled UTC :11/:41). Forward evidence is hash chained into `paper/early-radar-v2`; failure to push causes a red workflow. No missing intervals are backfilled. Optional advisory messages to Telegram require `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` already configured in Actions Secrets. See [V2 technical notes](docs/V2_RESEARCH_TR.md).

**Not yet implemented:** simulated fills/PAPER NAV, predictive win rates, US stocks/BIST/DEX execution-ready feeds, historical statistically independent validation. Real trading remains disabled.

## V4 original-target research tracks (separate from legacy large-cap crypto V3)

V3's BTC/ETH/SOL-led historical study failed its performance screen and **does not** establish profitability for the originally intended low-float / concentrated ownership / shallow-liquidity universe.

* DEX public discovery: `.github/workflows/v4_original_universe.yml` — a non-trading token-pair candidate and data-health sampler.
* **BIST + US small-cap free input diagnostics**: `.github/workflows/v4_equities.yml` — KAP/Yahoo, Nasdaq/Yahoo, optional SEC/optional free DataCedar. First-seen price and volume evidence is SHA-linked on independent `research/v4-equity-evidence` branch. A non-executable forward event outcome study runs only on observed future sessions, never on synthetic fills.
* Neither BIST nor US **float percentage, ownership concentration, depth, point-in-time historical universe or splits/dividends** is verified by this free-source sampler. PIT historical profitability, new PAPER NAV and real trading remain explicitly **blocked**. The existing large-cap crypto research/PAPER state remains unchanged.

Free source setup, transparent coverage limits and gate details: [V4 BIST/US research guide](docs/V4_EQUITIES_FREE_SOURCES_TR.md).

## V17 gerçek MVRV araştırması

Haftalık `V17 Real MVRV research (NO TRADING)` işi, Coin Metrics Community kaynağında hem piyasa değeri hem realized cap bulunan BTC ve ETH için gerçek MVRV’yi hesaplar. Fiyat tabanlı vekiller MVRV diye adlandırılmaz. `MVRV < 1`, yalnız keşif döneminde sabitlenen yüzdelikler ve expanding Z-score kuralları kronolojik doğrulama bölümünde, maliyet sonrası ve çakışmayan 90 günlük olaylarla ölçülür. İlk eşik teması dip veya alım sinyali değildir; sonuçlar Quant Superlab doğrulaması olmadan PAPER/Telegram işlem bildirimi üretemez.
