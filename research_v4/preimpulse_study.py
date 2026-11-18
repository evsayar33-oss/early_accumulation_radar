"""V9: strictly pre-impulse feature cohorts versus non-movers in the SAME futures universe.

Uses only timestamped observations saved by V8. A case labelled after future
price changes is NOT evidence that its as-of features were predictive.
Each symbol's snapshots are spaced >=4h for non-overlapping outcome windows.
Feature calculations are exclusively t and earlier; eligibility is decided
before the forward 4h price outcome is inspected. Never uses screenshot high/low.
"""
from __future__ import annotations
import argparse,json,math
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from statistics import median
from research_v4.perp_watch import read,unpack

HORIZON_MS=4*3600000
EXTREME_MOVE_PCT=12.0
MAX_FUTURE_DELAY_MS=45*60000
MIN_FUTURE_SAMPLES=4
MIN_CASES_PER_DIRECTION=30
MIN_CONTROLS=200
HISTORY_SCANS=1450  # <= ~30 days at 30-minute cadence, no change to ledger
SOURCE_ORDER=("okx","bitget","binance")
MOTIFS=("activity_up_20pct","activity_up_flat_3pct","quiet_price_2pct",
        "oi_contracts_up_10pct","oi_contracts_up_flat_3pct")

def near(history,ts,minutes,tolerance):
    options=[x for x in history if abs((ts-x[0])/60000-minutes)<=tolerance]
    return min(options,key=lambda x:abs((ts-x[0])/60000-minutes)) if options else None

def zone(volume,ret_24):
    if volume<1000000:v="L"
    elif volume<10000000:v="M"
    else:v="H"
    r=abs(ret_24)
    return v+(":CALM" if r<5 else ":MOVING" if r<15 else ":VERY_ACTIVE")

def features(history,t,venue):
    past=[(ts,assets[venue]) for ts,assets in history
          if ts<=t and venue in assets]
    cur=next((p for ts,p in reversed(past) if ts==t),None)
    one=near(past,t,60,25)
    two=near(past,t,120,30)
    if cur is None or one is None or two is None:return None
    q=cur.get("q");p=cur.get("p")
    q1=one[1].get("q");p1=one[1].get("p");p2=two[1].get("p")
    if not all(isinstance(x,(int,float)) and math.isfinite(x) and x>0
               for x in (p,p1,p2,q,q1)):return None
    r2=100*(p/p2-1)
    r1=100*(p/p1-1)
    # Both trend and liquidity/turnover are knowable AS OF timestamp t.
    # Rolling 24h turnover change is NOT trades executed during the last 1h.
    d24=cur.get("d")
    if not isinstance(d24,(int,float)) or not math.isfinite(d24):return None
    # OI in raw contracts is less mechanically price-inflated than OI in
    # USD. Available only on contemporaneous OKX snapshots after V9 deploy.
    oi_now=cur.get("oi_contracts")
    oi_then=one[1].get("oi_contracts")
    oi_change=(oi_now/oi_then-1
        if isinstance(oi_now,(int,float)) and isinstance(oi_then,(int,float))
           and 0<oi_then and 0<=oi_now and math.isfinite(oi_now) and math.isfinite(oi_then)
        else None)
    acceleration=q/q1-1
    return {"price_return_2h_pct":round(r2,5),
        "price_return_1h_pct":round(r1,5),
        "turnover_24h_change_1h_pct":round(100*acceleration,5),
        "turnover_24h_usdt":q,
        "return_24h_pct":d24,
        "turnover_proxy":bool(cur.get("q_proxy",False)),
        "oi_contracts_change_1h_pct":round(100*oi_change,5) if oi_change is not None else None,
        "motifs":{
            "activity_up_20pct":acceleration>=.2,
            "activity_up_flat_3pct":acceleration>=.2 and abs(r2)<=3,
            "quiet_price_2pct":abs(r2)<=2,
            "oi_contracts_up_10pct":oi_change>=.10 if oi_change is not None else None,
            "oi_contracts_up_flat_3pct":(oi_change>=.10 and abs(r2)<=3)
                if oi_change is not None else None},
        "funding_observed":False,"open_interest_observed":oi_change is not None,
        "stratum":zone(q,d24)}

