"""Fail-closed, multi-provider price audit. Research-only and no price replacement.

Historical sources: Bybit/OKX/MEXC spot (crypto); Stooq/Nasdaq (US).
Current-only snapshot: TradingView BIST/US, always explicitly NOT historical.
Provider failures and adjustment/venue differences are reported, never hidden.
"""
from __future__ import annotations
import argparse,csv,io,json,math,re,time
from collections import defaultdict
from datetime import datetime,date,timezone
from pathlib import Path
from statistics import median
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from research_v4.multimarket_exploratory import load

BYBIT="https://api.bybit.com/v5/market/kline"
OKX="https://www.okx.com/api/v5/market/history-candles"
MEXC="https://api.mexc.com/api/v3/klines"
STOOQ="https://stooq.com/q/d/l/"
NASDAQ="https://api.nasdaq.com/api/quote/"
TV_BIST="https://scanner.tradingview.com/turkey/scan"
TV_US="https://scanner.tradingview.com/america/scan"
MAX_PER_MARKET=12
MAX_BYTES=4000000
TIMEOUT=7

def json_get(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (EAR nontrading data audit)",
               "Accept":"application/json","Origin":"https://www.nasdaq.com"})
    with urlopen(req,timeout=TIMEOUT) as response:raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError("RESPONSE_TOO_LARGE")
    return json.loads(raw)

