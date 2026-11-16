"""Pre-registered *diagnostic* hypotheses from closed Binance spot 1m candles.

No predictive alpha is asserted; snapshots never authorize an entry.
"""
from __future__ import annotations
from .providers import SYMBOLS,FeedError,http
from urllib.parse import urlencode
from statistics import median
import math,time

MIN_BARS=80
STEP=60000

def url_for(asset):
    if asset not in SYMBOLS:raise ValueError("asset")
    return "https://api.binance.com/api/v3/klines?"+urlencode({"symbol":SYMBOLS[asset],"interval":"1m","limit":120})

def parse_candles(raw,now_ms):
    if not isinstance(raw,list):raise FeedError("CANDLE_NOT_LIST")
    bars=[]
    seen=set()
    try:
        for x in raw:
            t=int(x[0]); close_ts=int(x[6])
            if close_ts>=now_ms:continue  # open, not completed
            if t in seen:raise ValueError("duplicate time")
            seen.add(t)
            op,hi,lo,cl=map(float,(x[1],x[2],x[3],x[4]))
            q=float(x[7]); taker=float(x[10])
            if t%STEP!=0 or close_ts!=t+STEP-1:raise ValueError("invalid candle end")
            if not all(math.isfinite(v) for v in (op,hi,lo,cl,q,taker)) or min(op,hi,lo,cl)<=0 or lo>min(op,cl) or hi<max(op,cl):raise ValueError("bad OHLC")
            if q<0 or taker<0 or taker>q+1e-5:raise ValueError("bad taker volume")
            bars.append({"ts":t,"open":op,"high":hi,"low":lo,"close":cl,"quote_volume":q,"taker_buy_quote":taker})
    except (TypeError,IndexError,ValueError) as exc:raise FeedError("BAD_CANDLE:"+str(exc)[:100]) from exc
    bars.sort(key=lambda x:x["ts"])
    if len(bars)<MIN_BARS:raise FeedError("INSUFFICIENT_CLOSED_CANDLES")
    if any(b["ts"]-a["ts"]!=STEP for a,b in zip(bars,bars[1:])):raise FeedError("CANDLE_GAPS")
    if now_ms-(bars[-1]["ts"]+STEP)>180000:raise FeedError("STALE_CLOSED_CANDLES")
    return bars

def features(asset,bars):
    previous=bars[-70:-10];recent=bars[-10:]
    base=median(x["quote_volume"] for x in previous)
    recent_median=median(x["quote_volume"] for x in recent)
    buy=sum(x["taker_buy_quote"] for x in recent)
    total=sum(x["quote_volume"] for x in recent)
    change=(recent[-1]["close"]/previous[-1]["close"]-1)
    if base<=0 or total<=0:return {"asset":asset,"status":"INSUFFICIENT_VOLUME","trade_allowed":False}
    rvol=recent_median/base
    buy_fraction=buy/total
    # Fixed preregistered diagnostic thresholds, no optimization, no trading.
    accumulation=(rvol>=1.8 and buy_fraction>=0.56 and -.03<=change<=.025)
    distribution=(rvol>=1.5 and buy_fraction<=0.38 and change<=-.01)
    return {"asset":asset,"status":"HYPOTHESIS_ONLY","trade_allowed":False,"instrument":"BINANCE_SPOT",
            "last_closed_bar_ms":recent[-1]["ts"],"price":recent[-1]["close"],
            "relative_median_volume_10m_vs_60m":round(rvol,4),
            "taker_buy_quote_fraction_10m":round(buy_fraction,5),
            "closed_price_return_10m":round(change,6),
            "accumulation_watch":accumulation,"distribution_watch":distribution,
            "note":"Single-venue completed 1m candles, no continuous trade-tape or verified alpha."}

def fetch(asset,get=http,clock=lambda:int(time.time()*1000)):
    raw=get(url_for(asset))
    bars=parse_candles(raw,clock())
    return features(asset,bars)
