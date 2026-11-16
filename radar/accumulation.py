"""Closed 1-minute spot candle research. No order routing or inferred buying where unavailable."""
from __future__ import annotations
from .providers import SYMBOLS,FeedError,http
from urllib.parse import urlencode
from statistics import median
import math,time

MIN_BARS=80
STEP=60000
BINANCE_PUBLIC="https://data-api.binance.vision"
BINANCE_ALT="https://api.binance.com"

def url_for(asset,venue="binance",binance_host=BINANCE_PUBLIC):
    if asset not in SYMBOLS:raise ValueError("asset")
    if venue=="binance":
        return binance_host+"/api/v3/klines?"+urlencode({"symbol":SYMBOLS[asset],"interval":"1m","limit":120})
    if venue=="okx":
        return "https://www.okx.com/api/v5/market/candles?"+urlencode({"instId":asset+"-USDT","bar":"1m","limit":120})
    raise ValueError("venue")

def parse_candles(raw,now_ms,venue="binance"):
    if venue=="okx":
        try:
            if str(raw["code"])!="0":raise ValueError("OKX_CODE")
            # OKX API: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
            rows=[]
            for x in raw["data"]:
                if str(x[8])!="1":continue
                ts=int(x[0])
                rows.append([ts,x[1],x[2],x[3],x[4],x[5],ts+STEP-1,x[7],None,None,None,None])
            raw=rows
        except (KeyError,IndexError,TypeError,ValueError) as exc:
            raise FeedError("OKX_BAD_CANDLE_SCHEMA:"+str(exc)[:90]) from exc
    if not isinstance(raw,list):raise FeedError("CANDLE_NOT_LIST")
    bars=[];seen=set()
    try:
        for x in raw:
            t=int(x[0]);close_ts=int(x[6])
            if close_ts>=now_ms:continue
            if t in seen:raise ValueError("duplicate time")
            seen.add(t)
            op,hi,lo,cl=map(float,(x[1],x[2],x[3],x[4]))
            q=float(x[7]);taker=(float(x[10]) if venue=="binance" else None)
            if t%STEP!=0 or close_ts!=t+STEP-1:raise ValueError("invalid candle end")
            if not all(math.isfinite(v) for v in (op,hi,lo,cl,q)) or min(op,hi,lo,cl)<=0 or lo>min(op,cl) or hi<max(op,cl):raise ValueError("bad OHLC")
            if q<0 or (taker is not None and (not math.isfinite(taker) or taker<0 or taker>q+1e-5)):raise ValueError("bad taker volume")
            bars.append({"ts":t,"open":op,"high":hi,"low":lo,"close":cl,"quote_volume":q,"taker_buy_quote":taker})
    except (TypeError,IndexError,ValueError) as exc:
        raise FeedError("BAD_CANDLE:"+str(exc)[:90]) from exc
    bars.sort(key=lambda x:x["ts"])
    if len(bars)<MIN_BARS:raise FeedError("INSUFFICIENT_CLOSED_CANDLES")
    if any(b["ts"]-a["ts"]!=STEP for a,b in zip(bars,bars[1:])):raise FeedError("CANDLE_GAPS")
    if now_ms-(bars[-1]["ts"]+STEP)>180000:raise FeedError("STALE_CLOSED_CANDLES")
    return bars

def features(asset,bars,venue="binance"):
    previous=bars[-70:-10];recent=bars[-10:]
    base=median(x["quote_volume"] for x in previous)
    recent_median=median(x["quote_volume"] for x in recent)
    change=(recent[-1]["close"]/previous[-1]["close"]-1)
    total=sum(x["quote_volume"] for x in recent)
    if base<=0 or total<=0:return {"asset":asset,"status":"INSUFFICIENT_VOLUME","trade_allowed":False,"source_venue":venue}
    rvol=recent_median/base
    if venue=="binance":
        buy=sum(x["taker_buy_quote"] for x in recent)
        buy_fraction=buy/total
        accumulation=(rvol>=1.8 and buy_fraction>=0.56 and -.03<=change<=.025)
        distribution=(rvol>=1.5 and buy_fraction<=0.38 and change<=-.01)
    else:
        # OKX candle data has no taker-side volume. Do not impute or transplant Binance flow.
        buy_fraction=None;accumulation=False;distribution=False
    return {"asset":asset,"status":"HYPOTHESIS_ONLY" if venue=="binance" else "VOLUME_CONTEXT_ONLY",
            "trade_allowed":False,"instrument":venue.upper()+"_SPOT","source_venue":venue,
            "last_closed_bar_ms":recent[-1]["ts"],"price":recent[-1]["close"],
            "relative_median_volume_10m_vs_60m":round(rvol,4),
            "taker_buy_quote_fraction_10m":round(buy_fraction,5) if buy_fraction is not None else None,
            "closed_price_return_10m":round(change,6),
            "accumulation_watch":accumulation,"distribution_watch":distribution,
            "volume_watch_only":rvol>=1.8 and -.03<=change<=.025,
            "note":"Single spot venue, strictly completed candles; no independently verified alpha."}

def fetch(asset,get=http,clock=lambda:int(time.time()*1000)):
    failures=[]
    for venue,host in (("binance",BINANCE_PUBLIC),("binance",BINANCE_ALT),("okx",None)):
        url=url_for(asset,venue,binance_host=host or BINANCE_PUBLIC)
        try:
            raw=get(url)
            bars=parse_candles(raw,clock(),venue)
            result=features(asset,bars,venue)
            result["source_url"]=url
            result["attempted_source_failures"]=failures
            return result
        except (FeedError,ValueError,TypeError,KeyError) as exc:
            failures.append({"venue":venue,"endpoint":url.split("?")[0],
                             "error":type(exc).__name__+":"+str(exc)[:100]})
    raise FeedError("ALL_CANDLE_SOURCES_FAILED:"+str(failures)[:450])
