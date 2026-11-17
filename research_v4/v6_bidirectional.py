"""Two-sided price-expansion hypotheses and unverified structural-gap screening.

Research-only: positive upmoves are long hypotheses; downside continuation
is an informational downside-risk hypothesis, NOT a borrowable short.
Never turn a spot drawdown into a fabricated short-trade return.
All features use data through the signal close; hypothetical entry is next open.
"""
from __future__ import annotations
import argparse,json,math
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from statistics import mean,median
from research_v4.multimarket_exploratory import load,COST

FAMILIES=("upside_expansion","downside_expansion","capitulation_recovery","blowoff_exhaustion")
HOLD=5
MIN_HISTORY=61
GAP_MAX_MULTIPLIER=2.0
MIN_EVENTS=(25,12,12)

def structural_gaps(seq):
    """Causal flags: large open/previous-close ratio implies possible event or bad data.
    Does not claim that a split or rebase was verified."""
    flags=set()
    for i in range(1,len(seq)):
        prev=seq[i-1]["close"]
        opening=seq[i]["open"]
        if prev<=0 or opening<=0 or not math.isfinite(prev) or not math.isfinite(opening):
            flags.add(i)
        elif opening/prev>=GAP_MAX_MULTIPLIER or opening/prev<=1/GAP_MAX_MULTIPLIER:
            flags.add(i)
    return flags

def features(seq,i):
    if i<MIN_HISTORY or i>=len(seq):return None
    x=seq[i]; p=seq[i-1]; prior=seq[i-20:i]
    v=median(b["volume"] for b in prior)
    atr=median((b["high"]-b["low"])/b["close"] for b in prior)
    if not v or not atr:return None
    return {"r1":x["close"]/p["close"]-1,
            "r5":x["close"]/seq[i-5]["close"]-1,
            "r20":x["close"]/seq[i-20]["close"]-1,
            "rv":x["volume"]/v,
            "range_expansion":((x["high"]-x["low"])/x["close"])/atr,
            "location":((x["close"]-x["low"])/(x["high"]-x["low"])
                        if x["high"]>x["low"] else .5),
            "prior_high":max(b["high"] for b in prior),
            "prior_low":min(b["low"] for b in prior),
            "uptrend":x["close"]>mean(b["close"] for b in seq[i-60:i]),
            "downtrend":x["close"]<mean(b["close"] for b in seq[i-60:i]),
            "price":x["close"]}

def active(f,z):
    if f=="upside_expansion":
        return z["uptrend"] and z["price"]>z["prior_high"] and z["rv"]>=1.8 and z["location"]>=.75 and z["range_expansion"]>=1.25
    if f=="downside_expansion":
        return z["downtrend"] and z["price"]<z["prior_low"] and z["rv"]>=1.8 and z["location"]<=.25 and z["range_expansion"]>=1.25
    if f=="capitulation_recovery":
        return z["r5"]<=-.12 and z["r1"]>0 and z["rv"]>=1.8 and z["location"]>=.75
    if f=="blowoff_exhaustion":
        return z["r5"]>=.20 and z["rv"]>=2.2 and z["range_expansion"]>=1.8 and z["location"]<=.35
    raise ValueError("UNKNOWN_FAMILY")

def side(f):
    return "LONG" if f in ("upside_expansion","capitulation_recovery") else "DOWNSIDE_RISK_ONLY"

def detect(series, *, asof=None):
    out=[]; blocked=Counter();latest=[]
    for (market,symbol),seq in sorted(series.items()):
        flags=structural_gaps(seq)
        previous={i for i in flags}
        if len(seq)<=MIN_HISTORY:continue
        for i in range(MIN_HISTORY,len(seq)):
            z=features(seq,i)
            if z is None:continue
            for family in FAMILIES:
                if not active(family,z):continue
                # Cannot certify a suspected split/rebase/gap without corporate-event
                # records, so quarantine the signal and its 20-bar feature window.
                suspect=any(j in previous for j in range(max(1,i-20),i+1))
                record={"market":market,"symbol":symbol,"family":family,
                        "signal":seq[i]["date"].isoformat(),"direction":side(family),
                        "price_event_verified":False,"unverified_gap_in_lookback":suspect,
                        "trade_authorized":False,"paper_approved":False}
                if suspect:
                    blocked[(market,family)]+=1
                    continue
                if i==len(seq)-1:
                    latest.append(record)
                if i+HOLD>=len(seq):continue
                # Block any discontinuity throughout the entire prospective holding
                # period: otherwise a rebase turns into fictitious PnL.
                if any(j in previous for j in range(i+1,i+HOLD+1)):
                    blocked[(market,family)]+=1
                    continue
                entry=seq[i+1]["open"];finish=seq[i+HOLD]["close"]
                later=seq[i+2]["open"]
                gross=100*(finish/entry-1)
                signed=gross if side(family)=="LONG" else -gross
                record.update({"entry_date":seq[i+1]["date"].isoformat(),
                   "outcome":seq[i+HOLD]["date"].isoformat(),
                   "gross_underlying_pct":round(gross,5),
                   # DOWNSIDE_RISK_ONLY is NOT an executable short return.
                   "directional_diagnostic_pct":round(signed-COST[market],5),
                   "double_cost_diagnostic_pct":round(signed-2*COST[market],5),
                   "delayed_diagnostic_pct":round(
                       (100*(finish/later-1) if side(family)=="LONG"
                        else -100*(finish/later-1))-COST[market],5),
                   "executable_short_simulated":False})
                out.append(record)
    # Same-bar re-signals overlap; prune by family and symbol independent of outcomes.
    reduced=[];last={}
    for r in sorted(out,key=lambda x:(x["market"],x["symbol"],x["family"],x["signal"])):
        k=(r["market"],r["symbol"],r["family"])
        if k in last and r["signal"]<=last[k]:continue
        reduced.append(r)
        last[k]=r["outcome"]
    return reduced,blocked,latest

