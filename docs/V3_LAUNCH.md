# V3 launch and verification

This PR adds two GitHub Actions workflows. They run automatically on the first main push that adds the workflow files, and support manual workflow_dispatch.

1. V3 historical cost-stressed profitability research: downloads checksum-verified Binance Vision 1-minute archives for the frozen eight-symbol August-October 2026 universe. Compares accumulation versus breakout and buy-and-hold under base/stress fees and slippage. Reports matrix.csv, trades.csv, summary.json, report.md as 90-day Actions artifacts. Backtest is exploratory; historical fill prices are proxies and universe is not point-in-time.
2. V3 prospective PAPER NAV and SHA evidence: starts a 10,000 USDT simulated portfolio from first live observation; runs at UTC minutes 17 and 47. It appends a hash-linked events ledger and state to the independent paper/early-radar-nav branch, not main or the existing V2 paper branch. Remote ledger/state are verified after push. It cannot place live orders.

Do not claim profitability until the historical workflow completes and its missing-data manifest is examined. The first prospective PAPER tick is not a 30-day result; the 30/60/90-day checkpoints require actual elapsed time. Source outages and missing marks are not backfilled.

A model-code change after paper inception intentionally stops the forward study instead of silently changing the strategy. GitHub Actions needs contents:write permission to persist the evidence branch.
