"""V13-CRYPTO: separately qualified costed USDT perpetual MARK-TO-MARK research.

Consumes only SHA-verified real V8 snapshots, V9/V11 as-of precursor motifs,
and new V13 prospective observation/outcome registers. Does NOT turn V9
future extrema into fills. Entry is only at a later same-venue snapshot,
exit is a later same-venue snapshot, including modeled spread/fees/slippage
and an UNKNOWN-real-funding buffer. This is NOT broker execution or PnL.
Never creates initial historic signals from previously published V8 scans.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from statistics import mean,stdev

from radar.ledger import read_verify
from research_v4.perp_watch import unpack
from research_v4.preimpulse_study import features, SOURCE_ORDER
from research_v4.pattern_learner import RULES, flag, append_sealed

MARKET="CRYPTO_PERPETUAL"
DIRECTIONS=("LONG","SHORT")
HORIZONS_MIN=(60,240)
MAX_SOURCE_AGE_MIN=90
SOURCE_SCANS_FOR_FEATURES=180
MAX_SYMBOLS_PER_SCAN=220
MIN_ASOF_TURNOVER_USDT=100000
MAX_ASOF_SPREAD_BPS=100
MAX_ASOF_2H_MOVE_PCT=3
MAX_ASOF_24H_MOVE_PCT=15
MIN_ENSEMBLE_VENUES=2
ENTRY_MAX_DELAY_MIN=75
EXIT_TOLERANCE_MIN=45
MAX_QUOTE_GAP_MIN=95
STALE_OUTCOME_HOURS=48
FEE_ROUND_TRIP_PCT=.12
SLIPPAGE_ROUND_TRIP_PCT=.20
FUNDING_RISK_BUFFER_PCT=.12
EXTRA_STRESS_PCT=.20
MAX_SIMULTANEOUS=5
MIN_CASES=35
MIN_MATCHED_CONTROLS=100
MIN_SYMBOLS=12
MIN_DAYS=6
MIN_BLOCKS=8
MIN_PROFIT_FACTOR=1.3
MIN_WIN_RATE=.48
MIN_NET_MEAN=.20
MIN_EXCESS=.20
# Conservative multiplicity screen, NOT robust p value proof.
MULTIPLICITY_Z=3.7
TRIAL_DAYS=30
TRIAL_GRACE_DAYS=3
COOLDOWN_DAYS=45
CHECKPOINT_WEEKDAY=0
METHOD_FILES=("research_v4/v13_crypto_profit.py",
              "research_v4/preimpulse_study.py",
              "research_v4/perp_anomaly.py",
              "research_v4/perp_watch.py",
              "research_v4/pattern_learner.py")


def iso_ms(t):
    return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()


def ms(s):
    t=datetime.fromisoformat(s.replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("TIMEZONE_REQUIRED")
    return int(t.timestamp()*1000)


def ident(*parts):
    return hashlib.sha256("|".join(map(str,parts)).encode()).hexdigest()


def method_hash():
    h=hashlib.sha256()
    for filename in METHOD_FILES:
        h.update(filename.encode())
        h.update(Path(filename).read_bytes())
    return h.hexdigest()


def source_rows(path):
    """Verify full V8 SHA chain, expand only bounded recent source history."""
    rows=read_verify(path)
    if not rows:raise ValueError("NO_V8_EVIDENCE")
    last=-1
    for row in rows:
        t=row.get("scan_utc_ms")
        if (row.get("schema")!="EAR.perp_forward.v1"
                or row.get("market_type")!="USDT_LINEAR_PERPETUAL_ONLY"
                or row.get("trade_authorized") is not False
                or not isinstance(t,int) or t<=last):
            raise ValueError("UNTRUSTED_V8_SOURCE")
        last=t
    return [(r["scan_utc_ms"],unpack(r["packed_assets"]),r["sha256"])
            for r in rows[-SOURCE_SCANS_FOR_FEATURES:]]


def spread_bps(quote):
    v=quote.get("spread_bps") if isinstance(quote,dict) else None
    return (float(v) if isinstance(v,(float,int)) and not isinstance(v,bool)
            and math.isfinite(v) and 0<=v<=MAX_ASOF_SPREAD_BPS else None)


def asof_signals(snapshots,now_ms,previous_ids,version):
    """Only latest actually observed scan, never backfill earlier history."""
    if not snapshots or snapshots[-1][0]>now_ms:
        raise ValueError("V8_SOURCE_EMPTY_OR_FUTURE")
    if now_ms-snapshots[-1][0]>MAX_SOURCE_AGE_MIN*60000:
        # Source outage is a recorded degraded state, NEVER an invitation
        # to manufacture new first-seen signals from old V8 snapshots.
        return [],{"STALE_UPSTREAM_V8_NEW_OBSERVATIONS_BLOCKED":1}
    t,assets,sha=snapshots[-1]
    own=defaultdict(list)
    for when,frame,_ in snapshots:
        for sym,venues in frame.items():
            own[sym].append((when,venues))
    bucket=t//(4*3600000)
    # Deterministic rotating as-of sample, NOT cherry-picked past winners.
    chosen=sorted(assets,
                  key=lambda sym:ident(bucket,sym))[:MAX_SYMBOLS_PER_SCAN]
    observations=[]
    failed=Counter()
    for sym in chosen:
        venues=assets[sym]
        if len(venues)<MIN_ENSEMBLE_VENUES:
            failed["INSUFFICIENT_INDEPENDENT_VENUES"]+=1
            continue
        sid=ident(MARKET,sym,bucket)
        if sid in previous_ids:continue
        for venue in SOURCE_ORDER:
            cur=venues.get(venue)
            if cur is None or spread_bps(cur) is None:
                continue
            if not 0<cur.get("p",0) or cur.get("q",0)<MIN_ASOF_TURNOVER_USDT:
                continue
            if abs(cur.get("d",999))>MAX_ASOF_24H_MOVE_PCT:
                continue
            z=features(own[sym],t,venue)
            if z is None:
                continue
            if abs(z["price_return_2h_pct"])>MAX_ASOF_2H_MOVE_PCT:
                continue
            if z.get("turnover_proxy") is True:
                failed["INFERRED_TURNOVER_NOT_USED"]+=1
                continue
            motifs=z["motifs"]
            # Missing metrics stay null; no guessing omitted funding/OI.
            observations.append({
                "schema":"EAR.v13_crypto_asof.v1","kind":"asof",
                "id":sid,"market":MARKET,"symbol":sym,"venue":venue,
                "bucket":bucket,"observed_utc":iso_ms(t),
                "entry_after_ms":t,"source_scan_sha256":sha,
                "methodology_sha256":version,"stratum":z["stratum"],
                "motifs":motifs,
                "asof_spread_bps":spread_bps(cur),
                "asof_quote_turnover_usdt":cur["q"],
                "asof_price_not_executable":cur["p"],
                "entry_and_exit_prices_unknown":True,
                "missing_oi_not_assumed_false":True,
                "trade_authorized":False,"paper_approved":False,
            })
            break
        else:failed["NO_USABLE_PRICE_SPREAD_OR_PRECURSOR"]+=1
    return observations,dict(failed)


def valid_quote(q):
    if not isinstance(q,dict):return None
    p=q.get("p")
    sp=spread_bps(q)
    if (not isinstance(p,(int,float)) or isinstance(p,bool)
            or not math.isfinite(p) or p<=0 or sp is None):return None
    return float(p),sp


def future_mark(signal,snapshots,horizon,now_ms):
    """Entry AFTER signal at next price observation, not V9 hindsight high."""
    t=signal["entry_after_ms"]
    upcoming=[(stamp,venues.get(signal["symbol"],{}).get(signal["venue"]))
              for stamp,venues,_ in snapshots if stamp>t]
    entry=next(((stamp,v) for stamp,v in upcoming
                if 0<stamp-t<=ENTRY_MAX_DELAY_MIN*60000 and valid_quote(v)),None)
    if entry is None:
        if now_ms<t+STALE_OUTCOME_HOURS*3600000:return None
        return {"status":"CENSORED_NO_VERIFIABLE_NEXT_QUOTE"}
    start,quote=entry
    target=start+horizon*60000
    exits=[(stamp,v) for stamp,v in upcoming
           if abs(stamp-target)<=EXIT_TOLERANCE_MIN*60000
           and valid_quote(v)]
    end=min(exits,key=lambda row:abs(row[0]-target)) if exits else None
    if end is None:
        if now_ms<t+STALE_OUTCOME_HOURS*3600000:return None
        return {"status":"CENSORED_FUTURE_QUOTE_GAP"}
    stop,exit_quote=end
    all_venue=[(stamp,v) for stamp,v in upcoming if start<=stamp<=stop]
    contiguous=[(stamp,v) for stamp,v in all_venue if valid_quote(v)]
    if (len(contiguous)!=len(all_venue) or not contiguous
            or contiguous[0][0]!=start or contiguous[-1][0]!=stop
            or any((b[0]-a[0])>MAX_QUOTE_GAP_MIN*60000
                   for a,b in zip(contiguous,contiguous[1:]))):
        return {"status":"CENSORED_NONCONTIGUOUS_FUTURE_PRICES"}
    prices=[valid_quote(v)[0] for _,v in contiguous]
    if any(abs(b/a-1)>.75 for a,b in zip(prices,prices[1:])):
        return {"status":"CENSORED_POSSIBLE_REBASE_OR_BAD_PRICE"}
    entry_p,entry_sp=valid_quote(quote)
    exit_p,exit_sp=valid_quote(exit_quote)
    # Indicator quotes, not executable bid/ask/depth. Half-spread both legs.
    spread_pct=(entry_sp+exit_sp)/200
    friction=spread_pct+FEE_ROUND_TRIP_PCT+SLIPPAGE_ROUND_TRIP_PCT+FUNDING_RISK_BUFFER_PCT
    gross_long=100*(exit_p/entry_p-1)
    gross_short=-gross_long
    return {
        "status":"FUTURE_SNAPSHOT_MARK_ONLY",
        "entry_snapshot_utc":iso_ms(start),
        "exit_snapshot_utc":iso_ms(stop),
        "entry_snapshot_price":entry_p,
        "exit_snapshot_price":exit_p,
        "observed_spread_cost_pct":round(spread_pct,6),
        "fee_model_pct":FEE_ROUND_TRIP_PCT,
        "slippage_model_pct":SLIPPAGE_ROUND_TRIP_PCT,
        "unverified_funding_risk_buffer_pct":FUNDING_RISK_BUFFER_PCT,
        "model_total_friction_pct":round(friction,6),
        "gross_long_pct":round(gross_long,6),
        "gross_short_pct":round(gross_short,6),
        "modeled_net_long_pct":round(gross_long-friction,6),
        "modeled_net_short_pct":round(gross_short-friction,6),
        "actual_funding_not_collected":True,
        "execution_depth_unverified":True,
        "short_margin_borrow_and_liquidation_unmodeled":True,
        "trade_authorized":False,"paper_approved":False,
    }


def evidence_rows(signals,outcomes,version,horizon,direction):
    lookup={o["signal_id"]:o for o in outcomes
            if o["horizon_minutes"]==horizon and o["status"]=="FUTURE_SNAPSHOT_MARK_ONLY"}
    result=[]
    for s in signals:
        if s["methodology_sha256"]!=version or s["id"] not in lookup:continue
        o=lookup[s["id"]]
        if o["source_signal_methodology_sha256"]!=version:
            raise ValueError("CROSS_VERSION_OUTCOME")
        pnl=o["modeled_net_"+direction.lower()+"_pct"]
        result.append({
            "id":s["id"],"symbol":s["symbol"],"venue":s["venue"],
            "observed_utc":s["observed_utc"],"stratum":s["stratum"],
            "motifs":s["motifs"],
            "entry_utc":o["entry_snapshot_utc"],
            "exit_utc":o["exit_snapshot_utc"],
            "net_pct":pnl,"stressed_pct":pnl-EXTRA_STRESS_PCT,
        })
    return result


def candidate_summary(rows,rule,direction,horizon,since=None,before=None):
    chosen=[r for r in rows
            if (since is None or ms(r["observed_utc"])>=since)
            and (before is None or ms(r["observed_utc"])<before)]
    positive=[r for r in chosen if flag(r["motifs"],rule) is True]
    # Same timestamp, price-band, and same venue non-rule controls.
    cohorts=defaultdict(list)
    for x in chosen:cohorts[(x["observed_utc"],x["stratum"],x["venue"])].append(x)
    controls=[]
    for group in cohorts.values():
        if any(flag(x["motifs"],rule) is True for x in group):
            controls += [x for x in group if flag(x["motifs"],rule) is False]
    # Chronological, as-of tie-break: no winner-dependent allocation.
    active=[]
    blocked=Counter()
    for x in sorted(positive,key=lambda r:(r["entry_utc"],ident(r["symbol"],r["id"]))):
        if any(y["symbol"]==x["symbol"] and
               ms(y["exit_utc"])>=ms(x["entry_utc"]) for y in active):
            blocked["SYMBOL_OVERLAP"]+=1
            continue
        simultaneous=sum(ms(y["entry_utc"])<=ms(x["entry_utc"])<=ms(y["exit_utc"])
                         for y in active)
        if simultaneous>=MAX_SIMULTANEOUS:
            blocked["MAX_SLOTS"]+=1
            continue
        active.append(x)
    n=len(active)
    pnl=[x["net_pct"] for x in active]
    stress=[x["stressed_pct"] for x in active]
    cm=[x["net_pct"] for x in controls]
    pos=sum(max(0,x) for x in pnl)
    neg=-sum(min(0,x) for x in pnl)
    profit_factor=pos/neg if neg>0 else None
    groups=defaultdict(list)
    for x in active:
        groups[ms(x["exit_utc"])//(4*3600000)].append(x["stressed_pct"])
    blocks=[mean(v) for _,v in sorted(groups.items())]
    lower=(mean(blocks)-MULTIPLICITY_Z*stdev(blocks)/math.sqrt(len(blocks))
           if len(blocks)>=MIN_BLOCKS else None)
    avg=mean(pnl) if pnl else None
    avg_s=mean(stress) if stress else None
    base=mean(cm) if cm else None
    excess=avg-base if avg is not None and base is not None else None
    win=sum(x>0 for x in pnl)/n if n else None
    valid=(n>=MIN_CASES and len(controls)>=MIN_MATCHED_CONTROLS
           and len({x["symbol"] for x in active})>=MIN_SYMBOLS
           and len({x["observed_utc"][:10] for x in active})>=MIN_DAYS
           and len(blocks)>=MIN_BLOCKS
           and profit_factor is not None and profit_factor>=MIN_PROFIT_FACTOR
           and win is not None and win>=MIN_WIN_RATE
           and avg is not None and avg>=MIN_NET_MEAN
           and avg_s is not None and avg_s>0
           and excess is not None and excess>=MIN_EXCESS
           and lower is not None and lower>0)
    return {
        "rule":rule,"direction":direction,"horizon_minutes":horizon,
        "hypothetical_mark_trades":n,"controls":len(controls),
        "distinct_symbols":len({x["symbol"] for x in active}),
        "distinct_days":len({x["observed_utc"][:10] for x in active}),
        "four_hour_exit_blocks":len(blocks),"skip_counts":dict(blocked),
        "mean_model_net_pct":round(avg,6) if avg is not None else None,
        "stressed_mean_net_pct":round(avg_s,6) if avg_s is not None else None,
        "matched_control_mean_net_pct":round(base,6) if base is not None else None,
        "excess_over_matched_controls_pct":round(excess,6) if excess is not None else None,
        "win_rate":round(win,6) if win is not None else None,
        "profit_factor":round(profit_factor,6) if profit_factor is not None else None,
        "multiplicity_screen_lower_pct":round(lower,6) if lower is not None else None,
        "fixed_costed_research_gates_pass":valid,
        "actual_profit_proven":False,
    }


def run(source_path,state_dir,now_ms,version=None,root="."):
    version=version or method_hash()
    snapshots=source_rows(source_path)
    if snapshots[-1][0]>now_ms:raise ValueError("V8_IN_FUTURE")
    state=Path(state_dir)
    state.mkdir(parents=True,exist_ok=True)
    files={n:state/(n+".jsonl") for n in
           ("observations","outcomes","frozen","decisions")}
    old={name:read_verify(path) for name,path in files.items()}
    if any(v and v[-1]["scan_utc_ms"]>now_ms+60000 for v in old.values()):
        raise ValueError("EVIDENCE_CLOCK_REWIND")
    existing={x["id"] for x in old["observations"]}
    new_obs,skips=asof_signals(snapshots,now_ms,existing,version)
    observations=append_sealed(files["observations"],new_obs,now_ms)
    prior_outcomes={x["id"] for x in old["outcomes"]}
    future=[]
    pending=0
    for s in observations:
        for horizon in HORIZONS_MIN:
            oid=ident(s["id"],horizon)
            if oid in prior_outcomes:continue
            o=future_mark(s,snapshots,horizon,now_ms)
            if o is None:
                pending+=1
                continue
            future.append({
                "schema":"EAR.v13_crypto_outcome.v1","kind":"outcome",
                "id":oid,"signal_id":s["id"],"market":MARKET,
                "symbol":s["symbol"],"venue":s["venue"],
                "horizon_minutes":horizon,
                "source_signal_methodology_sha256":s["methodology_sha256"],
                "settlement_source_sha256":snapshots[-1][2],
                **o,
            })
    outcomes=append_sealed(files["outcomes"],future,now_ms+len(new_obs)+20)
    reports=[]
    for horizon in HORIZONS_MIN:
        for direction in DIRECTIONS:
            rows=evidence_rows(observations,outcomes,version,horizon,direction)
            for rule in RULES:
                reports.append(candidate_summary(rows,rule,direction,horizon))
    winner=[x for x in reports if x["fixed_costed_research_gates_pass"]]
    winner.sort(key=lambda x:(-x["multiplicity_screen_lower_pct"],
                              -x["excess_over_matched_controls_pct"],
                              x["rule"],x["direction"],x["horizon_minutes"]))
    frozen=old["frozen"]
    done={x["hypothesis_id"] for x in old["decisions"]}
    locks=[]
    now=datetime.fromtimestamp(now_ms/1000,timezone.utc)
    if (now.weekday()==CHECKPOINT_WEEKDAY and winner and
            not any(x["id"] not in done for x in frozen) and
            all(now-ms_to_datetime(x["created_utc"])>=timedelta(days=COOLDOWN_DAYS)
                for x in frozen)):
        already={(x["rule"],x["direction"],x["horizon_minutes"],x["methodology_sha256"])
                 for x in frozen}
        selected=next((x for x in winner if
                       (x["rule"],x["direction"],x["horizon_minutes"],version)
                       not in already),None)
        if selected:
            start=datetime.combine(now.date()+timedelta(days=1),
                                   datetime.min.time(),tzinfo=timezone.utc)
            locks=[{
                "schema":"EAR.v13_crypto_frozen_trial.v1","kind":"freeze",
                "id":ident(selected["rule"],selected["direction"],
                           selected["horizon_minutes"],now.isoformat(),version),
                "rule":selected["rule"],"direction":selected["direction"],
                "horizon_minutes":selected["horizon_minutes"],
                "methodology_sha256":version,
                "created_utc":now.isoformat(),
                "trial_start_utc":start.isoformat(),
                "trial_end_utc":(start+timedelta(days=TRIAL_DAYS)).isoformat(),
                "training_evidence":selected,
                "paper_approved":False,"trade_authorized":False,
            }]
    frozen=append_sealed(files["frozen"],locks,now_ms+len(new_obs)+len(future)+50)
    decisions=[]
    for x in frozen:
        if x["id"] in done or x["methodology_sha256"]!=version:continue
        if now<ms_to_datetime(x["trial_end_utc"])+timedelta(days=TRIAL_GRACE_DAYS):
            continue
        rows=evidence_rows(observations,outcomes,version,
                           x["horizon_minutes"],x["direction"])
        hold=candidate_summary(rows,x["rule"],x["direction"],
                               x["horizon_minutes"],
                               since=ms(x["trial_start_utc"]),
                               before=ms(x["trial_end_utc"]))
        decisions.append({
            "schema":"EAR.v13_crypto_forward_decision.v1","kind":"decision",
            "id":ident(x["id"],"decision"),"hypothesis_id":x["id"],
            "status":("POSITIVE_STRESSED_SNAPSHOT_MARK_ASSOCIATION"
                      if hold["fixed_costed_research_gates_pass"]
                      else "FAILED_OR_INSUFFICIENT_FORWARD_EVIDENCE"),
            "rule":x["rule"],"direction":x["direction"],
            "horizon_minutes":x["horizon_minutes"],
            "methodology_sha256":version,"future_report":hold,
            "evaluated_utc":now.isoformat(),"actual_profit_proven":False,
            "trade_authorized":False,"paper_approved":False,
        })
    all_decisions=append_sealed(files["decisions"],decisions,
                                now_ms+len(new_obs)+len(future)+len(locks)+100)
    return {
        "schema":"EAR.v13_crypto_costed_research.v1",
        "source_status":("STALE_UPSTREAM_V8_WATCH_ONLY" if
                         skips.get("STALE_UPSTREAM_V8_NEW_OBSERVATIONS_BLOCKED")
                         else "FRESH_V8_RESEARCH_OBSERVATIONS"),
        "source_age_minutes":round((now_ms-snapshots[-1][0])/60000,3),
        "asof_utc":now.isoformat(),"source_v8_last_sha256":snapshots[-1][2],
        "source_v8_scans_in_window":len(snapshots),
        "methodology_sha256":version,
        "asof_observations":len(observations),"new_observations":len(new_obs),
        "modeled_outcomes":len(outcomes),"new_outcomes":len(future),
        "pending_future_outcomes":pending,"source_rejections":skips,
        "strategy_variants_tested":len(reports),
        "exploratory_candidates":winner[:10],
        "frozen_trials":len(frozen),"new_frozen":locks,
        "completed_forward_trials":len(all_decisions),"new_decisions":decisions,
        "active_trials":[{
            "id":x["id"],"rule":x["rule"],"direction":x["direction"],
            "status":("PAUSED_METHODOLOGY_DRIFT" if
                      x["methodology_sha256"]!=version
                      else "AWAITING_FUTURE_VALIDATION")}
            for x in frozen if x["id"] not in
            {d["hypothesis_id"] for d in all_decisions}],
        "all_rule_horizon_results":reports,
        "limitations":{
            "indicative_last_prices_not_executable":True,
            "actual_funding_unverified_buffer_only":True,
            "liquidations_and_margin_unmodeled":True,
            "perp_spread_and_market_impact_not_executable_depth":True,
            "rotating_asof_sample_not_full_universe":True,
            "no_intrabar_stops_or_high_low_peeking":True,
            "shorts_are_not_verified_fills":True,
            "repeated_symbols_and_venue_dependence":True,
            "not_profitable_alpha_proof":True,
            "trade_authorized":False,"paper_approved":False,
        },
    }


def ms_to_datetime(s):
    return datetime.fromtimestamp(ms(s)/1000,timezone.utc)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--v8-ledger",required=True)
    p.add_argument("--state",required=True)
    p.add_argument("--out",default="out/v13_crypto")
    a=p.parse_args()
    now_ms=int(datetime.now(timezone.utc).timestamp()*1000)
    report=run(a.v8_ledger,a.state,now_ms)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True,
                                         allow_nan=False)+"\n",encoding="utf8")
    lines=["# V13 CRYPTO — cost-stressed, future-only perpetual research",
        "",f"V8 source status: {report['source_status']} (age min: {report['source_age_minutes']})",
        f"Real V8 snapshots available in features window: {report['source_v8_scans_in_window']}",
        f"First-seen observations: {report['asof_observations']} (+{report['new_observations']})",
        f"Modelled quote-to-quote future outcomes: {report['modeled_outcomes']} (+{report['new_outcomes']})",
        f"Pending: {report['pending_future_outcomes']}",
        f"Tested rule × side × horizon variants: {report['strategy_variants_tested']}",
        f"Training cost-positive candidates: {len(report['exploratory_candidates'])}",
        f"Frozen future trials: {report['frozen_trials']}",
        f"Completed future trial decisions: {report['completed_forward_trials']}",
        "", "These are NOT executable fills, actual funding, verified liquidations,",
        "live short positions or broker PnL. Funding/cost risk BUFFER is assumed."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    print("V13_CRYPTO",report["new_observations"],"new",
          report["new_outcomes"],"future marks",
          len(report["exploratory_candidates"]),"candidate")
if __name__=="__main__":main()
