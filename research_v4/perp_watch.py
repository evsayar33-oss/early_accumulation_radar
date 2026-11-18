"""V8 observational USDT perpetual universe, separate from spot/PAPER/DEX research.

ALL active linear USDT perpetuals are discovered from current exchange metadata.
A completed snapshot can detect an *already starting* move; it cannot prove
that a pump was predictable before the first observation. No trading or shorts.
Two independent venues are requested; source outages are never called agreement.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from radar.ledger import canonical, digest, read_verify

BINANCE_INFO="https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_TICKERS="https://fapi.binance.com/fapi/v1/ticker/24hr"
OKX_INFO="https://www.okx.com/api/v5/public/instruments?instType=SWAP"
OKX_TICKERS="https://www.okx.com/api/v5/market/tickers?instType=SWAP"
BITGET_INFO="https://api.bitget.com/api/v2/mix/market/contracts?productType=USDT-FUTURES"
BITGET_TICKERS="https://api.bitget.com/api/v2/mix/market/tickers?productType=USDT-FUTURES"
MAX_SOURCE_AGE_MS=300000
MAX_COMPARISON_GAP_MIN=100
COOLDOWN_MIN=90
MIN_OBSERVED_QUOTE_TURNOVER_USDT=100000
HORIZONS_MIN=(30,60,240)
PERP_NAME=re.compile(r"^[A-Z0-9]{2,25}USDT$")
OKX_NAME=re.compile(r"^([A-Z0-9]{2,25})-USDT-SWAP$")

def public_json(url):
    request=Request(url,headers={"Accept":"application/json",
        "User-Agent":"early-accumulation-v8-perp-research/1.0"})
    try:
        with urlopen(request,timeout=15) as response:
            if response.status!=200:raise ValueError("SOURCE_STATUS_NOT_200")
            payload=response.read(9000000+1)
            if len(payload)>9000000:raise ValueError("SOURCE_OVERSIZED")
            return json.loads(payload)
    except Exception as exc:
        # Never echo URLs or untrusted raw provider exception strings.
        raise RuntimeError("SOURCE_UNAVAILABLE_"+type(exc).__name__) from None

def number(v):
    if isinstance(v,bool) or v is None:raise ValueError("INVALID_NUMBER")
    result=float(v)
    if not math.isfinite(result):raise ValueError("NONFINITE")
    return result

def fresh(ts,now_ms):
    return isinstance(ts,int) and -30000<=now_ms-ts<=MAX_SOURCE_AGE_MS

def parse_binance(info,tickers,now_ms):
    if not isinstance(info,dict) or not isinstance(info.get("symbols"),list) or not isinstance(tickers,list):
        raise ValueError("BINANCE_FUTURES_SCHEMA")
    active=set()
    for obj in info["symbols"]:
        if not isinstance(obj,dict):continue
        symbol=obj.get("symbol")
        if (isinstance(symbol,str) and PERP_NAME.fullmatch(symbol) and
            obj.get("contractType")=="PERPETUAL" and obj.get("status")=="TRADING" and
            obj.get("quoteAsset")=="USDT" and obj.get("marginAsset")=="USDT"):
            active.add(symbol)
    if not active:raise ValueError("BINANCE_NO_ACTIVE_USDT_PERPS")
    rows={}
    for t in tickers:
        if not isinstance(t,dict) or t.get("symbol") not in active:continue
        try:
            p=number(t["lastPrice"])
            turn=number(t["quoteVolume"])
            change=number(t["priceChangePercent"])
            ts=int(t["closeTime"])
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
        if p<=0 or turn<0 or not fresh(ts,now_ms):continue
        rows[t["symbol"]]={"p":round(p,12),"q":round(turn,2),
                            "d":round(change,4),"ts":ts}
    if not rows:raise ValueError("BINANCE_NO_FRESH_PERP_TICKERS")
    return rows

def parse_okx(info,tickers,now_ms):
    if not isinstance(info,dict) or str(info.get("code"))!="0" or not isinstance(info.get("data"),list):
        raise ValueError("OKX_INSTRUMENT_SCHEMA")
    if not isinstance(tickers,dict) or str(tickers.get("code"))!="0" or not isinstance(tickers.get("data"),list):
        raise ValueError("OKX_TICKER_SCHEMA")
    active={}
    for obj in info["data"]:
        if not isinstance(obj,dict):continue
        m=OKX_NAME.fullmatch(str(obj.get("instId") or ""))
        if (m and obj.get("state")=="live" and obj.get("ctType")=="linear"
            and obj.get("settleCcy")=="USDT"):
            active[obj["instId"]]=m.group(1)+"USDT"
    if not active:raise ValueError("OKX_NO_ACTIVE_LINEAR_USDT_PERPS")
    rows={}
    for t in tickers["data"]:
        if not isinstance(t,dict) or t.get("instId") not in active:continue
        try:
            p=number(t["last"])
            opening=number(t["open24h"])
            ts=int(t["ts"])
            # OKX v5 linear SWAP tickers report volCcy24h in BASE units
            # and vol24h in contracts, unlike SPOT. Quote-currency volume
            # is unavailable on some schemas. NEVER treat base/contracts
            # as USDT; where necessary, estimate with the snapshot price.
            if t.get("volCcyQuote24h") not in (None,""):
                turn=number(t["volCcyQuote24h"])
                proxy=False
            else:
                turn=number(t["volCcy24h"])*p
                proxy=True
        except (KeyError,TypeError,ValueError,OverflowError):
            continue
        if p<=0 or opening<=0 or turn<0 or not fresh(ts,now_ms):continue
        sym=active[t["instId"]]
        rows[sym]={"p":round(p,12),"q":round(turn,2),
                   "q_proxy":proxy,
                   "d":round(100*(p/opening-1),4),"ts":ts}
    if not rows:raise ValueError("OKX_NO_FRESH_PERP_TICKERS")
    return rows

def parse_bitget(info,tickers,now_ms):
    """Bitget Classic V2 USDT-FUTURES; quoteVolume is quote USDT, unlike OKX base volume."""
    if not isinstance(info,dict) or str(info.get("code"))!="00000" or not isinstance(info.get("data"),list):
        raise ValueError("BITGET_INSTRUMENT_SCHEMA")
    if not isinstance(tickers,dict) or str(tickers.get("code"))!="00000" or not isinstance(tickers.get("data"),list):
        raise ValueError("BITGET_TICKER_SCHEMA")
    active=set()
    for obj in info["data"]:
        if not isinstance(obj,dict):continue
        sym=obj.get("symbol")
        if (isinstance(sym,str) and PERP_NAME.fullmatch(sym)
            and obj.get("quoteCoin")=="USDT"
            and obj.get("symbolType")=="perpetual"
            and obj.get("symbolStatus")=="normal"):
            active.add(sym)
    if not active:raise ValueError("BITGET_NO_ACTIVE_LINEAR_USDT_PERPS")
    rows={}
    for t in tickers["data"]:
        if not isinstance(t,dict) or t.get("symbol") not in active:continue
        try:
            price=number(t["lastPr"])
            opening=number(t["open24h"])  # Do not guess change24h percentage unit.
            turn=number(t["quoteVolume"])
            ts=int(t["ts"])
        except (KeyError,ValueError,TypeError,OverflowError):
            continue
        if min(price,opening)<=0 or turn<0 or not fresh(ts,now_ms):continue
        rows[t["symbol"]]={"p":round(price,12),"q":round(turn,2),
                            "q_proxy":False,
                            "d":round(100*(price/opening-1),4),"ts":ts}
    if not rows:raise ValueError("BITGET_NO_FRESH_PERP_TICKERS")
    return rows

def scan(get=public_json,clock=lambda:int(time.time()*1000)):
    now=clock()
    sources={};failed={}
    for name,first,second,parser in (
        ("binance",BINANCE_INFO,BINANCE_TICKERS,parse_binance),
        ("okx",OKX_INFO,OKX_TICKERS,parse_okx),
        ("bitget",BITGET_INFO,BITGET_TICKERS,parse_bitget)):
        try:
            info=get(first)
            ticker=get(second)
            seen_at=clock()  # provider timestamps may follow the scan's start clock
            sources[name]=parser(info,ticker,seen_at)
            now=max(now,seen_at)
        except (ValueError,RuntimeError,TypeError,KeyError,IndexError) as exc:
            failed[name]=type(exc).__name__  # No provider text or credentials.
    if not sources:raise RuntimeError("ALL_PERPETUAL_SOURCES_UNAVAILABLE")
    assets={}
    for name,items in sources.items():
        for sym,data in items.items():
            assets.setdefault(sym,{})[name]=data
    return {"schema":"EAR.perp_observations.v1",
            "scan_utc_ms":now,"sources":sorted(sources),
            "source_unavailable":failed,
            "assets":assets,"market_type":"USDT_LINEAR_PERPETUAL_ONLY",
            "trade_authorized":False,"paper_approved":False}

def pack(assets):
    encoded=json.dumps(assets,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf8")
    return base64.b64encode(zlib.compress(encoded,level=9)).decode("ascii")

def unpack(encoded):
    decompressor=zlib.decompressobj()
    raw=decompressor.decompress(base64.b64decode(encoded,validate=True),9000001)
    if len(raw)>9000000 or not decompressor.eof:raise ValueError("OVERSIZED_OR_INCOMPLETE_SNAPSHOT")
    raw+=decompressor.flush()
    if len(raw)>9000000:raise ValueError("OVERSIZED_SNAPSHOT")
    assets=json.loads(raw)
    if not isinstance(assets,dict):raise ValueError("SNAPSHOT_NOT_DICT")
    return assets

def common_venue(previous,current):
    for venue in ("binance","okx","bitget"):
        if venue in previous and venue in current:
            return venue
    return None

def cross_venue(current):
    if len(current)<2:return "UNCONFIRMED_SINGLE_VENUE"
    prices=[obj["p"] for obj in current.values()]
    dispersion=max(prices)/min(prices)-1
    return "CONSISTENT_MULTI_VENUE" if dispersion<=.04 else "DIVERGENT_MULTI_VENUE"

def classify(previous,current,prev_ms,now_ms):
    if prev_ms is None:return []
    lag=(now_ms-prev_ms)/60000
    if not 0<lag<=MAX_COMPARISON_GAP_MIN:return []
    out=[]
    for symbol,venues in sorted(current.items()):
        before=previous.get(symbol,{})
        venue=common_venue(before,venues)
        if venue is None:continue  # Never conflate different markets or missing history.
        old=before[venue];new=venues[venue]
        if old["p"]<=0 or new["p"]<=0:continue
        change=100*(new["p"]/old["p"]-1)
        extreme=abs(change)>75  # Retain, but quarantine possible rebase/redenomination.
        if max(x["q"] for x in venues.values())<MIN_OBSERVED_QUOTE_TURNOVER_USDT:
            continue
        stage="EXTREME_PRICE_MOVE_SCALE_UNVERIFIED" if extreme else None
        if not extreme and 0.8<=change<6 and new["d"]<20:
            stage="EARLY_UPWARD_MOTION_WATCH"
        elif not extreme and change>=6:
            stage="UPWARD_IMPULSE_ALREADY_IN_PROGRESS"
        elif not extreme and -6<change<=-.8 and new["d"]>-20:
            stage="EARLY_DOWNWARD_MOTION_WATCH"
        elif not extreme and change<=-6:
            stage="DOWNWARD_IMPULSE_ALREADY_IN_PROGRESS"
        if stage is None:continue
        out.append({"symbol":symbol,"stage":stage,"observed_venue":venue,
            "price_at_observation":new["p"],"prior_price":old["p"],
            "interval_minutes":round(lag,2),
            "interval_return_pct":round(change,4),
            "rolling_24h_change_pct":new["d"],
            "rolling_24h_turnover_usdt":new["q"],
            "rolling_24h_turnover_estimated_from_base_units":new.get("q_proxy",False),
            "venue_count":len(venues),"cross_venue":cross_venue(venues),
            "scale_change_verified":False,
            "signal_is_price_motion_observation_not_prediction":True,
            "trade_authorized":False,"paper_approved":False})
    return out

def append(scan_data,prior):
    timestamp=scan_data["scan_utc_ms"]
    if prior and timestamp<=prior[-1]["scan_utc_ms"]:
        raise ValueError("STALE_PERP_SCAN")
    before=unpack(prior[-1]["packed_assets"]) if prior else {}
    flags=classify(before,scan_data["assets"],
        prior[-1]["scan_utc_ms"] if prior else None,timestamp)
    # Cooldown is by direction, across early and already-moving stages.
    prior_signal={}
    for row in prior:
        for e in row["events"]:
            key=(e["symbol"],"UP" if e["interval_return_pct"]>0 else "DOWN")
            prior_signal[key]=row["scan_utc_ms"]
    recent=[]
    for e in flags:
        direction="UP" if e["interval_return_pct"]>0 else "DOWN"
        key=(e["symbol"],direction)
        if timestamp-prior_signal.get(key,0)<COOLDOWN_MIN*60000:
            continue
        recent.append(e)
    item={"schema":"EAR.perp_forward.v1","scan_utc_ms":timestamp,
        "scope":"FUTURES_RESEARCH_ONLY_NO_ORDERS",
        "packed_assets":pack(scan_data["assets"]),
        "market_type":scan_data["market_type"],
        "source_unavailable":scan_data["source_unavailable"],
        "venue_counts":{venue:sum(venue in x for x in scan_data["assets"].values())
                        for venue in scan_data["sources"]},
        "events":recent,"prev_sha256":prior[-1]["sha256"] if prior else "GENESIS",
        "trade_authorized":False,"paper_approved":False}
    item["sha256"]=digest(item)
    return item

def read(path):
    rows=read_verify(path)
    for x in rows:
        if x.get("schema")!="EAR.perp_forward.v1" or x.get("market_type")!="USDT_LINEAR_PERPETUAL_ONLY":
            raise ValueError("PERP_LEDGER_SCHEMA_CONFLICT")
        unpack(x["packed_assets"])
    return rows

def report(rows):
    if not rows:raise ValueError("EMPTY_PERP_REPORT")
    latest=rows[-1]
    followups=[]
    total_events=sum(len(r["events"]) for r in rows)
    # Keep routine reporting bounded as the immutable ledger grows over
    # months/years. Full historic events remain in the verified ledger and
    # can be recomputed offline; current report covers the last 48h only.
    recent_cutoff=latest["scan_utc_ms"]-48*3600000
    for i,r in enumerate(rows):
        if r["scan_utc_ms"]<recent_cutoff:continue
        for e in r["events"]:
            points={}
            for horizon in HORIZONS_MIN:
                venue=None
                for z in rows[i+1:]:
                    minutes=(z["scan_utc_ms"]-r["scan_utc_ms"])/60000
                    if minutes<horizon:continue
                    if minutes>horizon+60:break
                    venue=unpack(z["packed_assets"]).get(e["symbol"],{}).get(e["observed_venue"])
                    if venue:break
                if venue and e["stage"]!="EXTREME_PRICE_MOVE_SCALE_UNVERIFIED":
                    ret=100*(venue["p"]/e["price_at_observation"]-1)
                    points[str(horizon)]={"status":"OBSERVED_SNAPSHOT_PRICE_CHANGE_NOT_EXECUTABLE",
                         "underlying_return_pct":round(ret,4)}
                else:
                    points[str(horizon)]={"status":"SCALE_EVENT_UNVERIFIED" if e["stage"]=="EXTREME_PRICE_MOVE_SCALE_UNVERIFIED" else "PENDING_NO_MATCHED_OBSERVATION",
                         "underlying_return_pct":None}
            followups.append({"scan_utc_ms":r["scan_utc_ms"],
                "symbol":e["symbol"],"stage":e["stage"],
                "horizons_min":points})
    return {"schema":"EAR.perp_forward_summary.v1",
        "asof_utc":datetime.fromtimestamp(latest["scan_utc_ms"]/1000,timezone.utc).isoformat(),
        "scans":len(rows),"tracked_in_latest_snapshot":len(unpack(latest["packed_assets"])),
        "venue_counts":latest["venue_counts"],
        "source_unavailable":latest["source_unavailable"],
        "new_events":latest["events"],
        "all_event_count":total_events,
        "recent_event_count":len(followups),
        "forward_observations":followups[-120:],
        "forward_report_scope":"LAST_48H_ONLY_OLDER_EVENTS_IN_SHA_LEDGER",
        "realtime_guaranteed":False,"historical_early_detection_proven":False,
        "short_fills_verified":False,"trade_authorized":False,
        "paper_approved":False,"profitable_strategy_confirmed":False,
        "limitations":"30m scheduled scans can be delayed/skipped; 24h rolling turnover does not prove 30m signed flow, OI, executable spread or pre-move causation"}

def main():
    cli=argparse.ArgumentParser()
    cli.add_argument("--ledger",required=True)
    cli.add_argument("--out",default="out/v8_perp")
    a=cli.parse_args()
    old=read(a.ledger)
    snap=scan()
    item=append(snap,old)
    p=Path(a.ledger);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf8") as handle:handle.write(canonical(item)+"\n")
    after=read(p)
    result=report(after)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    lines=["# V8 broad USDT perpetual movement observations","",
        f"All active tracked: {result['tracked_in_latest_snapshot']}; scans: {result['scans']}",
        "Sources: "+str(result["venue_counts"])+", outages: "+str(result["source_unavailable"]),
        "Motion signals are *observations after the move starts*, NOT guaranteed pre-breakout predictions.",
        "Single venue is marked unconfirmed; rolling 24h turnover is NOT intraperiod volume.",
        "| Symbol | Observed stage | Interval % | 24h % | Sources |",
        "|---|---|---:|---:|---|"]
    for e in item["events"][:30]:
        lines.append(f"| {e['symbol']} | {e['stage']} | {e['interval_return_pct']} | {e['rolling_24h_change_pct']} | {e['cross_venue']} |")
    lines.append("\nNo real orders, no PAPER, no funding/borrow/short PnL, no backfilled missing scans.")
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("PERP_V8",len(snap["assets"]),"contracts",len(item["events"]),"new movements; sources",snap["sources"])

if __name__=="__main__":main()
