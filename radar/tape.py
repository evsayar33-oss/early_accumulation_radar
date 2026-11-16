"""Public *sampled* spot trade prints. Sampling is never labeled full CVD."""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlencode
from .providers import SYMBOLS,FeedError,http
import math,time

TRADE_VENUES=("binance","okx","bybit","gate")
MAX_AGE_MS=180000
@dataclass(frozen=True)
class Trade:
    venue:str
    asset:str
    trade_id:str
    event_ms:int
    price:float
    base_qty:float
    taker_side:str
    def __post_init__(self):
        if not self.trade_id or not math.isfinite(self.price) or not math.isfinite(self.base_qty) or self.price<=0 or self.base_qty<=0:
            raise FeedError("INVALID_TRADE")
        if self.taker_side not in ("buy","sell"):raise FeedError("INVALID_TAKER_SIDE")
    @property
    def notional(self): return self.price*self.base_qty

def url_for(venue,asset):
    if asset not in SYMBOLS:raise ValueError("asset")
    if venue=="binance":return "https://data-api.binance.vision/api/v3/aggTrades?"+urlencode({"symbol":SYMBOLS[asset],"limit":500})
    if venue=="bybit":return "https://api.bybit.com/v5/market/recent-trade?"+urlencode({"category":"spot","symbol":SYMBOLS[asset],"limit":60})
    if venue=="okx":return "https://www.okx.com/api/v5/market/trades?"+urlencode({"instId":asset+"-USDT","limit":100})
    if venue=="gate":return "https://api.gateio.ws/api/v4/spot/trades?"+urlencode({"currency_pair":asset+"_USDT","limit":100})
    raise ValueError("venue")

def parse(venue,asset,raw,now_ms):
    try:
        if venue=="binance":
            if not isinstance(raw,list):raise ValueError("not list")
            rows=[Trade(venue,asset,str(x["a"]),int(x["T"]),float(x["p"]),float(x["q"]),"sell" if x["m"] is True else "buy") for x in raw]
        elif venue=="bybit":
            if str(raw["retCode"])!="0":raise ValueError("retCode")
            rows=[Trade(venue,asset,str(x["execId"]),int(x["time"]),float(x["price"]),float(x["size"]),str(x["side"]).lower())
                  for x in raw["result"]["list"] if x.get("symbol")==SYMBOLS[asset] and x.get("isBlockTrade") is not True]
        elif venue=="okx":
            if str(raw["code"])!="0":raise ValueError("code")
            rows=[Trade(venue,asset,str(x["tradeId"]),int(x["ts"]),float(x["px"]),float(x["sz"]),str(x["side"]).lower())
                  for x in raw["data"] if x.get("instId")==asset+"-USDT"]
        elif venue=="gate":
            if not isinstance(raw,list):raise ValueError("not list")
            rows=[Trade(venue,asset,str(x["id"]),int(float(x["create_time_ms"])),
                        float(x["price"]),float(x["amount"]),str(x["side"]).lower())
                  for x in raw if x.get("currency_pair")==asset+"_USDT"]
        else:raise ValueError("venue")
    except (ValueError,TypeError,KeyError,IndexError) as exc:
        raise FeedError("TAPE_SCHEMA:"+str(exc)[:100]) from exc
    dedup={}
    for row in rows:
        if row.event_ms>now_ms+30000:raise FeedError("TAPE_FUTURE_TIMESTAMP")
        if now_ms-row.event_ms <0:continue
        if now_ms-row.event_ms<=MAX_AGE_MS:
            if row.trade_id in dedup and dedup[row.trade_id]!=row:raise FeedError("TAPE_CONFLICTING_ID")
            dedup[row.trade_id]=row
    return sorted(dedup.values(),key=lambda x:(x.event_ms,x.trade_id))

def summarize(venue,asset,trades,now_ms):
    if not trades:return {"venue":venue,"asset":asset,"status":"NO_FRESH_TRADES","count":0,"coverage":"RECENT_SAMPLE_NOT_CONTINUOUS"}
    buys=sum(x.notional for x in trades if x.taker_side=="buy")
    sells=sum(x.notional for x in trades if x.taker_side=="sell")
    span=(trades[-1].event_ms-trades[0].event_ms)/1000
    return {"venue":venue,"asset":asset,"status":"SAMPLED","count":len(trades),
            "first_event_ms":trades[0].event_ms,"last_event_ms":trades[-1].event_ms,
            "sample_span_s":round(span,3),"buy_usdt":round(buys,2),"sell_usdt":round(sells,2),
            "taker_buy_fraction":round(buys/(buys+sells),5) if buys+sells else None,
            "coverage":"RECENT_SAMPLE_NOT_CONTINUOUS","sampling_limit":500 if venue=="binance" else 60 if venue=="bybit" else 100}

def fetch(venue,asset,get=http,clock=lambda:int(time.time()*1000)):
    url=url_for(venue,asset)
    try:
        raw=get(url)
    except FeedError:
        if venue!="binance":raise
        url=url.replace("https://data-api.binance.vision","https://api.binance.com")
        raw=get(url)
    now_ms=clock()
    trades=parse(venue,asset,raw,now_ms)
    report=summarize(venue,asset,trades,now_ms)
    report["source_url"]=url
    return report
