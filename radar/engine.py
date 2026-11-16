"""Conservative watchlist scoring: no inferred manipulator identity or order execution."""
from __future__ import annotations
import math
from statistics import median
from .providers import Quote

def analyze(asset, quotes, min_venues=2, max_spread_bps=25, min_top_usd=1000):
    if not quotes: return {"asset":asset,"status":"NO_DATA","trade_allowed":False}
    good=[q for q in quotes if q.symbol==asset and q.quote_currency=="USDT" and q.spread_bps <= max_spread_bps and min(q.top_ask_usd,q.top_bid_usd)>=min_top_usd]
    if len({q.venue for q in good})<min_venues:
        return {"asset":asset,"status":"INSUFFICIENT_VERIFIED_LIQUIDITY","trade_allowed":False,"venues":len({q.venue for q in good})}
    mids=[q.mid for q in good]; m=median(mids)
    dispersion=max(abs(x/m-1)*10000 for x in mids)
    if dispersion>60: return {"asset":asset,"status":"CROSS_VENUE_DISLOCATION","trade_allowed":False,"dispersion_bps":round(dispersion,2)}
    spread=median([q.spread_bps for q in good])
    # This is an instantaneous top-of-book imbalance, NOT accumulated buying or CVD.
    imbalance=median([(q.top_bid_usd-q.top_ask_usd)/(q.top_bid_usd+q.top_ask_usd) for q in good])
    return {"asset":asset,"status":"WATCH_ONLY","trade_allowed":False,"venues":len(good),
            "median_mid":round(m,8),"median_spread_bps":round(spread,3),
            "cross_venue_dispersion_bps":round(dispersion,3),
            "top_book_imbalance":round(imbalance,4),
            "note":"Not a proven accumulation or trade-entry signal; need historical+forward evidence."}
