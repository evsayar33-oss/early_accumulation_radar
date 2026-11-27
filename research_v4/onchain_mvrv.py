"""V17 real on-chain MVRV research; standard-library only and NO TRADING."""
from __future__ import annotations
import argparse,json,math,statistics
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen

API="https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
ASSETS=("btc","eth")
ROUND_TRIP_COST_BPS=35

def _day(value):
    stamp=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if stamp.tzinfo is None: raise ValueError("COINMETRICS_TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc).date().isoformat()

def fetch(asset,start="2015-01-01"):
    if asset not in ASSETS: raise ValueError("REAL_MVRV_ASSET_NOT_ALLOWLISTED")
    params=urlencode({"assets":asset,"metrics":"PriceUSD,CapMrktCurUSD,CapRealUSD",
                      "frequency":"1d","start_time":start,"page_size":10000})
    req=Request(API+"?"+params,headers={"User-Agent":"early-accumulation-radar/17"})
    with urlopen(req,timeout=40) as response: payload=json.load(response)
    source=payload.get("data") if isinstance(payload,dict) else None
    if not isinstance(source,list) or not source: raise ValueError("COINMETRICS_REAL_MVRV_EMPTY")
    rows=[];seen=set()
    for item in source:
        try:
            day=_day(item["time"]);price,market,realized=(float(item[k]) for k in
                ("PriceUSD","CapMrktCurUSD","CapRealUSD"))
        except (KeyError,TypeError,ValueError) as exc:
            raise ValueError("COINMETRICS_REAL_MVRV_SCHEMA") from exc
        if day in seen or not all(math.isfinite(x) and x>0 for x in (price,market,realized)):
            raise ValueError("COINMETRICS_REAL_MVRV_INVALID_HISTORY")
        seen.add(day);rows.append({"date":day,"price":price,"market_cap":market,"realized_cap":realized})
    rows.sort(key=lambda x:x["date"])
    if len(rows)<365: raise ValueError("COINMETRICS_REAL_MVRV_INVALID_HISTORY")
    return rows

def _quantile(values,q):
    ordered=sorted(values);position=(len(ordered)-1)*q;lo,hi=math.floor(position),math.ceil(position)
    return ordered[lo] if lo==hi else ordered[lo]+(ordered[hi]-ordered[lo])*(position-lo)

def _events(mask,horizon):
    chosen=[];last=-horizon-1
    for i,value in enumerate(mask):
        if value and i>last+horizon: chosen.append(i);last=i
    return chosen

def _score(rows,mask,start,stop,horizon=90):
    idx=[i for i in _events(mask,horizon) if start<=i and i+horizon<stop]
    if not idx:return {"n":0,"mean_net":None,"hit_rate":None,"max_overlapping_positions":0}
    returns=[rows[i+horizon]["price"]/rows[i]["price"]-1-ROUND_TRIP_COST_BPS/10000 for i in idx]
    return {"n":len(idx),"mean_net":round(statistics.mean(returns),6),
            "median_net":round(statistics.median(returns),6),
            "hit_rate":round(sum(x>0 for x in returns)/len(returns),6),
            "worst":round(min(returns),6),"max_overlapping_positions":1}

def analyze(asset,source_rows):
    values=[];rows=[]
    for raw in sorted(source_rows,key=lambda x:x["date"]):
        market=float(raw.get("market_cap",raw.get("CapMrktCurUSD",0)))
        realized=float(raw.get("realized_cap",raw.get("CapRealUSD",0)))
        price=float(raw.get("price",raw.get("PriceUSD",0)))
        if not all(math.isfinite(x) and x>0 for x in (market,realized,price)):
            raise ValueError("INVALID_REAL_MVRV_OBSERVATION")
        mvrv=market/realized;z=None
        if len(values)>=365:
            mean,std=statistics.mean(values),statistics.pstdev(values)
            z=(mvrv-mean)/std if std>0 else None
        values.append(mvrv)
        if z is not None:rows.append({"date":str(raw["date"]),"price":price,"mvrv":mvrv,"z":z})
    if len(rows)<500:return {"asset":asset,"status":"INSUFFICIENT_REAL_MVRV_HISTORY",
                             "paper_eligible":False,"trade_authorized":False}
    boundary=int(len(rows)*.70);discovery=[x["mvrv"] for x in rows[:boundary]]
    q10,q20=_quantile(discovery,.10),_quantile(discovery,.20)
    rules={"mvrv_below_1":[x["mvrv"]<1 for x in rows],
           "mvrv_train_q10":[x["mvrv"]<=q10 for x in rows],
           "mvrv_train_q20":[x["mvrv"]<=q20 for x in rows],
           "mvrv_z_below_minus_1":[x["z"]<=-1 for x in rows]}
    results=[{"rule":name,"discovery":_score(rows,mask,0,boundary),
              "validation":_score(rows,mask,boundary,len(rows))} for name,mask in rules.items()]
    return {"schema":"EAR.v17.real_mvrv_research.v1","asset":asset,
      "source":"COIN_METRICS_COMMUNITY_ASSET_METRICS",
      "measurement":"REAL_MVRV_MARKET_CAP_DIVIDED_BY_REALIZED_CAP","proxy":False,
      "asof":rows[-1]["date"],"history":{"from":rows[0]["date"],"through":rows[-1]["date"],"observations":len(rows)},
      "split":{"discovery_end":rows[boundary-1]["date"],"validation_start":rows[boundary]["date"]},
      "thresholds_fit_on_discovery_only":{"q10":round(q10,6),"q20":round(q20,6)},"results":results,
      "staged_entry_interpretation":"RESEARCH_ONLY_FIRST_THRESHOLD_IS_NOT_A_DIP_CALL",
      "paper_eligible":False,"trade_authorized":False,"requires_quant_superlab_validation":True}

def main():
    p=argparse.ArgumentParser();p.add_argument("--out",default="out/v17_mvrv")
    p.add_argument("--asset",action="append",choices=ASSETS);args=p.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True);reports=[];errors={}
    for asset in args.asset or ASSETS:
        try:
            report=analyze(asset,fetch(asset));reports.append(report)
            (out/f"{asset}.json").write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")
        except Exception as exc:errors[asset]=f"{type(exc).__name__}: {exc}"
    summary={"schema":"EAR.v17.real_mvrv_batch.v1","reports":reports,"source_errors":errors,
             "paper_eligible":False,"trade_authorized":False}
    (out/"report.json").write_text(json.dumps(summary,indent=2,sort_keys=True,allow_nan=False)+"\n")
    lines=["# V17 real MVRV research","","Research only; no PAPER or live orders.","",
           "| Asset | History | Validation start | Rules |","|---|---:|---|---:|"]
    for r in reports:lines.append(f'| {r["asset"].upper()} | {r["history"]["observations"]} | {r["split"]["validation_start"]} | {len(r["results"])} |')
    if errors:lines+=["","Source errors: "+"; ".join(f"{k}: {v}" for k,v in errors.items())]
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("V17_REAL_MVRV",len(reports),"assets",len(errors),"source errors","NO_PAPER")

if __name__=="__main__":main()