def text_get(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (EAR nontrading price audit)"})
    with urlopen(req,timeout=TIMEOUT) as response:raw=response.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError("RESPONSE_TOO_LARGE")
    return raw.decode("utf-8")

def _daily_utc(ts):
    return datetime.fromtimestamp(int(ts)/1000,timezone.utc).date().isoformat()

def _valid(price):
    v=float(str(price).replace("$","").replace(",",""))
    if not math.isfinite(v) or v<=0:raise ValueError("INVALID_CLOSE")
    return v

def bybit_spot(symbol,get=json_get):
    url=BYBIT+"?"+urlencode({"category":"spot","symbol":symbol,"interval":"D","limit":200})
    obj=get(url)
    if not isinstance(obj,dict) or obj.get("retCode")!=0:raise ValueError("BYBIT_NOT_AVAILABLE")
    result=obj.get("result") or {}
    if result.get("category")!="spot" or result.get("symbol")!=symbol:
        raise ValueError("BYBIT_SYMBOL_MISMATCH")
    rows=result.get("list")
    if not isinstance(rows,list):raise ValueError("BYBIT_BAD_SCHEMA")
    out={}
    for row in rows:
        if not isinstance(row,list) or len(row)<6:raise ValueError("BYBIT_BAD_BAR")
        out[_daily_utc(row[0])]=_valid(row[4])
    return out

def okx_spot(symbol,get=json_get):
    if not re.fullmatch(r"[A-Z0-9]{2,18}USDT",symbol):raise ValueError("INVALID_SYMBOL")
    inst=symbol[:-4]+"-USDT"
    url=OKX+"?"+urlencode({"instId":inst,"bar":"1Dutc","limit":100})
    response=get(url)
    if not isinstance(response,dict) or str(response.get("code"))!="0" or not isinstance(response.get("data"),list):
        raise ValueError("OKX_UNAVAILABLE_OR_PAIR_NOT_LISTED")
    out={}
    for r in response["data"]:
        if not isinstance(r,list) or len(r)<9:raise ValueError("OKX_BAD_BAR")
        if str(r[8])!="1":continue  # closed UTC day only
        out[_daily_utc(r[0])]=_valid(r[4])
    return out

def mexc_spot(symbol,get=json_get):
    if not re.fullmatch(r"[A-Z0-9]{2,18}USDT",symbol):raise ValueError("INVALID_SYMBOL")
    url=MEXC+"?"+urlencode({"symbol":symbol,"interval":"1d","limit":100})
    data=get(url)
    if not isinstance(data,list):raise ValueError("MEXC_UNAVAILABLE_OR_PAIR_NOT_LISTED")
    now_ms=int(time.time()*1000)
    out={}
    for r in data:
        if not isinstance(r,list) or len(r)<7:raise ValueError("MEXC_BAD_BAR")
        if int(r[6])>=now_ms:continue  # incomplete candle
        out[_daily_utc(r[0])]=_valid(r[4])
    return out

def stooq_us(symbol,get_text=text_get):
    if not re.fullmatch(r"[A-Z]{1,8}",symbol):raise ValueError("INVALID_SYMBOL")
    raw=get_text(STOOQ+"?"+urlencode({"s":symbol.lower()+".us","i":"d"}))
    if not raw or len(raw)>MAX_BYTES:raise ValueError("STOOQ_BAD_RESPONSE")
    table=list(csv.DictReader(io.StringIO(raw)))
    if not table or not all(k in table[0] for k in ("Date","Close")):
        raise ValueError("STOOQ_BAD_SCHEMA")
    out={}
    for item in table:
        try:
            date.fromisoformat(item["Date"])
            out[item["Date"]]=_valid(item["Close"])
        except (ValueError,KeyError,TypeError):continue
    if not out:raise ValueError("STOOQ_NO_BARS")
    return out

def nasdaq_us(symbol,get=json_get):
    if not re.fullmatch(r"[A-Z]{1,8}",symbol):raise ValueError("INVALID_SYMBOL")
    url=NASDAQ+symbol.lower()+"/historical?"+urlencode({"assetclass":"stocks","limit":250})
    obj=get(url)
    data=obj.get("data") if isinstance(obj,dict) else None
    table=(data or {}).get("tradesTable") if isinstance(data,dict) else None
    rows=(table or {}).get("rows") if isinstance(table,dict) else None
    if not isinstance(rows,list):raise ValueError("NASDAQ_HISTORY_UNAVAILABLE")
    out={}
    for r in rows:
        if not isinstance(r,dict):continue
        try:
            raw=str(r.get("date") or "").strip()
            try:d=date.fromisoformat(raw).isoformat()
            except ValueError:d=datetime.strptime(raw,"%m/%d/%Y").date().isoformat()
            value=r.get("close")
            if value is None:continue
            out[d]=_valid(value)
        except (TypeError,ValueError):continue
    if not out:raise ValueError("NASDAQ_NO_BARS")
    return out

def compare(primary,other,last_n=90,threshold=3.0):
    overlap=sorted(set(primary)&set(other))[-last_n:]
    if len(overlap)<20:
        return {"overlap_days":len(overlap),"state":"INSUFFICIENT_OVERLAP",
                "median_abs_pct":None,"max_abs_pct":None}
    errs=[abs(100*(other[d]/primary[d]-1)) for d in overlap]
    md=round(median(errs),4)
    return {"overlap_days":len(overlap),
            "state":"CONSISTENT_REFERENCE_NOT_PIT" if md<=threshold else "DISAGREEMENT_REVIEW",
            "median_abs_pct":md,"max_abs_pct":round(max(errs),4)}

def tradingview_quote_snapshot(market,symbols,get_post=None):
    """Only a same-session quote check; NEVER substitutes for historical bars."""
    if get_post is None:
        from research_v4.equity_sources import download
        get_post=lambda u,p:download(u,payload=p)
    if market not in ("BIST","US"):return {}
    tickers=([f"BIST:{s}" for s in symbols] if market=="BIST" else
             [f"{ex}:{s}" for s in symbols for ex in ("NASDAQ","NYSE","AMEX")])
    payload={"symbols":{"tickers":tickers,"query":{"types":[]}},
             "columns":["close","time"],"range":[0,len(tickers)]}
    obj=get_post(TV_BIST if market=="BIST" else TV_US,payload)
    if not isinstance(obj,dict) or not isinstance(obj.get("data"),list):
        raise ValueError("TRADINGVIEW_SNAPSHOT_BAD_SCHEMA")
    out={}
    for item in obj["data"]:
        if not isinstance(item,dict) or not isinstance(item.get("s"),str):continue
        fields=item.get("d")
        if not isinstance(fields,list) or len(fields)<2:continue
        exchange,sym=item["s"].split(":",1) if ":" in item["s"] else ("","")
        if sym not in symbols or exchange not in (("BIST",) if market=="BIST" else ("NASDAQ","NYSE","AMEX")):continue
        try:
            px=_valid(fields[0])
            stamp=float(fields[1])
            if not math.isfinite(stamp) or stamp<=0:continue
            if stamp>1e11:stamp/=1000
            day=datetime.fromtimestamp(stamp,timezone.utc).date().isoformat()
        except (TypeError,ValueError,OverflowError,OSError):continue
        if sym in out and (out[sym]["date"]!=day or out[sym]["price"]!=px):
            out[sym]={"state":"AMBIGUOUS_EXCHANGE_QUOTE"}
        else:out[sym]={"date":day,"price":px}
    return out

def audit(series, *, get_bybit=None,get_stooq=None,get_okx=None,get_mexc=None,
          get_nasdaq=None,get_snapshot=None,limit=MAX_PER_MARKET):
    providers={"BYBIT_SPOT":get_bybit or bybit_spot,
               "OKX_SPOT_UTC":get_okx or okx_spot,
               "MEXC_SPOT_UTC":get_mexc or mexc_spot,
               "STOOQ_US":get_stooq or stooq_us,
               "NASDAQ_US":get_nasdaq or nasdaq_us}
    disabled=set()
    repeated_network=defaultdict(int)
    report={"schema":"EAR.secondary_market_audit.v2","paper_approved":False,
         "trade_authorized":False,"pit_verified":False,
         "price_reference_does_not_verify_corporate_actions":True,
         "cross_venue_spot_differences_not_data_errors":True,
         "current_quotes_are_not_historical_ohlcv":True,
         "comparisons":[],"provider_health":{}}
    for market in ("BIST","US","CRYPTO"):
        items=sorted((sym,rows) for (m,sym),rows in series.items() if m==market)[:limit]
        quotes={}
        if get_snapshot is not None and market in ("BIST","US") and items:
            try:quotes=get_snapshot(market,[x[0] for x in items])
            except (ValueError,OSError,KeyError,TypeError) as exc:
                report["provider_health"]["TV_"+market]={"state":"UNAVAILABLE","reason":type(exc).__name__}
        for symbol,seq in items:
            row={"market":market,"symbol":symbol,"tried":[]}
            baseline={b["date"].isoformat():b["close"] for b in seq}
            source_ids=(("STOOQ_US","NASDAQ_US") if market=="US" else
                        ("BYBIT_SPOT","OKX_SPOT_UTC","MEXC_SPOT_UTC") if market=="CRYPTO" else ())
            successful=False
            for provider in source_ids:
                if provider in disabled:
                    row["tried"].append({"provider":provider,"state":"CIRCUIT_OPEN"})
                    continue
                try:
                    other=providers[provider](symbol)
                    result=compare(baseline,other,threshold=5.0 if market=="CRYPTO" else 3.0)
                    row["tried"].append({"provider":provider,"state":result["state"]})
                    if result["state"]=="INSUFFICIENT_OVERLAP":continue
                    row.update(result)
                    row["provider"]=provider
                    successful=True
                    break
                except (HTTPError,URLError,ValueError,OSError,TypeError,KeyError,IndexError) as exc:
                    status=exc.code if isinstance(exc,HTTPError) else None
                    reason=type(exc).__name__
                    row["tried"].append({"provider":provider,"state":"UNAVAILABLE",
                                         "reason":reason,"http_status":status})
                    # Provider-wide block/rate limit: do not issue 12 known-bad queries.
                    if status in (401,403,418,429,451):
                        disabled.add(provider)
                    elif isinstance(exc,(URLError,OSError)):
                        repeated_network[provider]+=1
                        if repeated_network[provider]>=2:disabled.add(provider)
            if not successful:row["state"]=("NO_VERIFIED_SECOND_PROVIDER" if market=="BIST"
                                           else "SECONDARY_HISTORY_UNAVAILABLE")
            if market in ("BIST","US"):
                q=quotes.get(symbol)
                last=max(baseline) if baseline else None
                if q is None:
                    row["snapshot_state"]="NO_SNAPSHOT"
                elif q.get("state")=="AMBIGUOUS_EXCHANGE_QUOTE":
                    row["snapshot_state"]="AMBIGUOUS_SNAPSHOT"
                elif q["date"]!=last:
                    row["snapshot_state"]="DATE_MISMATCH_NOT_HISTORICAL"
                else:
                    row["snapshot_state"]="SAME_DATE_SNAPSHOT_ONLY"
                    row["snapshot_abs_pct"]=round(abs(q["price"]/baseline[last]-1)*100,4)
            report["comparisons"].append(row)
    report["provider_health"]["disabled_due_to_failures"]=sorted(disabled)
    return report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--csv",required=True)
    parser.add_argument("--out",default="out/secondary_source_audit")
    parser.add_argument("--limit",type=int,default=12)
    parser.add_argument("--with-snapshots",action="store_true")
    args=parser.parse_args()
    if not 1<=args.limit<=20:raise ValueError("INVALID_LIMIT")
    report=audit(load(args.csv),limit=args.limit,
                 get_snapshot=tradingview_quote_snapshot if args.with_snapshots else None)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    states=defaultdict(int)
    for row in report["comparisons"]:states[(row["market"],row["state"])]+=1
    lines=["# Independent sources / live-quote coverage","",
          "Quote comparison does not prove historical PIT, adjustments, or execution. Missing sources remain missing.","",
          "| Market | State | Count |","|---|---|---:|"]
    lines += [f"| {m} | {s} | {n} |" for (m,s),n in sorted(states.items())]
    lines.append("")
    lines.append("CIRCUIT_OPEN: "+", ".join(report["provider_health"]["disabled_due_to_failures"]))
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("SECONDARY_SOURCE_AUDIT",dict((str(k),v) for k,v in states.items()),flush=True)

if __name__=="__main__":main()
