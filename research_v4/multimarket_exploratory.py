"""Frozen multi-market exploratory candidates, never automatic PAPER/trading.
Current-survivor universe, unadjusted bars, previously inspected holdout.
"""
from __future__ import annotations
import argparse,csv,json,math
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean,median

COST={"BIST":2.0,"US":1.0,"CRYPTO":0.6}
STABLE={"FDUSDUSDT","TUSDUSDT","USDCUSDT","USDEUSDT","USDDUSDT",
        "DAIUSDT","USDPUSDT","PYUSDUSDT","USD1USDT","RLUSDUSDT","EURUSDT"}
FAMILIES=("compression_breakout","high_volume_trend","pullback_reclaim",
          "range_base_break","quiet_trend_acceleration","capitulation_reversal")
WARMUP=120
HOLD=5
COUNTS=(30,15,15)

def load(path):
    result=defaultdict(list)
    with open(path,newline="",encoding="utf8") as stream:
        for row in csv.DictReader(stream):
            market=row["market"].upper().strip()
            symbol=row["symbol"].upper().strip()
            if market not in COST or not symbol:raise ValueError("INVALID_UNIVERSE")
            if market=="CRYPTO" and symbol in STABLE:continue
            bar={k:float(row[k]) for k in ("open","high","low","close","volume")}
            if not all(math.isfinite(v) for v in bar.values()):raise ValueError("NONFINITE")
            if min(bar[k] for k in ("open","high","low","close"))<=0 or bar["volume"]<0:
                raise ValueError("INVALID_PRICE")
            if bar["low"]>min(bar["open"],bar["close"]) or bar["high"]<max(bar["open"],bar["close"]):
                raise ValueError("INVALID_OHLC")
            bar["date"]=date.fromisoformat(row["date"])
            bar["pit"]=row.get("pit_universe_verified","").lower()=="true"
            bar["actions"]=row.get("corporate_actions_verified","").lower()=="true"
            result[(market,symbol)].append(bar)
    for key,bars in result.items():
        bars.sort(key=lambda x:x["date"])
        if len({b["date"] for b in bars})!=len(bars):raise ValueError("DUPLICATE_DATE")
    return result

def features(seq,i):
    x=seq[i]
    p20=seq[i-20:i];p60=seq[i-60:i];p100=seq[i-100:i]
    v=median(y["volume"] for y in p20)
    if v<=0:return None
    h20=max(y["high"] for y in p20);l20=min(y["low"] for y in p20)
    h60=max(y["high"] for y in p60);l60=min(y["low"] for y in p60)
    return {"rv":x["volume"]/v,"r5":x["close"]/seq[i-5]["close"]-1,
            "r20":x["close"]/seq[i-20]["close"]-1,
            "r60":x["close"]/seq[i-60]["close"]-1,
            "trend":x["close"]>mean(y["close"] for y in p100),
            "h20":h20,"h60":h60,"range20":h20/l20-1,
            "range60":h60/l60-1,
            "prior_range_med":median((y["high"]-y["low"])/y["close"] for y in p60),
            "location":((x["close"]-x["low"])/(x["high"]-x["low"])
                        if x["high"]>x["low"] else .5)}

def signal(f,seq,i,z):
    x=seq[i];rv=z["rv"];r5=z["r5"]
    if f=="compression_breakout":
        return z["trend"] and z["range20"]<=.22 and rv>=1.7 and x["close"]>z["h20"] and z["location"]>=.7
    if f=="high_volume_trend":
        return z["trend"] and rv>=2 and .02<=z["r20"]<=.30 and x["close"]>x["open"] and z["location"]>=.7
    if f=="pullback_reclaim":
        return z["trend"] and z["r60"]>=.08 and -.09<=r5<=.015 and rv>=1.2 and x["close"]>x["open"]
    if f=="range_base_break":
        return z["range60"]<=.35 and rv>=1.3 and x["close"]>z["h60"] and z["location"]>=.65
    if f=="quiet_trend_acceleration":
        return z["trend"] and z["r60"]>=.06 and z["prior_range_med"]<=.065 and rv>=1.6 and 0<=r5<=.10 and x["close"]>x["open"]
    if f=="capitulation_reversal":
        return -.23<=r5<=-.08 and rv>=2.5 and z["location"]>=.7 and x["close"]>x["open"]
    raise ValueError("UNKNOWN_FAMILY")

