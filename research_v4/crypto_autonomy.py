"""V15: read-only crypto discovery health + conservative GitHub recovery.

This does not generate historical prices, strategies, fills, PnL or paper
positions. It connects existing V8 real futures observations to V11
association discovery and V13 costed prospective long/short research.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from research_v4.perp_watch import read as read_perp, unpack

WORKFLOWS = {
    "V8": "perp_early_watch.yml",
    "V11": "v11_pattern_discovery.yml",
    "V13": "v13_crypto_profit.yml",
}
V8_STALE_MIN = 90
V8_RECENT_ATTEMPT_MIN = 50
V13_SETTLE_GRACE_MIN = 12
V13_RETRY_BACKOFF_MIN = 45
V11_MAX_AGE_HOURS = 36
V11_RETRY_BACKOFF_HOURS = 12


def parse_time(value):
    if value is None:
        return None
    out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if out.tzinfo is None:
        raise ValueError("CRYPTO_V15_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def main_runs(rows):
    return sorted((r for r in rows if r.get("head_branch") == "main"),
                  key=lambda r: r.get("created_at", ""), reverse=True)


def active(rows):
    return any(r.get("status") in ("queued", "pending", "in_progress", "waiting",
                                   "requested") for r in main_runs(rows))


def success(rows):
    return next((r for r in main_runs(rows)
                 if r.get("conclusion") == "success"), None)


def newest(rows):
    return next(iter(main_runs(rows)), None)


def elapsed_minutes(now, at):
    return (now - at).total_seconds() / 60


def coverage_windows(stamps):
    """Count ACTUALLY observed four-hour intervals meeting V9's sample cadence.

    A window is considered only after its result horizon has truly elapsed.
    No missing scan is interpolated and no high/low is invented.
    """
    points = sorted(stamps)
    total = viable = 0
    last = points[-1] if points else 0
    for i, start in enumerate(points):
        if start + (4*60+45)*60000 > last:
            continue
        total += 1
        later = [x for x in points[i+1:] if x <= start + (4*60+45)*60000]
        within = [x for x in later if x <= start + 4*3600000]
        end = next((x for x in later if start+4*3600000 <= x
                    <= start+(4*60+45)*60000), None)
        if end is None or len(within) < 4:
            continue
        seq = [start] + within + [end]
        if all(0 < b-a <= 90*60000 for a,b in zip(seq,seq[1:])):
            viable += 1
    return {"eligible_completed_windows":total,
            "observed_cadence_viable_windows":viable,
            "no_synthetic_intervals":True}


def decide(now, source, runs, v11, v13):
    """Deterministic, bounded recovery requests; no state/evidence mutation."""
    if now.tzinfo is None:
        raise ValueError("NOW_MUST_HAVE_TZ")
    now=now.astimezone(timezone.utc)
    src=parse_time(source["last_scan_utc"])
    if src > now + timedelta(minutes=5):
        raise ValueError("V8_FUTURE_OBSERVATION_TIME")
    age=elapsed_minutes(now, src)
    actions=[]
    health={"V8":"CURRENT" if age<=V8_STALE_MIN else "STALE_SOURCE",
            "V11":"UNKNOWN","V13":"UNKNOWN"}

    def queue(key,reason):
        actions.append({"key":key,"workflow":WORKFLOWS[key],
                        "reason":reason,"inputs":{}})
        health[key]="RECOVERY_REQUESTED"

    if age>V8_STALE_MIN:
        last=newest(runs.get("V8",[]))
        if active(runs.get("V8",[])):
            health["V8"]="PRODUCER_ACTIVE"
        elif last and elapsed_minutes(now,parse_time(last["created_at"])) < V8_RECENT_ATTEMPT_MIN:
            health["V8"]="RECENT_PRODUCER_ATTEMPT_WAIT"
        else:
            queue("V8","V8_ARCHIVE_STALE_NO_RECENT_ACTIVE_PRODUCER")

    latest_v11=success(runs.get("V11",[]))
    if latest_v11 and elapsed_minutes(now,parse_time(
            latest_v11.get("updated_at") or latest_v11["created_at"])) <= V11_MAX_AGE_HOURS*60:
        health["V11"]="CURRENT_RESEARCH_WORKFLOW"
    elif active(runs.get("V11",[])):
        health["V11"]="RESEARCH_ACTIVE"
    elif newest(runs.get("V11",[])) and elapsed_minutes(
            now,parse_time(newest(runs["V11"])["created_at"])) < V11_RETRY_BACKOFF_HOURS*60:
        health["V11"]="RECENT_RESEARCH_ATTEMPT_WAIT"
    elif age<=V8_STALE_MIN:
        queue("V11","DAILY_PATTERN_RESEARCH_NOT_COMPLETED")
    else:
        health["V11"]="WAITING_V8_RECOVERY"

    consumed=(v13.get("source_v8_last_sha256")==source["sha256"]
              and v13.get("source_status")=="FRESH_V8_RESEARCH_OBSERVATIONS")
    if consumed:
        health["V13"]="CONSUMED_CURRENT_V8_SOURCE"
    elif active(runs.get("V13",[])):
        health["V13"]="RESEARCH_ACTIVE"
    elif age>V8_STALE_MIN:
        health["V13"]="WAITING_V8_RECOVERY"
    elif elapsed_minutes(now,src)<V13_SETTLE_GRACE_MIN:
        health["V13"]="WAITING_V8_PERSISTENCE"
    else:
        last=newest(runs.get("V13",[]))
        if last and elapsed_minutes(now,parse_time(last["created_at"]))<V13_RETRY_BACKOFF_MIN:
            health["V13"]="RECENT_COSTED_RESEARCH_ATTEMPT_WAIT"
        else:
            queue("V13","FRESH_V8_SOURCE_NOT_YET_CONSUMED_FOR_COSTED_RESEARCH")

    # No missing sample or negative hypothesis is allowed to auto-rewrite rules.
    return {"schema":"EAR.v15_crypto_evidence_autonomy.v1",
            "asof_utc":now.isoformat(),
            "source_age_minutes":round(age,3),
            "health":health,"recoveries":actions,
            "v11_matured_case_control_samples":v11.get("matured_case_control_samples"),
            "v11_frozen_hypotheses":v11.get("frozen_hypotheses_total"),
            "v13_first_seen_asof_observations":v13.get("asof_observations"),
            "v13_modeled_outcomes":v13.get("modeled_outcomes"),
            "v13_frozen_trials":v13.get("frozen_trials"),
            "v13_source_status":v13.get("source_status"),
            "no_live_or_paper_promotion":True,"trade_authorized":False}


def git_json(branch,path):
    subprocess.run(["git","fetch","--no-tags","origin",branch],check=True,
                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=50)
    raw=subprocess.run(["git","show","FETCH_HEAD:"+path],check=True,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                       text=True,timeout=35)
    return json.loads(raw.stdout)


def latest_report(branch,path):
    obj=git_json(branch,path)
    if not isinstance(obj,dict):
        raise ValueError("NONOBJECT_EVIDENCE_REPORT")
    return obj


def verified_v8():
    branch="research/v8-perp-forward"
    subprocess.run(["git","fetch","--no-tags","origin",branch],check=True,
                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=50)
    blob=subprocess.run(["git","show",
                        "FETCH_HEAD:observations/perp/snapshots.jsonl"],
                        check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                        timeout=50)
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"real_v8.jsonl"
        p.write_bytes(blob.stdout)
        rows=read_perp(p)
    if not rows:
        raise ValueError("EMPTY_VERIFIED_V8_ARCHIVE")
    latest=rows[-1]
    stamps=[r["scan_utc_ms"] for r in rows]
    if stamps != sorted(set(stamps)):
        raise ValueError("V8_DUPLICATE_OR_REORDERED_SCAN_TIME")
    last=unpack(latest["packed_assets"])
    multi=sum(len(venues)>=2 for venues in last.values())
    oi=sum(isinstance(v.get("oi_contracts"),(float,int))
           for venues in last.values() for v in venues.values())
    return {
        "last_scan_utc":datetime.fromtimestamp(stamps[-1]/1000,
                                               timezone.utc).isoformat(),
        "sha256":latest["sha256"],
        "total_verified_scans":len(rows),
        "latest_contracts":len(last),
        "latest_multi_venue_contracts":multi,
        "latest_observed_oi_venue_records":oi,
        "latest_provider_counts":latest.get("venue_counts",{}),
        "latest_provider_errors":list((latest.get("source_unavailable") or {}).keys()),
        "cadence":coverage_windows(stamps[-180:]),
        "full_source_evidence_verified":True,
        "price_observations_not_fills":True,
    }


def gh_runs(repo,wf):
    obj=json.loads(subprocess.run(
        ["gh","api",f"repos/{repo}/actions/workflows/{wf}/runs?per_page=30"],
        check=True,capture_output=True,text=True,timeout=40).stdout)
    if not isinstance(obj.get("workflow_runs"),list):
        raise ValueError("INVALID_ACTIONS_RUN_LIST")
    return obj["workflow_runs"]


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="out/v15_crypto_autonomy")
    p.add_argument("--dry-run",action="store_true")
    args=p.parse_args()
    repo=os.environ.get("GH_REPOSITORY")
    if not repo or "/" not in repo:
        raise ValueError("GH_REPOSITORY_REQUIRED")
    source=verified_v8()  # fail closed on hash/source errors
    v11=latest_report("research/v11-pattern-evidence",
                      "research_archive/v11/latest.json")
    v13=latest_report("research/v13-crypto-alpha-evidence",
                      "research_archive/v13_crypto/latest.json")
    runs={name:gh_runs(repo,wf) for name,wf in WORKFLOWS.items()}
    result=decide(datetime.now(timezone.utc),source,runs,v11,v13)
    result["source"]=source
    result["sampling_state"]=(
        "NO_COMPLETE_4H_PREIMPULSE_WINDOWS_YET" if
        source["cadence"]["observed_cadence_viable_windows"]==0
        else "OBSERVED_4H_WINDOWS_AVAILABLE_CHECK_MATURED_CASES"
    )
    result["data_provenance"]={
        "markets":"USDT_LINEAR_PERPETUAL_ONLY",
        "no_hindsight_signal_backfill":True,
        "no_threshold_relaxation":True,
        "no_lookahead_fill_claims":True,
        "not_full_market_execution":True,
    }
    result["dispatch"]=[]
    for action in result["recoveries"]:
        cmd=["gh","workflow","run",action["workflow"],
             "--repo",repo,"--ref","main"]
        try:
            if not args.dry_run:
                subprocess.run(cmd,check=True,capture_output=True,
                               text=True,timeout=35)
            result["dispatch"].append({"key":action["key"],
                                      "status":"DRY_RUN" if args.dry_run else "QUEUED"})
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
            result["dispatch"].append({"key":action["key"],"status":"FAILED",
                                      "error":type(exc).__name__})
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(result,sort_keys=True,indent=2)
                                  +"\n",encoding="utf8")
    lines=["# V15 Crypto Autonomous Discovery and Evidence Continuity","",
           "Evidence source: real, verified V8 snapshots; no orders.",
           "Health: "+json.dumps(result["health"],sort_keys=True),
           "Coverage: "+json.dumps(source["cadence"],sort_keys=True),
           "V8: "+str(source["latest_contracts"])+" contracts, "+
           str(source["latest_multi_venue_contracts"])+" two-or-more venues",
           "V11: "+str(result["v11_matured_case_control_samples"])+" matured samples",
           "V13: "+str(result["v13_first_seen_asof_observations"])+" first-seen signals, "+
           str(result["v13_modeled_outcomes"])+" modeled outcomes",
           "Sampling: "+result["sampling_state"],
           "Recovery: "+json.dumps(result["dispatch"],sort_keys=True),
           "No invented signals, shortened holdouts, or PAPER/live trades."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    print("\n".join(lines),flush=True)
    if any(x["status"]=="FAILED" for x in result["dispatch"]):
        raise SystemExit("V15_CRYPTO_WORKFLOW_RECOVERY_FAILED")


if __name__=="__main__":
    main()
