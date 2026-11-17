"""New fixed hypotheses + explicit cross-sectional bias audit (research-only).

Not PIT: current-survivor samples, missing delistings, unverified adjustments.
No previously exposed historical period is independent confirmation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from statistics import mean, median
from research_v4.multimarket_exploratory import load,COST

FAMILIES=("relative_strength_rotation","downside_exhaustion","volume_dryup_reclaim")
MIN_EVENTS=(30,15,15)
HOLD=5

def features(seq,i):
    if i<100:return None
    x=seq[i]
    prev=seq[i-20:i]
    prev60=seq[i-60:i]
    medvol=median(y["volume"] for y in prev)
    if medvol<=0:return None
    return {"r20":x["close"]/seq[i-20]["close"]-1,
            "r60":x["close"]/seq[i-60]["close"]-1,
            "r5":x["close"]/seq[i-5]["close"]-1,
            "r1":x["close"]/seq[i-1]["close"]-1,
            "vol":x["volume"]/medvol,
            "dry":median(y["volume"] for y in seq[i-5:i])/medvol,
            "trend":x["close"]>mean(y["close"] for y in seq[i-100:i]),
            "reclaim":x["close"]>max(y["close"] for y in seq[i-5:i]),
            "loc":(x["close"]-x["low"])/(x["high"]-x["low"]) if x["high"]>x["low"] else .5,
            "prior_low":min(y["low"] for y in prev),
            "drawdown":x["close"]/max(y["high"] for y in prev60)-1}

def selected(f,z,rank,n):
    if f=="relative_strength_rotation":
        # Rank is computed from same-day observable closes only; >=5 peers.
        return n>=5 and rank is not None and rank>=.8 and z["trend"] and z["vol"]>=1.1 and 0<z["r20"]<.5
    if f=="downside_exhaustion":
        return z["drawdown"]<=-.18 and -.20<=z["r5"]<=-.05 and z["vol"]>=1.8 and z["loc"]>=.75 and z["r1"]>0
    if f=="volume_dryup_reclaim":
        return z["trend"] and z["dry"]<=.65 and z["vol"]>=1.3 and z["reclaim"] and -.06<=z["r20"]<=.25
    raise ValueError("UNKNOWN_FAMILY")

def make_events(series):
    # Every market/date rank is constructed from the entire current sample.
    # This is contemporaneous, but membership remains survivorship-biased.
    candidates=defaultdict(list)
    for (market,symbol),bars in sorted(series.items()):
        for i in range(100,len(bars)-HOLD):
            z=features(bars,i)
            if z is not None:
                candidates[(market,bars[i]["date"])].append((symbol,bars,i,z))
    events=[]
    last={}
    for (market,day),group in sorted(candidates.items()):
        # Unique ranks, deterministic ties, no forward bars.
        ranked=sorted(group,key=lambda g:(g[3]["r20"],g[0]))
        n=len(ranked)
        ranks={g[0]:j/(n-1) for j,g in enumerate(ranked)} if n>=2 else {}
        for symbol,bars,i,z in group:
            for f in FAMILIES:
                key=(market,symbol,f)
                if i-last.get(key,-999)<=HOLD:continue
                if not selected(f,z,ranks.get(symbol),n):continue
                start=bars[i+1]["open"]
                delayed=bars[i+2]["open"]
                finish=bars[i+HOLD]["close"]
                gross=100*(finish/start-1)
                events.append({"market":market,"symbol":symbol,"family":f,
                    "signal":day.isoformat(),"outcome":bars[i+HOLD]["date"].isoformat(),
                    "net":gross-COST[market],"double_cost":gross-2*COST[market],
                    "delayed":100*(finish/delayed-1)-COST[market],
                    "pit":all(b["pit"] and b["actions"] for b in bars[i-100:i+HOLD+1])})
                last[key]=i
    return events

def stats(rows):
    if not rows:return {"n":0,"symbols":0,"avg_net":None,"avg_double_cost":None,"avg_delayed":None,"win_fraction":None}
    return {"n":len(rows),"symbols":len({x["symbol"] for x in rows}),
        "avg_net":round(mean(x["net"] for x in rows),4),
        "avg_double_cost":round(mean(x["double_cost"] for x in rows),4),
        "avg_delayed":round(mean(x["delayed"] for x in rows),4),
        "win_fraction":round(mean(x["net"]>0 for x in rows),4)}

def audit(series):
    ev=make_events(series)
    report={"schema":"EAR.new_hypotheses_bias_audit.v1","families":list(FAMILIES),
        "market_family_tests":len(FAMILIES)*len(COST),
        "paper_approved":False,"trade_authorized":False,"pristine_holdout":False,
        "current_survivors_only":True,"historical_membership_verified":False,
        "delisted_included":False,"corporate_actions_verified":False,
        "bias_note":"No PIT membership; no historical cap/float; delisted missing; previously exposed holdout; event averages not portfolio NAV",
        "results":[]}
    for market in COST:
        dates=sorted({b["date"] for (m,_),bars in series.items() if m==market for b in bars})
        if len(dates)<200:
            report["results"].append({"market":market,"status":"INSUFFICIENT_HISTORY"})
            continue
        cut1=dates[int(len(dates)*.6)]
        cut2=dates[int(len(dates)*.8)]
        for family in FAMILIES:
            x=[r for r in ev if r["market"]==market and r["family"]==family]
            groups=[
                [r for r in x if r["outcome"]<cut1.isoformat()],
                [r for r in x if r["signal"]>=cut1.isoformat() and r["outcome"]<cut2.isoformat()],
                [r for r in x if r["signal"]>=cut2.isoformat()]]
            summaries=[stats(g) for g in groups]
            adequate=all(len(g)>=threshold and len({r["symbol"] for r in g})>=3
                         for g,threshold in zip(groups,MIN_EVENTS))
            # Leave-one-symbol-out: test whether a single winner dominates.
            loo=[]
            for g in groups:
                bysymbol={r["symbol"] for r in g}
                if len(bysymbol)<3:
                    loo.append(None)
                else:
                    loo.append(round(min(mean(r["net"] for r in g if r["symbol"]!=s)
                                         for s in bysymbol),4))
            robust=adequate and all(
                all(mean(r[k] for r in g)>0 for k in ("net","double_cost","delayed"))
                and worst is not None and worst>0
                for g,worst in zip(groups,loo))
            report["results"].append({"market":market,"family":family,
                "train":summaries[0],"validation":summaries[1],
                "previously_exposed_holdout":summaries[2],
                "worst_leave_one_symbol_out_avg_net":loo,
                "diagnostic_robust":bool(robust),
                "status":"EXPLORATORY_ROBUST_NOT_VERIFIED" if robust else
                         "INSUFFICIENT_EVENTS_OR_SYMBOLS" if not adequate else
                         "FAILED_STRESS_OR_SYMBOL_CONCENTRATION",
                "pit_approved":False})
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--out",default="out/new_hypotheses_bias")
    a=p.parse_args()
    report=audit(load(a.csv))
    out=Path(a.out)
    out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# New fixed hypotheses and concentration/bias diagnostics","",
           "**EXPLORATORY ONLY** — current survivors, delistings missing, exposed holdout, no PAPER approval.","",
           "| Market | Hypothesis | Train n / avg % | Validation n / avg % | Exposed holdout n / avg % | Worst LOO net (train/valid/hold) | Status |",
           "|---|---|---:|---:|---:|---|---|"]
    for r in report["results"]:
        if "family" not in r:continue
        fmt=lambda x:f'{x["n"]} / {x["avg_net"]}'
        lines.append(f'| {r["market"]} | {r["family"]} | {fmt(r["train"])} | {fmt(r["validation"])} | {fmt(r["previously_exposed_holdout"])} | {r["worst_leave_one_symbol_out_avg_net"]} | {r["status"]} |')
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("NEW_HYPOTHESES_BIAS_AUDIT",len(report["results"]),"cells; PAPER disabled")

if __name__=="__main__":main()
