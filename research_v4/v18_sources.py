"""V18 exchange candles and authenticated V5 artifact input.
A late historical candle is valid OUTCOME evidence, never an earlier observation.
No synthetic fills or cross-exchange stitching.
"""
from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from research_v4.perp_watch import public_json, scan, unpack, OKX_INFO, BITGET_INFO, BINANCE_INFO
from research_v4.multimarket_exploratory import load, STABLE
from research_v4.v12_equity_patterns import read_quality
from radar.ledger import digest, read_verify

BAR_MS = 15 * 60_000
VENUES = ("okx", "bitget", "binance")
MAX_HISTORY = 300
MAX_SYMBOLS = 32
COHORT = "VERIFIED_CRYPTO_UNDERLYING_V1"
CORE = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"}

def now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)

def parse_bars(raw, venue, asof):
    if venue == "okx":
        if raw.get("code") != "0":
            raise ValueError("OKX_CANDLE_ERROR")
        source = raw["data"]
    elif venue == "bitget":
        if raw.get("code") != "00000":
            raise ValueError("BITGET_CANDLE_ERROR")
        source = raw["data"]
    elif venue == "binance":
        source = raw
    else:
        raise ValueError("UNKNOWN_VENUE")
    rows = {}
    for r in source:
        t = int(r[0])
        if t % BAR_MS:
            raise ValueError("NONALIGNED_CANDLE")
        if t + BAR_MS > asof or (venue == "okx" and (len(r) < 9 or str(r[8]) != "1")):
            continue
        op, hi, lo, cl = map(float, r[1:5])
        # Use venue-native base volume, not OKX contracts.
        vol = float(r[6] if venue == "okx" else r[5])
        vals = (op, hi, lo, cl, vol)
        if not all(math.isfinite(v) for v in vals) or min(vals[:4]) <= 0 or vol < 0 or lo > min(op,cl) or hi < max(op,cl):
            raise ValueError("INVALID_CANDLE")
        q = {"start": t, "end": t + BAR_MS, "open": op, "high": hi, "low": lo, "close": cl, "volume": vol}
        if venue == "binance" and len(r) > 10 and float(r[5]) > 0:
            ratio = float(r[9]) / float(r[5])
            if math.isfinite(ratio) and 0 <= ratio <= 1:
                q["buy_fraction"] = ratio
        if t in rows and rows[t] != q:
            raise ValueError("CONFLICTING_CANDLE")
        rows[t] = q
    return sorted(rows.values(), key=lambda r:r["start"])

def fetch_candles(symbol, venue, asof, get=public_json):
    if not re.fullmatch(r"[A-Z0-9]{2,25}USDT", symbol):
        raise ValueError("UNSAFE_SYMBOL")
    if venue == "okx":
        url = f"https://www.okx.com/api/v5/market/candles?instId={symbol[:-4]}-USDT-SWAP&bar=15m&limit=300"
    elif venue == "bitget":
        url = f"https://api.bitget.com/api/v2/mix/market/candles?symbol={symbol}&productType=USDT-FUTURES&granularity=15m&limit=300"
    elif venue == "binance":
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=300"
    else:
        raise ValueError("UNKNOWN_VENUE")
    return parse_bars(get(url), venue, asof)

