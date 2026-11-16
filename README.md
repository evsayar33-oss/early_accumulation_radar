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
