"""Paired normal-vs-inverse forward diagnostics from immutable EAR V2 snapshots.

Crucial: a signal close is not an executable entry price. Both theoretical
directions use the first subsequently OBSERVED and fresh Binance closed-candle
price within MAX_ENTRY_DELAY, and a subsequent observation near a target
elapsed-time horizon. No interpolation, no manufactured fills, no backfill.
Inverse of a bullish accumulation is an *avoided-long / bearish hypothesis*,
NOT an executable borrowed or margined short.
"""
from __future__ import annotations
import argparse,json,math
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from statistics import mean
from radar.ledger import read_verify

HORIZONS_MIN=(30,60,240)
MAX_ENTRY_DELAY_MIN=40
MAX_EXIT_DELAY_MIN=40
COOLDOWN_MIN=60
ROUND_TRIP_COST_BPS=30

def observation(row,asset):
    """A reproducible closed Binance 1m bar, not a sampled tape mid."""
    if not row.get("scan_utc_ms"):return None
    q=next((x for x in row.get("quote_health",[]) if x.get("asset")==asset),None)
    if not q or q.get("status")!="WATCH_ONLY":return None
    for c in row.get("candle_diagnostics",[]):
        if c.get("asset")!=asset or c.get("source_venue")!="binance" or c.get("instrument")!="BINANCE_SPOT":continue
        price=c.get("price")
        stamp=c.get("last_closed_bar_ms")
        if not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
            return None
        if not isinstance(stamp,(int,float)) or not 0<=row["scan_utc_ms"]-(stamp+60000)<=240000:
            return None
        return {"price":float(price),"scan_ms":int(row["scan_utc_ms"]),
                "closed_ms":int(stamp)+60000,"candle":c}
    return None

def future_point(rows,asset,after_ms,min_delay,max_delay):
    for row in rows:
        scan_ms=int(row["scan_utc_ms"])
        lag=(scan_ms-after_ms)/60000
        if lag<min_delay:continue
        if lag>max_delay:break
        o=observation(row,asset)
        if o and o["closed_ms"]>after_ms:
            return o
    return None

