"""Secondary-source data audit, deliberately separate from return generation.

Bybit spot is NOT Binance: price differences can reflect exchange basis.
Stooq is an independent, unofficial US equity history endpoint. Missing access
is an explicit audit gap, NEVER fabricated agreement or replacement prices.
BIST has no verified independent OHLCV provider here; report this limitation.
"""
from __future__ import annotations
import argparse,csv,io,json,math
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen,Request
from statistics import median
from research_v4.historical_real_data import get_json
from research_v4.multimarket_exploratory import load

BYBIT="https://api.bybit.com/v5/market/kline"
STOOQ="https://stooq.com/q/d/l/"
MAX_PER_MARKET=12
OKX="https://www.okx.com/api/v5/market/history-candles"

def bybit_spot(symbol,get=get_json):
    url=BYBIT+"?"+urlencode({"category":"spot","symbol":symbol,"interval":"D","limit":200})
    obj=get(url)
    if not isinstance(obj,dict) or obj.get("retCode")!=0:raise ValueError("BYBIT_NOT_AVAILABLE")
    result=obj.get("result") or {}
    if result.get("category")!="spot" or result.get("symbol")!=symbol:raise ValueError("BYBIT_SYMBOL_MISMATCH")
    rows=result.get("list")
    if not isinstance(rows,list):raise ValueError("BYBIT_BAD_SCHEMA")
    from datetime import datetime,timezone
    result={}
    for row in rows:
        if not isinstance(row,list) or len(row)<6:raise ValueError("BYBIT_BAD_BAR")
        day=datetime.fromtimestamp(int(row[0])/1000,timezone.utc).date().isoformat()
        price=float(row[4])
        if not math.isfinite(price) or price<=0:raise ValueError("BYBIT_BAD_PRICE")
        result[day]=price
    return result


def okx_spot(symbol,get=get_json):
    if not symbol.endswith("USDT") or len(symbol)<=4:
        raise ValueError("OKX_INVALID_SPOT_PAIR")
    inst=symbol[:-4]+"-USDT"
    url=OKX+"?"+urlencode({"instId":inst,"bar":"1Dutc","limit":100})
    obj=get(url)
    if not isinstance(obj,dict) or str(obj.get("code"))!="0":
        raise ValueError("OKX_NOT_AVAILABLE")
    rows=obj.get("data")
    if not isinstance(rows,list):raise ValueError("OKX_BAD_SCHEMA")
    from datetime import datetime,timezone
    result={}
    for row in rows:
        if not isinstance(row,list) or len(row)<5:raise ValueError("OKX_BAD_BAR")
        day=datetime.fromtimestamp(int(row[0])/1000,timezone.utc).date().isoformat()
        px=float(row[4])
        if not math.isfinite(px) or px<=0:raise ValueError("OKX_BAD_PRICE")
        result[day]=px
    return result

def stooq_us(symbol,get_text):
    url=STOOQ+"?"+urlencode({"s":symbol.lower()+".us","i":"d"})
    raw=get_text(url)
    if not raw or len(raw)>8000000:raise ValueError("STOOQ_BAD_RESPONSE")
    table=list(csv.DictReader(io.StringIO(raw)))
    if not table or not all(x in table[0] for x in ("Date","Close")):
        raise ValueError("STOOQ_BAD_SCHEMA")
    out={}
    for item in table:
        try:
            d=item["Date"]
            from datetime import date
            date.fromisoformat(d)
            px=float(item["Close"])
            if not math.isfinite(px) or px<=0:continue
            out[d]=px
        except (ValueError,KeyError,TypeError):continue
    if not out:raise ValueError("STOOQ_NO_BARS")
    return out

def text_get(url):
    with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0 (research audit, no trade)"}),timeout=16) as r:
        raw=r.read(8000001)
    if len(raw)>8000000:raise ValueError("STOOQ_TOO_LARGE")
    return raw.decode("utf-8")

def compare(primary,other,last_n=90):
    common=sorted(set(primary)&set(other))[-last_n:]
    if len(common)<20:return {"overlap_days":len(common),"state":"INSUFFICIENT_OVERLAP","median_abs_pct":None,"max_abs_pct":None}
    diffs=[abs(100*(other[d]/primary[d]-1)) for d in common]
    return {"overlap_days":len(common),"state":"COMPARED_NOT_PIT_VERIFIED",
            "median_abs_pct":round(median(diffs),4),
            "max_abs_pct":round(max(diffs),4)}

def audit(series, *, get_bybit=bybit_spot, get_okx=okx_spot, get_stooq=None, limit=MAX_PER_MARKET):
    if get_stooq is None:get_stooq=lambda s:stooq_us(s,text_get)
    result={"schema":"EAR.secondary_market_audit.v1","paper_approved":False,
            "trade_authorized":False,"pit_verified":False,
            "bybit_is_distinct_spot_venue":True,
            "stooq_adjustment_conventions_not_equivalent_to_yahoo":True,
            "bist_independent_price_source":"NOT_AVAILABLE_UNVERIFIED",
            "comparisons":[]}
    for market in ("BIST","US","CRYPTO"):
        items=sorted((symbol,seq) for (m,symbol),seq in series.items() if m==market)
        # Deterministic audited subset; never choose providers based on results.
        for symbol,seq in items[:limit]:
            row={"market":market,"symbol":symbol}
            if market=="BIST":
                row["state"]="NO_VERIFIED_SECOND_PROVIDER"
                result["comparisons"].append(row)
                continue
            baseline={b["date"].isoformat():b["close"] for b in seq}
            attempts=[]
            providers=(("BYBIT_SPOT",get_bybit),("OKX_SPOT",get_okx)) if market=="CRYPTO" else (("STOOQ_US",get_stooq),)
            for provider,fetch in providers:
                try:
                    secondary=fetch(symbol)
                    check=compare(baseline,secondary)
                    attempts.append({"provider":provider,"state":check["state"],"overlap_days":check["overlap_days"]})
                    if check["state"]=="COMPARED_NOT_PIT_VERIFIED":
                        row.update(check)
                        row["provider"]=provider
                        break
                except (ValueError,OSError,TypeError,KeyError,IndexError) as e:
                    attempts.append({"provider":provider,"state":"UNAVAILABLE","error_type":type(e).__name__,
                                     "error_detail":str(e)[:160]})
            if "state" not in row:
                row["state"]="SECONDARY_SOURCE_UNAVAILABLE_OR_INSUFFICIENT_OVERLAP"
            row["attempts"]=attempts
            result["comparisons"].append(row)
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--out",default="out/secondary_source_audit")
    p.add_argument("--limit",type=int,default=12)
    a=p.parse_args()
    if not 1<=a.limit<=20:raise ValueError("INVALID_LIMIT")
    report=audit(load(a.csv),limit=a.limit)
    dest=Path(a.out);dest.mkdir(parents=True,exist_ok=True)
    (dest/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    states=defaultdict(int)
    for r in report["comparisons"]:states[r["state"]]+=1
    text=["# Secondary price source audit (not a strategy signal)","",
          "Bybit/OKX vs Binance spot may differ by venue and UTC day cut; Stooq vs Yahoo may differ by adjustment convention.",
          "BIST independent 2nd OHLC source NOT verified. Failed providers never silently pass.","",
          "| State | Count |","|---|---:|"]
    text.extend(f"| {k} | {v} |" for k,v in sorted(states.items()))
    (dest/"report.md").write_text("\n".join(text)+"\n")
    print("SECONDARY_SOURCE_AUDIT",dict(states))

if __name__=="__main__":main()
