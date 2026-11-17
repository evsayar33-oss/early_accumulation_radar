"""Benchmark-matched historical event diagnostics across existing 15 hypotheses.

Long-only equal-weight SAME-DATE current-survivor peers, excluding the signal
symbol. Frictionless peer return is a deliberately difficult comparison hurdle.
Still not a PIT universe, independence proof, portfolio NAV, or PAPER approval.
"""
from __future__ import annotations
import argparse,json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from research_v4.multimarket_exploratory import load,events as v2_events,COST
from research_v4.historical_discovery import events as base_events
from research_v4.new_hypotheses_bias import make_events as v3_events
from research_v4.regime_event_research import events as v4_events

MIN_PEERS=5
MIN_COUNTS=(30,15,15)

def aligned_events(series):
    out=[]
    maps={}
    for key,seq in series.items():
        maps[key]={b["date"].isoformat():(i,b) for i,b in enumerate(seq)}
    sources=(
       ("base",base_events(series)),
       ("v2",v2_events(series)),
       ("v3",v3_events(series)),
       ("v4",v4_events(series)))
    for prefix,rows in sources:
        for e in rows:
            market,sym=e["market"],e["symbol"]
            signal_day=e.get("signal",e.get("signal_date"))
            outcome=e.get("outcome",e.get("outcome_date"))
            key=(market,sym)
            if key not in maps or signal_day not in maps[key]:continue
            i,_=maps[key][signal_day]
            seq=series[key]
            if i+2>=len(seq):continue
            start=seq[i+1]["open"]
            delayed=seq[i+2]["open"]
            finish=maps[key].get(outcome,(None,None))[1]
            if not finish:continue
            end=finish["close"]
            gross=100*(end/start-1)
            out.append({"market":market,"symbol":sym,
                "family":prefix+"/"+e["family"],
                "signal":signal_day,"outcome":outcome,
                "entry_date":seq[i+1]["date"].isoformat(),
                "gross":gross,"net":gross-COST[market],
                "double_cost":gross-2*COST[market],
                "delayed":100*(end/delayed-1)-COST[market]})
    return out,maps

def matched_peer(maps,market,symbol,entry_day,exit_day):
    values=[]
    for (m,s),bars in maps.items():
        if m!=market or s==symbol:continue
        o=bars.get(entry_day)
        c=bars.get(exit_day)
        if o and c:
            values.append(100*(c[1]["close"]/o[1]["open"]-1))
    return (mean(values),len(values)) if len(values)>=MIN_PEERS else (None,len(values))

def summary(rows):
    if not rows:return {"n":0,"symbols":0,"mean_net_pct":None,
                          "mean_excess_pct":None,"mean_double_cost_pct":None,
                          "mean_delayed_pct":None,"min_leave_one_symbol_out_excess":None}
    symbols={r["symbol"] for r in rows}
    with_ref=[r for r in rows if r["excess"] is not None]
    loo=(min(mean(r["excess"] for r in with_ref if r["symbol"]!=sym)
             for sym in symbols) if len(symbols)>=3 and
             all(any(r["symbol"]!=sym for r in with_ref) for sym in symbols)
             else None)
    return {"n":len(rows),"symbols":len(symbols),
        "reference_eligible":len(with_ref),
        "mean_net_pct":round(mean(r["net"] for r in rows),4),
        "mean_excess_pct":round(mean(r["excess"] for r in with_ref),4) if with_ref else None,
        "mean_double_cost_pct":round(mean(r["double_cost"] for r in rows),4),
        "mean_delayed_pct":round(mean(r["delayed"] for r in rows),4),
        "min_leave_one_symbol_out_excess":round(loo,4) if loo is not None else None}

def study(series):
    events,maps=aligned_events(series)
    for e in events:
        peer,n=matched_peer(maps,e["market"],e["symbol"],e["entry_date"],e["outcome"])
        e["peer_count"]=n
        e["excess"]=e["net"]-peer if peer is not None else None
    report={"schema":"EAR.matched_historical_event_diagnostics.v1",
        "trade_authorized":False,"paper_approved":False,"pristine_holdout":False,
        "selection_survivorship_bias_unresolved":True,"benchmark_is_current_survivors":True,
        "benchmark_is_frictionless":True,
        "trial_count":15*3,
        "multiple_hypothesis_correction_applied":False,
        "event_average_not_portfolio_nav":True,"results":[]}
    for market in COST:
        dates=sorted({b["date"].isoformat() for (m,s),seq in series.items()
                      if m==market for b in seq})
        if len(dates)<200:continue
        cut1=dates[int(len(dates)*.6)]
        cut2=dates[int(len(dates)*.8)]
        for family in sorted({e["family"] for e in events if e["market"]==market} |
                    {prefix+"/"+f for prefix,fs in (
                        ("base",("volume_breakout","quiet_accumulation","pullback_rebound")),
                        ("v2",("compression_breakout","high_volume_trend","pullback_reclaim",
                              "range_base_break","quiet_trend_acceleration","capitulation_reversal")),
                        ("v3",("relative_strength_rotation","downside_exhaustion","volume_dryup_reclaim")),
                        ("v4",("overnight_gap_continuation","overnight_gap_fade","post_shock_volatility_cooldown")))
                        for f in fs}):
            x=[r for r in events if r["market"]==market and r["family"]==family]
            groups=([
                [r for r in x if r["outcome"]<cut1],
                [r for r in x if r["signal"]>=cut1 and r["outcome"]<cut2],
                [r for r in x if r["signal"]>=cut2]])
            sums=[summary(g) for g in groups]
            robust=all(len(g)>=threshold and sumr["reference_eligible"]==len(g) and
                sumr["symbols"]>=3 and
                all(sumr[k] is not None and sumr[k]>0 for k in (
                     "mean_net_pct","mean_excess_pct","mean_double_cost_pct",
                     "mean_delayed_pct","min_leave_one_symbol_out_excess"))
                for g,sumr,threshold in zip(groups,sums,MIN_COUNTS))
            report["results"].append({"market":market,"family":family,
                "train":sums[0],"validation":sums[1],
                "previously_exposed_holdout":sums[2],
                "status":"EXPLORATORY_ROBUST_NOT_PIT" if robust else "NOT_ROBUST_OR_INSUFFICIENT",
                "historical_pit_verified":False})
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--out",default="out/matched_benchmark")
    a=p.parse_args()
    report=study(load(a.csv))
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    robust=[r for r in report["results"] if r["status"]=="EXPLORATORY_ROBUST_NOT_PIT"]
    lines=["# All signal families vs contemporaneous, frictionless current-survivor peers","",
      f'Tested {len(report["results"])} market/family cells; diagnostic-robust only: {len(robust)}.',
      "No intact holdout/PIT, multiple-testing correction or PAPER authorization.",
      "Market-average and excess figures are **event** averages, not executable portfolio NAV.","",
      "| Market | Family | Train excess % | Validation excess % | Exposed excess % | Status |",
      "|---|---|---:|---:|---:|---|"]
    for r in report["results"]:
        lines.append("| "+" | ".join((r["market"],r["family"],
            str(r["train"]["mean_excess_pct"]),
            str(r["validation"]["mean_excess_pct"]),
            str(r["previously_exposed_holdout"]["mean_excess_pct"]),r["status"]))+" |")
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("MATCHED_BENCHMARK",len(report["results"]),"market/family research comparisons",flush=True)

if __name__=="__main__":main()