def forward(samples,index,symbol,venue,start_price):
    start=samples[index][0]
    later=[(ts,assets[symbol][venue]["p"])
           for ts,assets in samples[index+1:]
           if ts<=start+HORIZON_MS+MAX_FUTURE_DELAY_MS
              and symbol in assets and venue in assets[symbol]
              and isinstance(assets[symbol][venue].get("p"),(float,int))]
    end=next(((ts,p) for ts,p in later if
             start+HORIZON_MS<=ts<=start+HORIZON_MS+MAX_FUTURE_DELAY_MS),None)
    within=[(ts,p) for ts,p in later if ts<=start+HORIZON_MS]
    if end is None or len(within)<MIN_FUTURE_SAMPLES:
        return {"status":"PENDING_INCOMPLETE_FUTURE_SNAPSHOTS"}
    sampled=[(start,start_price)]+within+[end]
    if any((b[0]-a[0])>90*60000 for a,b in zip(sampled,sampled[1:])):
        return {"status":"PENDING_GAPS_IN_FUTURE_SAMPLING"}
    if any(not math.isfinite(p) or p<=0 for _,p in sampled):
        return {"status":"CENSORED_INVALID_FUTURE_PRICE"}
    if any(abs(b[1]/a[1]-1)>.75 for a,b in zip(sampled,sampled[1:])):
        return {"status":"CENSORED_POSSIBLE_SCALE_CHANGE"}
    high=max(p for _,p in within)
    low=min(p for _,p in within)
    up=100*(high/start_price-1)
    down=100*(low/start_price-1)
    label=("BOTH_SIDES_EXTREME" if up>=EXTREME_MOVE_PCT and down<=-EXTREME_MOVE_PCT
           else "UPSIDE_EXTREME" if up>=EXTREME_MOVE_PCT
           else "DOWNSIDE_EXTREME" if down<=-EXTREME_MOVE_PCT
           else "NO_EXTREME_MOVE")
    return {"status":"OBSERVED_FUTURE_ONLY_NOT_EXECUTION",
            "label":label,"forward_4h_max_snapshot_return_pct":round(up,5),
            "forward_4h_min_snapshot_return_pct":round(down,5),
            "future_end_utc":datetime.fromtimestamp(end[0]/1000,timezone.utc).isoformat()}

