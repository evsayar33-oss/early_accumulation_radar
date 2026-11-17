"""Fixed gap/volatility regime hypotheses; event-time stress, not PAPER signals.

No grid search. Entries next available open, exits close five bars later.
Regime windows and signals use historical OHLCV only.
"""
from __future__ import annotations
import argparse,json
from collections import defaultdict
from pathlib import Path
from statistics import mean,median
from research_v4.multimarket_exploratory import load,COST

FAMILIES=("overnight_gap_continuation","overnight_gap_fade","post_shock_volatility_cooldown")
HOLD=5

def indicator(seq,i):
    if i<101:return None
    x=seq[i]
    p=seq[i-1]
    prior=seq[i-21:i]
    median_range=median((b["high"]-b["low"])/b["close"] for b in prior)
    median_volume=median(b["volume"] for b in prior)
    if median_volume<=0:return None
    gap=x["open"]/p["close"]-1
    return {"gap":gap,"rv":x["volume"]/median_volume,
            "body":x["close"]/x["open"]-1,
            "range":(x["high"]-x["low"])/x["close"],
            "range_ref":median_range,
            "trend":x["close"]>mean(b["close"] for b in seq[i-100:i]),
            "r5":x["close"]/seq[i-5]["close"]-1,
            "prior_shock":(p["high"]-p["low"])/p["close"]>=2.5*median_range,
            "prior_low":min(b["low"] for b in prior),
            "close_reclaim":x["close"]>p["close"]}

def signal(f,z,market):
    if f=="overnight_gap_continuation":
        # Stocks only: 24x7 crypto does not have a comparable overnight gap.
        return market in ("US","BIST") and .025<=z["gap"]<=.12 and z["body"]>0 and z["rv"]>=1.5 and z["trend"]
    if f=="overnight_gap_fade":
        return market in ("US","BIST") and -.12<=z["gap"]<=-.025 and z["body"]>0 and z["rv"]>=1.5 and z["close_reclaim"]
    if f=="post_shock_volatility_cooldown":
        return z["prior_shock"] and z["range"]<=.6*z["range_ref"] and z["rv"]<=.85 and z["close_reclaim"]
    raise ValueError("UNKNOWN_FAMILY")

def events(series):
    result=[]
    for (market,symbol),bars in sorted(series.items()):
        last={f:-999 for f in FAMILIES}
        for i in range(101,len(bars)-HOLD):
            z=indicator(bars,i)
            if z is None:continue
            for fam in FAMILIES:
                if i-last[fam]<=HOLD or not signal(fam,z,market):continue
                start=bars[i+1]["open"]
                late=bars[i+2]["open"]
                exit_price=bars[i+HOLD]["close"]
                result.append({"market":market,"symbol":symbol,"family":fam,
                    "signal":bars[i]["date"].isoformat(),"outcome":bars[i+HOLD]["date"].isoformat(),
                    "net":100*(exit_price/start-1)-COST[market],
                    "double_cost":100*(exit_price/start-1)-2*COST[market],
                    "delayed":100*(exit_price/late-1)-COST[market]})
                last[fam]=i
    return result

def stats(rows):
    if not rows:return {"n":0,"avg_net":None,"avg_double_cost":None,"avg_delayed":None,"symbols":0}
    return {"n":len(rows),"avg_net":round(mean(r["net"] for r in rows),4),
            "avg_double_cost":round(mean(r["double_cost"] for r in rows),4),
            "avg_delayed":round(mean(r["delayed"] for r in rows),4),
            "symbols":len({r["symbol"] for r in rows})}

def study(series):
    all_events=events(series)
    report={"schema":"EAR.regime_event_v1","families":list(FAMILIES),
         "paper_approved":False,"trade_authorized":False,"pristine_holdout":False,
         "survivorship_bias_unresolved":True,"historical_market_cap_unverified":True,
         "corporate_actions_unverified":True,"results":[]}
    for market in COST:
        dates=sorted({b["date"].isoformat() for (m,s),seq in series.items() if m==market for b in seq})
        if len(dates)<200:continue
        a=dates[int(len(dates)*.6)]
        b=dates[int(len(dates)*.8)]
        for fam in FAMILIES:
            subs=[r for r in all_events if r["market"]==market and r["family"]==fam]
            train=[r for r in subs if r["outcome"]<a]
            valid=[r for r in subs if r["signal"]>=a and r["outcome"]<b]
            exposed=[r for r in subs if r["signal"]>=b]
            groups=[train,valid,exposed]
            robust=all(len(g)>=n and len({r["symbol"] for r in g})>=3 and
                 all(mean(r[k] for r in g)>0 for k in ("net","double_cost","delayed"))
                 for g,n in zip(groups,(30,15,15)))
            report["results"].append({"market":market,"family":fam,
                "train":stats(train),"validation":stats(valid),
                "previously_exposed_holdout":stats(exposed),
                "status":"EXPLORATORY_ROBUST_NOT_VERIFIED" if robust else "FAILED_OR_INSUFFICIENT",
                "pit_approved":False})
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--out",default="out/regime_events")
    a=p.parse_args()
    report=study(load(a.csv))
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# New gap and volatility-regime event hypotheses","",
           "Current survivors, exposed holdout, no independent validation. Not PAPER approved.","",
           "| Market | Family | Train n/mean % | Valid n/mean % | Exposed n/mean % | Result |",
           "|---|---|---:|---:|---:|---|"]
    for r in report["results"]:
        fmt=lambda x:str(x["n"])+"/"+str(x["avg_net"])
        lines.append("| "+" | ".join((r["market"],r["family"],fmt(r["train"]),
                     fmt(r["validation"]),fmt(r["previously_exposed_holdout"]),r["status"]))+" |")
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("REGIME_EVENT_RESEARCH",len(report["results"]),"cells, no PAPER")

if __name__=="__main__":main()
