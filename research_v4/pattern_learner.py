"""V11 autonomous *association* discovery with locked prospective holdouts.

Never asserts that a correlated precursor CAUSES a move or makes money.
The preliminary scan has family-wide multiple-testing control; a frozen,
never-retuned 7-day future window must independently replicate. Signals are
not orders and are never inserted into old V3/V5/PAPER state.
"""
from __future__ import annotations
import argparse,hashlib,json,math
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from research_v4.preimpulse_study import study,MOTIFS
from research_v4.perp_watch import read
from radar.ledger import canonical,digest,read_verify

TRIAL_DAYS=7
NEW_LOCK_COOLDOWN_DAYS=14
LOCK_WEEKDAY_UTC=0  # Monday; bounded multiple looks across calendar time
RESEARCH_SNAPSHOTS=450
MIN_CASES=30
MIN_CONTROLS=200
MIN_DISTINCT_CASE_SYMBOLS=10
MIN_CASES_EXPOSED=8
MAX_FPR=.10
MIN_LIFT=2.
FDR_ALPHA=.05
METHOD_FILES=("research_v4/preimpulse_study.py",
              "research_v4/perp_anomaly.py",
              "research_v4/perp_watch.py",
              "research_v4/pattern_learner.py")

# These are fixed, declared in advance; pairs are distinct information groups
# and do not include an 'any' aggregator paired with its own constituents.
PAIR_BASE=("relative_turnover_24h_outlier",
           "relative_oi_contracts_outlier",
           "relative_spread_outlier",
           "relative_funding_outlier",
           "relative_mark_basis_outlier")
PAIRS=tuple(a+" + "+b for i,a in enumerate(PAIR_BASE) for b in PAIR_BASE[i+1:])
PAIR_COMPLEMENT=("activity_up_flat_3pct + oi_contracts_up_flat_3pct",)
RULES=tuple(MOTIFS)+PAIRS+PAIR_COMPLEMENT
DIRECTIONS=("UPSIDE_EXTREME","DOWNSIDE_EXTREME")

