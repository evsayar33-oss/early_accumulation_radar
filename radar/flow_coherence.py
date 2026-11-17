"""Causal provenance audit, NOT a multi-venue buy-side vote.

The 10m Binance *candle* taker ratio is a full 10-minute aggregate.
Trade feeds are venue-specific recent capped samples, often seconds long.
A conflicting sample is a risk flag, never a like-for-like contradiction or
reason to silently reverse/replace the original alert.
"""
from __future__ import annotations
from collections import defaultdict

def annotate(candle_features,tape):
    by_asset=defaultdict(list)
    for t in tape:
        by_asset[t.get("asset")].append(t)
    for c in candle_features:
        c["signal_evidence_scope"]="BINANCE_10M_CLOSED_CANDLES_ONLY" if c.get("source_venue")=="binance" else "VOLUME_ONLY_FALLBACK"
        c["multi_venue_taker_confirmation"]=False
        c["flow_confidence"]="NOT_ASSESSED"
        c["flow_quality_warnings"]=[]
        c["sampled_tape_summary"]=[]
        if c.get("source_venue")!="binance":continue
        candle_buy=c.get("taker_buy_quote_fraction_10m")
        for t in sorted(by_asset[c.get("asset")],key=lambda a:a.get("venue","")):
            if t.get("status")!="SAMPLED":continue
            item={"venue":t.get("venue"),"sample_span_seconds":t.get("sample_span_s"),
                  "sampled_taker_buy_fraction":t.get("taker_buy_fraction"),
                  "sample_count":t.get("count"),"coverage":t.get("coverage")}
            c["sampled_tape_summary"].append(item)
            if t.get("venue")=="binance" and isinstance(candle_buy,(float,int)) and isinstance(t.get("taker_buy_fraction"),(float,int)):
                if (c.get("accumulation_watch") and candle_buy>=.56 and t["taker_buy_fraction"]<.45) or (
                    c.get("distribution_watch") and candle_buy<=.38 and t["taker_buy_fraction"]>.55):
                    c["flow_quality_warnings"].append("BINANCE_RECENT_SAMPLED_FLOW_OPPOSES_10M_CANDLE_FLOW_DIFFERENT_TIME_WINDOWS")
        if not c["sampled_tape_summary"]:
            c["flow_quality_warnings"].append("NO_RECENT_TRADE_SAMPLE")
        c["flow_confidence"]="TIME_WINDOWS_NOT_COMPARABLE"
    return candle_features
