"""V10 pre-move, multi-metric, COIN-RELATIVE anomaly observations.

A metric is compared ONLY with strictly earlier snapshots of the SAME
instrument, SAME venue and SAME unit. No post-event price extreme, cross-coin
size threshold, current-snapshot baseline contamination, or retrospective fill.

Outlier classification is observational and unvalidated, never an order.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from research_v4.perp_watch import read, unpack, cross_venue

LOOKBACK_MS=7*86400000
MIN_PRIOR=24
ESTABLISHED_PRIOR=96
MIN_SPAN_MS=10*3600000
LAST_HOUR_TARGET_MS=3600000
LAST_TWO_HOUR_TARGET_MS=7200000
HOUR_TOLERANCE_MS=25*60000
MAX_PRIOR=336

# Metric groups are explicitly independent of their denominations.
METRICS=(
    "turnover_24h_level_usdt",
    "turnover_24h_accel_1h_pct",
    "oi_contracts_level",
    "oi_contracts_accel_1h_pct",
    "bid_ask_spread_bps",
    "day_range_pct",
    "mark_basis_abs_bps",
    "funding_abs_pct",
    "price_motion_1h_abs_pct",
    "cross_venue_dispersion_bps",
)
# Minimum meaningful unit-scale change for a flat historical metric.
FLOORS={
    "turnover_24h_level_usdt":10000.,
    "turnover_24h_accel_1h_pct":0.5,
    "oi_contracts_level":1.,
    "oi_contracts_accel_1h_pct":0.5,
    "bid_ask_spread_bps":1.,
    "day_range_pct":0.5,
    "mark_basis_abs_bps":0.5,
    "funding_abs_pct":0.001,
    "price_motion_1h_abs_pct":0.25,
    "cross_venue_dispersion_bps":1.,
}

def finite(value,positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        return None
    if not math.isfinite(value) or (positive and value<=0):
        return None
    return float(value)

def preceding(history,at_ms,lag_ms):
    valid=[(t,rec) for t,rec in history if t<at_ms and
           abs(at_ms-t-lag_ms)<=HOUR_TOLERANCE_MS]
    return min(valid,key=lambda item:abs(at_ms-item[0]-lag_ms))[1] if valid else None

def metric_values(current,prior,at_ms):
    """Price/volume state frozen at at_ms; no future bars or cross-venue mixing.

    prior is a per-symbol chronological list of (timestamp, venue_record).
    For cross-venue dispersion, a synthetic per-symbol 'consensus' venue is
    scored separately, never mixed with one exchange's OI.
    """
    rec=dict(current)
    vals={}
    q=finite(rec.get("q"),positive=True)
    if q is not None:vals["turnover_24h_level_usdt"]=q
    spread=finite(rec.get("spread_bps"))
    if spread is not None and spread>=0:vals["bid_ask_spread_bps"]=spread
    intrarange=finite(rec.get("range24h_pct"))
    if intrarange is not None and intrarange>=0:vals["day_range_pct"]=intrarange
    mark=finite(rec.get("mark_basis_bps"))
    if mark is not None:vals["mark_basis_abs_bps"]=abs(mark)
    funding=finite(rec.get("funding_rate_pct"))
    if funding is not None:vals["funding_abs_pct"]=abs(funding)
    oi=finite(rec.get("oi_contracts"),positive=True)
    if oi is not None:vals["oi_contracts_level"]=oi
    disp=finite(rec.get("cross_dispersion_bps"))
    if disp is not None and disp>=0:vals["cross_venue_dispersion_bps"]=disp

    hour=preceding(prior,at_ms,LAST_HOUR_TARGET_MS)
    if hour is not None:
        old_q=finite(hour.get("q"),positive=True)
        if q is not None and old_q is not None:
            vals["turnover_24h_accel_1h_pct"]=100*(q/old_q-1)
        old_oi=finite(hour.get("oi_contracts"),positive=True)
        if oi is not None and old_oi is not None:
            vals["oi_contracts_accel_1h_pct"]=100*(oi/old_oi-1)
        p=finite(rec.get("p"),positive=True)
        old_p=finite(hour.get("p"),positive=True)
        if p is not None and old_p is not None:
            vals["price_motion_1h_abs_pct"]=abs(100*(p/old_p-1))
    return vals

def enrich_consensus(venues):
    """Pure as-of price dispersion; no coupling of disjoint instrument types."""
    p=[finite(x.get("p"),positive=True) for x in venues.values()]
    if len(p)<2 or None in p:return None
    return 10000*(max(p)/min(p)-1)

def percentile(arr,p):
    ordered=sorted(arr)
    return ordered[int((len(ordered)-1)*p)]

def score_metric(metric,value,previous):
    if value is None:return {"status":"MISSING_VALUE"}
    history=[v for v in previous if v is not None and math.isfinite(v)]
    if len(history)<MIN_PRIOR:
        return {"status":"BASELINE_BUILDING","prior_samples":len(history)}
    med=median(history)
    mad=median(abs(v-med) for v in history)
    p95=percentile(history,.95)
    # Quarantine scale mismatches: negative or zero flat baseline cannot give
    # an infinite ratio. Absolute floors and MAD create finite scores.
    scale=max(1.4826*mad,abs(med)*.05,FLOORS[metric])
    robust_z=(value-med)/scale
    ratio=value/med if med>0 else None
    passed=value>p95 and robust_z>=3
    return {"status":"OUTLIER_ABOVE_OWN_BASELINE" if passed else "WITHIN_OWN_BASELINE",
        "prior_samples":len(history),
        "baseline_median":round(med,6),
        "baseline_mad":round(mad,6),
        "baseline_p95":round(p95,6),
        "relative_to_baseline_median":round(ratio,4) if ratio is not None else None,
        "robust_positive_z":round(robust_z,4),
        "current_value":round(value,6),
        "exceeds_baseline":bool(passed),
        "baseline_maturity":"ESTABLISHED" if len(history)>=ESTABLISHED_PRIOR else "PROVISIONAL"}

def metric_sequence(prior,current,at_ms):
    """Compute baseline using ONLY strictly earlier observations.

    Individual values derived from previous observations (e.g. 1h OI change)
    need a preceding snapshot even for each baseline sample.
    """
    series=[(t,obj) for t,obj in prior if
            at_ms-LOOKBACK_MS<=t<at_ms]
    metric_hist=defaultdict(list)
    for index,(t,record) in enumerate(series):
        past=series[:index]
        values=metric_values(record,past,t)
        for key,val in values.items():
            if key in METRICS and math.isfinite(val):metric_hist[key].append(val)
    present=metric_values(current,series,at_ms)
    span=series[-1][0]-series[0][0] if len(series)>=2 else 0
    scored={}
    for metric in METRICS:
        if span<MIN_SPAN_MS:
            scored[metric]={"status":"BASELINE_BUILDING",
                 "prior_samples":len(metric_hist[metric])}
            continue
        scored[metric]=score_metric(metric,present.get(metric),metric_hist[metric])
    return scored

def select_venue(venues):
    for venue in ("okx","bitget","binance"):
        if venue in venues:return venue
    return None

def analyze_one(sym,at_ms,venues,history):
    venue=select_venue(venues)
    if not venue:return None
    before=[(t,assets[venue]) for t,assets in history if t<at_ms and venue in assets]
    current=dict(venues[venue])
    disp=enrich_consensus(venues)
    if disp is not None:
        # Cross-venue consensus is computed only if no suspicious 4%+ spread;
        # unstable contract identities get an explicit risk state.
        current["cross_dispersion_bps"]=disp
    # Historic dispersion uses historic venue consensus only; never cached
    # using today’s venue availability for old snapshots.
    prior=[]
    for t,items in history:
        if t>=at_ms or venue not in items:continue
        record=dict(items[venue])
        d=enrich_consensus(items)
        if d is not None:record["cross_dispersion_bps"]=d
        prior.append((t,record))
    scored=metric_sequence(prior,current,at_ms)
    status_counts=Counter(v["status"] for v in scored.values())
    anomalous=[k for k,v in scored.items() if v["status"]=="OUTLIER_ABOVE_OWN_BASELINE"]
    price=finite(current.get("p"),positive=True)
    two=preceding(prior,at_ms,LAST_TWO_HOUR_TARGET_MS)
    p2=finite(two.get("p"),positive=True) if two else None
    r2=100*(price/p2-1) if price is not None and p2 is not None else None
    day=finite(current.get("d"))
    contrast=cross_venue(venues)
    precondition=(r2 is not None and abs(r2)<=3 and day is not None and abs(day)<=15
                  and contrast!="DIVERGENT_MULTI_VENUE")
    # Observation, not prediction: a single as-of outlier is interesting even
    # if all other metrics stay normal. Keep all metric values for ablations.
    if not anomalous:stage="NO_ANOMALY_OR_BASELINE_BUILDING"
    elif not precondition:stage="OUTLIER_WITH_PRIOR_MOTION_OR_UNVERIFIED_PRICE"
    else:stage="PREMOVE_ANOMALY_OBSERVED_RESEARCH_ONLY"
    return {"symbol":sym,"venue":venue,
            "observed_utc":datetime.fromtimestamp(at_ms/1000,timezone.utc).isoformat(),
            "price_at_observation":price,
            "prior_2h_return_pct":round(r2,5) if r2 is not None else None,
            "rolling_24h_change_pct":day,
            "venue_consistency":contrast,
            "metric_results":scored,"outlier_metrics":anomalous,
            "available_metrics":len([v for v in scored.values() if v["status"] not in
                                     ("MISSING_VALUE","BASELINE_BUILDING")]),
            "distinct_metric_outliers":len(anomalous),
            "baseline_status":("ESTABLISHED" if any(v.get("baseline_maturity")=="ESTABLISHED"
                 for v in scored.values()) else "PROVISIONAL" if any(v.get("baseline_maturity")=="PROVISIONAL"
                 for v in scored.values()) else "BUILDING"),
            "stage":stage,
            "early_prediction_proven":False,"trade_authorized":False,"paper_approved":False}

def latest_cohort(records):
    """Return EVERY currently observed coin, including nonmovers/zero-outliers."""
    if not records:raise ValueError("NO_V8_OBSERVATIONS")
    recent=records[-MAX_PRIOR-1:]
    by_symbol=defaultdict(list)
    for row in recent:
        t=row["scan_utc_ms"]
        for sym,venues in unpack(row["packed_assets"]).items():
            by_symbol[sym].append((t,venues))
    now=records[-1]["scan_utc_ms"]
    assets=unpack(records[-1]["packed_assets"])
    allrows=[]
    for sym,venues in sorted(assets.items()):
        rec=analyze_one(sym,now,venues,by_symbol[sym])
        if rec:allrows.append(rec)
    anomalies=[x for x in allrows if x["stage"]=="PREMOVE_ANOMALY_OBSERVED_RESEARCH_ONLY"]
    # High count first is descriptive only; explicitly NOT a profitability rank.
    anomalies.sort(key=lambda x:(-x["distinct_metric_outliers"],x["symbol"]))
    tally=Counter(key for row in allrows for key in row["outlier_metrics"])
    return {"schema":"EAR.v10_asset_relative_multimetric.v1",
       "asof_utc":datetime.fromtimestamp(now/1000,timezone.utc).isoformat(),
       "coins_in_snapshot":len(allrows),
       "pre_move_anomaly_research_count":len(anomalies),
       "observed_anomalies_by_metric":dict(sorted(tally.items())),
       "baseline_states":dict(Counter(x["baseline_status"] for x in allrows)),
       "stages":dict(Counter(x["stage"] for x in allrows)),
       "full_cohort":allrows,
       "top_research_observations":anomalies[:30],
       "technical_evidence":["7-day same-symbol same-venue backward-only rolling baselines",
          "24-observation minimum with 10-hour span, provisional until 96 observations",
          "robust z vs prior median/MAD and strictly past 95th percentile",
          "no multi-metric outlier threshold validated as trading entry",
          "30-minute Github cron snapshots may be late, skipped or stale",
          "day-long turnover is a 24h window, not 30-minute traded volume"],
       "no_realtime_guarantee":True,"no_validated_leading_metric":True,
       "trade_authorized":False,"paper_approved":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--ledger",required=True)
    parser.add_argument("--out",default="out/v10_anomalies")
    args=parser.parse_args()
    result=latest_cohort(read(args.ledger))
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    # Full denominators are essential for false-positive research, not just
    # the most exciting symbols. This output is a report, NOT a new ledger.
    (out/"report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    (out/"cohort.jsonl").write_text("".join(json.dumps(x,sort_keys=True,
         separators=(",",":"),allow_nan=False)+"\n" for x in result["full_cohort"]))
    lines=["# V10 — Multi-metric same-coin baseline anomalies","",
           "**Research only**: an unusual value is not a proven precursor, signal or fill.","",
           f"Observed symbols: {result['coins_in_snapshot']}; provisional/established: {result['baseline_states']}",
           f"Pre-motion observations with >=1 outlier: {result['pre_move_anomaly_research_count']}.",
           "Each metric is separately compared to its own strictly earlier 7-day window.","",
           "| Symbol | Venue | Pre-motion outlier metrics | Baseline state |",
           "|---|---|---|---|"]
    for row in result["top_research_observations"]:
        lines.append(f"| {row['symbol']} | {row['venue']} | {', '.join(row['outlier_metrics'])} | {row['baseline_status']} |")
    lines.append("\nNo independent prospective performance proof; no orders; no recommendation.")
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("V10_MULTIMETRIC",result["coins_in_snapshot"],"symbols",
          result["pre_move_anomaly_research_count"],"research anomalies")

if __name__=="__main__":main()
