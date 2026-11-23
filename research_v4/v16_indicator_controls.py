"""V16: isolated, exploratory as-of indicator/control study on genuine V8 evidence.

This is NOT a CVD, liquidation, depth, or proven trading signal collector.
All metrics are computed from V8 snapshots already observed at t or earlier.
The V9 future label is attached only after the as-of metrics are complete.
Existing frozen V11/V12/V13 hypotheses and evidence are read-only.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from research_v4.perp_watch import read, unpack
from research_v4.preimpulse_study import study

SCHEMA = "EAR.v16_asof_indicator_controls.v1"
# Hypothesis families fixed BEFORE prospective validation; no threshold search.
RULES = (
    "funding_sign_flip",
    "spread_compression_with_activity",
    "mark_basis_normalization",
)
DIRECTIONS = ("UPSIDE_EXTREME", "DOWNSIDE_EXTREME")
MIN_CASES = 30
MIN_CONTROLS = 200


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def candidate_flags(current, previous):
    """Exactly one venue, approximately 1h apart; missing is never False."""
    if current is None or previous is None:
        return {rule: None for rule in RULES}
    p, p0 = finite(current.get("p")), finite(previous.get("p"))
    if p is None or p0 is None or p <= 0 or p0 <= 0:
        return {rule: None for rule in RULES}
    quiet = abs(100 * (p / p0 - 1)) <= 1.0

    f, f0 = finite(current.get("funding_rate_pct")), finite(previous.get("funding_rate_pct"))
    # Both strictly signed and non-tiny; this is indicative funding only.
    funding = (f * f0 < 0 and min(abs(f), abs(f0)) >= 0.002 and quiet
               if f is not None and f0 is not None else None)

    s, s0 = finite(current.get("spread_bps")), finite(previous.get("spread_bps"))
    q, q0 = finite(current.get("q")), finite(previous.get("q"))
    spread = (s >= 0 and 0 < s0 and s <= 0.7 * s0 and q >= 1.2 * q0
              and quiet if all(v is not None for v in (s, s0, q, q0)) and q0 > 0
              else None)

    b, b0 = finite(current.get("mark_basis_bps")), finite(previous.get("mark_basis_bps"))
    # Mark vs last, NOT spot-vs-perp basis and not executable arbitrage.
    basis = (abs(b0) >= 20 and abs(b) <= 0.5 * abs(b0) and quiet
             if b is not None and b0 is not None else None)
    return dict(zip(RULES, (funding, spread, basis)))


def asof_features(history, observed_ms, venue):
    """Reject venue mixing, missing prior snapshot and post-event data."""
    before = [(ts, data[venue]) for ts, data in history
              if ts <= observed_ms and venue in data]
    current = next((data for ts, data in reversed(before) if ts == observed_ms), None)
    # A real sample 35..85 min before t, never an interpolated candle.
    candidates = [(abs((observed_ms - ts) / 60000 - 60), data)
                  for ts, data in before
                  if 35 * 60000 <= observed_ms - ts <= 85 * 60000]
    earlier = min(candidates, key=lambda x: x[0])[1] if candidates else None
    return candidate_flags(current, earlier)


def matched_stats(rows, direction, rule):
    by_stratum = defaultdict(list)
    for row in rows:
        label = row["future"]["label"]
        if label in (direction, "NO_EXTREME_MOVE"):
            by_stratum[(row["observed_utc"], row["features"]["stratum"])].append(row)
    cases, controls = [], []
    for cohort in by_stratum.values():
        yes = [x for x in cohort if x["future"]["label"] == direction]
        no = [x for x in cohort if x["future"]["label"] == "NO_EXTREME_MOVE"]
        if yes and no:
            cases.extend(yes)
            controls.extend(no)
    c = [x for x in cases if x["v16"][rule] is not None]
    n = [x for x in controls if x["v16"][rule] is not None]
    positives = sum(x["v16"][rule] is True for x in c)
    false_alarms = sum(x["v16"][rule] is True for x in n)
    return {
        "direction": direction, "rule": rule,
        "matched_cases_available": len(c),
        "matched_nonmover_controls_available": len(n),
        "exposed_cases": positives, "exposed_controls": false_alarms,
        "case_exposure_rate": round(positives / len(c), 6) if c else None,
        "control_exposure_rate": round(false_alarms / len(n), 6) if n else None,
        # Even a high observed lift is NOT accepted without FDR/forward holdout.
        "verdict": ("INSUFFICIENT_EVIDENCE" if len(c) < MIN_CASES or len(n) < MIN_CONTROLS
                    else "EXPLORATORY_ONLY_NEEDS_MULTIPLICITY_AND_FUTURE_HOLDOUT"),
        "validated_alpha": False,
    }


def analyze(records):
    if not records:
        raise ValueError("NO_SHA_VERIFIED_V8_OBSERVATIONS")
    # read() has already verified hash continuity, UTC clock and schema.
    snapshots = [(row["scan_utc_ms"], unpack(row["packed_assets"])) for row in records]
    histories = defaultdict(list)
    for ts, instruments in snapshots:
        for symbol, venues in instruments.items():
            histories[symbol].append((ts, venues))
    v9 = study(records, include_rows=True)
    matured = v9.pop("matured_cohort_rows")
    for row in matured:
        t = int(datetime.fromisoformat(row["observed_utc"]).timestamp() * 1000)
        row["v16"] = asof_features(histories[row["symbol"]], t, row["venue"])

    ts, latest = snapshots[-1]
    available = Counter()
    observed = 0
    for symbol, venues in latest.items():
        for venue in sorted(venues):
            flags = asof_features(histories[symbol], ts, venue)
            observed += 1
            for name, flag in flags.items():
                if flag is not None:
                    available[name] += 1

    results = [matched_stats(matured, direction, rule)
               for direction in DIRECTIONS for rule in RULES]
    return {
        "schema": SCHEMA,
        "source_last_sha256": records[-1]["sha256"],
        "source_scan_utc_ms": ts,
        "source_v8_scans": len(records),
        "latest_symbol_venue_observations": observed,
        "latest_metric_availability": {rule: available[rule] for rule in RULES},
        "v9_asof_cohort_count": v9["eligible_asof_cohort_count"],
        "v9_matured_nonexecuted_outcomes": len(matured),
        "v9_future_status_counts": v9["future_label_counts"],
        "predeclared_research_tests": len(results),
        "matched_case_control_results": results,
        "methodology": {
            "price_motion_gate": "V9 PRE-2H <=3%, ABS 24H <=15%",
            "historical_alignment": "same symbol, same venue, 35..85m earlier actual observation",
            "controls": "same V9 UTC scan and asof liquidity/return stratum",
            "no_intra_bar_fills": True,
            "no_historical_backfill": True,
            "no_cvd_or_orderbook_or_spot_perp_claim": True,
            "multiple_testing_and_prospective_holdout_not_performed": True,
            "research_only": True, "trade_authorized": False,
            "paper_approved": False, "alpha_validated": False,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--out", default="out/v16_indicator_controls")
    args = parser.parse_args()
    report = analyze(read(args.ledger))
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    lines = [
        "# V16 independent exploratory as-of indicators",
        "",
        f"Verified V8 scans: {report['source_v8_scans']}; V9 matured observations: {report['v9_matured_nonexecuted_outcomes']}.",
        "Missing metrics remain unknown. No CVD/L2/actual funding cash flows measured.",
        "Results are NOT valid alpha or a selection of a live strategy.",
        "",
        "| Target | Candidate | Matched cases | Matched controls | Verdict |",
        "|---|---|---:|---:|---|",
    ]
    for row in report["matched_case_control_results"]:
        lines.append("| " + " | ".join(str(row[key]) for key in (
            "direction", "rule", "matched_cases_available",
            "matched_nonmover_controls_available", "verdict")) + " |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("V16_RESEARCH_ONLY", report["v9_matured_nonexecuted_outcomes"], "matured snapshots")


if __name__ == "__main__":
    main()