def events(series):
    output=[]
    for (market,symbol),seq in sorted(series.items()):
        last={f:-999 for f in FAMILIES}
        for i in range(WARMUP,len(seq)-HOLD-1):
            z=features(seq,i)
            if z is None:continue
            for family in FAMILIES:
                if i-last[family]<=HOLD or not signal(family,seq,i,z):continue
                start=seq[i+1]["open"];late=seq[i+2]["open"]
                finish=seq[i+HOLD]["close"]
                gross=100*(finish/start-1)
                output.append({"market":market,"symbol":symbol,"family":family,
                  "signal":seq[i]["date"].isoformat(),
                  "outcome":seq[i+HOLD]["date"].isoformat(),
                  "net":gross-COST[market],"double_cost":gross-2*COST[market],
                  "delayed":100*(finish/late-1)-COST[market],
                  "provenance":all(x["pit"] and x["actions"] for x in seq[i-100:i+HOLD+1])})
                last[family]=i
    return output

def summary(rows):
    if not rows:return {"n":0,"avg_net":None,"median_net":None,
                         "positive_fraction":None,"avg_double_cost":None,
                         "avg_delayed":None,"symbols":0}
    return {"n":len(rows),"avg_net":round(mean(r["net"] for r in rows),4),
            "median_net":round(median(r["net"] for r in rows),4),
            "positive_fraction":round(sum(r["net"]>0 for r in rows)/len(rows),4),
            "avg_double_cost":round(mean(r["double_cost"] for r in rows),4),
            "avg_delayed":round(mean(r["delayed"] for r in rows),4),
            "symbols":len({r["symbol"] for r in rows})}

def study(series):
    all_events=events(series)
    report={"schema":"EAR.multi_market_exploratory.v1","families":list(FAMILIES),
      "attempts":len(FAMILIES)*len(COST),"paper_approved":False,"trade_authorized":False,
      "pristine_holdout":False,
      "holdout_warning":"PREVIOUS_V1_HOLDOUT_ALREADY_VIEWED; NEW RESULTS EXPLORATORY_ONLY",
      "selection_warning":"LATEST_CURRENT_SURVIVORS_NOT_HISTORICAL_PIT; DELISTED_MISSING",
      "adjustment_verified":False,"no_portfolio_nav":True,
      "excluded_peg_assets":sorted(STABLE),"results":[]}
    for market in COST:
        dates=sorted({r["date"].isoformat() for (m,_),seq in series.items()
                      if m==market for r in seq})
        if len(dates)<200:
            report["results"].append({"market":market,"status":"INSUFFICIENT_HISTORY"})
            continue
        a=dates[int(len(dates)*.6)];b=dates[int(len(dates)*.8)]
        for family in FAMILIES:
            subset=[x for x in all_events if x["market"]==market and x["family"]==family]
            train=[x for x in subset if x["outcome"]<a]
            valid=[x for x in subset if x["signal"]>=a and x["outcome"]<b]
            hold=[x for x in subset if x["signal"]>=b]
            groups=(train,valid,hold)
            sufficient=all(len(g)>=minimum for g,minimum in zip(groups,COUNTS))
            positive=sufficient and all(mean(x["net"] for x in g)>0 for g in groups)
            robust=positive and all(mean(x["double_cost"] for x in g)>0 and
                                    mean(x["delayed"] for x in g)>0 for g in groups)
            status=("EXPLORATORY_POSITIVE_NOT_VERIFIED" if robust else
                    "SOME_POSITIVE_NOT_ROBUST" if positive else
                    "INSUFFICIENT_EVENTS" if not sufficient else
                    "FAILED_POSITIVE_ALL_PERIODS")
            report["results"].append({"market":market,"family":family,"status":status,
                "train":summary(train),"validation":summary(valid),
                "previously_exposed_holdout":summary(hold),
                "train_end":a,"holdout_start":b,"pit_approved":False})
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True);p.add_argument("--out",default="out/multimarket_exploratory")
    a=p.parse_args()
    report=study(load(a.csv))
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf8")
    lines=["# Multi-market exploratory strategy families","",
      "Prior holdout is exposed; current survivors only; NOT an independent backtest or PAPER approval.","",
      "| Market | Family | Train N/mean net % | Validation N/mean net % | Exposed holdout N/mean net % | Status |",
      "|---|---|---:|---:|---:|---|"]
    for r in report["results"]:
        if "family" not in r:continue
        fmt=lambda k:str(r[k]["n"])+"/"+str(r[k]["avg_net"])
        lines.append("| "+r["market"]+" | "+r["family"]+" | "+fmt("train")+" | "+fmt("validation")+" | "+fmt("previously_exposed_holdout")+" | "+r["status"]+" |")
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    print("MULTIMARKET_EXPLORATORY",len(report["results"]),"market-family diagnostics; no PAPER approval")

if __name__=="__main__":main()
