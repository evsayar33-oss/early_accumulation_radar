"""Offline historical candidate discovery. NO trade routing or PAPER promotion.

Input CSV columns: market,symbol,date,open,high,low,close,volume,
pit_universe_verified,corporate_actions_verified.
Data provenance is asserted by the operator, not inferred from prices.
"""
from __future__ import annotations
import argparse
import csv
from collections import defaultdict
from datetime import date
import json
import math
from pathlib import Path
from statistics import mean, median

COST_PCT={"BIST":2.0,"US":1.0,"CRYPTO":0.6}
HOLD=5
WARMUP=25
MIN_COUNTS=(30,15,15)
FAMILIES=("volume_breakout","quiet_accumulation","pullback_rebound")

def load_csv(path):
    series=defaultdict(list)
    with open(path,newline="",encoding="utf8") as stream:
        for r in csv.DictReader(stream):
            market=r["market"].strip().upper()
            if market not in COST_PCT: raise ValueError("UNKNOWN_MARKET")
            sym=r["symbol"].strip().upper()
            if not sym: raise ValueError("EMPTY_SYMBOL")
            dt=date.fromisoformat(r["date"])
            vals={k:float(r[k]) for k in ("open","high","low","close","volume")}
            if not all(math.isfinite(v) for v in vals.values()):raise ValueError("NONFINITE")
            if min(vals[k] for k in ("open","high","low","close"))<=0 or vals["volume"]<0:
                raise ValueError("BAD_OHLCV")
            if not(vals["low"]<=min(vals["open"],vals["close"])<=max(vals["open"],vals["close"])<=vals["high"]):
                raise ValueError("INCONSISTENT_OHLC")
            series[(market,sym)].append({"date":dt,**vals,
                "pit":r.get("pit_universe_verified","").lower()=="true",
                "adjusted":r.get("corporate_actions_verified","").lower()=="true"})
    for key,rows in series.items():
        rows.sort(key=lambda r:r["date"])
        if len({r["date"] for r in rows})!=len(rows):raise ValueError("DUPLICATE_SESSION_"+key[1])
    return series

def signal(family,rows,i):
    x=rows[i]
    prev=rows[i-20:i]
    vols=[r["volume"] for r in prev]
    base=median(vols)
    if base<=0:return False
    rv=x["volume"]/base
    ret5=x["close"]/rows[i-5]["close"]-1
    high20=max(r["high"] for r in prev)
    low20=min(r["low"] for r in prev)
    if family=="volume_breakout":return rv>=2 and x["close"]>high20 and ret5<=0.20
    if family=="quiet_accumulation":
        return rv>=1.5 and abs(ret5)<=0.04 and (high20/low20-1)<=0.16
    if family=="pullback_rebound":
        return rv>=1.8 and -.12<=ret5<=-.025 and x["close"]>x["open"]
    raise ValueError("UNKNOWN_FAMILY")

def events(series):
    out=[]
    for (market,sym),rows in sorted(series.items()):
        last={family:-999 for family in FAMILIES}
        for i in range(WARMUP,len(rows)-HOLD):
            for family in FAMILIES:
                if i-last[family]<=HOLD or not signal(family,rows,i):continue
                # Signal is known only after close i; entry is next session open.
                entry=rows[i+1]["open"]
                exit_=rows[i+HOLD]["close"]
                gross=100*(exit_/entry-1)
                out.append({"market":market,"symbol":sym,"family":family,
                    "signal_date":rows[i]["date"].isoformat(),
                    "outcome_date":rows[i+HOLD]["date"].isoformat(),
                    "net_pct":gross-COST_PCT[market],
                    "gross_pct":gross,
                    "pit_verified":all(r["pit"] for r in rows[i-20:i+HOLD+1]),
                    "corporate_actions_verified":all(r["adjusted"] for r in rows[i-20:i+HOLD+1])})
                last[family]=i
    return out