def utc_ms(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("TZ_REQUIRED")
    return int(d.timestamp()*1000)

def iso(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()

def methodology_hash(root="."):
    h=hashlib.sha256()
    for p in METHOD_FILES:
        h.update(p.encode())
        h.update((Path(root)/p).read_bytes())
    return h.hexdigest()

def flag(motifs,rule):
    parts=rule.split(" + ")
    vals=[motifs.get(m) for m in parts]
    if any(v is None for v in vals):return None
    if not all(isinstance(v,bool) for v in vals):raise ValueError("INVALID_BOOLEAN_MOTIF")
    return all(vals)

def case_control(rows,direction):
    """Match contemporaneous controls before computing rule statistics.

    Cases and controls use the exact UTC as-of scan and same 24h
    turnover/current 24h return stratum, as in V9. Opposite-side and
    both-sides extreme outcomes are NOT treated as clean nonmover controls.
    """
    cohorts=defaultdict(list)
    for row in rows:
        if row["future"]["label"] not in (direction,"NO_EXTREME_MOVE"):continue
        key=(row["observed_utc"],row["features"]["stratum"])
        cohorts[key].append(row)
    matched=[]
    for cohort in cohorts.values():
        has_case=any(r["future"]["label"]==direction for r in cohort)
        has_control=any(r["future"]["label"]=="NO_EXTREME_MOVE" for r in cohort)
        if has_case and has_control:matched.extend(cohort)
    return matched

def logadd(values):
    m=max(values)
    return m+math.log(sum(math.exp(x-m) for x in values))

def fisher_greater(a,b,c,d):
    """P(positive association | fixed margins), one-sided exact hypergeometric."""
    n=a+b+c+d
    if n==0:return 1.
    pos=a+c
    chosen=a+b
    hi=min(pos,chosen)
    def logchoose(n,k):
        return math.lgamma(n+1)-math.lgamma(k+1)-math.lgamma(n-k+1)
    denom=logchoose(n,chosen)
    return max(0.,min(1.,math.exp(logadd([
        logchoose(pos,k)+logchoose(n-pos,chosen-k)-denom
        for k in range(a,hi+1)
        if 0<=chosen-k<=n-pos
    ]))))

def measure(matched,rule,direction):
    valid=[r for r in matched if flag(r["features"]["motifs"],rule) is not None]
    cases=[r for r in valid if r["future"]["label"]==direction]
    controls=[r for r in valid if r["future"]["label"]=="NO_EXTREME_MOVE"]
    a=sum(flag(r["features"]["motifs"],rule) is True for r in cases)
    c=sum(flag(r["features"]["motifs"],rule) is True for r in controls)
    b=len(cases)-a
    d=len(controls)-c
    prevalence=(a+b)/(a+b+c+d) if a+b+c+d else None
    precision=a/(a+c) if a+c else None
    recall=a/(a+b) if a+b else None
    fpr=c/(c+d) if c+d else None
    lift=precision/prevalence if precision is not None and prevalence else None
    case_symbols={r["symbol"] for r in cases}
    case_days={r["observed_utc"][:10] for r in cases}
    return {"direction":direction,"rule":rule,
       "matched_case_total":a+b,"matched_nonmover_controls":c+d,
       "case_with_rule":a,"case_without_rule":b,
       "control_with_rule_false_alarms":c,"control_without_rule":d,
       "case_symbols":len(case_symbols),"case_days":len(case_days),
       "sampled_precision":round(precision,6) if precision is not None else None,
       "sampled_base_rate":round(prevalence,6) if prevalence is not None else None,
       "sampled_recall":round(recall,6) if recall is not None else None,
       "sampled_false_alarm_rate":round(fpr,6) if fpr is not None else None,
       "sampled_lift_vs_prevalence":round(lift,6) if lift is not None else None,
       "fisher_one_sided_p":fisher_greater(a,b,c,d),
       "not_full_universe_precision":"Matched strata require cases; other as-of strata are omitted."}

def fdr(results):
    """Benjamini–Hochberg FDR over ALL preregistered rules, BOTH directions."""
    indexes=sorted(range(len(results)),key=lambda i:results[i]["fisher_one_sided_p"])
    n=len(indexes)
    adjusted=[1.]*n
    bound=1.
    for rank in range(n,0,-1):
        i=indexes[rank-1]
        bound=min(bound,results[i]["fisher_one_sided_p"]*n/rank)
        adjusted[i]=min(1.,bound)
    for i,row in enumerate(results):
        row["bh_fdr_q"]=round(adjusted[i],9)

def qualifies(x):
    return (x["matched_case_total"]>=MIN_CASES
        and x["matched_nonmover_controls"]>=MIN_CONTROLS
        and x["case_symbols"]>=MIN_DISTINCT_CASE_SYMBOLS
        and x["case_days"]>=3
        and x["case_with_rule"]>=MIN_CASES_EXPOSED
        and x["sampled_false_alarm_rate"] is not None
        and x["sampled_false_alarm_rate"]<=MAX_FPR
        and x["sampled_lift_vs_prevalence"] is not None
        and x["sampled_lift_vs_prevalence"]>=MIN_LIFT
        and x["bh_fdr_q"]<=FDR_ALPHA)

def summarize(rows):
    result=[]
    for direction in DIRECTIONS:
        matched=case_control(rows,direction)
        for rule in RULES:
            result.append(measure(matched,rule,direction))
    fdr(result)
    for x in result:x["passes_fixed_research_gates"]=qualifies(x)
    return result

def digest_event(row):
    return hashlib.sha256((row["observed_utc"]+"|"+row["symbol"]+
             "|"+row["venue"]).encode()).hexdigest()

def compact_row(row):
    return {"event_id":digest_event(row),
       "observed_utc":row["observed_utc"],"symbol":row["symbol"],
       "venue":row["venue"],"stratum":row["features"]["stratum"],
       "label":row["future"]["label"],
       "future_end_utc":row["future"].get("future_end_utc"),
       "motifs":row["features"]["motifs"]}

def raw_to_row(row):
    return {"observed_utc":row["observed_utc"],"symbol":row["symbol"],
       "venue":row["venue"],
       "future":{"label":row["label"]},
       "features":{"stratum":row["stratum"],"motifs":row["motifs"]}}

def append_sealed(path,events,at_ms):
    """Strictly monotonic write timestamps; never modify old registry entries."""
    old=read_verify(path)
    prev=old[-1]["sha256"] if old else "GENESIS"
    ts=max(at_ms,old[-1]["scan_utc_ms"]+1 if old else 1)
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    if not events:return old
    with p.open("a",encoding="utf8") as f:
        for event in events:
            stamped={**event,"scan_utc_ms":ts,
                     "prev_sha256":prev}
            stamped["sha256"]=digest(stamped)
            f.write(canonical(stamped)+"\n")
            prev=stamped["sha256"]
            old.append(stamped);ts+=1
    return old

def infer_report(v8_records,state_dir,asof,version,root="."):
    now=utc_ms(asof)
    if not v8_records:raise ValueError("NO_SOURCE_V8_SCANS")
    if v8_records[-1]["scan_utc_ms"]>now:
        raise ValueError("ANALYSIS_CLOCK_BEFORE_LEDGER")
    frozen_path=state_dir/"frozen.jsonl"
    trial_path=state_dir/"trial_observations.jsonl"
    status_path=state_dir/"decisions.jsonl"
    frozen=read_verify(frozen_path)
    trial=read_verify(trial_path)
    decisions=read_verify(status_path)
    # Only a bounded, non-backfilled research window; signals at t require
    # actual V8 historical observations available at or before t.
    research=study(v8_records[-RESEARCH_SNAPSHOTS:],include_rows=True)
    rows=research.pop("matured_cohort_rows",[])
    # A source clock mismatch must never let a future outcome enter today's
    # exploratory search or a locked prospective trial.
    compact=[compact_row(row) for row in rows
             if utc_ms(row["observed_utc"])<=now
             and row["future"].get("future_end_utc")
             and utc_ms(row["future"]["future_end_utc"])<=now]
    train_rows=[raw_to_row(x) for x in compact]
    exploration=summarize(train_rows)

    prior_keys={(x["direction"],x["rule"],x["methodology_sha256"]) for x in frozen}
    locks=[]
    # No new rule may be "frozen" by relabeling prior completed outcomes as
    # prospective; all locked trials begin at next UTC midnight.
    next_midnight=((now//86400000)+1)*86400000
    is_freeze_checkpoint=datetime.fromtimestamp(now/1000,timezone.utc).weekday()==LOCK_WEEKDAY_UTC
    already_decided={d["hypothesis_id"] for d in decisions}
    for direction in DIRECTIONS:
        if not is_freeze_checkpoint:continue
        # One fixed future trial per direction at a time; cool down before
        # another weekly search to limit optional stopping/data dredging.
        prior_direction=[x for x in frozen if x["direction"]==direction
                         and x["methodology_sha256"]==version]
        if any(x["id"] not in already_decided for x in prior_direction):
            continue
        if any(now-utc_ms(x["created_utc"])<NEW_LOCK_COOLDOWN_DAYS*86400000
               for x in prior_direction):
            continue
        best=next((x for x in sorted(
                    (x for x in exploration if x["direction"]==direction
                     and x["passes_fixed_research_gates"]),
                    key=lambda x:(x["bh_fdr_q"],
                                  -x["sampled_lift_vs_prevalence"],x["rule"]))
                  if (x["direction"],x["rule"],version) not in prior_keys),None)
        if best is None:continue
        locked={"schema":"EAR.v11_frozen_hypothesis.v1",
            "kind":"freeze","direction":direction,"rule":best["rule"],
            "methodology_sha256":version,
            "created_utc":asof,"train_end_utc":asof,
            "trial_start_utc":iso(next_midnight),
            "trial_end_utc":iso(next_midnight+TRIAL_DAYS*86400000),
            "exploratory_support":best,
            "status":"FROZEN_NO_RETROACTIVE_HOLDOUT",
            "paper_approved":False,"trade_authorized":False}
        locked["id"]=digest({"direction":direction,"rule":best["rule"],
                         "code":version,"created":asof})
        locks.append(locked)
    frozen=append_sealed(frozen_path,locks,now)
    active=[x for x in frozen if not any(y.get("hypothesis_id")==x["id"]
                 for y in decisions)]
    current_ids={x["event_id"] for x in trial}
    fresh=[]
    for row in compact:
        if row["event_id"] in current_ids:continue
        t=utc_ms(row["observed_utc"])
        # Only rows after lock + start, and with observed matured outcome,
        # for at least one of the truly frozen trials.
        if any(x["methodology_sha256"]==version
               and utc_ms(x["trial_start_utc"])<=t<utc_ms(x["trial_end_utc"])
               for x in active):
            fresh.append({"schema":"EAR.v11_frozen_cohort_row.v1",
                "kind":"prospective_row","methodology_sha256":version,
                **row})
    fresh.sort(key=lambda x:(x["observed_utc"],x["symbol"],x["venue"]))
    trial=append_sealed(trial_path,fresh,now+len(locks)+10)
    completed=[]
    trial_end_lag=5*3600000
    for x in active:
        if x["methodology_sha256"]!=version:continue
        if now<utc_ms(x["trial_end_utc"])+trial_end_lag:continue
        selected=[raw_to_row(r) for r in trial
            if r["methodology_sha256"]==version
            and utc_ms(x["trial_start_utc"])<=utc_ms(r["observed_utc"])<
                utc_ms(x["trial_end_utc"])]
        # Pre-registered trial is fixed; evaluate exactly once, no peeking
        # at partially matured 7-day windows or retuning thresholds.
        candidates=summarize(selected)
        result=next(z for z in candidates
            if z["direction"]==x["direction"] and z["rule"]==x["rule"])
        status=("PROSPECTIVE_ASSOCIATION_REPLICATED_NOT_TRADING_ALPHA"
                if result["passes_fixed_research_gates"]
                else "NOT_REPLICATED_OR_INSUFFICIENT")
        completed.append({"schema":"EAR.v11_hypothesis_decision.v1",
            "kind":"decision","hypothesis_id":x["id"],
            "direction":x["direction"],"rule":x["rule"],
            "methodology_sha256":version,
            "trial_start_utc":x["trial_start_utc"],
            "trial_end_utc":x["trial_end_utc"],
            "evaluated_utc":asof,
            "status":status,"heldout_support":result,
            "sampled_association_not_causality":True,
            "cost_adjusted_profitability_not_proven":True,
            "paper_approved":False,"trade_authorized":False})
    decisions=append_sealed(status_path,completed,now+len(locks)+len(fresh)+100)
    # Emission events are CREATED only on a new discovery/closed trial, never
    # on ordinary 30min observations or unchanged daily reports.
    notices=([{"kind":"NEW_RESEARCH_CANDIDATE","rule":x["rule"],
               "direction":x["direction"],"hypothesis_id":x["id"],
               "n":x["exploratory_support"]["matched_case_total"],
               "q":x["exploratory_support"]["bh_fdr_q"]}
              for x in locks]+[
             {"kind":"HOLDOUT_RESULT","rule":x["rule"],
               "direction":x["direction"],"hypothesis_id":x["hypothesis_id"],
               "status":x["status"],
               "n":x["heldout_support"]["matched_case_total"],
               "q":x["heldout_support"]["bh_fdr_q"]}
              for x in completed])
    report={"schema":"EAR.v11_automatic_pattern_discovery.v1",
        "asof_utc":asof,"source_sha256":v8_records[-1]["sha256"],
        "methodology_sha256":version,
        "source_scans_in_window":research["scans_in_window"],
        "eligible_asof_samples":research["eligible_asof_cohort_count"],
        "matured_case_control_samples":research["matured_full_control_population"],
        "source_outcome_counts":research["future_label_counts"],
        "new_lock_checkpoint_utc_weekday":LOCK_WEEKDAY_UTC,
        "is_new_lock_checkpoint_now":is_freeze_checkpoint,
        "minimum_days_between_same_direction_locks":NEW_LOCK_COOLDOWN_DAYS,
        "families_tested":len(RULES),
        "familywise_tests_including_directions":len(RULES)*len(DIRECTIONS),
        "provisional_leading_associations":[x for x in exploration
              if x["passes_fixed_research_gates"]][:15],
        "frozen_hypotheses_total":len(frozen),
        "new_hypotheses_frozen":len(locks),
        "prospective_rows_total":len(trial),
        "new_prospective_rows":len(fresh),
        "decisions_total":len(decisions),
        "completed_decisions_now":completed,
        "active_trials":[{"id":x["id"],"rule":x["rule"],"direction":x["direction"],
              "trial_end_utc":x["trial_end_utc"],
              "status":("PAUSED_CODE_DRIFT" if x["methodology_sha256"]!=version
                        else "AWAITING_CLOSED_7_DAY_HOLDOUT")}
              for x in active if not any(d["hypothesis_id"]==x["id"] for d in completed)],
        "notices":notices,
        "evidence_thresholds":{"min_cases":MIN_CASES,
            "min_controls":MIN_CONTROLS,"min_distinct_case_symbols":MIN_DISTINCT_CASE_SYMBOLS,
            "min_case_days":3,"min_exposed_cases":MIN_CASES_EXPOSED,
            "max_control_false_positive_rate":MAX_FPR,
            "min_lift_vs_matched_base":MIN_LIFT,
            "fdr_q_max":FDR_ALPHA,"holdout_days":TRIAL_DAYS},
        "claims":{"association_not_causation":True,
            "not_a_profitable_strategy":True,
            "no_false_short_pnl":True,"paper_approved":False,
            "trade_authorized":False,
            "matched_controls_not_full_universe_ppv":True,
            "symbol_dependence_and_gaps_remain":True},
        "full_rule_summaries":exploration}
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--ledger",required=True)
    p.add_argument("--state",required=True)
    p.add_argument("--out",default="out/v11_discovery")
    p.add_argument("--asof")
    a=p.parse_args()
    now=a.asof or datetime.now(timezone.utc).isoformat()
    root=Path(a.state);root.mkdir(parents=True,exist_ok=True)
    report=infer_report(read(a.ledger),root,now,methodology_hash())
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    (out/"notices.json").write_text(json.dumps(report["notices"],indent=2,sort_keys=True)+"\n")
    lines=["# V11 Autonomous Pre-Impulse Discovery | RESEARCH ONLY",
       f"Observed V8 archive snapshots: {report['source_scans_in_window']}",
       f"Matured as-of case/control observations: {report['matured_case_control_samples']}",
       f"Pre-registered tests: {report['familywise_tests_including_directions']} (BH-FDR across both sides)",
       f"Exploratory candidates meeting gates: {len(report['provisional_leading_associations'])}",
       f"Frozen future-only trials: {report['frozen_hypotheses_total']}",
       f"Completed prospective trials: {report['decisions_total']}",
       "", "| Direction | Rule | Case n | Control n | FPR | Lift | FDR q |",
       "|---|---|---:|---:|---:|---:|---:|"]
    for row in report["provisional_leading_associations"]:
        lines.append("| "+" | ".join(str(row[k]) for k in
            ("direction","rule","matched_case_total","matched_nonmover_controls",
             "sampled_false_alarm_rate","sampled_lift_vs_prevalence","bh_fdr_q"))+" |")
    lines+=["","No validated common metric yet unless an independent, preregistered 7-day holdout closes and passes.",
            "Patterns are associations, NOT causes, shorts, real fills or profitable PAPER trades."]
    (out/"report.md").write_text("\n".join(lines)+"\n")
    (root/"latest.json").write_text(json.dumps({k:v for k,v in report.items()
             if k not in ("full_rule_summaries","provisional_leading_associations")},
             indent=2,sort_keys=True)+"\n")
    print("V11_DISCOVERY",len(report["provisional_leading_associations"]),
        "exploratory",len(report["notices"]),"new notices",
        report["matured_case_control_samples"],"matured cases+controls")

if __name__=="__main__":main()
