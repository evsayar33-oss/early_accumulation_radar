"""Read-only, independent depth study; never changes frozen PAPER marks.

Top-of-book sizes cannot stand in for aggregate executable liquidity.
Collect full price levels and calculate bid/ask VWAP for a target USDT notional.
No paper fills, no NAV writes, no strategy model alteration.
"""
from __future__ import annotations
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from radar.providers import http, SYMBOLS


VENUES = ("binance", "okx", "gate")
TARGET_USDT = 500.0


def depth_url(venue, asset):
    sym = SYMBOLS[asset]
    if venue == "binance":
        return f"https://data-api.binance.vision/api/v3/depth?symbol={sym}&limit=20"
    if venue == "okx":
        return f"https://www.okx.com/api/v5/market/books?instId={asset}-USDT&sz=20"
    if venue == "gate":
        return f"https://api.gateio.ws/api/v4/spot/order_book?currency_pair={asset}_USDT&limit=20"
    raise ValueError("UNKNOWN_VENUE")


def decode_levels(venue, data):
    if venue == "okx":
        if data.get("code") != "0":
            raise ValueError("OKX_CODE")
        row = data["data"][0]
        # OKX book level: price, size, deprecated liquidation size, order count.
        raw_bids, raw_asks = row["bids"], row["asks"]
    else:
        raw_bids, raw_asks = data["bids"], data["asks"]
    def side(raw, reverse):
        levels = []
        for entry in raw:
            price, qty = float(entry[0]), float(entry[1])
            if not (math.isfinite(price) and math.isfinite(qty) and price > 0 and qty > 0):
                raise ValueError("INVALID_DEPTH_LEVEL")
            levels.append((price, qty))
        if not levels:
            raise ValueError("EMPTY_BOOK_SIDE")
        if any(levels[i][0] < levels[i+1][0] if reverse else levels[i][0] > levels[i+1][0]
               for i in range(len(levels)-1)):
            raise ValueError("UNSORTED_BOOK")
        return levels
    bids, asks = side(raw_bids, True), side(raw_asks, False)
    if bids[0][0] >= asks[0][0]:
        raise ValueError("CROSSED_BOOK")
    return bids, asks


def vwap_for_notional(levels, target=TARGET_USDT):
    """Buy/sell BASE quantity that has target USDT notional at observed levels."""
    if not math.isfinite(target) or target <= 0:
        raise ValueError("INVALID_NOTIONAL")
    remaining = target
    filled_base = 0.
    consumed = 0
    available = 0.
    for price, qty in levels:
        capacity = price * qty
        available += capacity
        if remaining > 1e-9:
            used_usdt = min(remaining, capacity)
            filled_base += used_usdt / price
            remaining -= used_usdt
            consumed += 1
    if remaining > 1e-7:
        return {"executable": False, "available_notional_usdt": round(available, 5),
                "levels_used": consumed, "vwap": None}
    return {"executable": True, "available_notional_usdt": round(available, 5),
            "levels_used": consumed, "vwap": target / filled_base}


def evaluate(venue, asset, getter=http):
    url = depth_url(venue, asset)
    bids, asks = decode_levels(venue, getter(url))
    bid = vwap_for_notional(bids)
    ask = vwap_for_notional(asks)
    spread_bps = 10000 * (asks[0][0] - bids[0][0]) / ((asks[0][0] + bids[0][0]) / 2)
    bid_impact = None if not bid["executable"] else 10000 * (bids[0][0] - bid["vwap"]) / bids[0][0]
    ask_impact = None if not ask["executable"] else 10000 * (ask["vwap"] - asks[0][0]) / asks[0][0]
    return {"venue": venue, "asset": asset, "source": url,
            "bid_best": bids[0][0], "ask_best": asks[0][0],
            "spread_bps": spread_bps,
            "bid": bid, "ask": ask,
            "bid_impact_bps": bid_impact, "ask_impact_bps": ask_impact,
            "both_sides_executable": bid["executable"] and ask["executable"],
            "snapshot_only": True}


def collect(assets=("SUI", "LINK", "XRP"), venues=VENUES, getter=http):
    rows = []
    with ThreadPoolExecutor(max_workers=9) as executor:
        jobs = {executor.submit(evaluate, v, a, getter): (v, a)
                for a in assets for v in venues}
        for f in as_completed(jobs):
            venue, asset = jobs[f]
            try:
                rows.append(f.result())
            except Exception as exc:
                rows.append({"venue": venue, "asset": asset,
                             "error": f"{type(exc).__name__}:{str(exc)[:160]}",
                             "both_sides_executable": False})
    rows.sort(key=lambda x: (x["asset"], x["venue"]))
    return {"schema": "EAR.depth.shadow.v1", "observed_ms": int(time.time()*1000),
            "target_usdt": TARGET_USDT, "diagnostic_only": True,
            "not_a_paper_mark": True, "rows": rows}


if __name__ == "__main__":
    output = Path("out/v3_paper/depth_shadow.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = collect()
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("DEPTH_SHADOW", output)
    for row in result["rows"]:
        if not row["both_sides_executable"]:
            print("::warning title=Depth not executable::" + row["asset"] + "/" + row["venue"]
                  + " " + row.get("error", "insufficient cumulative depth"))