def select_assets(assets, cursor, limit=MAX_SYMBOLS, priority=()):
    """Cyclic, outcome-independent rotation across eligible non-core contracts."""
    syms = sorted(s for s, vs in assets.items() if s not in CORE | STABLE
                  and any(v.get("q",0) >= 100_000 for v in vs.values()))
    if not syms:
        return [], cursor
    count = min(limit, len(syms))
    # At least 75% budget remains unbiased cyclic coverage, never allow a
    # snapshot heuristic to starve unselected instruments.
    ranked=list(dict.fromkeys(s for s in priority if s in syms))[:count//4]
    rotated=[syms[(cursor+i)%len(syms)] for i in range(count-len(ranked))]
    chosen=list(dict.fromkeys(rotated+ranked))
    i=len(rotated)
    while len(chosen)<count and i<len(syms):
        candidate=syms[(cursor+i)%len(syms)]
        if candidate not in chosen:chosen.append(candidate)
        i+=1
    return chosen, (cursor+i)%len(syms)

def classified_assets(assets, instrument_info):
    """Use actual venue metadata, not symbol-name heuristics. Unknown is excluded.

    OKX instCategory=1, Bitget isRwa=NO, Binance underlyingType=COIN.
    If a symbol has contradictory classifications, do not compare its prices.
    """
    categories = {}
    for venue, info in instrument_info.items():
        rows=info.get("symbols" if venue=="binance" else "data", [])
        if not isinstance(rows,list):continue
        for row in rows:
            if not isinstance(row,dict):continue
            sym=row.get("symbol") if venue!="okx" else str(row.get("instId", "")).replace("-USDT-SWAP","USDT")
            field, expected = {"okx":("instCategory","1"),"bitget":("isRwa","NO"),"binance":("underlyingType","COIN")}[venue]
            value=row.get(field)
            if value not in (None, ""):
                categories[(sym,venue)]={"field":field,"value":str(value),"crypto":str(value)==expected}
    eligible={};excluded={}
    for sym, venues in assets.items():
        known={v:categories[(sym,v)] for v in venues if (sym,v) in categories}
        if any(not c["crypto"] for c in known.values()):
            excluded[sym]="NON_CRYPTO_OR_CONFLICTING_UNDERLYING"
            continue
        valid={v:{**values,"underlying_metadata":known[v]} for v,values in venues.items() if v in known}
        if valid:eligible[sym]=valid
        else:excluded[sym]="UNVERIFIED_UNDERLYING"
    return eligible, excluded

def read_forward_priority(path, asof):
    """New independent survey can suggest a limited deep-research budget.
    No inferred feature, price outcome or trading authority enters V18.
    """
    import json
    from pathlib import Path
    if not path or not Path(path).is_file():return []
    try:
        doc=json.loads(Path(path).read_text())
        if doc.get("schema")!="EAR.v18.forward_universe.v1" or not 0<=asof-int(doc["asof_ms"])<=2*3600000:return []
        return list(dict.fromkeys(r["symbol"] for r in doc.get("deep_research_priority",[])
            if re.fullmatch(r"[A-Z0-9]{2,25}USDT",r["symbol"]) and 0<=asof-int(r["seen"])<=2*3600000))[:128]
    except (ValueError,TypeError,KeyError,OSError):return []

def collect_crypto(previous, pending, *, asof, cursor, limit=MAX_SYMBOLS, get=public_json, priority=()):
    """Pending symbols have priority for settlement; new symbols rotate independently.
    Use an archived universe only for settlement if current discovery fails.
    """
    errors = {}
    info = {}
    def capture(url):
        result=get(url)
        for v,u in (("okx",OKX_INFO),("bitget",BITGET_INFO),("binance",BINANCE_INFO)):
            if url==u and isinstance(result,dict):info[v]=result
        return result
    try:
        live = scan(get=capture)
        assets = live["assets"]
        universe_status = "CURRENT_MULTI_VENUE_DISCOVERY"
        errors.update(live["source_unavailable"])
    except (RuntimeError,ValueError,KeyError,TypeError) as exc:
        assets = {}
        universe_status = "LIVE_UNIVERSE_UNAVAILABLE"
        errors["universe"] = type(exc).__name__
    raw_size=len(assets)
    assets, excluded=classified_assets(assets,info)
    symbols, next_cursor = select_assets(assets, cursor, limit, priority)
    preferred = {}
    for s in symbols:
        preferred[s] = [v for v in VENUES if v in assets[s]]
    # Keep follow-through workload bounded and never switch an observation's venue.
    # Prioritize oldest unresolved outcome, max 2*limit independent requests.
    req = sorted({(r["symbol"],r["venue"]) for r in pending if r["market"]=="CRYPTO" and asof-r["seen"]>=4*3600000},
                 key=lambda pair:min(r["seen"] for r in pending if (r["symbol"],r["venue"])==pair))[:2*limit]
    def one(pair):
        sym, venue = pair
        try:
            rows = fetch_candles(sym,venue,asof,get)
            if len(rows)<20:
                raise ValueError("SHORT_NATIVE_HISTORY")
            return pair, rows, None
        except (ValueError,RuntimeError,KeyError,TypeError,IndexError,OSError) as exc:
            return pair, None, type(exc).__name__
    all_requests = list(dict.fromkeys(req+[(s,v) for s in symbols for v in preferred[s][:2]]))
    data = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for pair,rows,error in pool.map(one,all_requests):
            if error: errors[":".join(pair)]=error
            else: data[pair]=rows
    fallback=[(s,v) for s in symbols if sum((s,x) in data for x in preferred[s][:2])<2
              for v in preferred[s][2:]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for pair,rows,error in pool.map(one,fallback):
            if error:errors[":".join(pair)]=error
            else:data[pair]=rows
    new_panels={}
    for s in symbols:
        candidates=[(v,data[(s,v)]) for v in preferred[s] if (s,v) in data]
        if not candidates:
            continue
        venue, rows = candidates[0]
        corroboration = "ONE_VENUE_ONLY"
        if len(candidates)>1:
            other={r["start"]:r["close"] for r in candidates[1][1]}
            common=[abs(r["close"]/other[r["start"]]-1) for r in rows[-16:] if r["start"] in other]
            if len(common)>=8:
                corroboration="AGREEMENT" if max(common)<=.02 else "DIVERGENT"
        if corroboration=="DIVERGENT":
            errors[s]="CROSS_VENUE_PRICE_DISAGREEMENT"
            continue
        new_panels[("CRYPTO",s,venue)]={"bars":rows,"corroboration":corroboration,"asof_microstructure":assets[s][venue],"cohort":COHORT,
             "underlying_metadata":assets[s][venue]["underlying_metadata"]}
    settle={("CRYPTO",s,v):b for (s,v),b in data.items()}
    return new_panels,settle,next_cursor,{"universe_status":universe_status,"universe_size":raw_size,"verified_crypto_universe":len(assets),
        "excluded_underlyings":excluded,"cohort":COHORT,
        "selected":len(symbols),"priority_selected":sum(s in priority for s in symbols),"new_panels":len(new_panels),"settlement_requests":len(req),"errors":errors}

def equity_panels(csv, quality, asof):
    sha,_=read_quality(csv,quality)
    today=datetime.fromtimestamp(asof/1000,timezone.utc).date()
    out={}
    for (market,symbol),bars in load(csv).items():
        if market not in ("BIST","US"):
            continue
        valid=[]
        for b in bars:
            if b["date"] >= today:
                continue
            start=int(datetime.combine(b["date"],datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)
            valid.append({**{k:b[k] for k in ("open","high","low","close","volume")},
                          "start":start,"end":start+86_400_000})
        if len(valid)>=90:
            out[(market,symbol,"V5_YAHOO")]={"bars":valid,"corroboration":"PIT_UNVERIFIED","source_sha":sha}
    return out

def macro_context(path, asof):
    """Only newly received, dated context; never apply today's macro to past events."""
    import json
    from pathlib import Path
    if not path or not Path(path).is_file():
        return {"status":"MISSING"}
    doc=json.loads(Path(path).read_text())
    seen=int(datetime.fromisoformat(doc["seen_at"]).timestamp()*1000)
    if seen>asof or asof-seen>7*86_400_000:
        return {"status":"STALE_OR_FUTURE"}
    flags={};provenance={}
    for a in doc.get("assets",[]):
        if a.get("symbol") not in ("SPY","IWM","IBIT","ETHA","GLD","SGOV"):
            continue
        symbol=a["symbol"]
        primary=a
        if primary.get("error") or primary.get("status")=="VERİ EKSİK":
            alt=doc.get("continuity",{}).get("assets",{}).get(symbol,{}).get("selected",{})
            if alt.get("status")!="OBSERVED" or alt.get("stale") is not False:
                continue
            a=alt
        h=a.get("horizons",{}).get("1H",{})
        flow=h.get("net_usd_m")
        if not isinstance(flow,(int,float)) or not math.isfinite(flow) or not a.get("flow_asof"):
            continue
        date=int(datetime.fromisoformat(a["flow_asof"]).replace(tzinfo=timezone.utc).timestamp()*1000)
        if date>seen or seen-date>14*86_400_000:
            continue
        flags["macro_"+symbol+"_inflow"]=bool(flow>0)
        provenance[symbol]={"flow_asof":a["flow_asof"],"provider":a.get("provider","PRIMARY"),"flow_net_usd_m":flow}
    return {"status":"DATED_CONTEXT" if flags else "NO_VERIFIED_FLOW","seen":seen,"sha":digest(doc),"flags":flags,"provenance":provenance}
