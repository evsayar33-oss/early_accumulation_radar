"""V17 real on-chain MVRV research with explicit source/proxy labels.

Only assets for which Coin Metrics Community supplies both market and realized
capitalisation are evaluated as REAL_MVRV.  No price-only proxy is renamed MVRV.
All thresholds are fixed on the chronological discovery fold and evaluated on
later observations.  Output is research-only and cannot create PAPER orders.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

API = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
ASSETS = ("btc", "eth")
ROUND_TRIP_COST_BPS = 35


def fetch(asset, start="2015-01-01"):
    if asset not in ASSETS:
        raise ValueError("REAL_MVRV_ASSET_NOT_ALLOWLISTED")
    params = urlencode({"assets": asset, "metrics": "PriceUSD,CapMrktCurUSD,CapRealUSD",
                        "frequency": "1d", "start_time": start, "page_size": 10000})
    req = Request(API + "?" + params, headers={"User-Agent": "early-accumulation-radar/17"})
    with urlopen(req, timeout=40) as response:
        payload = json.load(response)
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("COINMETRICS_REAL_MVRV_EMPTY")
    frame = pd.DataFrame(rows)
    required = {"time", "PriceUSD", "CapMrktCurUSD", "CapRealUSD"}
    if not required.issubset(frame):
        raise ValueError("COINMETRICS_REAL_MVRV_SCHEMA")
    frame.index = pd.to_datetime(frame.pop("time"), utc=True).dt.tz_localize(None)
    frame = frame[list(required - {"time"})].apply(pd.to_numeric, errors="coerce").sort_index()
    frame = frame[~frame.index.duplicated(keep=False)].dropna()
    if len(frame) < 365 or (frame <= 0).any().any():
        raise ValueError("COINMETRICS_REAL_MVRV_INVALID_HISTORY")
    return frame


def _events(mask, horizon):
    chosen, last = [], -horizon - 1
    for i, value in enumerate(mask):
        if value and i > last + horizon:
            chosen.append(i)
            last = i
    return chosen


def _score(frame, mask, start, stop, horizon=90):
    idx = [i for i in _events(mask.to_numpy(), horizon)
           if start <= i and i + horizon < stop]
    if not idx:
        return {"n": 0, "mean_net": None, "hit_rate": None,
                "max_overlapping_positions": 0}
    price = frame.PriceUSD.to_numpy()
    returns = np.array([price[i + horizon] / price[i] - 1 - ROUND_TRIP_COST_BPS / 10000
                        for i in idx])
    return {"n": len(idx), "mean_net": round(float(returns.mean()), 6),
            "median_net": round(float(np.median(returns)), 6),
            "hit_rate": round(float((returns > 0).mean()), 6),
            "worst": round(float(returns.min()), 6),
            "max_overlapping_positions": 1}


def analyze(asset, frame):
    x = frame.copy()
    x["mvrv"] = x.CapMrktCurUSD / x.CapRealUSD
    expanding_mean = x.mvrv.expanding(min_periods=365).mean().shift(1)
    expanding_std = x.mvrv.expanding(min_periods=365).std(ddof=0).shift(1)
    x["mvrv_z"] = (x.mvrv - expanding_mean) / expanding_std.replace(0, np.nan)
    x = x.dropna()
    if len(x) < 500:
        return {"asset": asset, "status": "INSUFFICIENT_REAL_MVRV_HISTORY",
                "paper_eligible": False, "trade_authorized": False}
    boundary = int(len(x) * .70)
    discovery = x.iloc[:boundary]
    q10, q20 = discovery.mvrv.quantile([.10, .20])
    rules = {
        "mvrv_below_1": x.mvrv < 1,
        "mvrv_train_q10": x.mvrv <= q10,
        "mvrv_train_q20": x.mvrv <= q20,
        "mvrv_z_below_minus_1": x.mvrv_z <= -1,
    }
    results = []
    for name, mask in rules.items():
        results.append({"rule": name,
                        "discovery": _score(x, mask, 0, boundary),
                        "validation": _score(x, mask, boundary, len(x))})
    return {
        "schema": "EAR.v17.real_mvrv_research.v1", "asset": asset,
        "source": "COIN_METRICS_COMMUNITY_ASSET_METRICS",
        "measurement": "REAL_MVRV_MARKET_CAP_DIVIDED_BY_REALIZED_CAP",
        "proxy": False, "asof": x.index[-1].date().isoformat(),
        "history": {"from": x.index[0].date().isoformat(),
                    "through": x.index[-1].date().isoformat(), "observations": len(x)},
        "split": {"discovery_end": x.index[boundary - 1].date().isoformat(),
                  "validation_start": x.index[boundary].date().isoformat()},
        "thresholds_fit_on_discovery_only": {"q10": round(float(q10), 6),
                                              "q20": round(float(q20), 6)},
        "results": results,
        "staged_entry_interpretation": "RESEARCH_ONLY_FIRST_THRESHOLD_IS_NOT_A_DIP_CALL",
        "paper_eligible": False, "trade_authorized": False,
        "requires_quant_superlab_validation": True,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="out/v17_mvrv")
    p.add_argument("--asset", action="append", choices=ASSETS)
    args = p.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    reports, errors = [], {}
    for asset in args.asset or ASSETS:
        try:
            report = analyze(asset, fetch(asset))
            reports.append(report)
            (out / f"{asset}.json").write_text(json.dumps(report, indent=2,
                sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        except Exception as exc:
            errors[asset] = f"{type(exc).__name__}: {exc}"
    summary = {"schema": "EAR.v17.real_mvrv_batch.v1", "reports": reports,
               "source_errors": errors, "paper_eligible": False,
               "trade_authorized": False}
    (out / "report.json").write_text(json.dumps(summary, indent=2,
        sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# V17 real MVRV research", "",
             "Coin Metrics market cap / realized cap. Research only; no PAPER or live orders.", "",
             "| Asset | History | Validation start | Rules |", "|---|---:|---|---:|"]
    for r in reports:
        lines.append(f'| {r["asset"].upper()} | {r["history"]["observations"]} | '
                     f'{r["split"]["validation_start"]} | {len(r["results"])} |')
    if errors:
        lines += ["", "Source errors: " + "; ".join(f"{k}: {v}" for k,v in errors.items())]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("V17_REAL_MVRV", len(reports), "assets", len(errors), "source errors", "NO_PAPER")


if __name__ == "__main__":
    main()
