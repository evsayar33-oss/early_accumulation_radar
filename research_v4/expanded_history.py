"""Separate expanded CURRENT-universe experiment for BIST, US microcaps and altcoins.

Research only. No point-in-time membership reconstruction, PAPER or orders.
Keeps V4 evidence and the original historical workflow unchanged.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
from research_v4.equity_sources import KAP, download as equity_download, parse_kap
from research_v4.us_fallback import TV_URL, tv_payload, parse_tv
from research_v4.historical_real_data import (
    FIELDS, BINANCE_INFO, COINGECKO, binance_bars, yahoo_bars, validate, get_json
)

LIMITS={"BIST":36,"US":36,"CRYPTO":48}
CAP_LOW=10000000
CAP_HIGH=500000000
PEG_IDS={"tether","usd-coin","first-digital-usd","true-usd","dai",
         "ethena-usde","pax-dollar","paypal-usd","usdd","usdx-money-usdx",
         "usual-usd","world-liberty-financial-usd","ripple-usd"}
PEG_SYMBOLS={"USDT","USDC","FDUSD","TUSD","USDE","USDD","DAI","USDP",
             "PYUSD","USD1","RLUSD","EURC","EUR","GUSD","FRAX","USD0"}
PEG_NAME=re.compile(r"(?:stablecoin|stable coin|usd stable|dollar stable)",re.I)

def stable(coin):
    sym=str(coin.get("symbol") or "").upper()
    return (sym in PEG_SYMBOLS or str(coin.get("id") or "").lower() in PEG_IDS or
            bool(PEG_NAME.search(str(coin.get("name") or ""))))

def altcoins(get=get_json,limit=LIMITS["CRYPTO"]):
    exchange=get(BINANCE_INFO)
    if not isinstance(exchange,dict) or not isinstance(exchange.get("symbols"),list):
        raise ValueError("BINANCE_EXCHANGE_INFO_SCHEMA")
    active={x.get("symbol") for x in exchange["symbols"] if isinstance(x,dict)
            and x.get("status")=="TRADING" and x.get("quoteAsset")=="USDT"
            and x.get("isSpotTradingAllowed",True) and isinstance(x.get("symbol"),str)}
    coins=[]
    for page in range(1,5):
        url=COINGECKO+"?"+urlencode({"vs_currency":"usd","order":"market_cap_desc",
                 "per_page":250,"page":page,"sparkline":"false"})
        data=get(url)
        if not isinstance(data,list):raise ValueError("COINGECKO_BAD_SCHEMA")
        coins.extend(x for x in data if isinstance(x,dict))
        if len(data)<250:break
    # Do not accept ambiguous CoinGecko symbols, even across pages.
    counts={}
    for c in coins:
        ticker=str(c.get("symbol") or "").upper()
        counts[ticker]=counts.get(ticker,0)+1
    result=[]
    for c in coins:
        ticker=str(c.get("symbol") or "").upper()
        cap=c.get("market_cap")
        pair=ticker+"USDT"
        if (not re.fullmatch(r"[A-Z0-9]{2,15}",ticker) or
            not isinstance(cap,(int,float)) or isinstance(cap,bool) or
            not CAP_LOW<=cap<=CAP_HIGH or pair not in active or
            counts[ticker]!=1 or stable(c)):continue
        result.append({"symbol":pair,"selection_source":"COINGECKO_CURRENT_CAP_BINANCE_ACTIVE",
                       "cap_snapshot_usd":cap,"coingecko_id":c.get("id")})
    # Deterministic hash selection limits concentration in rank order.
    result.sort(key=lambda x:hashlib.sha256(x["symbol"].encode()).hexdigest())
    if len(result)<2:raise ValueError("CRYPTO_CURRENT_UNIVERSE_TOO_SMALL")
    return result[:limit]

def bist_symbols(html,limit=LIMITS["BIST"]):
    symbols=parse_kap(html)
    if len(symbols)<2:raise ValueError("KAP_CURRENT_DIRECTORY_TOO_SMALL")
    # No verified market-cap / float data from KAP ticker listing.
    chosen=sorted(symbols,key=lambda s:hashlib.sha256(s.encode()).hexdigest())[:limit]
    return [{"symbol":s,"selection_source":"KAP_CURRENT_DIRECTORY_NOT_SMALLCAP_VERIFIED",
             "cap_snapshot_usd":None} for s in chosen]

def us_symbols(document,limit=LIMITS["US"]):
    parsed=parse_tv(document)
    unique={}
    for x in parsed:
        sym=x["symbol"]
        if sym not in unique:
            unique[sym]={"symbol":sym,"selection_source":"TRADINGVIEW_CURRENT_SMALLCAP_FILTER",
                         "cap_snapshot_usd":x["market_cap_usd_screen"]}
    if len(unique)<2:raise ValueError("US_CURRENT_SMALLCAP_UNIVERSE_TOO_SMALL")
    selected=sorted(unique.values(),key=lambda x:hashlib.sha256(x["symbol"].encode()).hexdigest())
    return selected[:limit]

def collect(output, *, get=get_json, get_equity=equity_download,
            timestamp_ms=None, limits=None):
    now=int(timestamp_ms if timestamp_ms is not None else time.time()*1000)
    limits=LIMITS if limits is None else limits
    # Avoid a silent fallback to the previous six-symbol diagnostic.
    kaph=get_equity(KAP,as_text=True)
    tv=get_equity(TV_URL,payload=tv_payload())
    chosen={"BIST":bist_symbols(kaph,limits["BIST"]),
            "US":us_symbols(tv,limits["US"]),
            "CRYPTO":altcoins(get,limits["CRYPTO"])}
    manifest={"schema":"EAR.expanded_current_universe.v1",
        "asof_utc":datetime.fromtimestamp(now/1000,timezone.utc).isoformat(),
        "source_class":"CURRENT_ONLY_NOT_POINT_IN_TIME",
        "limits":limits,"universe":chosen,"coverage":{},"errors":[],"sources":[],
        "pit_universe_verified":False,"corporate_actions_verified":False,
        "historically_delisted_included":False,"smallcap_verified_bist":False,
        "trade_authorized":False,"paper_approved":False}
    rows=[]
    for market,entries in chosen.items():
        complete=0
        for item in entries:
            symbol=item["symbol"]
            try:
                if market=="CRYPTO":
                    bars=binance_bars(symbol,now,download=get)
                    source="BINANCE_SPOT_DAILY"
                else:
                    bars,host=yahoo_bars(symbol,market,now,download=get)
                    source="YAHOO_CHART_DAILY"
                valid=validate(bars,symbol,market,min_bars=180 if market=="CRYPTO" else 300)
            except (ValueError,KeyError,IndexError,TypeError,OSError) as exc:
                # Keep a controlled machine-readable reason, without exposing URLs or credentials.
                reason=(str(exc).split(":",1)[0] if isinstance(exc,ValueError)
                        else type(exc).__name__)
                if not re.fullmatch(r"[A-Za-z0-9_]{2,100}",reason):
                    reason=type(exc).__name__
                manifest["errors"].append({"market":market,"symbol":symbol,
                                           "reason":type(exc).__name__,
                                           "reason_code":reason,
                                           "http_status":getattr(exc,"code",None)})
                continue
            rows.extend(valid)
            complete+=1
            manifest["sources"].append({"market":market,"symbol":symbol,
                         "source":source,"bars":len(valid),"first":valid[0][2],"last":valid[-1][2]})
        manifest["coverage"][market]={"requested":len(entries),"usable":complete}
    out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    if any(v["usable"]<2 for v in manifest["coverage"].values()):
        manifest["status"]="BLOCKED_INSUFFICIENT_SOURCE_COVERAGE"
        (out/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
        raise ValueError("EXPANDED_UNIVERSE_COVERAGE_BELOW_MINIMUM")
    path=out/"prices.csv"
    with path.open("w",encoding="utf8",newline="") as f:
        writer=csv.writer(f)
        writer.writerow(FIELDS)
        writer.writerows(sorted(rows))
    manifest["rows"]=len(rows)
    manifest["symbols"]=sum(x["usable"] for x in manifest["coverage"].values())
    manifest["csv_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["status"]="PARTIAL_COVERAGE" if manifest["errors"] else "COMPLETE_CURRENT_SAMPLE"
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print("EXPANDED_RESEARCH_OHLCV",manifest["rows"],"rows",manifest["symbols"],
          "symbols",manifest["status"],flush=True)
    return manifest

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="out/expanded_history")
    parser.add_argument("--bist",type=int,default=LIMITS["BIST"])
    parser.add_argument("--us",type=int,default=LIMITS["US"])
    parser.add_argument("--crypto",type=int,default=LIMITS["CRYPTO"])
    args=parser.parse_args()
    limits={"BIST":args.bist,"US":args.us,"CRYPTO":args.crypto}
    if any(not 2<=v<=60 for v in limits.values()):raise ValueError("INVALID_SAMPLE_LIMIT")
    collect(args.out,limits=limits)

if __name__=="__main__":
    main()