def summary(rows):
    if not rows:return {"n":0,"symbols":0,"mean_directional_diagnostic_pct":None,
                         "mean_double_cost_pct":None,"mean_delayed_pct":None}
    return {"n":len(rows),"symbols":len({r["symbol"] for r in rows}),
       "mean_directional_diagnostic_pct":round(mean(x["directional_diagnostic_pct"] for x in rows),4),
       "mean_double_cost_pct":round(mean(x["double_cost_diagnostic_pct"] for x in rows),4),
       "mean_delayed_pct":round(mean(x["delayed_diagnostic_pct"] for x in rows),4)}

def evaluate(series):
    events,blocked,latest=detect(series)
    report={"schema":"EAR.v6_both_sides_event_research.v1",
       "paper_approved":False,"trade_authorized":False,
       "historical_pit_verified":False,"pristine_holdout":False,
       "historical_rebase_events_verified":False,
       "spot_short_allowed":False,"short_financing_or_borrow_model":False,
       "positive_returns_are_not_alpha_proof":True,
       "latest_unverified_watchlist":latest[:100],
       "blocked_suspected_price_discontinuities":[{"market":k[0],"family":k[1],"n":v}
          for k,v in sorted(blocked.items())],
       "results":[]}
    for market in COST:
        days=sorted({b["date"].isoformat() for (m,_),seq in series.items()
                     if m==market for b in seq})
        if len(days)<200:continue
        split1=days[int(len(days)*.6)]
        split2=days[int(len(days)*.8)]
        for family in FAMILIES:
            rows=[e for e in events if e["market"]==market and e["family"]==family]
            partitions=(
                [r for r in rows if r["outcome"]<split1],
                [r for r in rows if r["signal"]>=split1 and r["outcome"]<split2],
                [r for r in rows if r["signal"]>=split2])
            scores=[summary(p) for p in partitions]
            adequate=all(x["n"]>=n and x["symbols"]>=3 for x,n in zip(scores,MIN_EVENTS))
            all_positive=adequate and all(all(x[k] is not None and x[k]>0 for k in
                ("mean_directional_diagnostic_pct","mean_double_cost_pct","mean_delayed_pct"))
                for x in scores)
            report["results"].append({"market":market,"family":family,"direction":side(family),
              "train":scores[0],"validation":scores[1],
              "previously_exposed_holdout":scores[2],
              "status":"EXPLORATORY_DIAGNOSTIC_ONLY" if all_positive else
                       "REJECT_OR_INSUFFICIENT",
              "trade_authorized":False})
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--out",default="out/v6_bidirectional")
    a=p.parse_args()
    result=evaluate(load(a.csv))
    dest=Path(a.out);dest.mkdir(parents=True,exist_ok=True)
    (dest/"report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    lines=["# V6 two-sided event research and post-event watchlist","",
      "LONG hypotheses vs DOWNSIDE_RISK_ONLY hypotheses. No spot short fills, borrow, live orders or PAPER approval.",
      "Suspected split/rebase/bad gaps quarantined; no corporate action has been verified by the candle-only screen.",
      "All historic periods exposed; current survivors only. Never treat directional diagnostic as realized short PnL.","",
      "| Market | Family | Direction | Validation n / diagnostic % | Exposed n / diagnostic % | Status |",
      "|---|---|---|---:|---:|---|"]
    for x in result["results"]:
        fmt=lambda y:f'{y["n"]} / {y["mean_directional_diagnostic_pct"]}'
        lines.append("| "+" | ".join((x["market"],x["family"],x["direction"],
            fmt(x["validation"]),fmt(x["previously_exposed_holdout"]),x["status"]))+" |")
    lines+=["",f'Latest signals (historical close only, **not actionable**): {len(result["latest_unverified_watchlist"])}']
    (dest/"report.md").write_text("\n".join(lines)+"\n")
    print("V6_BIDIRECTIONAL",len(result["results"]),"cells; latest",len(result["latest_unverified_watchlist"]),
       "suspect gaps blocked",sum(x["n"] for x in result["blocked_suspected_price_discontinuities"]))

if __name__=="__main__":main()
