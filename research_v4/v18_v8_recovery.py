"""Outcome-only recovery from sealed V8 snapshots, using real exchange OHLC.

V9/V11 snapshot labels and V13 execution mark records are never changed.
A next-bar 4h diagnostic is deliberately a different observation protocol.
"""
from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from radar.ledger import digest, read_verify
from research_v4.preimpulse_study import SOURCE_ORDER, features, HORIZON_MS
from research_v4.v18_sources import BAR_MS, parse_bars, public_json
from research_v4.perp_watch import unpack
import re

BUDGET=16

def candidates(records, known, asof, limit=BUDGET):
    scans=[(r["scan_utc_ms"],unpack(r["packed_assets"]),r["sha256"]) for r in records[-450:]]
    history=defaultdict(list)
    for t,assets,_ in scans:
        for sym,vs in assets.items():history[sym].append((t,vs))
    selected=[];buckets=set()
    for t,assets,sha in scans:
        if t+HORIZON_MS+2*BAR_MS>asof:continue
        for sym,venues in sorted(assets.items()):
            bucket=(sym,t//HORIZON_MS)
            if bucket in buckets:continue
            ident=digest(["V8_NEXT_BAR_DIAGNOSTIC",sym,bucket[1]])
            if ident in known:
                buckets.add(bucket);continue
            for venue in SOURCE_ORDER:
                if venue not in venues:continue
                z=features(history[sym],t,venue)
                if z is None:continue
                if abs(z["price_return_2h_pct"])>3 or abs(z["return_24h_pct"])>15 or z["turnover_24h_usdt"]<100000:break
                buckets.add(bucket)
                selected.append({"id":ident,"symbol":sym,"venue":venue,"source_seen":t,
                                 "source_sha":sha,"asof_features":z,
                                 "original_reference_price":venues[venue]["p"]})
                if len(selected)>=limit:return selected
                break
    return selected

def native_range(symbol,venue,seen,asof,get=public_json):
    if not re.fullmatch(r"[A-Z0-9]{2,25}USDT",symbol):raise ValueError("SYMBOL")
    # Strictly next bar, never a partially observed candle.
    start=(seen//BAR_MS+1)*BAR_MS
    end=start+16*BAR_MS
    if end>asof:return []
    if venue=="okx":
        url=f"https://www.okx.com/api/v5/market/history-candles?instId={symbol[:-4]}-USDT-SWAP&bar=15m&after={end}&limit=30"
    elif venue=="bitget":
        url=f"https://api.bitget.com/api/v2/mix/market/history-candles?symbol={symbol}&productType=USDT-FUTURES&granularity=15m&startTime={start}&endTime={end}&limit=100"
    elif venue=="binance":
        url=f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&startTime={start}&endTime={end-1}&limit=100"
    else:raise ValueError("VENUE")
    return [b for b in parse_bars(get(url),venue,asof) if start<=b["start"]<end]

def recover(ledger,known,asof,get=public_json):
    from research_v4.v18_adaptive import outcome
    if not ledger or not Path(ledger).is_file():return [],{"status":"V8_LEDGER_UNAVAILABLE"}
    records=read_verify(ledger)
    selected=candidates(records,known,asof)
    def one(row):
        try:
            b=native_range(row["symbol"],row["venue"],row["source_seen"],asof,get)
            o=outcome(b,"CRYPTO",row["source_seen"],now=asof)
            if o is None:return {**row,"status":"NO_COMPLETE_NATIVE_OUTCOME"}
            return {**row,"status":o["status"],"outcome":o,"protocol":"V8_ASOF_NEXT_BAR_DIAGNOSTIC_ONLY"}
        except (ValueError,RuntimeError,KeyError,TypeError,IndexError,OSError) as exc:
            return {**row,"status":"SOURCE_FAILED","reason":type(exc).__name__}
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(one,selected))
    from collections import Counter
    return rows,{"status":"OUTCOME_ONLY_NATIVE_RECOVERY","attempted":len(rows),
                 "statuses":dict(Counter(x["status"] for x in rows)),
                 "legacy_v9_v11_v13_unchanged":True}
