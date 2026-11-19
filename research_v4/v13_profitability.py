"""V13: prospective cost-adjusted strategy discovery, not a profitability guarantee.

Consumes only SHA-valid V12 first-seen observations and subsequently matured
outcomes. Searches 16 predeclared entry patterns x 4 hold horizons separately
for BIST and US. Never mines historical daily bars for retrospective fills.
Selection is TRAIN-ONLY; forward holdout begins AFTER rule/horizon freeze.
No actual broker fills, PIT universe, issuer-clustered proof or order routing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev

from radar.ledger import read_verify
from research_v4.pattern_learner import append_sealed
from research_v4.v12_equity_patterns import (
    MARKETS, HORIZONS, RULES, hash_method as v12_method_hash,
    stable_id, timestamp,
)

MAX_SLOTS = 5
STRESS_EXTRA_COST_PCT = 0.30
MIN_TRAIN_EXECUTIONS = 30
MIN_CONTROL_MATCHES = 60
MIN_SYMBOLS = 8
MIN_SIGNAL_DAYS = 12
MIN_TIME_BLOCKS = 8
MIN_NET_MEAN_PCT = 0.35
MIN_EXCESS_MEAN_PCT = 0.35
MIN_WIN_RATE = 0.48
MIN_PROFIT_FACTOR = 1.25
MAX_REALIZED_DRAWDOWN_PROXY_PCT = 20.
BLOCK_DAYS = 10
# 3.35 is a conservative approximate one-sided multiple-comparison bound
# for 64 variants; not an issuer-clustered, exact FWER guarantee.
MULTIPLE_SEARCH_Z = 3.35
TRIAL_DAYS = 90
TRIAL_GRACE_DAYS = 25
RELOCK_COOLDOWN_DAYS = 120
CHECKPOINT_WEEKDAY = 0
METHOD_FILES = ("research_v4/v13_profitability.py",
                "research_v4/v12_equity_patterns.py")


def method_hash():
    h = hashlib.sha256()
    for filename in METHOD_FILES:
        h.update(filename.encode())
        h.update(Path(filename).read_bytes())
    return h.hexdigest()


def utc_now():
    return datetime.now(timezone.utc)


def iso(t):
    return t.astimezone(timezone.utc).isoformat()


def assert_source(source_root, market, now):
    if market not in MARKETS:
        raise ValueError("UNKNOWN_MARKET")
    root = Path(source_root) / market
    result = {name: read_verify(root / (name + ".jsonl"))
              for name in ("observations", "outcomes", "frozen", "decisions")}
    if not result["observations"]:
        return result
    seen = set()
    for s in result["observations"]:
        if (s.get("schema") != "EAR.v12_equity_observation.v1"
                or s.get("kind") != "first_seen"
                or s.get("market") != market
                or s.get("id") in seen
                or s.get("trade_authorized") is not False
                or s.get("paper_approved") is not False
                or timestamp(s["observed_utc"]) > now):
            raise ValueError("V12_INVALID_FIRST_SEEN_RECORD")
        seen.add(s["id"])
    outcome_ids = set()
    for o in result["outcomes"]:
        if (o.get("signal_id") not in seen or o.get("market") != market
                or o.get("horizon_sessions") not in HORIZONS
                or o.get("id") in outcome_ids
                or (o.get("status") == "OBSERVED_FUTURE_CLOSED_SESSIONS"
                    and o.get("trade_authorized") is not False)
                or (o.get("status") != "OBSERVED_FUTURE_CLOSED_SESSIONS"
                    and o.get("trade_authorized") not in (None, False))
                or o.get("status") not in (
                    "OBSERVED_FUTURE_CLOSED_SESSIONS",
                    "SUSPECTED_CORPORATE_ACTION_OR_PRICE_GAP",
                    "ENTRY_NOT_OBSERVED_IN_ALLOWED_WINDOW")):
            raise ValueError("V12_UNTRUSTED_OR_DUPLICATE_OUTCOME")
        outcome_ids.add(o["id"])
    return result


def rule_on(motifs, rule):
    values = [motifs.get(part) for part in rule.split(" + ")]
    return all(x is True for x in values) if all(
        isinstance(x, bool) for x in values) else None


def mature_rows(source, market, horizon, now, v12_version):
    """No rejected/missing outcome may be silently treated as a zero return."""
    signals = source["observations"]
    outcomes = {o["signal_id"]: o for o in source["outcomes"]
                if o["horizon_sessions"] == horizon
                and o["status"] == "OBSERVED_FUTURE_CLOSED_SESSIONS"}
    records = []
    for s in signals:
        o = outcomes.get(s["id"])
        if o is None or s["methodology_sha256"] != v12_version:
            continue
        if (o.get("methodology_sha256") != v12_version
                or o.get("symbol") != s["symbol"]
                or o.get("market") != market):
            raise ValueError("OUTCOME_SOURCE_VERSION_OR_IDENTITY_CHANGED")
        t = timestamp(s["observed_utc"])
        entry = date.fromisoformat(o["entry_session"])
        exited = date.fromisoformat(o["last_session"])
        if (entry <= t.date() or exited < entry or exited > now.date()
                or o["entry_open_price_unverified_fill"] <= 0
                or o["exit_close_price_unverified_fill"] <= 0
                or not isinstance(o.get("gross_return_pct"), (int, float))
                or not math.isfinite(o["gross_return_pct"])):
            raise ValueError("FUTURE_OUTCOME_NOT_MATURE_OR_INVALID")
        # Independently recalculate PnL, do not trust a bare outcome return.
        calc = 100 * (o["exit_close_price_unverified_fill"] /
                      o["entry_open_price_unverified_fill"] - 1)
        if abs(calc - o["gross_return_pct"]) > 0.00002:
            raise ValueError("V12_OUTCOME_PNL_MISMATCH")
        cost = s["round_trip_cost_proxy_pct"]
        if not (isinstance(cost, (int, float)) and 0 < cost < 20
                and abs(calc - cost - o["long_costed_diagnostic_pct"]) < 0.00005):
            raise ValueError("V12_COST_PROVENANCE_MISMATCH")
        records.append({
            "id": s["id"], "market": market, "symbol": s["symbol"],
            "observed_utc": s["observed_utc"], "stratum": s["stratum"],
            "motifs": s["motifs"], "entry_session": entry.isoformat(),
            "exit_session": exited.isoformat(), "horizon": horizon,
            "net_pct": float(o["long_costed_diagnostic_pct"]),
            "stressed_net_pct": float(o["long_costed_diagnostic_pct"]) -
                                STRESS_EXTRA_COST_PCT,
        })
    return sorted(records, key=lambda x: (
        x["observed_utc"], x["symbol"], x["id"]))


def one_rule(rows, rule, *, since=None, before=None):
    """Match same scan and liquidity/momentum strata, before return inspection."""
    eligible = [x for x in rows
                if (since is None or timestamp(x["observed_utc"]) >= since)
                and (before is None or timestamp(x["observed_utc"]) < before)]
    cohorts = defaultdict(list)
    for x in eligible:
        if rule_on(x["motifs"], rule) is not None:
            cohorts[(x["observed_utc"], x["stratum"])].append(x)
    matched_ids = set()
    controls = []
    for group in cohorts.values():
        active = [x for x in group if rule_on(x["motifs"], rule)]
        inactive = [x for x in group if rule_on(x["motifs"], rule) is False]
        if active and inactive:
            matched_ids.update(x["id"] for x in active)
            controls.extend(inactive)
    active = [x for x in eligible
              if x["id"] in matched_ids and rule_on(x["motifs"], rule)]
    return active, controls


def chronological_fills(candidates):
    """Deterministic signal-time allocation, never sorted by future PnL."""
    by_day = defaultdict(list)
    for row in candidates:
        by_day[row["observed_utc"][:10]].append(row)
    selected = []
    last_exit = {}
    skipped = Counter()
    for day in sorted(by_day):
        # Stable hash tie-break avoids selecting winners using future returns.
        bucket = sorted(by_day[day],
                        key=lambda r: stable_id(r["symbol"], r["observed_utc"]))
        for x in bucket:
            entry = x["entry_session"]
            exited = x["exit_session"]
            # Limit simultaneous hypothetical positions; no intraday execution.
            concurrent = sum(
                r["entry_session"] <= entry <= r["exit_session"]
                for r in selected)
            if concurrent >= MAX_SLOTS:
                skipped["portfolio_slots"] += 1
                continue
            if last_exit.get(x["symbol"], "") >= entry:
                skipped["same_symbol_overlap"] += 1
                continue
            selected.append(x)
            last_exit[x["symbol"]] = exited
    return selected, dict(skipped)


def realized_drawdown_proxy(fills):
    """Closed-result proxy only. NOT full daily marked NAV or max live DD."""
    cumulative = peak = 0.
    worst = 0.
    for x in sorted(fills, key=lambda v:(v["exit_session"], v["id"])):
        cumulative += x["net_pct"] / MAX_SLOTS
        peak = max(peak, cumulative)
        worst = min(worst, cumulative - peak)
    return round(-worst, 6)


def summarize(rows, rule, horizon, *, since=None, before=None):
    case, controls = one_rule(rows, rule, since=since, before=before)
    fills, skipped = chronological_fills(case)
    n = len(fills)
    profits = [r["net_pct"] for r in fills]
    stressed = [r["stressed_net_pct"] for r in fills]
    ctrl = [x["net_pct"] for x in controls]
    gross_pos = sum(max(v, 0.) for v in profits)
    gross_neg = sum(-min(v, 0.) for v in profits)
    pf = (gross_pos / gross_neg) if gross_neg > 0 else None
    # Ten-calendar-day exit blocks reduce, but do not remove, within-issuer
    # and cross-stock dependence. All 64 rule x horizon tests are screened.
    blocks = defaultdict(list)
    for fill in fills:
        key = date.fromisoformat(fill["exit_session"]).toordinal() // BLOCK_DAYS
        blocks[key].append(fill["stressed_net_pct"])
    independentish = [mean(v) for _, v in sorted(blocks.items())]
    block_lower = None
    if len(independentish) >= MIN_TIME_BLOCKS:
        block_lower = (mean(independentish) -
                       MULTIPLE_SEARCH_Z * stdev(independentish) /
                       math.sqrt(len(independentish)))
    net_mean = mean(profits) if profits else None
    stress_mean = mean(stressed) if stressed else None
    benchmark = mean(ctrl) if ctrl else None
    excess = net_mean - benchmark if net_mean is not None and benchmark is not None else None
    win_rate = sum(v > 0 for v in profits) / n if n else None
    days = {x["observed_utc"][:10] for x in fills}
    symbols = {x["symbol"] for x in fills}
    max_dd_proxy = realized_drawdown_proxy(fills)
    passes = (
        n >= MIN_TRAIN_EXECUTIONS and len(ctrl) >= MIN_CONTROL_MATCHES
        and len(days) >= MIN_SIGNAL_DAYS and len(symbols) >= MIN_SYMBOLS
        and len(blocks) >= MIN_TIME_BLOCKS and pf is not None
        and pf >= MIN_PROFIT_FACTOR and net_mean > MIN_NET_MEAN_PCT
        and stress_mean > 0 and excess > MIN_EXCESS_MEAN_PCT
        and win_rate >= MIN_WIN_RATE and block_lower is not None
        and block_lower > 0 and max_dd_proxy <= MAX_REALIZED_DRAWDOWN_PROXY_PCT
    )
    return {
        "rule": rule, "horizon_sessions": horizon, "matched_case_events": len(case),
        "matched_control_events": len(ctrl), "hypothetical_closed_trades": n,
        "distinct_symbols": len(symbols), "signal_days": len(days),
        "ten_day_exit_blocks": len(blocks), "candidate_skip_counts": skipped,
        "net_mean_pct": round(net_mean, 6) if net_mean is not None else None,
        "stressed_net_mean_pct": round(stress_mean, 6) if stress_mean is not None else None,
        "matched_control_net_mean_pct": round(benchmark, 6) if benchmark is not None else None,
        "excess_vs_matched_control_pct": round(excess, 6) if excess is not None else None,
        "closed_win_rate": round(win_rate, 6) if win_rate is not None else None,
        "closed_profit_factor": round(pf, 6) if pf is not None else None,
        "worst_realized_pnl_drawdown_proxy_pct": max_dd_proxy,
        "stressed_ten_day_block_lower_bound_pct": (round(block_lower, 6)
            if block_lower is not None else None),
        "passes_fixed_research_gates": passes,
        "realized_only_not_daily_nav": True,
        "matched_controls_not_venue_executable": True,
    }


def run(source_root, state_root, now, v13_version=None, source_version=None):
    if now.tzinfo is None:
        raise ValueError("NAIVE_ASOF")
    now = now.astimezone(timezone.utc)
    version = v13_version or method_hash()
    source_version = source_version or v12_method_hash()
    state_root = Path(state_root)
    report = {
        "schema": "EAR.v13_costed_profitability_discovery.v1",
        "asof_utc": iso(now), "methodology_sha256": version,
        "source_v12_methodology_sha256": source_version,
        "research_only": True, "paper_approved": False,
        "trade_authorized": False, "profitable_strategy_proven": False,
        "markets": {},
    }
    for market in MARKETS:
        archive = assert_source(source_root, market, now)
        dest = state_root / market
        dest.mkdir(parents=True, exist_ok=True)
        frozen_file = dest / "frozen.jsonl"
        decision_file = dest / "decisions.jsonl"
        frozen = read_verify(frozen_file)
        decisions = read_verify(decision_file)
        done = {x["hypothesis_id"] for x in decisions}
        by_horizon = {h:mature_rows(archive, market, h, now, source_version)
                      for h in HORIZONS}
        trials = [summarize(by_horizon[h], rule, h)
                  for h in HORIZONS for rule in RULES]
        winners = [x for x in trials if x["passes_fixed_research_gates"]]
        winners.sort(key=lambda x: (
            -x["stressed_ten_day_block_lower_bound_pct"],
            -x["excess_vs_matched_control_pct"], x["rule"], x["horizon_sessions"]))
        active = [x for x in frozen if x["id"] not in done]
        locks = []
        if (now.weekday() == CHECKPOINT_WEEKDAY and winners
                and not active
                and all((now - timestamp(f["created_utc"])).days
                        >= RELOCK_COOLDOWN_DAYS for f in frozen)):
            prior = {(x["rule"], x["horizon_sessions"], x["methodology_sha256"])
                     for x in frozen}
            selected = next((x for x in winners
                             if (x["rule"], x["horizon_sessions"], version)
                             not in prior), None)
            if selected:
                start = datetime.combine(now.date() + timedelta(days=1),
                                         datetime.min.time(), tzinfo=timezone.utc)
                lock = {
                    "schema": "EAR.v13_frozen_costed_strategy.v1", "kind": "freeze",
                    "id": stable_id(market, selected["rule"], selected["horizon_sessions"],
                                    iso(now), version),
                    "market": market, "rule": selected["rule"],
                    "horizon_sessions": selected["horizon_sessions"],
                    "created_utc": iso(now), "training_end_utc": iso(now),
                    "trial_start_utc": iso(start),
                    "trial_end_utc": iso(start + timedelta(days=TRIAL_DAYS)),
                    "methodology_sha256": version,
                    "v12_methodology_sha256": source_version,
                    "selection_evidence": selected,
                    "paper_approved": False, "trade_authorized": False,
                }
                locks = [lock]
        stamp = int(now.timestamp() * 1000)
        frozen = append_sealed(frozen_file, locks, stamp)
        new_decisions = []
        for trial in frozen:
            if trial["id"] in done:
                continue
            if (trial["methodology_sha256"] != version
                    or trial["v12_methodology_sha256"] != source_version):
                continue  # Incompatible trial is PAUSED, not silently rewritten.
            if now < timestamp(trial["trial_end_utc"]) + timedelta(
                    days=TRIAL_GRACE_DAYS):
                continue
            h = trial["horizon_sessions"]
            hold = summarize(
                by_horizon[h], trial["rule"], h,
                since=timestamp(trial["trial_start_utc"]),
                before=timestamp(trial["trial_end_utc"]))
            new_decisions.append({
                "schema": "EAR.v13_future_profitability_decision.v1",
                "kind": "decision", "id": stable_id(trial["id"], "decision"),
                "hypothesis_id": trial["id"], "market": market,
                "rule": trial["rule"], "horizon_sessions": h,
                "trial_start_utc": trial["trial_start_utc"],
                "trial_end_utc": trial["trial_end_utc"],
                "evaluated_utc": iso(now), "methodology_sha256": version,
                "status": ("POSITIVE_NET_FORWARD_RESEARCH_ONLY"
                    if hold["passes_fixed_research_gates"]
                    else "FAILED_OR_INSUFFICIENT_FORWARD_EVIDENCE"),
                "future_costed_metrics": hold,
                "requires_broker_execution_and_pit_verification": True,
                "profitable_strategy_proven": False,
                "trade_authorized": False, "paper_approved": False,
            })
        decisions = append_sealed(decision_file, new_decisions,
                                  stamp + len(locks) + 50)
        report["markets"][market] = {
            "v12_first_seen_total": len(archive["observations"]),
            "v12_matured_outcomes": {str(h):len(by_horizon[h]) for h in HORIZONS},
            "rule_horizon_trials": len(trials),
            "exploratory_positive_candidates": winners[:10],
            "all_trial_statistics": trials,
            "frozen_total": len(frozen),
            "new_frozen": locks,
            "completed_forward_decisions_total": len(decisions),
            "new_forward_decisions": new_decisions,
            "active_trials": [{
                "id": x["id"], "rule": x["rule"],
                "horizon_sessions": x["horizon_sessions"],
                "status": ("PAUSED_VERSION_DRIFT" if
                           x["methodology_sha256"] != version or
                           x["v12_methodology_sha256"] != source_version
                           else "FUTURE_VALIDATION_PENDING")}
                for x in frozen if x["id"] not in
                {y["hypothesis_id"] for y in decisions}],
        }
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True,
                   help="SHA-verified V12 research_archive/v12 root")
    p.add_argument("--state", required=True,
                   help="Independent V13 research evidence root")
    p.add_argument("--out", default="out/v13_alpha")
    a = p.parse_args()
    report = run(a.source, a.state, utc_now())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    lines = ["# V13 cost-adjusted automatic strategy research",
             "", "BIST and US: 16 patterns x 4 horizons = 64 candidate strategies each.",
             "No retrospectively created first-seen signals and no actual executable trades."]
    for market in MARKETS:
        row = report["markets"][market]
        lines += ["", "## " + market,
                  "V12 observed: " + str(row["v12_first_seen_total"]),
                  "Matured outcomes per horizon: " +
                  json.dumps(row["v12_matured_outcomes"], sort_keys=True),
                  "Exploratory cost-positive candidates: " +
                  str(len(row["exploratory_positive_candidates"])),
                  "New independent future trials: " + str(len(row["new_frozen"])),
                  "New completed future tests: " +
                  str(len(row["new_forward_decisions"]))]
    lines += ["", "Costs, matched excess return, trade overlap, multiple",
              "testing search penalties and conservative risk diagnostics screened.",
              "PIT universe and executable slippage remain unverified; not a",
              "live profitability guarantee or trading authorization."]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print("V13_PROFITABILITY_DISCOVERY", " ".join(
        f"{m}:{len(report['markets'][m]['exploratory_positive_candidates'])}"
        for m in MARKETS), "research-only")


if __name__ == "__main__":
    main()