def study(records):
    # A bounded review window is EXPLORATORY. No retrospective re-labelling
    # of a signal. Requires V8 samples *before* each event.
    valid=records[-HISTORY_SCANS:]
    scans=[(r["scan_utc_ms"],unpack(r["packed_assets"])) for r in valid]
    by_asset=defaultdict(list)
    for ts,assets in scans:
        for sym,venues in assets.items():
            by_asset[sym].append((ts,venues))
    rows=[];skipped=Counter();last_eligible={}
    for idx,(t,assets) in enumerate(scans):
        for sym,current in sorted(assets.items()):
            if last_eligible.get(sym,0)+HORIZON_MS>t:continue
            own=by_asset[sym]
            for venue in SOURCE_ORDER:
                if venue not in current:continue
                z=features(own,t,venue)
                if z is None:
                    skipped["NO_2H_ASOF_HISTORY"]+=1
                    break
                # Exclude already-running moves BEFORE any future labels.
                if abs(z["price_return_2h_pct"])>3 or abs(z["return_24h_pct"])>15:
                    skipped["ALREADY_MOVING_NOT_PRECURSOR"]+=1
                    break
                if z["turnover_24h_usdt"]<100000:
                    skipped["INSUFFICIENT_ASOF_LIQUIDITY_PROXY"]+=1
                    break
                last_eligible[sym]=t
                outcome=forward(scans,idx,sym,venue,current[venue]["p"])
                rows.append({"observed_utc":datetime.fromtimestamp(t/1000,timezone.utc).isoformat(),
                    "symbol":sym,"venue":venue,"features":z,"future":outcome,
                    "case_ascertainment":"FULL_ASOF_COHORT_NOT_SELECTED_BY_POST_EVENT_WINNER",
                    "trade_authorized":False})
                break
    eligible=[r for r in rows if r["future"]["status"]=="OBSERVED_FUTURE_ONLY_NOT_EXECUTION"]
    # Report full-universe denominators and matched contemporaneous controls
    # in frozen as-of liquidity + 24h return bands.
    bystratum=defaultdict(list)
    for r in eligible:
        # Controls must coexist at the exact SAME observation timestamp.
        bystratum[(r["observed_utc"],r["features"]["stratum"])].append(r)
    stats=[]
    for direction in ("UPSIDE_EXTREME","DOWNSIDE_EXTREME"):
        for motif in MOTIFS:
            cases=[];controls=[]
            for cohort in bystratum.values():
                yes=[r for r in cohort if r["future"]["label"]==direction]
                no=[r for r in cohort if r["future"]["label"]=="NO_EXTREME_MOVE"]
                if not yes or not no:continue
                cases.extend(yes);controls.extend(no)
            # Null OI is *missing*, never an absence of the risk motif.
            available_cases=[r for r in cases if r["features"]["motifs"][motif] is not None]
            available_controls=[r for r in controls if r["features"]["motifs"][motif] is not None]
            n=len(available_cases);m=len(available_controls)
            a=sum(r["features"]["motifs"][motif] is True for r in available_cases)
            b=sum(r["features"]["motifs"][motif] is True for r in available_controls)
            case_frac=a/n if n else None
            control_frac=b/m if m else None
            stats.append({"target":direction,"motif":motif,
                "all_cases_in_matching_strata":len(cases),
                "all_controls_in_matching_strata":len(controls),
                "cases_with_matched_asof_stratum":n,
                "matched_nonmover_controls":m,
                "cases_with_motif":a,"controls_with_motif":b,
                "case_motif_fraction":round(case_frac,5) if case_frac is not None else None,
                "control_motif_fraction":round(control_frac,5) if control_frac is not None else None,
                "enrichment_ratio_exploratory":round(case_frac/control_frac,4)
                  if case_frac is not None and control_frac else None,
                "status":"NO_PRECURSOR_EVIDENCE" if n<MIN_CASES_PER_DIRECTION or m<MIN_CONTROLS
                   else "EXPLORATORY_ONLY_MUST_PREREGISTER_AND_FORWARD_VALIDATE"})
    return {"schema":"EAR.v9_preimpulse_case_control.v1",
       "scans_in_window":len(scans),"eligible_asof_cohort_count":len(rows),
       "matured_full_control_population":len(eligible),
       "future_label_counts":dict(Counter(r["future"].get("label",r["future"]["status"]) for r in rows)),
       "skipped_asof_reasons":dict(skipped),
       "case_control_stats":stats,"recent_examples":rows[-40:],
       "constraints":{"decision_timestamp":"BEFORE_SUBSEQUENT_4H_OUTCOME",
          "event_definition":">=12pct observed up/down move within 4h from frozen earlier asof price",
          "prior_motion_screen":"ABS_PREVIOUS_2H_RETURN<=3pct_AND_ABS_24H_RETURN<=15pct",
          "control_selection":"EXACT_SAME_ASOF_SCAN_TIME_24H_TURNOVER_AND_PRICE_MOVE_BANDS_NOT_POST_HOC_WINNER_LIST",
          "one_sample_per_symbol_per_4h":True,
          "underlying_future_extrema_are_SAMPLED_not_actual_high_low":True,
          "zero_backfill_before_first_v8_observation":True,
          "historical_asof_features_only":True,
          "rolling_24h_turnover_changes_not_true_1h_buy_volume":True,
          "OI_on_OKX_only_from_FIRST_V9_asof_snapshot_no_historical_backfill":True,
          "funding_and_signed_taker_flow_NOT_AVAILABLE":True,
          "multiple_hypotheses_not_corrected":True,
          "pristine_holdout":False},
       "significant_common_metric_discovered":False,
       "proven_profitable_strategy":False,
       "paper_approved":False,"trade_authorized":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--ledger",required=True)
    parser.add_argument("--out",default="out/v9_preimpulse")
    args=parser.parse_args()
    report=study(read(args.ledger))
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    lines=["# V9 pre-event commonality vs controls",
       "All cases are defined from future observations ONLY AFTER their as-of features were frozen.",
       f"Snapshots: {report['scans_in_window']}; as-of cohort: {report['eligible_asof_cohort_count']}; matured: {report['matured_full_control_population']}.",
       "Outcome counts: "+json.dumps(report["future_label_counts"],sort_keys=True),
       "No common pre-event metric validated without enough independent cases and same-period nonmovers.",
       "| Direction | Pre-event metric | Cases with controls | Nonmover controls | Observed case fraction | Control fraction | Status |",
       "|---|---|---:|---:|---:|---:|---|"]
    for r in report["case_control_stats"]:
        lines.append("| "+" | ".join(str(r[k]) for k in ("target","motif","cases_with_matched_asof_stratum",
           "matched_nonmover_controls","case_motif_fraction","control_motif_fraction","status"))+" |")
    lines+=["","No continuous OI/funding/delta collection in V8. Historical PIPPIN rise cannot be claimed as anticipated; the first V8 scan is after its move.",
            "No trade, no short fill, no PAPER, no validated alpha."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    print("V9_PREIMPULSE",report["eligible_asof_cohort_count"],"asof",
          report["matured_full_control_population"],"matured",report["future_label_counts"])

if __name__=="__main__":main()
