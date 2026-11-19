"""V12: BIST/US separate, forward-only automatic equity-pattern discovery.

Consumes ONLY the completed, quality-screened V5 daily OHLCV artifact. These
are current-survivor, not historical PIT universes. No real fills, orders,
shorting, verified float, intraday order flow or profitable strategy claim.
No historical bar is ever enrolled as a first-seen research observation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from radar.ledger import read_verify
from research_v4.multimarket_exploratory import COST, load
from research_v4.pattern_learner import (
    append_sealed, case_control, fdr, measure,
)
from research_v4.v6_bidirectional import structural_gaps

MARKETS = ("BIST", "US")
HORIZONS = (1, 3, 5, 10)
PRIMARY_HORIZON = 5
# Uncalibrated, fixed before first prospective observation. No retroactive tuning.
EXTREME_PCT = {"BIST": 12.0, "US": 15.0}
SINGLE_RULES = (
    "volume_surge", "turnover_surge", "quiet_price",
    "range_compression", "volatility_expansion", "close_near_high",
    "close_near_low", "breakout_20d", "drawdown_base",
    "relative_strength",
)
PAIR_RULES = (
    "volume_surge + quiet_price",
    "turnover_surge + range_compression",
    "volume_surge + close_near_high",
    "turnover_surge + close_near_low",
    "quiet_price + drawdown_base",
    "breakout_20d + volume_surge",
)
RULES = SINGLE_RULES + PAIR_RULES
DIRECTIONS = ("UPSIDE_EXTREME", "DOWNSIDE_EXTREME")
MIN_CASES = 15
MIN_CONTROLS = 90
MIN_CASE_SYMBOLS = 5
MIN_CASE_DAYS = 4
MIN_EXPOSED = 5
FDR_MAX = 0.05
MAX_FPR = 0.15
MIN_LIFT = 1.6
TRIAL_DAYS = 60
TRIAL_SETTLEMENT_LAG_DAYS = 18
COOLDOWN_DAYS = 90
LOCK_WEEKDAY = 0  # Precommitted Monday UTC checkpoint
METHOD_FILES = (
    "research_v4/v12_equity_patterns.py",
    "research_v4/pattern_learner.py",
    "research_v4/multimarket_exploratory.py",
    "research_v4/v6_bidirectional.py",
    "research_v4/data_quality.py",
)


def iso(now):
    return now.astimezone(timezone.utc).isoformat()


def timestamp(s):
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("ASOF_MUST_BE_TIMEZONE_AWARE")
    return t.astimezone(timezone.utc)


def hash_method():
    h = hashlib.sha256()
    for filename in METHOD_FILES:
        h.update(filename.encode())
        h.update(Path(filename).read_bytes())
    return h.hexdigest()


def stable_id(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def read_quality(csv, report):
    quality = json.loads(Path(report).read_text(encoding="utf8"))
    sha = hashlib.sha256(Path(csv).read_bytes()).hexdigest()
    if (quality.get("schema") != "EAR.non_pit_quality_screen.v1"
            or quality.get("screened_csv_sha256") != sha
            or quality.get("trade_authorized") is not False
            or quality.get("paper_approved") is not False
            or quality.get("source_universe") != "CURRENT_SURVIVORS_NOT_PIT"):
        raise ValueError("V12_UNTRUSTED_V5_SOURCE_OR_SHA")
    return sha, quality


def observation_features(seq):
    """The current LAST CLOSED session is allowed; all baselines are prior."""
    if len(seq) < 91:
        return None
    i = len(seq) - 1
    if any(j in structural_gaps(seq) for j in range(max(1, i - 20), i + 1)):
        return None
    x = seq[i]
    prior = seq[i - 60:i]
    v = median(b["volume"] for b in prior)
    t = median(b["close"] * b["volume"] for b in prior)
    ranges = [(b["high"] - b["low"]) / b["close"] for b in prior]
    rng = median(ranges)
    if min(v, t, rng) <= 0 or x["volume"] <= 0:
        return None
    r1 = x["close"] / seq[i - 1]["close"] - 1
    r5 = x["close"] / seq[i - 5]["close"] - 1
    r20 = x["close"] / seq[i - 20]["close"] - 1
    candle_range = (x["high"] - x["low"]) / x["close"]
    location = ((x["close"] - x["low"]) / (x["high"] - x["low"])
                if x["high"] > x["low"] else 0.5)
    five_range = median((b["high"] - b["low"]) / b["close"] for b in seq[i - 4:i + 1])
    volume_ratio = x["volume"] / v
    turnover_ratio = x["close"] * x["volume"] / t
    motifs = {
        "volume_surge": volume_ratio >= 1.8,
        "turnover_surge": turnover_ratio >= 2.0,
        "quiet_price": abs(r1) <= 0.02,
        "range_compression": five_range <= 0.65 * rng,
        "volatility_expansion": candle_range >= 2.0 * rng,
        "close_near_high": location >= 0.8,
        "close_near_low": location <= 0.2,
        "breakout_20d": x["close"] > max(b["high"] for b in seq[i - 20:i]),
        "drawdown_base": r20 <= -0.10 and abs(r5) <= 0.04,
        "relative_strength": False,  # Populated from SAME-market as-of peers.
    }
    return {
        "motifs": motifs, "last_close": x["close"],
        "volume_ratio": round(volume_ratio, 6),
        "turnover_ratio": round(turnover_ratio, 6),
        "turnover_local": x["close"] * x["volume"],
        "prior_20d_return": r20,
        "prior_5d_return": r5,
        "relative_range": round(candle_range / rng, 6),
    }


def latest_observations(series, market, now, source_sha, source_run_id, version):
    """Do not backfill older bar events; dedupe by market+symbol+session."""
    today = now.date()
    prepared = []
    for (m, symbol), bars in sorted(series.items()):
        if m != market:
            continue
        closed = [b for b in bars if b["date"] < today]
        if not closed or not 0 <= (today - closed[-1]["date"]).days <= 7:
            continue
        feat = observation_features(closed)
        if feat is not None:
            prepared.append((symbol, closed[-1]["date"], feat))
    if not prepared:
        return []
    median_turn = median(z[2]["turnover_local"] for z in prepared)
    median_strength = median(z[2]["prior_20d_return"] for z in prepared)
    rows = []
    for symbol, session, z in prepared:
        motifs = dict(z["motifs"])
        motifs["relative_strength"] = (
            z["prior_20d_return"] - median_strength >= 0.05
        )
        stratum = ("HIGH" if z["turnover_local"] >= median_turn else "LOW")
        stratum += ":CALM" if abs(z["prior_5d_return"]) < 0.08 else ":MOVING"
        rows.append({
            "kind": "first_seen", "schema": "EAR.v12_equity_observation.v1",
            "id": stable_id(market, symbol, session.isoformat()),
            "market": market, "symbol": symbol,
            "signal_session": session.isoformat(),
            "observed_utc": iso(now),
            "entry_strictly_after_utc_date": today.isoformat(),
            "source_run_id": str(source_run_id),
            "source_sha256": source_sha, "methodology_sha256": version,
            "close_reference_not_executable": z["last_close"],
            "stratum": stratum, "motifs": motifs,
            "asof_features": {
                "relative_volume": z["volume_ratio"],
                "relative_turnover": z["turnover_ratio"],
                "relative_range": z["relative_range"],
                "prior_20d_return_pct": round(z["prior_20d_return"] * 100, 5),
            },
            "historical_pit_verified": False,
            "corporate_actions_verified": False,
            "trade_authorized": False, "paper_approved": False,
        })
    return rows


def evaluate_horizon(signal, bars, horizon):
    """Only new, subsequently closed sessions; no retroactive signal dates."""
    if not bars:
        return None
    after = date.fromisoformat(signal["entry_strictly_after_utc_date"])
    future = [(i, b) for i, b in enumerate(bars) if b["date"] > after]
    if len(future) < horizon:
        return None
    i, first = future[0]
    j, final = future[horizon - 1]
    if (first["date"] - after).days > 7:
        return {
            "kind": "outcome", "id": stable_id(signal["id"], horizon),
            "signal_id": signal["id"], "horizon_sessions": horizon,
            "market": signal["market"], "symbol": signal["symbol"],
            "status": "ENTRY_NOT_OBSERVED_IN_ALLOWED_WINDOW",
            "label": None,
        }
    if any(g in structural_gaps(bars) for g in range(i, j + 1)):
        return {
            "kind": "outcome", "id": stable_id(signal["id"], horizon),
            "signal_id": signal["id"], "horizon_sessions": horizon,
            "market": signal["market"], "symbol": signal["symbol"],
            "status": "SUSPECTED_CORPORATE_ACTION_OR_PRICE_GAP",
            "label": None,
        }
    entry = first["open"]
    exit_price = final["close"]
    if entry <= 0 or exit_price <= 0:
        return None
    gross = 100 * (exit_price / entry - 1)
    threshold = EXTREME_PCT[signal["market"]]
    label = ("UPSIDE_EXTREME" if gross >= threshold else
             "DOWNSIDE_EXTREME" if gross <= -threshold else
             "NO_EXTREME_MOVE") if horizon == PRIMARY_HORIZON else None
    return {
        "kind": "outcome", "schema": "EAR.v12_equity_outcome.v1",
        "id": stable_id(signal["id"], horizon),
        "signal_id": signal["id"], "market": signal["market"],
        "symbol": signal["symbol"], "horizon_sessions": horizon,
        "status": "OBSERVED_FUTURE_CLOSED_SESSIONS",
        "observed_signal_utc": signal["observed_utc"],
        "entry_session": first["date"].isoformat(),
        "last_session": final["date"].isoformat(),
        "entry_open_price_unverified_fill": entry,
        "exit_close_price_unverified_fill": exit_price,
        "gross_return_pct": round(gross, 6),
        "long_assumed_cost_pct": COST[signal["market"]],
        "long_costed_diagnostic_pct": round(gross - COST[signal["market"]], 6),
        "bearish_result_is_not_executable_short": True,
        "label": label,
        "paper_approved": False, "trade_authorized": False,
        "corporate_actions_verified": False,
    }


def research_rows(signals, outcomes, market):
    pairs = {o["signal_id"]: o for o in outcomes
             if o["horizon_sessions"] == PRIMARY_HORIZON
             and o["market"] == market
             and o["status"] == "OBSERVED_FUTURE_CLOSED_SESSIONS"}
    rows = []
    for s in signals:
        if s["market"] != market or s["id"] not in pairs:
            continue
        o = pairs[s["id"]]
        rows.append({
            "observed_utc": s["observed_utc"], "symbol": s["symbol"],
            "venue": market, "source_id": s["id"],
            "future": {"label": o["label"]},
            "features": {"stratum": s["stratum"], "motifs": s["motifs"]},
        })
    return rows


def stats(rows):
    all_rows = []
    for direction in DIRECTIONS:
        matched = case_control(rows, direction)
        for rule in RULES:
            all_rows.append(measure(matched, rule, direction))
    fdr(all_rows)
    for r in all_rows:
        r["passes_fixed_gates"] = (
            r["matched_case_total"] >= MIN_CASES
            and r["matched_nonmover_controls"] >= MIN_CONTROLS
            and r["case_symbols"] >= MIN_CASE_SYMBOLS
            and r["case_days"] >= MIN_CASE_DAYS
            and r["case_with_rule"] >= MIN_EXPOSED
            and r["sampled_false_alarm_rate"] is not None
            and r["sampled_false_alarm_rate"] <= MAX_FPR
            and r["sampled_lift_vs_prevalence"] is not None
            and r["sampled_lift_vs_prevalence"] >= MIN_LIFT
            and r["bh_fdr_q"] <= FDR_MAX
        )
    return all_rows


def execute(series, market, now, source_sha, source_run_id, state_root, version=None):
    if market not in MARKETS:
        raise ValueError("UNKNOWN_MARKET")
    if now.tzinfo is None:
        raise ValueError("NAIVE_RUN_TIME")
    now = now.astimezone(timezone.utc)
    version = version or hash_method()
    state = Path(state_root) / market
    state.mkdir(parents=True, exist_ok=True)
    paths = {n: state / (n + ".jsonl")
             for n in ("observations", "outcomes", "frozen", "decisions")}
    old = {k: read_verify(v) for k, v in paths.items()}
    stamp = int(now.timestamp() * 1000)
    if any(rows and rows[-1]["scan_utc_ms"] > stamp + 1000 for rows in old.values()):
        raise ValueError("CLOCK_BEFORE_PRIOR_EVIDENCE")

    existing = {s["id"] for s in old["observations"]}
    new_signals = [s for s in latest_observations(
        series, market, now, source_sha, source_run_id, version)
        if s["id"] not in existing]
    signals = append_sealed(paths["observations"], new_signals, stamp)

    already = {o["id"] for o in old["outcomes"]}
    future = []
    pending = Counter()
    for s in signals:
        bars = series.get((market, s["symbol"]))
        for h in HORIZONS:
            key = stable_id(s["id"], h)
            if key in already:
                continue
            out = evaluate_horizon(s, bars, h)
            if out is not None:
                out["source_sha256_at_settlement"] = source_sha
                out["methodology_sha256"] = s["methodology_sha256"]
                future.append(out)
            else:
                pending[h] += 1
    future.sort(key=lambda x: (x["signal_id"], x["horizon_sessions"]))
    outcomes = append_sealed(paths["outcomes"], future, stamp + len(new_signals) + 100)

    rows = research_rows(signals, outcomes, market)
    exploration = stats(rows)
    frozen = old["frozen"]
    decisions = old["decisions"]
    decided = {x["hypothesis_id"] for x in decisions}
    freeze_today = now.weekday() == LOCK_WEEKDAY
    locks = []
    if freeze_today:
        for direction in DIRECTIONS:
            prior = [x for x in frozen if x["direction"] == direction]
            if any(x["id"] not in decided for x in prior):
                continue  # Including code-drifted trials: never silently replace.
            if any((now - timestamp(x["created_utc"])).days < COOLDOWN_DAYS
                   for x in prior):
                continue
            already_tested = {(x["direction"], x["rule"], x["methodology_sha256"])
                              for x in prior}
            eligible = [x for x in exploration
                        if x["direction"] == direction and x["passes_fixed_gates"]
                        and (direction, x["rule"], version) not in already_tested]
            if not eligible:
                continue
            best = min(eligible, key=lambda x: (
                x["bh_fdr_q"], -x["sampled_lift_vs_prevalence"], x["rule"]))
            begin = datetime.combine(
                now.date() + timedelta(days=1), datetime.min.time(),
                tzinfo=timezone.utc)
            lock = {
                "schema": "EAR.v12_equity_frozen.v1", "kind": "freeze",
                "market": market, "direction": direction, "rule": best["rule"],
                "id": stable_id(market, direction, best["rule"], iso(now), version),
                "created_utc": iso(now), "training_ends_utc": iso(now),
                "trial_start_utc": iso(begin),
                "trial_end_utc": iso(begin + timedelta(days=TRIAL_DAYS)),
                "methodology_sha256": version, "exploratory_support": best,
                "status": "FROZEN_FUTURE_ONLY",
                "paper_approved": False, "trade_authorized": False,
            }
            locks.append(lock)
    frozen = append_sealed(paths["frozen"], locks, stamp + len(new_signals) + len(future) + 200)
    active = [x for x in frozen if x["id"] not in decided]
    new_decisions = []
    for lock in active:
        if lock["methodology_sha256"] != version:
            continue  # PAUSED_CODE_DRIFT, visible in report.
        if now < timestamp(lock["trial_end_utc"]) + timedelta(days=TRIAL_SETTLEMENT_LAG_DAYS):
            continue
        heldout = [r for r in rows
                   if timestamp(lock["trial_start_utc"]) <= timestamp(r["observed_utc"])
                   < timestamp(lock["trial_end_utc"])]
        result = next(x for x in stats(heldout)
                      if x["direction"] == lock["direction"]
                      and x["rule"] == lock["rule"])
        new_decisions.append({
            "schema": "EAR.v12_equity_decision.v1", "kind": "decision",
            "id": stable_id(lock["id"], "decision"),
            "hypothesis_id": lock["id"], "market": market,
            "direction": lock["direction"], "rule": lock["rule"],
            "methodology_sha256": version,
            "evaluated_utc": iso(now),
            "status": ("PROSPECTIVE_ASSOCIATION_REPLICATED_RESEARCH_ONLY"
                       if result["passes_fixed_gates"]
                       else "FAILED_OR_INSUFFICIENT_HOLDOUT"),
            "holdout_support": result,
            "not_profitable_alpha_proof": True,
            "paper_approved": False, "trade_authorized": False,
        })
    decisions = append_sealed(
        paths["decisions"], new_decisions,
        stamp + len(new_signals) + len(future) + len(locks) + 300)
    notices = ([{"kind": "NEW_FROZEN_PATTERN", "market": market,
                 "direction": x["direction"], "rule": x["rule"],
                 "hypothesis_id": x["id"]} for x in locks]
               + [{"kind": "FUTURE_HOLDOUT_CLOSED", "market": market,
                   "direction": x["direction"], "rule": x["rule"],
                   "status": x["status"], "hypothesis_id": x["hypothesis_id"]}
                  for x in new_decisions])
    report = {
        "schema": "EAR.v12_equity_discovery.v1",
        "market": market, "asof_utc": iso(now),
        "source_run_id": str(source_run_id), "source_csv_sha256": source_sha,
        "methodology_sha256": version,
        "asof_observations_total": len(signals),
        "new_asof_observations": len(new_signals),
        "forward_outcomes_total": len(outcomes),
        "new_forward_outcomes": len(future),
        "pending_horizons": dict(pending),
        "matured_primary_cohort": len(rows),
        "primary_label_counts": dict(Counter(r["future"]["label"] for r in rows)),
        "tests_per_checkpoint": len(RULES) * len(DIRECTIONS),
        "rules": len(RULES), "new_frozen_patterns": len(locks),
        "total_frozen_patterns": len(frozen),
        "completed_holdout_decisions": len(decisions),
        "new_completed_holdouts": len(new_decisions),
        "active_trials": [{"id": x["id"], "direction": x["direction"],
                           "rule": x["rule"],
                           "status": ("PAUSED_CODE_DRIFT"
                                      if x["methodology_sha256"] != version
                                      else "WAITING_FUTURE_HOLDOUT")}
                          for x in active],
        "exploratory_candidates": [x for x in exploration
                                  if x["passes_fixed_gates"]][:10],
        "all_rule_statistics": exploration,
        "notices": notices,
        "thresholds": {
            "primary_hold_sessions": PRIMARY_HORIZON,
            "additional_horizons": list(HORIZONS),
            "extreme_pct": EXTREME_PCT[market],
            "round_trip_cost_proxy_pct": COST[market],
            "min_cases": MIN_CASES, "min_controls": MIN_CONTROLS,
            "min_case_symbols": MIN_CASE_SYMBOLS, "min_case_days": MIN_CASE_DAYS,
            "max_control_fpr": MAX_FPR, "min_lift": MIN_LIFT,
            "fdr_q": FDR_MAX, "holdout_days": TRIAL_DAYS,
        },
        "limitations": {
            "current_survivor_universe_not_historical_pit": True,
            "corporate_actions_unverified": True,
            "unofficial_free_daily_prices_can_fail": True,
            "intraday_precursors_not_measured": True,
            "no_actual_depth_or_float": True,
            "matched_case_strata_do_not_estimate_full_universe_precision": True,
            "repeated_symbols_create_statistical_dependence": True,
            "not_causal_proof": True,
            "no_verified_trade_execution": True,
            "bearish_signals_not_executable_shorts": True,
            "paper_approved": False, "trade_authorized": False,
        },
    }
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--quality", required=True)
    p.add_argument("--state-root", required=True)
    p.add_argument("--market", choices=MARKETS, required=True)
    p.add_argument("--out", default="out/v12_equities")
    p.add_argument("--source-run-id", required=True)
    p.add_argument("--asof")
    a = p.parse_args()
    source_sha, quality = read_quality(a.csv, a.quality)
    if quality.get("coverage", {}).get(a.market, {}).get("screened", 0) < 2:
        raise ValueError("NO_VALID_EQUITY_SOURCE_COVERAGE")
    now = timestamp(a.asof) if a.asof else datetime.now(timezone.utc)
    report = execute(
        load(a.csv), a.market, now, source_sha,
        a.source_run_id, a.state_root)
    out = Path(a.out) / a.market
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf8")
    lines = [
        "# V12 " + a.market + " independent first-seen pattern discovery",
        "",
        "Observations: " + str(report["asof_observations_total"]),
        "New observations: " + str(report["new_asof_observations"]),
        "Matured five-session samples: " + str(report["matured_primary_cohort"]),
        "Forward outcomes: " + str(report["forward_outcomes_total"]),
        "Frozen rules: " + str(report["total_frozen_patterns"]),
        "Holdout decisions: " + str(report["completed_holdout_decisions"]),
        "",
        "Current-screen survivor bias and unverified corporate actions remain.",
        "Only first-seen future daily sessions count. No intraday alpha/PAPER/order claims.",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    print("V12_EQUITY", a.market, "new", report["new_asof_observations"],
          "matured", report["matured_primary_cohort"],
          "locks", report["new_frozen_patterns"],
          "closed", report["new_completed_holdouts"])


if __name__ == "__main__":
    main()
