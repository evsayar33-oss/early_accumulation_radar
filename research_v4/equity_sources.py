"""V4 equity price/universe source probes; discovery-only, no order routing.

Current screener survivors and 3-month charts MUST NOT be used for historical alpha.
Free public endpoints are unofficial where specified, may rate limit and may prohibit
certain reuse. Unverified float or holder concentration is never guessed.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from research_v4.us_fallback import TV_URL, tv_payload, parse_tv, sec_universe, sec_sample

NASDAQ = "https://api.nasdaq.com/api/screener/stocks"
KAP = "https://kap.org.tr/tr/bist-sirketler"
SEC_MAP = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/"
YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/",
         "https://query2.finance.yahoo.com/v8/finance/chart/")
CEDAR = "https://api.datacedar.com/v3/stocks/"
BIST_SEEDS = ("KFEIN", "JANTS", "KATMR", "OBASE", "KRVGD", "ASELS")
MARKETS = ("BIST", "US")
MAX_BODY = 6000000
MAX_US_SAMPLE = 6
MAX_BIST_SAMPLE = 6

def number(x):
    if isinstance(x, bool) or x is None:
        return None
    try:
        s = str(x).strip().replace(",", "").replace("$", "").replace("%", "")
        mult = {"K": 1000, "M": 1000000, "B": 1000000000, "T": 1000000000000}
        scale = mult.get(s[-1:].upper(), 1)
        if scale != 1:
            s = s[:-1]
        n = float(s) * scale
        return n if math.isfinite(n) and n >= 0 else None
    except (ValueError, TypeError):
        return None

def download(url, headers=None, *, as_text=False, payload=None):
    # Never log credentials or untrusted response bodies.
    h = {"User-Agent": "Mozilla/5.0 (compatible; EAR-V4-nontrading-source-health/1.0)",
         "Accept": "application/json,text/html;q=0.8"}
    h.update(headers or {})
    body=json.dumps(payload).encode("utf8") if payload is not None else None
    if body is not None:
        h["Content-Type"]="application/json"
    with urlopen(Request(url, headers=h, data=body, method="POST" if body else "GET"), timeout=12) as resp:
        if resp.status != 200:
            raise ValueError("HTTP_" + str(resp.status))
        raw = resp.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError("RESPONSE_TOO_LARGE")
    return raw.decode("utf8", errors="replace") if as_text else json.loads(raw)

class KapTables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = 0
        self.buffer = []
        self.symbols = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "td":
            self.stack += 1
            if self.stack == 1:
                self.buffer = []
    def handle_data(self, data):
        if self.stack:
            self.buffer.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "td" and self.stack:
            self.stack -= 1
            if not self.stack:
                s = "".join(self.buffer).strip()
                if re.fullmatch(r"[A-Z]{3,6}", s):
                    self.symbols.append(s)

def parse_kap(html):
    if not isinstance(html, str):
        raise ValueError("KAP_NOT_HTML")
    p = KapTables()
    p.feed(html)
    return sorted(set(p.symbols))

def parse_nasdaq(raw, exchange):
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), dict):
        raise ValueError("NASDAQ_SCHEMA")
    data = raw["data"]
    if not isinstance(data.get("rows"), list):
        raise ValueError("NASDAQ_ROWS_MISSING")
    out = []
    for row in data["rows"]:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol", "")).upper()
        if not re.fullmatch(r"[A-Z]{1,6}", sym):
            continue
        name = str(row.get("name") or "")
        if " ETF" in name.upper() or " FUND" in name.upper():
            continue
        cap = number(row.get("marketCap"))
        volume = number(row.get("volume"))
        price = number(row.get("lastsale"))
        if cap is None or volume is None or price is None:
            continue
        # Explicit, uncalibrated RESEARCH sampling thresholds, not alpha gates.
        if 10000000 <= cap <= 500000000 and volume >= 25000 and 0.25 <= price <= 50:
            out.append({"market": "US", "symbol": sym, "exchange_reported": exchange,
                        "name": name, "market_cap_usd_screen": cap,
                        "last_price_usd_unverified": price,
                        "last_volume_shares_unverified": volume,
                        "source": "NASDAQ_PUBLIC_WEB_SCREENER_UNDOCUMENTED",
                        "float_pct": None, "ownership_concentration_pct": None,
                        "point_in_time_membership_verified": False,
                        "depth_verified": False, "trade_authorized": False})
    return out, len(data["rows"]), number(data.get("totalRecords"))

def parse_yahoo(raw, expected_symbol):
    chart = raw.get("chart") if isinstance(raw, dict) else None
    rows = (chart or {}).get("result")
    if not isinstance(rows, list) or not rows:
        raise ValueError("YAHOO_CHART_UNAVAILABLE")
    obj = rows[0]
    meta = obj.get("meta", {})
    if meta.get("symbol", "").upper() != expected_symbol.upper():
        raise ValueError("YAHOO_WRONG_SYMBOL")
    stamps = obj.get("timestamp", [])
    values = ((obj.get("indicators") or {}).get("quote") or [None])[0] or {}
    columns = ("open", "high", "low", "close", "volume")
    arrays = [values.get(k) for k in columns]
    if not all(isinstance(a, list) and len(a) == len(stamps) for a in arrays):
        raise ValueError("YAHOO_BAD_BARS")
    daily = []
    for i, stamp in enumerate(stamps):
        vals = [number(a[i]) for a in arrays]
        o, h, l, c, v = vals
        if any(x is None for x in vals) or min(o, h, l, c) <= 0 or l > min(o,c) or h < max(o,c):
            continue
        t = int(stamp) * 1000
        daily.append({"ts_ms": t, "session_utc": datetime.fromtimestamp(t/1000, timezone.utc).date().isoformat(),
                      "open": o, "high": h, "low": l, "close": c, "volume": v})
    if any(b["ts_ms"]<=a["ts_ms"] for a,b in zip(daily,daily[1:])):
        raise ValueError("YAHOO_OUT_OF_ORDER_OR_DUPLICATE")
    if not daily:
        raise ValueError("YAHOO_NO_COMPLETE_VALID_BARS")
    return {"symbol": expected_symbol, "currency": meta.get("currency"),
            "bars": daily, "price_source": "YAHOO_CHART_UNOFFICIAL",
            "adjustment": "UNVERIFIED_CORPORATE_ACTION_HANDLING"}

def parse_cedar(raw, symbol):
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, list):
        raise ValueError("CEDAR_SCHEMA")
    bars = []
    for item in data:
        if not isinstance(item, dict):
            continue
        ts = number(item.get("ts_ms"))
        vals = [number(item.get(k)) for k in ("open","high","low","close","volume")]
        if ts is None or any(v is None for v in vals):
            continue
        o,h,l,c,v = vals
        if min(o,h,l,c)<=0 or l>min(o,c) or h>0 and h<max(o,c):
            continue
        bars.append({"ts_ms":int(ts),
                     "session_utc":datetime.fromtimestamp(int(ts)/1000,timezone.utc).date().isoformat(),
                     "open":o,"high":h,"low":l,"close":c,"volume":v})
    if not bars:
        raise ValueError("CEDAR_NO_BARS")
    bars.sort(key=lambda x:x["ts_ms"])
    if len({x["ts_ms"] for x in bars}) != len(bars):
        raise ValueError("CEDAR_DUPLICATE")
    return {"symbol":symbol, "bars": bars, "price_source":"DATACEDAR_OPTIONAL_FREE_KEY",
            "adjustment":"RAW_REQUESTED"}

def parse_sec_map(raw):
    if not isinstance(raw, dict):
        raise ValueError("SEC_MAP_SCHEMA")
    fields = raw.get("fields", [])
    rows = raw.get("data", [])
    if not all(x in fields for x in ("cik", "ticker")) or not isinstance(rows, list):
        raise ValueError("SEC_MAP_COLUMNS")
    return {str(dict(zip(fields,r))["ticker"]).upper(): int(dict(zip(fields,r))["cik"])
            for r in rows if isinstance(r, list) and len(r) == len(fields)}

def latest_sec_fact(raw, section, tag, unit, today):
    series = (((raw.get("facts") or {}).get(section) or {}).get(tag) or {}).get("units", {}).get(unit, [])
    eligible = []
    for row in series:
        if not isinstance(row, dict):
            continue
        filed = row.get("filed")
        end = row.get("end")
        value = number(row.get("val"))
        if not isinstance(filed, str) or not isinstance(end, str) or filed > today or end > today or value is None:
            continue
        if row.get("form") not in ("10-K","10-Q","10-K/A","10-Q/A"):
            continue
        eligible.append((filed, end, value, row.get("accn")))
    if not eligible:
        return None
    filed,end,val,accn = max(eligible, key=lambda r: (r[0],r[1]))
    return {"value": val, "filing_date": filed, "period_end": end, "accession": accn}

def safe_call(errors, stage, call):
    try:
        return call()
    except Exception as ex:
        # Do not echo API keys in errors; only type and controlled stage.
        errors.append({"stage":stage, "error":type(ex).__name__,
                       "http_status":ex.code if isinstance(ex, HTTPError) else None})
        return None

def probe_market(market, get=download, now_ms=None, sec_agent=None, cedar_key=None,
                 sleep=time.sleep, monotonic=time.monotonic, tv_primary=False):
    if market not in MARKETS:
        raise ValueError("UNKNOWN_MARKET")
    now_ms = int(time.time()*1000) if now_ms is None else int(now_ms)
    today = datetime.fromtimestamp(now_ms/1000,timezone.utc).date().isoformat()
    errors = []
    out = {"schema": "EAR.V4.equity.source_probe.v1", "market":market,
           "observed_ms":now_ms, "sources":[], "errors":errors, "observations":[],
           "historical_pit_backtest_allowed":False, "paper_entries_allowed":False,
           "trade_authorized":False, "sampling_is_representative":False,
           "float_ownership_verified":False, "corporate_actions_verified":False,
           "universe_point_in_time_verified":False,
           "audit_explanation":"CURRENT_DISCOVERY_ONLY_NO_PIT_MEMBERSHIP_OR_FLOAT"}
    cedar_state={"last_at":None}
    def cedar_get(url):
        # DataCedar free Explorer tier: 1 request/second.
        last=cedar_state["last_at"]
        if last is not None:
            wait=max(0.0,1.12-(monotonic()-last))
            if wait:
                sleep(wait)
        cedar_state["last_at"]=monotonic()
        try:
            return get(url,{"X-API-Key":cedar_key})
        except HTTPError as exc:
            if exc.code!=429:
                raise
            sleep(2.2)
            cedar_state["last_at"]=monotonic()
            return get(url,{"X-API-Key":cedar_key})
    if market=="US":
        sample=[]
        # Production discovery: prefer the working independent market-cap
        # screener. Keep Nasdaq as a fallback only if TV fails to return
        # candidates; do not poll a known-invalid provider every run.
        if tv_primary:
            tv=safe_call(errors,"tradingview_scan",lambda:get(TV_URL,payload=tv_payload()))
            if tv is not None:
                observed=safe_call(errors,"tradingview_parse",lambda:parse_tv(tv))
                if observed is not None:
                    sample.extend(observed)
                    out["sources"].append({"provider":"TRADINGVIEW_PUBLIC_SCANNER_UNOFFICIAL",
                                           "rows_returned":len(tv["data"]),"complete_universe":False})
        if not sample:
          for exchange in ("NASDAQ","AMEX","NYSE"):
              url=NASDAQ+"?"+urlencode({"tableonly":"true","limit":1000,"offset":0,"exchange":exchange})
              raw=safe_call(errors,"nasdaq_"+exchange,lambda u=url:get(u))
              if raw is None:
                  continue
              # Nasdaq sometimes returns HTTP 200 with data=null, an error
              # envelope, or no rows. These are provider-unavailable outcomes,
              # not usable screener responses. Never interpret them as zero
              # qualifying securities or a complete universe.
              data=raw.get("data") if isinstance(raw,dict) else None
              if not isinstance(data,dict) or not isinstance(data.get("rows"),list):
                  errors.append({"stage":"nasdaq_"+exchange,
                                 "error":"UNUSABLE_RESPONSE_SCHEMA",
                                 "http_status":None})
                  continue
              parsed=safe_call(errors,"nasdaq_parse_"+exchange,lambda:parse_nasdaq(raw,exchange))
              if parsed is None:
                  continue
              matches, scanned,total=parsed
              out["sources"].append({"provider":"NASDAQ_PUBLIC_WEB_SCREENER_UNDOCUMENTED",
                                     "exchange":exchange,"rows_scanned":scanned,
                                     "rows_total_unverified":total,
                                     "complete_universe":False})
              sample.extend(matches)
        # Fail over Nasdaq outage to independent current-cap discovery.
        if not sample:
            tv=safe_call(errors,"tradingview_scan",lambda:get(TV_URL,payload=tv_payload()))
            if tv is not None:
                observed=safe_call(errors,"tradingview_parse",lambda:parse_tv(tv))
                if observed is not None:
                    sample.extend(observed)
                    out["sources"].append({"provider":"TRADINGVIEW_PUBLIC_SCANNER_UNOFFICIAL",
                                           "rows_returned":len(tv["data"]),"complete_universe":False})
        unique={}
        for item in sample:
            unique.setdefault(item["symbol"],item)
        sample=sorted(unique.values(),key=lambda x:(x["market_cap_usd_screen"],x["symbol"]))
        sec_headers={"User-Agent":sec_agent,"Accept-Encoding":"identity"} if sec_agent else None
        mapping=safe_call(errors,"sec_cik_map",lambda:get(SEC_MAP,sec_headers)) if sec_headers else None
        cik_map=safe_call(errors,"sec_map_parse",lambda:parse_sec_map(mapping)) if mapping is not None else None
        if not sample and mapping is not None:
            rows=safe_call(errors,"sec_universe",lambda:sec_universe(mapping))
            if rows is not None:
                sample=sec_sample(rows,now_ms,MAX_US_SAMPLE)
                out["sources"].append({"provider":"SEC_EDGAR_EXCHANGE_TICKERS_DIAGNOSTIC",
                                       "available_current_tickers":len(rows),
                                       "market_cap_screen_verified":False,"complete_universe":False})
                out["candidate_selection_status"]="UNVERIFIED_CAP_SEC_ONLY"
        out["observations"]=sample[:MAX_US_SAMPLE]
        if sec_headers:
            for rec in out["observations"]:
                cik=rec.get("sec_cik") or (cik_map or {}).get(rec["symbol"])
                rec["sec_cik"]=cik
                if cik is None:
                    continue
                url=SEC_FACTS+"CIK"+str(cik).zfill(10)+".json"
                data=safe_call(errors,"sec_companyfacts_"+rec["symbol"],lambda u=url:get(u,sec_headers))
                if isinstance(data,dict):
                    rec["sec_public_float_usd_filing"]=latest_sec_fact(data,"dei","EntityPublicFloat","USD",today)
                    rec["sec_shares_outstanding_filing"]=(latest_sec_fact(data,"dei","EntityCommonStockSharesOutstanding","shares",today)
                        or latest_sec_fact(data,"us-gaap","CommonStockSharesOutstanding","shares",today))
                    rec["sec_free_float_percentage_verified"]=False
            out["sources"].append({"provider":"SEC_EDGAR_COMPANYFACTS","api_key_required":False,
                                   "user_agent_required":True})
        else:
            out["errors"].append({"stage":"sec_companyfacts","error":"SEC_USER_AGENT_NOT_CONFIGURED"})
    else:
        text=safe_call(errors,"kap_listing",lambda:get(KAP, as_text=True))
        symbols = safe_call(errors,"kap_parse",lambda:parse_kap(text)) if text is not None else None
        if symbols:
            chosen=[s for s in BIST_SEEDS if s in symbols]
            out["sources"].append({"provider":"KAP_PUBLIC_COMPANY_DIRECTORY","symbols_extracted":len(symbols),
                                   "ticker_membership_only":True})
            out["ticker_source"]="KAP_MATCHED_SAMPLE"
        else:
            chosen=list(BIST_SEEDS)
            out["ticker_source"]="STATIC_PROBE_SEEDS_KAP_UNAVAILABLE"
            errors.append({"stage":"kap_listing","error":"UNVERIFIED_TICKER_MEMBERSHIP"})
        for symbol in chosen[:MAX_BIST_SAMPLE]:
            record={"market":"BIST","symbol":symbol,"exchange_reported":"BIST",
                    "ticker_source":out["ticker_source"],"float_pct":None,
                    "ownership_concentration_pct":None,"fundamentals_verified":False,
                    "depth_verified":False,"trade_authorized":False}
            out["observations"].append(record)
    for rec in out["observations"]:
        sym=rec["symbol"]+(".IS" if market=="BIST" else "")
        chart=None
        for index,host in enumerate(YAHOO):
            url=host+quote(sym,safe="") +"?"+urlencode({"interval":"1d","range":"3mo"})
            raw=safe_call(errors,"yahoo_chart_"+str(index)+"_"+sym,lambda u=url:get(u))
            if raw is None:
                continue
            chart=safe_call(errors,"yahoo_parse_"+sym,lambda:parse_yahoo(raw,sym))
            if chart is not None:
                break
        if cedar_key and (market=="BIST" or chart is None):
            # Cross-check BIST, or recover US OHLCV when Yahoo fails.
            prefix=("bist" if market=="BIST" else
                    "nasdaq" if rec.get("exchange_reported","").upper()=="NASDAQ" else
                    "nyse" if rec.get("exchange_reported","").upper()=="NYSE" else
                    "amex")
            sid=prefix+":"+rec["symbol"]
            url=CEDAR+quote(sid,safe=":")+"/bars?"+urlencode({
                "timeframe":"1d","adjustment":"raw","order":"asc","limit":100})
            raw=safe_call(errors,"cedar_"+rec["symbol"],lambda u=url:cedar_get(u))
            second=safe_call(errors,"cedar_parse_"+rec["symbol"],lambda:parse_cedar(raw,sym)) if raw is not None else None
            if second:
                out["sources"].append({"provider":"DATACEDAR_OPTIONAL_KEY","symbol":sym})
                rec["secondary_bars_count"]=len(second["bars"])
                if chart:
                    a={x["ts_ms"]//86400000:x["close"] for x in chart["bars"]}
                    b={x["ts_ms"]//86400000:x["close"] for x in second["bars"]}
                    overlap=sorted(set(a)&set(b))
                    rec["price_crosscheck"]={"common_days":len(overlap),
                        "max_close_deviation_pct":round(max(abs(a[d]/b[d]-1)*100 for d in overlap),4) if overlap else None,
                        "consistent_under_2pct":bool(overlap) and all(abs(a[d]/b[d]-1)*100<=2 for d in overlap)}
                else:
                    chart=second
        if chart:
            # Only bounded recent daily bars, as of actual observation, never retro PIT.
            valid=[b for b in chart["bars"] if b["ts_ms"]<=now_ms]
            if valid:
                rec.update({"daily_bars_recent":valid,"price_source":chart["price_source"],
                            "currency":chart.get("currency","TRY" if market=="BIST" else "USD"),
                            "adjustment":chart["adjustment"],
                            "bar_count":len(valid),"latest_bar_ms":valid[-1]["ts_ms"]})
            else:
                errors.append({"stage":"price_"+sym,"error":"NO_ASOF_BAR"})
        else:
            rec["price_status"]="UNAVAILABLE"
    usable=sum("daily_bars_recent" in x for x in out["observations"])
    out["coverage"]={"observed_tickers":len(out["observations"]),"recent_price_series":usable,
                     "verified_float":0,"verified_depth":0,"pit_universe":0,
                     "smallcap_screened_tickers":sum(p.get("market_cap_usd_screen") is not None
                         for p in out["observations"]) if market=="US" else 0}
    out["status"]=("RECENT_DATA_AVAILABLE_NOT_PIT_READY" if usable else
                   "SOURCE_UNAVAILABLE_OR_INCOMPLETE_NO_SIGNAL")
    if market=="US" and usable and not out["coverage"]["smallcap_screened_tickers"]:
        out["status"]="SEC_DIAGNOSTIC_PRICE_ONLY_NO_SMALLCAP_VALIDATION"
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="out/v4_equities")
    args=p.parse_args()
    directory=Path(args.out);directory.mkdir(parents=True,exist_ok=True)
    for market in MARKETS:
        doc=probe_market(market,sec_agent=os.environ.get("SEC_USER_AGENT"),
                         cedar_key=os.environ.get("DATACEDAR_API_KEY"),
                         tv_primary=(market=="US"))
        (directory/(market.lower()+".json")).write_text(json.dumps(doc,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf8")
        print("V4_EQUITY_SOURCE",market,doc["status"],"tickers",doc["coverage"]["observed_tickers"],
              "price_series",doc["coverage"]["recent_price_series"],"errors",len(doc["errors"]),flush=True)
        for e in doc["errors"]:
            print("V4_EQUITY_SOURCE_ERROR",market,e["stage"],e["error"],
                  e.get("http_status"),flush=True)

if __name__=="__main__":
    main()
