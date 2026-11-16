"""Unauthenticated public spot venue snapshots, with explicit provenance."""
from __future__ import annotations
import json, math, time
from dataclasses import replace
from dataclasses import dataclass
from urllib.request import Request, urlopen
from urllib.parse import urlencode

class FeedError(RuntimeError):
    pass

@dataclass(frozen=True)
class Quote:
    venue: str
    symbol: str
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    observed_ms: int
    retrieved_ms: int
    source: str
    market_type: str = "SPOT"
    quote_currency: str = "USDT"
    def __post_init__(self):
        vals = (self.bid, self.ask, self.bid_qty, self.ask_qty)
        if not all(math.isfinite(x) for x in vals) or self.bid <= 0 or self.ask <= self.bid or self.bid_qty < 0 or self.ask_qty < 0:
            raise FeedError("INVALID_OR_CROSSED_QUOTE")
        if self.observed_ms > self.retrieved_ms + 30000 or self.retrieved_ms - self.observed_ms > 120000:
            raise FeedError("STALE_OR_FUTURE_QUOTE")
    @property
    def mid(self): return (self.bid + self.ask)/2
    @property
    def spread_bps(self): return 10000*(self.ask-self.bid)/self.mid
    @property
    def top_bid_usd(self): return self.bid*self.bid_qty
    @property
    def top_ask_usd(self): return self.ask*self.ask_qty

SYMBOLS = {"BTC":"BTCUSDT","ETH":"ETHUSDT","SOL":"SOLUSDT"}
VENUES = ("binance","okx","bybit","bitget","gate","kraken","coinbase")
def http(url, timeout=9):
    req=Request(url,headers={"User-Agent":"early-accumulation-radar/0.1 research","Accept":"application/json"})
    try:
        with urlopen(req,timeout=timeout) as r:
            if r.status != 200: raise FeedError("HTTP_"+str(r.status))
            return json.load(r)
    except Exception as exc:
        raise FeedError(type(exc).__name__+":"+str(exc)[:100]) from exc

def as_float(x):
    y=float(x)
    if not math.isfinite(y): raise ValueError("nonfinite")
    return y

def _parse(venue, asset, obj, recv_ms):
    sym=SYMBOLS[asset]
    try:
        if venue=="binance":
            bid,ask,bq,aq=obj["bidPrice"],obj["askPrice"],obj["bidQty"],obj["askQty"]
            event=recv_ms
        elif venue=="okx":
            row=obj["data"][0]
            if row["instId"]!=asset+"-USDT": raise ValueError("symbol")
            bid,ask,bq,aq=row["bidPx"],row["askPx"],row["bidSz"],row["askSz"];event=int(row["ts"])
        elif venue=="bybit":
            if obj["retCode"]!=0: raise ValueError("retCode")
            row=obj["result"]["list"][0]
            if row["symbol"]!=sym: raise ValueError("symbol")
            bid,ask,bq,aq=row["bid1Price"],row["ask1Price"],row["bid1Size"],row["ask1Size"]
            event=int(obj["time"])
        elif venue=="bitget":
            if str(obj["code"])!="00000": raise ValueError("code")
            row=obj["data"][0]
            bid,ask,bq,aq=row["bidPr"],row["askPr"],row["bidSz"],row["askSz"];event=int(row["ts"])
        elif venue=="gate":
            bid,ask,bq,aq=obj["highest_bid"],obj["lowest_ask"],obj["highest_size"],obj["lowest_size"]
            event=recv_ms
        elif venue=="kraken":
            result=obj["result"]
            row=next(iter(result.values()))
            bid,ask,bq,aq=row["b"][0],row["a"][0],row["b"][2],row["a"][2]
            event=recv_ms
        elif venue=="coinbase":
            bid,ask,bq,aq=obj["bids"][0][0],obj["asks"][0][0],obj["bids"][0][1],obj["asks"][0][1]
            event=recv_ms
        else: raise ValueError("venue")
        return Quote(venue,asset,as_float(bid),as_float(ask),as_float(bq),as_float(aq),event,recv_ms,venue,"SPOT","USD" if venue in ("kraken","coinbase") else "USDT")
    except (KeyError,IndexError,TypeError,ValueError,StopIteration) as exc:
        raise FeedError("BAD_SCHEMA:"+str(exc)[:100]) from exc

def url_for(venue, asset):
    if asset not in SYMBOLS: raise ValueError("unsupported asset")
    sym=SYMBOLS[asset]
    if venue=="binance": return "https://api.binance.com/api/v3/ticker/bookTicker?"+urlencode({"symbol":sym})
    if venue=="okx": return "https://www.okx.com/api/v5/market/ticker?"+urlencode({"instId":asset+"-USDT"})
    if venue=="bybit": return "https://api.bybit.com/v5/market/tickers?"+urlencode({"category":"spot","symbol":sym})
    if venue=="bitget": return "https://api.bitget.com/api/v2/spot/market/tickers?"+urlencode({"symbol":sym})
    if venue=="gate": return "https://api.gateio.ws/api/v4/spot/order_book?"+urlencode({"currency_pair":asset+"_USDT","limit":1})
    if venue=="kraken": return "https://api.kraken.com/0/public/Ticker?"+urlencode({"pair":asset+"USD"})
    if venue=="coinbase": return "https://api.exchange.coinbase.com/products/"+asset+"-USD/book?level=1"
    raise ValueError("unknown venue")

def fetch_quote(venue,asset,get=http,clock=lambda:int(time.time()*1000)):
    url=url_for(venue,asset)
    raw=get(url)
    recv=clock()
    if venue=="gate":
        # Gate order_book response uses array levels, never ticker quantity heuristics.
        try:
            b,a=raw["bids"][0],raw["asks"][0]
            raw={"highest_bid":b[0],"highest_size":b[1],"lowest_ask":a[0],"lowest_size":a[1]}
        except (KeyError,IndexError,TypeError,ValueError) as exc:raise FeedError("BAD_GATE_BOOK") from exc
    return replace(_parse(venue,asset,raw,recv),source=url)
