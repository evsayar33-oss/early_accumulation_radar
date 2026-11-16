"""Independent fail-closed SHA-chain, freshness and missing-observation audit."""
from __future__ import annotations
import argparse,json,time
from datetime import datetime, timezone
from pathlib import Path
from .ledger import read_verify

def audit(path, now_ms=None, max_age_ms=7_200_000):
    now_ms=int(time.time()*1000) if now_ms is None else int(now_ms)
    rows=read_verify(path)
    if not rows:
        return {"status":"NO_PERSISTED_EVIDENCE","entries":0,"ok":False}
    last=rows[-1];last_ms=int(last["scan_utc_ms"])
    age=now_ms-last_ms
    if age < -30000: raise ValueError("FUTURE_LAST_OBSERVATION")
    gaps=[]
    for a,b in zip(rows,rows[1:]):
        delta=int(b["scan_utc_ms"])-int(a["scan_utc_ms"])
        if delta>45*60000: gaps.append({"from_ms":a["scan_utc_ms"],"to_ms":b["scan_utc_ms"],"elapsed_minutes":round(delta/60000,1),
             "estimated_unobserved_30m_slots":max(0,round(delta/(30*60000))-1)})
    candles={x.get("asset"):(x.get("status"),x.get("last_closed_bar_ms")) for x in last.get("candle_diagnostics",[])}
    tapes={asset:sorted(x.get("venue") for x in last.get("tape",[]) if x.get("asset")==asset and x.get("status")=="SAMPLED")
           for asset in ("BTC","ETH","SOL")}
    missing_candles=[a for a in ("BTC","ETH","SOL")
                     if a not in candles or candles[a][0] not in ("HYPOTHESIS_ONLY","VOLUME_CONTEXT_ONLY")
                     or not isinstance(candles[a][1],int)
                     or int(candles[a][1])>last_ms
                     or last_ms-int(candles[a][1])>5*60000]
    quote_health={x.get("asset"):x.get("status") for x in last.get("quote_health",[])}
    weak_quotes=[a for a in ("BTC","ETH","SOL") if quote_health.get(a)!="WATCH_ONLY"]
    healthy= age<=max_age_ms and not missing_candles and not weak_quotes and not last.get("zero_valid_candle_sources",True)
    return {"status":"HEALTHY" if healthy else "DATA_HEALTH_DEGRADED",
            "ok":healthy,"entries":len(rows),"latest_scan_utc_ms":last_ms,
            "latest_age_minutes":round(age/60000,2),"chain_valid":True,
            "prior_gaps":gaps[-10:],"prior_gap_count":len(gaps),
            "latest_venue_tape":tapes,"missing_candle_assets":missing_candles,"unhealthy_quote_assets":weak_quotes,
            "latest_failed_source_count":last.get("failed_source_count"),
            "trade_allowed":False}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ledger",required=True)
    ap.add_argument("--max-age-minutes",type=int,default=120)
    args=ap.parse_args()
    result=audit(args.ledger,max_age_ms=args.max_age_minutes*60000)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    if not result["ok"]:raise SystemExit(2)
if __name__=="__main__":main()
