# Real OHLCV acquisition for historical hypothesis discovery

The manual GitHub Actions workflow **Historical strategy discovery (real data, research only)** now downloads historical data on the runner, tests candidate families, and uploads CSV, provenance manifest and discovery reports as downloadable artifacts. Nothing is written to main, PAPER branches, or V4 immutable evidence.

**BIST / US:** latest 6-symbol current candidate samples obtained from the hash-verified `research/v4-equity-evidence` ledger; Yahoo Finance public chart, two hosts, 5y interval 1d. Yahoo is an unofficial endpoint; its terms, availability and adjustment treatment must be reviewed independently. **Crypto:** BTCUSDT, ETHUSDT, SOLUSDT from Binance public spot 1-day klines, using bounded pagination. History is real fetched bars, not reconstructed first-seen observations.

The workflow requires 300 valid closed daily bars per sampled symbol and fails visibly on missing/blocked providers or invalid OHLC. It will not silently replace missing prices with fabricated values. The latest partially formed daily candle is excluded, but timezone/calendar alignment and venue adjustment require further review.

Artifacts contain:
- `out/historical_real_data/prices.csv`, the source-fed CSV consumed by `historical_discovery.py`.
- `out/historical_real_data/manifest.json`, source, symbol, first/last date, bar count, checksum and selection ledger SHA.
- `out/historical_discovery/report.json` and `report.md`.

**Critical limitation:** historical prices do not imply historical universe membership. BIST and US samples are today's surviving candidates; they are not broad historical PIT universes or delisted-inclusive, and corporate action adjustments are not independently verified. Both flags are false in every row. Crypto sample is also current and not a complete historical crypto universe. Therefore candidate numbers are **exploratory and selection-biased**, not verified out-of-sample profitability. No PAPER/trading approval. After initial acquisition, next research stage is independent PIT universe membership, delistings, spread/depth/cost validation, and benchmark comparisons.

Source documentation:
- Binance Spot REST market data: https://developers.binance.com/en/docs/products/spot/rest-api
- Yahoo unofficial chart endpoints: https://query1.finance.yahoo.com/v8/finance/chart/