def metrics(rows):
    v=[x["net_pct"] for x in rows]
    return {"count":len(v),"mean_net_pct":round(mean(v),4) if v else None,
            "median_net_pct":round(median(v),4) if v else None,
            "positive_fraction":round(sum(x>0 for x in v)/len(v),4) if v else None}

def discover(series):
    all_events=events(series)
    markets=sorted({key[0] for key in series})
    report={"schema":"EAR.historical_discovery.v1","historical_only":True,
            "paper_approved":False,"trade_authorized":False,
            "candidate_results":[],"limitations":[
                "COSTS_ARE_STRESS_ASSUMPTIONS_NOT_EXECUTION_MEASUREMENTS",
                "INPUT_UNIVERSE_PIT_AND_CORPORATE_ACTIONS_REQUIRE_INDEPENDENT_VERIFICATION",
                "NO_SPREAD_DEPTH_OR_FILL_PROOF","NO_PROSPECTIVE_PROFIT_CLAIM"]}
    for market in markets:
        dates=sorted({r["date"].isoformat() for (m,_),rows in series.items() if m==market for r in rows})
        if len(dates)<100:
            report["candidate_results"].append({"market":market,"status":"INSUFFICIENT_HISTORY","sessions":len(dates)})
            continue
        train_end=dates[int(len(dates)*.6)]
        valid_end=dates[int(len(dates)*.8)]
        for family in FAMILIES:
            sample=[e for e in all_events if e["market"]==market and e["family"]==family]
            # Split by outcome date, and purge cross-boundary signals to avoid leakage.
            train=[e for e in sample if e["outcome_date"]<train_end]
            valid=[e for e in sample if e["signal_date"]>=train_end and e["outcome_date"]<valid_end]
            test=[e for e in sample if e["signal_date"]>=valid_end]
            stages=[train,valid,test]
            counts_ok=all(len(v)>=minimum for v,minimum in zip(stages,MIN_COUNTS))
            positive=counts_ok and all(mean(e["net_pct"] for e in stage)>0 for stage in stages)
            provenance=all(e["pit_verified"] and e["corporate_actions_verified"] for stage in stages for e in stage)
            # Research-only candidate status; even strong history cannot authorize PAPER.
            status=("HISTORICAL_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW" if positive and provenance
                    else "POSITIVE_BUT_PROVENANCE_UNVERIFIED" if positive
                    else "INSUFFICIENT_EVENTS" if not counts_ok else "FAILED_OUT_OF_SAMPLE_SCREEN")
            report["candidate_results"].append({"market":market,"family":family,"status":status,
                "train":metrics(train),"validation":metrics(valid),"holdout":metrics(test),
                "pit_and_adjustments_verified":provenance,"train_end":train_end,"holdout_start":valid_end})
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True,help="Historical OHLCV CSV; no automatic backfill")
    p.add_argument("--out",default="out/historical_discovery")
    args=p.parse_args()
    result=discover(load_csv(args.csv))
    target=Path(args.out);target.mkdir(parents=True,exist_ok=True)
    (target/"report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
    lines=["# Historical strategy discovery (not PAPER or live approval)","",
        "| Market | Family | Train N / Net % | Validation N / Net % | Holdout N / Net % | Decision |",
        "|---|---|---:|---:|---:|---|"]
    for x in result["candidate_results"]:
        if "family" not in x:
            lines.append(f"| {x['market']} | — | — | — | — | {x['status']} |")
            continue
        def fmt(stage):
            m=x[stage]
            return f"{m['count']} / {m['mean_net_pct']}"
        lines.append(f"| {x['market']} | {x['family']} | {fmt('train')} | {fmt('validation')} | {fmt('holdout')} | {x['status']} |")
    (target/"report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    print("HISTORICAL_DISCOVERY",len(result["candidate_results"]),"candidates; paper_approved false")

if __name__=="__main__":main()
