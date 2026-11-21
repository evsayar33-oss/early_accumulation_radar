"""V14 equity continuity controller for V5 -> V12 -> V13, RESEARCH ONLY.

This is an unattended orchestration and evidence-health layer, not another
unvalidated alpha signal or broker interface. Its decision logic is pure and
unit-testable. GitHub workflow delays are normal; retries are rate-limited.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKFLOWS = {
    "V5": "research_autonomous.yml",
    "V12": "v12_equity_discovery.yml",
    "V13": "v13_profitability.yml",
}
V5_SCHEDULE_HOUR = 3
V5_SCHEDULE_MINUTE = 47
V5_GRACE_HOURS = 9
CHILD_GRACE_MINUTES = 90
RETRY_COOLDOWN_HOURS = 12


def aware(s):
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("WORKFLOW_TIME_MUST_BE_AWARE")
    return d.astimezone(timezone.utc)


def v5_matured_slot(now):
    """Last Tue-Sat 03:47 UTC schedule whose allowed delay has elapsed."""
    for offset in range(9):
        day = (now - timedelta(days=offset)).date()
        if day.weekday() not in (1, 2, 3, 4, 5):
            continue
        slot = datetime(day.year, day.month, day.day,
                        V5_SCHEDULE_HOUR, V5_SCHEDULE_MINUTE,
                        tzinfo=timezone.utc)
        if now >= slot + timedelta(hours=V5_GRACE_HOURS):
            return slot
    raise ValueError("NO_RECENT_MATURED_V5_SLOT")


def pick(runs):
    """Newest successful/active/attempted runs, even when the API is unordered."""
    rows = sorted(runs, key=lambda x: x.get("created_at", ""), reverse=True)
    success = next((x for x in rows if x.get("conclusion") == "success"
                    and x.get("head_branch") == "main"), None)
    active = next((x for x in rows if x.get("status") in ("queued", "in_progress", "pending", "waiting")
                   and x.get("head_branch") == "main"), None)
    return rows, success, active


def recovery_plan(runs, now):
    """A plan never changes data and must not invent success from green CI."""
    if now.tzinfo is None:
        raise ValueError("V14_REQUIRES_UTC_AWARE_NOW")
    now = now.astimezone(timezone.utc)
    entries = {}
    for key in WORKFLOWS:
        rows, success, active = pick(runs.get(key, []))
        entries[key] = {"rows": rows, "success": success, "active": active}
    actions = []
    health = {}

    def schedule(key, source, reason, args=None, grace_minutes=CHILD_GRACE_MINUTES):
        record = entries[key]
        last_ok = record["success"]
        threshold = aware(source)
        if threshold is None:
            health[key] = "WAITING_UPSTREAM_PROOF"
            return False
        if last_ok and aware(last_ok["created_at"]) >= threshold:
            health[key] = "CURRENT"
            return True
        if record["active"]:
            health[key] = "RUN_ALREADY_ACTIVE"
            return False
        recent_attempts = [r for r in record["rows"]
                           if r.get("head_branch") == "main"
                           and (t := aware(r.get("created_at"))) is not None
                           and t >= threshold]
        latest = recent_attempts[0] if recent_attempts else None
        if latest and now - aware(latest["created_at"]) < timedelta(
                hours=RETRY_COOLDOWN_HOURS if latest.get("event") == "workflow_dispatch"
                else grace_minutes / 60):
            health[key] = "RECENT_ATTEMPT_WAITING"
            return False
        if now - threshold < timedelta(minutes=grace_minutes):
            health[key] = "SOURCE_SETTLING"
            return False
        actions.append({"workflow": WORKFLOWS[key], "key": key,
                        "reason": reason, "inputs": args or {}})
        health[key] = "RECOVERY_REQUESTED"
        return False

    slot = v5_matured_slot(now)
    v5_success = schedule("V5", slot.isoformat(), "MISSED_OR_FAILED_DAILY_V5",
                          grace_minutes=V5_GRACE_HOURS * 60)
    source_v5 = entries["V5"]["success"]
    if source_v5 and v5_success:
        # A job completing successfully cannot instantly create a completed child.
        ended = aware(source_v5.get("updated_at") or source_v5["created_at"])
        v12_ok = schedule("V12", ended.isoformat(),
                          "V5_FINISHED_BUT_V12_EVIDENCE_NOT_CURRENT",
                          {"source_run_id": str(source_v5["id"])})
    else:
        health["V12"] = "UPSTREAM_V5_WAITING"
        v12_ok = False

    source_v12 = entries["V12"]["success"]
    if source_v12 and v12_ok:
        ended = aware(source_v12.get("updated_at") or source_v12["created_at"])
        schedule("V13", ended.isoformat(),
                 "V12_FINISHED_BUT_V13_EVIDENCE_NOT_CURRENT")
    else:
        health["V13"] = "UPSTREAM_V12_WAITING"

    return {"schema": "EAR.v14_equity_continuity.v1",
            "asof_utc": now.isoformat(), "last_matured_v5_schedule_utc":slot.isoformat(),
            "health": health, "recoveries": actions,
            "research_only": True, "paper_approved": False,
            "trade_authorized": False, "price_data_generated": False}


def gh_api(endpoint):
    proc = subprocess.run(["gh", "api", endpoint], check=True,
                          capture_output=True, text=True, timeout=30)
    return json.loads(proc.stdout)


def read_latest(repo, branch, path):
    proc = subprocess.run(["git", "fetch", "--no-tags", "origin", branch],
                          capture_output=True, text=True, timeout=40)
    if proc.returncode:
        return {"state": "SOURCE_BRANCH_UNAVAILABLE", "branch": branch}
    show = subprocess.run(["git", "show", "FETCH_HEAD:" + path],
                          capture_output=True, text=True, timeout=15)
    if show.returncode:
        return {"state": "LATEST_NOT_FOUND", "branch": branch}
    try:
        obj = json.loads(show.stdout)
    except ValueError:
        return {"state": "MALFORMED_REPORT", "branch": branch}
    if not isinstance(obj, dict) or "asof_utc" not in obj:
        return {"state": "REPORT_SCHEMA_UNRECOGNIZED", "branch": branch}
    if branch.endswith("v12-equity-pattern-evidence"):
        return {k: obj.get(k) for k in (
            "market", "asof_utc", "asof_observations_total",
            "matured_primary_cohort", "forward_outcomes_total", "pending_horizons",
            "new_frozen_patterns", "completed_holdout_decisions", "active_trials",
            "source_run_id")}
    return {
        "asof_utc": obj.get("asof_utc"),
        "BIST": {k: (obj.get("markets", {}).get("BIST", {}) or {}).get(k) for k in
                 ("v12_first_seen_total", "v12_matured_outcomes", "frozen_total",
                  "completed_forward_decisions_total", "exploratory_positive_candidates")},
        "US": {k: (obj.get("markets", {}).get("US", {}) or {}).get(k) for k in
               ("v12_first_seen_total", "v12_matured_outcomes", "frozen_total",
                "completed_forward_decisions_total", "exploratory_positive_candidates")},
    }


def dispatch(repo, action):
    cmd = ["gh", "workflow", "run", action["workflow"], "--repo", repo,
           "--ref", "main"]
    for key, value in action["inputs"].items():
        cmd += ["-f", key + "=" + str(value)]
    subprocess.run(cmd, check=True, timeout=40)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="out/v14_equity_autonomy")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    repo = os.environ.get("GH_REPOSITORY", "")
    if not repo or "/" not in repo:
        raise SystemExit("GH_REPOSITORY_REQUIRED")
    now = datetime.now(timezone.utc)
    runs = {}
    for key, wf in WORKFLOWS.items():
        payload = gh_api("repos/" + repo + "/actions/workflows/" + wf +
                         "/runs?per_page=20")
        runs[key] = payload.get("workflow_runs", [])
    report = recovery_plan(runs, now)
    report["markets"] = {
        "BIST": read_latest(repo, "research/v12-equity-pattern-evidence",
                            "research_archive/v12/BIST/latest.json"),
        "US": read_latest(repo, "research/v12-equity-pattern-evidence",
                          "research_archive/v12/US/latest.json"),
        "V13": read_latest(repo, "research/v13-alpha-evidence",
                           "research_archive/v13/latest.json"),
    }
    report["dispatch_result"] = []
    for request in report["recoveries"]:
        try:
            if not args.dry_run:
                dispatch(repo, request)
            report["dispatch_result"].append({"key": request["key"],
                                               "state": "DRY_RUN" if args.dry_run else "QUEUED"})
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            report["dispatch_result"].append({"key": request["key"],
                                               "state": "FAILED", "error": str(exc)[:150]})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True,
                             default=str) + "\n", encoding="utf8")
    lines = ["# V14 independent BIST / US evidence continuity", "",
             "Status: " + json.dumps(report["health"], sort_keys=True), "",
             "Dispatch: " + json.dumps(report["dispatch_result"], sort_keys=True), "",
             "BIST V12: " + json.dumps(report["markets"]["BIST"], sort_keys=True), "",
             "US V12: " + json.dumps(report["markets"]["US"], sort_keys=True), "",
             "V13: " + json.dumps(report["markets"]["V13"], sort_keys=True), "",
             "No PAPER promotion or trade authority. GitHub schedules are best-effort."]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    print("\n".join(lines), flush=True)
    if any(x["state"] == "FAILED" for x in report["dispatch_result"]):
        raise SystemExit("V14_RECOVERY_DISPATCH_FAILED")


if __name__ == "__main__":
    main()
