"""Independent per-venue quote eligibility diagnostics. Never marks NAV or trades."""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from radar.providers import fetch_quote
from research_v3.paper import ASSETS, QUOTE_VENUES, MARK_AGE_MS


def check(quote, now):
    reasons = []
    if quote.market_type != "SPOT" or quote.quote_currency != "USDT":
        reasons.append("WRONG_MARKET_OR_CURRENCY")
    if not 0 <= now - quote.retrieved_ms <= MARK_AGE_MS:
        reasons.append("STALE_QUOTE")
    if quote.spread_bps > 25:
        reasons.append("SPREAD_OVER_25_BPS")
    if min(quote.top_bid_usd, quote.top_ask_usd) < 500:
        reasons.append("TOP_OF_BOOK_DEPTH_BELOW_500_USDT")
    return reasons


def collect(assets=ASSETS, venues=QUOTE_VENUES, quote_get=fetch_quote,
            clock=lambda: int(time.time()*1000)):
    entries = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(quote_get, venue, asset): (venue, asset)
                   for asset in assets for venue in venues}
        for future in as_completed(futures):
            venue, asset = futures[future]
            try:
                q = future.result()
                entries.append((asset, venue, q, None))
            except Exception as exc:
                entries.append((asset, venue, None, f"{type(exc).__name__}:{str(exc)[:180]}"))
    now = clock()
    results = {}
    for asset in assets:
        rows = []
        for a, venue, q, error in entries:
            if a != asset:
                continue
            if error:
                rows.append({"venue": venue, "eligible": False, "reasons": ["FETCH_ERROR"],
                             "error": error})
            else:
                reasons = check(q, now)
                rows.append({"venue": venue, "eligible": not reasons, "reasons": reasons,
                             "bid": q.bid, "ask": q.ask, "spread_bps": round(q.spread_bps, 4),
                             "bid_depth_usdt": round(q.top_bid_usd, 2),
                             "ask_depth_usdt": round(q.top_ask_usd, 2),
                             "quote_age_ms": now-q.retrieved_ms, "source": q.source})
        eligible = [r for r in rows if r["eligible"]]
        if len(eligible) >= 2:
            mids = sorted((r["bid"]+r["ask"])/2 for r in eligible)
            median = mids[len(mids)//2]
            inconsistent = max(abs(((r["bid"]+r["ask"])/2)/median-1)*10000 for r in eligible)>60
        else:
            inconsistent = False
        results[asset] = {"venues": sorted(rows, key=lambda r: r["venue"]),
                          "eligible_venues": len(eligible),
                          "cross_venue_inconsistent": inconsistent,
                          "mark_eligible": len(eligible)>=2 and not inconsistent}
    return {"observed_ms": now, "assets": results, "diagnostic_only": True,
            "paper_mark_created": False}


if __name__ == "__main__":
    from pathlib import Path
    output = Path("out/v3_paper/venue_diagnostics.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = collect()
    output.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
    for asset, result in report["assets"].items():
        if not result["mark_eligible"]:
            print(f"::warning title={asset} insufficient quotes::{json.dumps(result, sort_keys=True)}")
    print(f"QUOTE_DIAGNOSTICS_WRITTEN {output}")
