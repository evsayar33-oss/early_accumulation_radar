"""Collect actual historical daily OHLCV; never promote current survivors to PIT history.

BIST and US: Yahoo public chart endpoint (unofficial); crypto: Binance public
spot klines. Fail closed on missing sources, partial bars, invalid schema or
insufficient history. Data are downloaded to workflow artifacts, never to main.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timedelta, timezone, date
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from radar.ledger import read_verify

FIELDS=("market","symbol","date","open","high","low","close","volume",
        "pit_universe_verified","corporate_actions_verified")
BINANCE="https://data-api.binance.vision/api/v3/klines"
YAHOO=("https://query1.finance.yahoo.com/v8/finance/chart/",
       "https://query2.finance.yahoo.com/v8/finance/chart/")
CRYPTO_BENCHMARKS=("BTCUSDT","ETHUSDT","SOLUSDT")
COINGECKO="https://api.coingecko.com/api/v3/coins/markets"
BINANCE_INFO="https://data-api.binance.vision/api/v3/exchangeInfo"
MIN_MARKET_CAP_USD=10000000
MAX_MARKET_CAP_USD=500000000
MAX_ALTCOINS=20

def discover_current_altcoins(download=get_json):
    """Current-cap discovery only. Never assert historical cap or delisted coverage."""
    listed=download(BINANCE_INFO)
    if not isinstance(listed,dict) or not isinstance(listed.get("symbols"),list):
        raise ValueError("BINANCE_EXCHANGEINFO_SCHEMA")
    tradable={x["symbol"] for x in listed["symbols"]
              if isinstance(x,dict) and x.get("status")=="TRADING"
              and x.get("quoteAsset")=="USDT" and x.get("isSpotTradingAllowed",True)
              and isinstance(x.get("symbol"),str)}
    selected=[]
    seen=set()
    for page in range(1,5):
        query=urlencode({"vs_currency":"usd","order":"market_cap_desc",
                         "per_page":250,"page":page,"sparkline":"false"})
        coins=download(COINGECKO+"?"+query)
        if not isinstance(coins,list):raise ValueError("COINGECKO_MARKETS_SCHEMA")
        for coin in coins:
            if not isinstance(coin,dict):continue
            cap=coin.get("market_cap")
            ticker=str(coin.get("symbol") or "").upper()
            if not isinstance(cap,(int,float)) or not MIN_MARKET_CAP_USD<=cap<=MAX_MARKET_CAP_USD:
                continue
            if not re.fullmatch(r"[A-Z0-9]{2,15}",ticker):continue
            pair=ticker+"USDT"
            if pair not in tradable or pair in seen:continue
            # Symbol mapping can be ambiguous: exclude collision candidates.
            if sum(1 for c in coins if isinstance(c,dict) and str(c.get("symbol") or "").upper()==ticker)>1:
                continue
            seen.add(pair)
            selected.append({"symbol":pair,"coingecko_id":coin.get("id"),
                             "snapshot_market_cap_usd":cap})
            if len(selected)>=MAX_ALTCOINS:return selected
        if len(coins)<250:break
    if len(selected)<2:raise ValueError("INSUFFICIENT_CURRENT_ALTCOIN_CANDIDATES")
    return selected

DAY_MS=86400000
MAX_RESPONSE_BYTES=12000000

def get_json(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (EAR historical research; no trading)",
                             "Accept":"application/json"})
    with urlopen(req,timeout=18) as res:
        data=res.read(MAX_RESPONSE_BYTES+1)
    if len(data)>MAX_RESPONSE_BYTES:
        raise ValueError("RESPONSE_TOO_LARGE")
    return json.loads(data)

def current_equity_symbols(ledger):
    # Hash validation catches modified or incomplete snapshots.
    records=read_verify(Path(ledger))
    if not records:
        raise ValueError("EMPTY_V4_EQUITY_LEDGER")
    latest=records[-1]
    result={}
    for market in ("BIST","US"):
        sample=latest.get("markets",{}).get(market,{}).get("sample",[])
        symbols=sorted({x.get("symbol","") for x in sample
                        if isinstance(x,dict) and re.fullmatch(r"[A-Z]{1,8}",x.get("symbol",""))})
        if len(symbols)<2:
            raise ValueError("INSUFFICIENT_"+market+"_CURRENT_SAMPLE")
        result[market]=symbols
    return result,latest["sha256"]

def yahoo_bars(symbol,market,now_ms,download=get_json):
    yf=symbol+(".IS" if market=="BIST" else "")
    # Five years, without using Yahoo adjusted close as unverified OHLC.
    params=urlencode({"range":"5y","interval":"1d","events":"div,splits"})
    errors=[]
    for host in YAHOO:
        try:
            response=download(host+quote(yf,safe="")+"?"+params)
            chart=response["chart"]
            if chart.get("error"):
                raise ValueError("YAHOO_CHART_ERROR")
            result=chart["result"][0]
            if result.get("meta",{}).get("symbol","").upper()!=yf.upper():
                raise ValueError("YAHOO_SYMBOL_MISMATCH")
            ts=result["timestamp"]
            ohlcv=result["indicators"]["quote"][0]
            out=[]
            for i,t in enumerate(ts):
                # Exclude today's incomplete session (UTC conservative).
                if int(t)*1000//DAY_MS>=now_ms//DAY_MS:
                    continue
                try:
                    vals=[float(ohlcv[k][i]) for k in ("open","high","low","close","volume")]
                    d=datetime.fromtimestamp(int(t),timezone.utc).date().isoformat()
                except (TypeError,ValueError,IndexError,KeyError):
                    continue
                out.append((d,*vals))
            if not out:raise ValueError("YAHOO_NO_BARS")
            return out,host
        except (KeyError,IndexError,TypeError,ValueError,OSError) as exc:
            errors.append(type(exc).__name__)
    raise ValueError("YAHOO_BOTH_HOSTS_FAILED:"+",".join(errors))

def binance_bars(symbol,now_ms,download=get_json,years=5):
    end_ms=(now_ms//DAY_MS)*DAY_MS
    cursor=end_ms-years*366*DAY_MS
    out={}
    pages=0
    while cursor<end_ms and pages<10:
        url=BINANCE+"?"+urlencode({"symbol":symbol,"interval":"1d",
                                   "startTime":cursor,"endTime":end_ms-1,"limit":1000})
        raw=download(url)
        if not isinstance(raw,list):
            raise ValueError("BINANCE_SCHEMA")
        if not raw:
            break
        new_cursor=cursor
        for bar in raw:
            if not isinstance(bar,list) or len(bar)<7:
                raise ValueError("BINANCE_BAR_SCHEMA")
            open_ms=int(bar[0])
            close_ms=int(bar[6])
            if open_ms<cursor or open_ms>=end_ms:
                continue
            if close_ms>=now_ms:
                continue
            d=datetime.fromtimestamp(open_ms/1000,timezone.utc).date().isoformat()
            out[d]=(d,float(bar[1]),float(bar[2]),float(bar[3]),float(bar[4]),float(bar[5]))
            new_cursor=max(new_cursor,open_ms+DAY_MS)
        if new_cursor<=cursor:raise ValueError("BINANCE_PAGINATION_STALLED")
        cursor=new_cursor
        pages+=1
        if len(raw)<1000:break
    if pages>=10 and cursor<end_ms:
        raise ValueError("BINANCE_PAGE_LIMIT")
    if not out:raise ValueError("BINANCE_NO_BARS")
    return [out[k] for k in sorted(out)]

def validate(rows,symbol,market,min_bars=300):
    unique={}
    for raw in rows:
        d,*vals=raw
        day=date.fromisoformat(d)
        if d in unique:raise ValueError("DUPLICATE_DATE_"+symbol)
        if any(not __import__("math").isfinite(x) for x in vals):
            raise ValueError("NONFINITE_"+symbol)
        o,h,l,c,v=vals
        if min(o,h,l,c)<=0 or v<0 or l>min(o,c) or h<max(o,c) or h<l:
            raise ValueError("BAD_BAR_"+symbol)
        unique[d]=(market,symbol,d,*vals,"false","false")
    if len(unique)<min_bars:
        raise ValueError("INSUFFICIENT_HISTORY_"+market+"_"+symbol+"_"+str(len(unique)))
    return [unique[d] for d in sorted(unique)]

def fetch_all(ledger,output,download=get_json,now_ms=None):
    now_ms=int(now_ms if now_ms is not None else time.time()*1000)
    selection,ledger_sha=current_equity_symbols(ledger)
    altcoin_candidates=discover_current_altcoins(download=download)
    selection["CRYPTO"]=[c["symbol"] for c in altcoin_candidates]
    altcoin_meta={c["symbol"]:c for c in altcoin_candidates}
    # Individual delistings/outages must not fabricate data or suppress
    # coverage gaps. Demand at least two genuine series per market.
    all_rows=[]
    manifest={"schema":"EAR.historical.real_ohlcv.v1","asof_utc":datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat(),
              "universe_reference_sha256":ledger_sha,
              "universe_type":"LATEST_CURRENT_SAMPLE_NOT_HISTORICAL_PIT",
              "pit_universe_verified":False,"corporate_actions_verified":False,
              "sources":[],"errors":[],"coverage":{},\n              "crypto_selection":{"method":"CURRENT_COINGECKO_MARKET_CAP_AND_BINANCE_SPOT",\n                 "min_market_cap_usd":MIN_MARKET_CAP_USD,"max_market_cap_usd":MAX_MARKET_CAP_USD,\n                 "historical_market_cap_verified":False,"delisted_included":False,\n                 "benchmark_only":list(CRYPTO_BENCHMARKS)},
              "trade_authorized":False,"paper_approved":False}
    for market,symbols in selection.items():
        good=0
        for symbol in symbols:
            try:
                if market=="CRYPTO":
                    bars=binance_bars(symbol,now_ms,download=download)
                    provider="BINANCE_SPOT_PUBLIC_KLINES"
                else:
                    bars,host=yahoo_bars(symbol,market,now_ms,download=download)
                    provider="YAHOO_PUBLIC_CHART_"+("QUERY1" if host==YAHOO[0] else "QUERY2")
                valid=validate(bars,symbol,market)
            except (ValueError,TypeError,KeyError,IndexError,OSError) as exc:
                # Do not log the request URL or raw payload.
                manifest["errors"].append({"market":market,"symbol":symbol,
                                           "reason":type(exc).__name__})
                continue
            good+=1
            all_rows.extend(valid)
            manifest["sources"].append({"market":market,"symbol":symbol,"provider":provider,
                "bars":len(valid),"first_date":valid[0][2],"last_date":valid[-1][2]})
        manifest["coverage"][market]={"requested":len(symbols),"usable":good,
                                     "complete":good==len(symbols)}
    target=Path(output);target.mkdir(parents=True,exist_ok=True)
    if any(x["usable"]<2 for x in manifest["coverage"].values()):
        manifest["status"]="FAILED_INSUFFICIENT_REAL_SERIES"
        (target/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf8")
        raise ValueError("INSUFFICIENT_REAL_SERIES_PER_MARKET")
    manifest["status"]="PARTIAL_COVERAGE" if manifest["errors"] else "COMPLETE_CURRENT_SAMPLE"
    csvpath=target/"prices.csv"
    with csvpath.open("w",newline="",encoding="utf8") as stream:
        writer=csv.writer(stream);writer.writerow(FIELDS);writer.writerows(sorted(all_rows))
    manifest["rows"]=len(all_rows)
    manifest["csv_sha256"]=hashlib.sha256(csvpath.read_bytes()).hexdigest()
    (target/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print("REAL_HISTORICAL_OHLCV",len(all_rows),"bars",len(manifest["sources"]),"symbols",flush=True)
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ledger",required=True)
    p.add_argument("--out",default="out/historical_real_data")
    args=p.parse_args()
    fetch_all(args.ledger,args.out)

if __name__=="__main__":
    main()