def study(ledger):
    # Caller must use read_verify to verify the hash-linked immutable archive.
    rows=sorted(ledger,key=lambda r:r["scan_utc_ms"])
    events=[]
    last_signal=defaultdict(lambda:-10**20)
    for i,row in enumerate(rows):
        for c in row.get("candle_diagnostics",[]):
            asset=c.get("asset")
            if not asset:continue
            if not ((c.get("accumulation_watch") is True) or (c.get("distribution_watch") is True)):
                continue
            kind="ACCUMULATION" if c.get("accumulation_watch") else "DISTRIBUTION"
            signal=observation(row,asset)
            if signal is None:continue
            key=(asset,kind)
            if signal["scan_ms"]-last_signal[key]<COOLDOWN_MIN*60000:continue
            last_signal[key]=signal["scan_ms"]
            entry=future_point(rows[i+1:],asset,signal["scan_ms"],0.001,MAX_ENTRY_DELAY_MIN)
            report={"asset":asset,"type":kind,
                "signal_utc":datetime.fromtimestamp(signal["scan_ms"]/1000,timezone.utc).isoformat(),
                "signal_price_observed_not_executable":signal["price"],
                "entry_price":entry["price"] if entry else None,
                "entry_utc":(datetime.fromtimestamp(entry["scan_ms"]/1000,timezone.utc).isoformat() if entry else None),
                "entry_delay_minutes":(round((entry["scan_ms"]-signal["scan_ms"])/60000,2) if entry else None),
                "horizons":[]}
            for horizon in HORIZONS_MIN:
                h={"minutes":horizon,"status":"PENDING_MISSING_VALID_ENTRY" if not entry
                   else "PENDING_NO_EXIT_OBSERVATION",
                   "normal_direction":"LONG" if kind=="ACCUMULATION" else "BEARISH_DIAGNOSTIC",
                   "inverse_direction":"BEARISH_DIAGNOSTIC" if kind=="ACCUMULATION" else "LONG"}
                if entry:
                    exit_obs=future_point(rows[i+1:],asset,entry["scan_ms"],horizon,horizon+MAX_EXIT_DELAY_MIN)
                    if exit_obs:
                        gross=100*(exit_obs["price"]/entry["price"]-1)
                        fee=ROUND_TRIP_COST_BPS/100
                        # Costed directional comparisons are symmetric only as
                        # mathematically signed returns. No borrow/funding or
                        # executable short is implied.
                        nominal=gross if kind=="ACCUMULATION" else -gross
                        h.update({"status":"OBSERVED_DIRECTIONAL_COMPARISON",
                            "exit_price":exit_obs["price"],
                            "exit_utc":datetime.fromtimestamp(exit_obs["scan_ms"]/1000,timezone.utc).isoformat(),
                            "underlying_return_pct":round(gross,5),
                            "normal_directional_net_pct":round(nominal-fee,5),
                            "inverse_directional_net_pct":round(-nominal-fee,5),
                            "executable_short_verified":False,
                            "real_fill_verified":False})
                report["horizons"].append(h)
            events.append(report)
    groups=[]
    for kind in ("ACCUMULATION","DISTRIBUTION"):
        for asset in sorted({e["asset"] for e in events if e["type"]==kind}):
            for horizon in HORIZONS_MIN:
                valid=[h for e in events if e["type"]==kind and e["asset"]==asset
                       for h in e["horizons"] if h["minutes"]==horizon and h["status"]=="OBSERVED_DIRECTIONAL_COMPARISON"]
                groups.append({"asset":asset,"type":kind,"horizon_minutes":horizon,
                    "n":len(valid),"mean_normal_directional_net_pct":round(mean(h["normal_directional_net_pct"] for h in valid),5) if valid else None,
                    "mean_inverse_directional_net_pct":round(mean(h["inverse_directional_net_pct"] for h in valid),5) if valid else None,
                    "status":"INSUFFICIENT_FOR_DIRECTIONAL_SELECTION" if len(valid)<30
                        else "EXPLORATORY_STILL_REQUIRES_OUT_OF_SAMPLE_PROOF"})
    return {"schema":"EAR.v2_paired_inverse_forward.v1","events":events,"summaries":groups,
        "observations":len(rows),"verified_hash_chain":True,
        "round_trip_assumed_cost_bps":ROUND_TRIP_COST_BPS,
        "entry_rule":"next subsequent, fresh Binance spot closed-candle observation <=40 min after signal",
        "exit_rule":"subsequent fresh candle at least H minutes after entry and <=H+40 min",
        "signal_cooldown_minutes":COOLDOWN_MIN,
        "sampling_bias":"Sparse irregular GitHub scans, not continuous 1m trade execution; missing entries/exits remain pending",
        "no_short_borrow_or_derivatives_execution":True,
        "spot_inverse_means_avoid_long_or_bearish_hypothesis":True,
        "not_paper_or_live_approved":True,
        "profitability_confirmed":False,
        "previous_examples_are_exploratory":True}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ledger",required=True)
    p.add_argument("--out",default="out/v2_inverse")
    args=p.parse_args()
    report=study(read_verify(args.ledger))
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf8")
    lines=["# EAR V2 normal vs inverse paired signal test","",
        "Hash-verified observed Binance spot candle snapshots; neither the alert price nor a signed short return is an actual fill.",
        "30/60/240 minutes after the NEXT observed entry, costed with 30 bps round-trip; missing observations stay pending.",
        "Min 30 matched comparisons per group before even considering directional selection; STILL no PAPER approval.","",
        "| Asset | Alert | Horizon | Matched n | Normal diagnostic net % | Inverse diagnostic net % | Status |",
        "|---|---|---:|---:|---:|---:|---|"]
    for x in report["summaries"]:
        lines.append("| "+" | ".join(str(x[k]) for k in ("asset","type","horizon_minutes","n",
           "mean_normal_directional_net_pct","mean_inverse_directional_net_pct","status"))+" |")
    pending=Counter(h["status"] for e in report["events"] for h in e["horizons"])
    lines+=["","Maturity: "+json.dumps(dict(pending),sort_keys=True),
       "No actual short fills, no verified funding/borrow, no alpha proof."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    print("V2_INVERSE_FORWARD",len(report["events"]),"signals",dict(pending))

if __name__=="__main__":main()
