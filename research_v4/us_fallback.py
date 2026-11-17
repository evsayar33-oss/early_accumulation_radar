"""Free US discovery failover. Never promote SEC-only listings to small-cap signals."""
import math
import re

TV_URL="https://scanner.tradingview.com/america/scan"

def tv_payload():
    return {"filter":[{"left":"market_cap_basic","operation":"in_range","right":[10000000,500000000]},
                      {"left":"close","operation":"in_range","right":[0.25,50]},
                      {"left":"volume","operation":"greater","right":24999},
                      {"left":"type","operation":"equal","right":"stock"}],
            "options":{"lang":"en"},"symbols":{"query":{"types":[]},"tickers":[]},
            "columns":["name","description","market_cap_basic","close","volume","exchange","type"],
            "sort":{"sortBy":"market_cap_basic","sortOrder":"asc"},"range":[0,100]}

def num(x):
    if isinstance(x,bool):
        return None
    try:
        v=float(x)
        return v if math.isfinite(v) and v>=0 else None
    except (TypeError,ValueError):
        return None

def parse_tv(obj):
    if not isinstance(obj,dict) or not isinstance(obj.get("data"),list):
        raise ValueError("TRADINGVIEW_BAD_SCHEMA")
    rows=[]
    for item in obj["data"]:
        if not isinstance(item,dict) or not isinstance(item.get("d"),list) or len(item["d"])<7:
            continue
        ticker,name,cap,price,volume,exchange,kind=item["d"][:7]
        ident=item.get("s","")
        if not isinstance(ticker,str) or not re.fullmatch(r"[A-Z]{1,6}",ticker):
            continue
        if ident not in ("NASDAQ:"+ticker,"NYSE:"+ticker,"AMEX:"+ticker):
            continue
        if str(kind).lower() not in ("stock","common stock"):
            continue
        cap,price,volume=num(cap),num(price),num(volume)
        if None in (cap,price,volume):
            continue
        if not (10000000<=cap<=500000000 and .25<=price<=50 and volume>=25000):
            continue
        rows.append({"market":"US","symbol":ticker,"exchange_reported":exchange,
                     "name":name,"market_cap_usd_screen":cap,
                     "last_price_usd_unverified":price,"last_volume_shares_unverified":volume,
                     "source":"TRADINGVIEW_PUBLIC_SCANNER_UNOFFICIAL","float_pct":None,
                     "ownership_concentration_pct":None,"point_in_time_membership_verified":False,
                     "depth_verified":False,"trade_authorized":False})
    return rows

def sec_universe(obj):
    if not isinstance(obj,dict) or not isinstance(obj.get("fields"),list) or not isinstance(obj.get("data"),list):
        raise ValueError("SEC_UNIVERSE_BAD_SCHEMA")
    fields=obj["fields"]
    if not all(x in fields for x in ("cik","ticker","exchange")):
        raise ValueError("SEC_UNIVERSE_COLUMNS")
    seen=set()
    result=[]
    for line in obj["data"]:
        if not isinstance(line,list) or len(line)!=len(fields):
            continue
        row=dict(zip(fields,line))
        sym=str(row["ticker"]).upper()
        exch=str(row["exchange"]).upper()
        if (not re.fullmatch(r"[A-Z]{2,5}",sym) or
            exch not in ("NASDAQ","NYSE","NYSE AMERICAN","NYSE MKT","AMEX") or sym in seen):
            continue
        try:
            cik=int(row["cik"])
        except (TypeError,ValueError):
            continue
        seen.add(sym)
        result.append({"market":"US","symbol":sym,"exchange_reported":exch,
                       "name":str(row.get("name") or ""),"sec_cik":cik,
                       "market_cap_usd_screen":None,"last_price_usd_unverified":None,
                       "last_volume_shares_unverified":None,
                       "source":"SEC_CURRENT_LIST_DIAGNOSTIC_NOT_SMALLCAP",
                       "float_pct":None,"ownership_concentration_pct":None,
                       "point_in_time_membership_verified":False,
                       "depth_verified":False,"trade_authorized":False})
    return result

def sec_sample(entries,now_ms,n=6):
    day=int(now_ms//86400000)
    return sorted(entries,key=lambda row:((row["sec_cik"]*2654435761+day*2246822519)%4294967291,row["symbol"]))[:n]
