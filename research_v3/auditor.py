"""Read-only V3 performance gate. Historical evidence is not forward alpha approval."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from radar.ledger import read_verify
from .model import UNIVERSE, MODEL_VERSION

MIN_TRADES = 30
MIN_TAIL_TRADES = 10
MAX_DRAWDOWN_PCT = 25
MIN_WIN_RATE = 0.40
MIN_PROFIT_FACTOR = 1.10
MIN_STRESS_POSITIVE_SYMBOLS = 6
MIN_TAIL_POSITIVE_SYMBOLS = 5
MIN_BREAKOUT_BEATS = 5
MIN_BUYHOLD_BEATS = 5
MAX_MARK_GAP_MINUTES = 120


def examine_historical(doc):
    manifest = doc.get("manifest", {})
    rows = doc.get("matrix", [])
    reasons = []
    if manifest.get("model") != MODEL_VERSION:
        reasons.append("MODEL_VERSION_MISMATCH")
    if set(manifest.get("universe", [])) != set(UNIVERSE):
        reasons.append("UNIVERSE_MISMATCH")
    if set(manifest.get("symbols_testable", [])) != set(UNIVERSE) or manifest.get("data_errors"):
        reasons.append("INCOMPLETE_ARCHIVE_COVERAGE")
    if any(not m.get("official_checksum_verified") for sources in manifest.get("source_files", {}).values() for m in sources):
        reasons.append("UNVERIFIED_OFFICIAL_ARCHIVE")
    index = {}
    for row in rows:
        key = (row.get("symbol"), row.get("cohort"), row.get("scenario"), row.get("model"))
        if key in index:
            reasons.append("DUPLICATE_MATRIX_KEY")
        index[key] = row
    expected = {(a, cohort, scenario, model) for a in UNIVERSE
                for cohort in ("ALL", "EARLY", "MIDDLE", "TAIL")
                for scenario in ("base", "stress")
                for model in ("acc", "breakout")}
    if set(index) != expected:
        reasons.append("INCOMPLETE_OR_EXTRA_MATRIX")
    def value(row, field):
        x = row.get(field) if row else None
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            return None
        from math import isfinite
        return float(x) if isfinite(x) else None

    per_symbol = []
    stress_profitable = tail_profitable = breakout_beats = buyhold_beats = 0
    qualifying = 0
    for sym in UNIVERSE:
        base = index.get((sym, "ALL", "base", "acc"))
        stress = index.get((sym, "ALL", "stress", "acc"))
        tail = index.get((sym, "TAIL", "stress", "acc"))
        breakout = index.get((sym, "ALL", "stress", "breakout"))
        bret = value(base, "net_return_pct")
        sret = value(stress, "net_return_pct")
        tret = value(tail, "net_return_pct")
        cret = value(breakout, "net_return_pct")
        bench = value(stress, "buyhold_return_pct")
        dd = value(stress, "max_drawdown_pct")
        pf = value(stress, "profit_factor")
        win = value(stress, "win_rate")
        trades = value(stress, "trades")
        tail_trades = value(tail, "trades")
        checks = {
            "cost_stress_positive": sret is not None and sret > 0,
            "tail_stress_positive": tret is not None and tret > 0 and tail_trades is not None and tail_trades >= MIN_TAIL_TRADES,
            "beats_breakout_stress": sret is not None and cret is not None and sret > cret,
            "beats_buyhold_stress": sret is not None and bench is not None and sret > bench,
            "trade_count": trades is not None and trades >= MIN_TRADES,
            "win_rate": win is not None and win >= MIN_WIN_RATE,
            "profit_factor": pf is not None and pf >= MIN_PROFIT_FACTOR,
            "drawdown": dd is not None and dd <= MAX_DRAWDOWN_PCT,
            "no_base_to_stress_inversion": bret is not None and sret is not None and bret >= sret,
        }
        stress_profitable += checks["cost_stress_positive"]
        tail_profitable += checks["tail_stress_positive"]
        breakout_beats += checks["beats_breakout_stress"]
        buyhold_beats += checks["beats_buyhold_stress"]
        qualifying += all(checks.values())
        per_symbol.append({"symbol": sym, "base_net_return_pct": bret, "stress_net_return_pct": sret,
                           "tail_stress_net_return_pct": tret, "stress_buyhold_return_pct": bench,
                           "stress_breakout_return_pct": cret, "stress_win_rate": win,
                           "stress_profit_factor": pf, "stress_max_drawdown_pct": dd,
                           "stress_trade_count": trades, "checks": checks})
    tests = {"positive_stress_symbols": stress_profitable >= MIN_STRESS_POSITIVE_SYMBOLS,
             "positive_tail_stress_symbols": tail_profitable >= MIN_TAIL_POSITIVE_SYMBOLS,
             "beats_breakout_symbols": breakout_beats >= MIN_BREAKOUT_BEATS,
             "beats_buyhold_symbols": buyhold_beats >= MIN_BUYHOLD_BEATS,
             "all_individual_conditions_symbols": qualifying >= MIN_STRESS_POSITIVE_SYMBOLS}
    if reasons:
        decision = "INSUFFICIENT_EVIDENCE"
    elif all(tests.values()):
        decision = "HISTORICAL_SCREEN_PASS_NOT_ALPHA_APPROVAL"
    else:
        decision = "HISTORICAL_SCREEN_FAIL"
    return {"decision": decision, "integrity_blockers": sorted(set(reasons)),
            "gates": tests, "counts": {"stress_positive": stress_profitable,
            "tail_stress_positive": tail_profitable, "breakout_outperformance": breakout_beats,
            "buyhold_outperformance": buyhold_beats, "all_conditions": qualifying},
            "thresholds": {"min_trades": MIN_TRADES, "min_tail_trades": MIN_TAIL_TRADES,
                           "max_drawdown_pct": MAX_DRAWDOWN_PCT, "min_win_rate": MIN_WIN_RATE,
                           "min_profit_factor": MIN_PROFIT_FACTOR,
                           "min_stress_positive_symbols": MIN_STRESS_POSITIVE_SYMBOLS,
                           "min_tail_positive_symbols": MIN_TAIL_POSITIVE_SYMBOLS,
                           "min_breakout_beats": MIN_BREAKOUT_BEATS,
                           "min_buyhold_beats": MIN_BUYHOLD_BEATS},
            "per_symbol": per_symbol,
            "limitations": ["NOT_POINT_IN_TIME_UNIVERSE", "OHLC_EXECUTION_PROXY",
                            "ASSUMED_COSTS", "NO_MULTIPLE_TEST_CORRECTION",
                            "SYMBOLS_ARE_CORRELATED", "NOT_FORWARD_ALPHA_PROOF"]}


def examine_paper(ledger_path, state_path=None):
    path = Path(ledger_path)
    if not path.exists():
        return {"status": "NO_PROSPECTIVE_PAPER_EVIDENCE", "ticks": 0,
                "checkpoint_days": {"30": "PENDING", "60": "PENDING", "90": "PENDING"}}
    rows = read_verify(path)  # Raises on a corrupt hash chain: fail closed.
    if not rows:
        return {"status": "NO_PROSPECTIVE_PAPER_EVIDENCE", "ticks": 0}
    last = rows[-1]
    if state_path:
        p = Path(state_path)
        if not p.exists():
            raise ValueError("PAPER_STATE_MISSING")
        state = json.loads(p.read_text(encoding="utf8"))
        if state.get("last_event_sha256") != last["sha256"] or state.get("last_observed_ms") != last["scan_utc_ms"]:
            raise ValueError("PAPER_STATE_LEDGER_MISMATCH")
    marks = [x for x in rows if x.get("status") == "MARKED" and x.get("nav") is not None]
    start = rows[0]["scan_utc_ms"]
    end = rows[-1]["scan_utc_ms"]
    elapsed_days = (end - start) / 86400000
    gaps = [(b["scan_utc_ms"] - a["scan_utc_ms"])/60000 for a,b in zip(rows, rows[1:])]
    gaps_count = sum(g > MAX_MARK_GAP_MINUTES for g in gaps)
    outages = sum(x.get("status") != "MARKED" for x in rows)
    trades = sum(1 for x in rows for t in x.get("transactions", []) if t.get("type") == "PAPER_EXIT")
    milestones = {str(d): "REACHED" if elapsed_days >= d else "PENDING" for d in (30,60,90)}
    status = ("UNRELIABLE_OBSERVATION_COVERAGE" if gaps_count or outages
              else "FORWARD_OBSERVATION_IN_PROGRESS")
    if elapsed_days < 30 or trades < 30:
        status = "INSUFFICIENT_FORWARD_EVIDENCE" if not (gaps_count or outages) else status
    return {"status": status, "ticks": len(rows), "elapsed_days": round(elapsed_days, 4),
            "marked_ticks": len(marks), "outage_ticks": outages,
            "gaps_over_120m": gaps_count, "closed_trades": trades,
            "last_observed_ms": end, "last_tick_status": last.get("status"),
            "last_marked_nav_usdt": marks[-1]["nav"] if marks else None,
            "last_mark_is_current": last.get("status") == "MARKED",
            "checkpoint_days": milestones,
            "historical_backtest_decision_is_not_paper_approval": True}


def render(doc):
    h = doc["historical"]
    p = doc["paper"]
    lines = ["# V3 Independent Performance Auditor", "",
             "**Historical screen:** " + h["decision"],
             "**Prospective PAPER:** " + p["status"], "",
             "This is NOT live-trading authorization; historical results are neither independent nor PIT survivorship-free.", "",
             "## Historical checks", "",
             "| Gate | Pass |", "|---|---|"]
    for gate, val in h["gates"].items():
        lines.append(f"| {gate} | {'YES' if val else 'NO'} |")
    lines.extend(["", "## Per-asset stressed risk/return", "",
                  "| Asset | Stress net % | Stress win % | Stress PF | Stress DD % | Tail stress net % |",
                  "|---|---:|---:|---:|---:|---:|"])
    def fmt(v, mult=1):
        return "N/A" if v is None else f"{v*mult:.2f}"
    for r in h["per_symbol"]:
        lines.append(f"| {r['symbol']} | {fmt(r['stress_net_return_pct'])} | {fmt(r['stress_win_rate'],100)} | {fmt(r['stress_profit_factor'])} | {fmt(r['stress_max_drawdown_pct'])} | {fmt(r['tail_stress_net_return_pct'])} |")
    lines.extend(["", "## PAPER evidence", "",
                  f"- Observations: {p['ticks']}; elapsed days: {p.get('elapsed_days','N/A')}; outages: {p.get('outage_ticks','N/A')}; gaps >120 minutes: {p.get('gaps_over_120m','N/A')}",
                  f"- Closed trades: {p.get('closed_trades','N/A')}; last NAV: {p.get('last_marked_nav_usdt','N/A')}; last tick has valid NAV: {p.get('last_mark_is_current','N/A')}",
                  f"- Checkpoints: {p.get('checkpoint_days',{})}", "",
                  "## Integrity and interpretation", "",
                  f"- Historical blockers: {h['integrity_blockers']}",
                  "- Frozen rule thresholds are initial screening conventions, not statistically calibrated proof.",
                  "- Historical screening PASS cannot authorize live trading; forward PAPER results require separate elapsed days, sample size, source uptime, and independent execution checks."])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--historical", required=True)
    ap.add_argument("--paper-ledger", default="")
    ap.add_argument("--paper-state", default="")
    ap.add_argument("--out", default="out/v3_audit")
    args = ap.parse_args()
    hist = json.loads(Path(args.historical).read_text(encoding="utf8"))
    result = {"schema": "EAR.V3.performance.audit.v1",
              "historical": examine_historical(hist),
              "paper": examine_paper(args.paper_ledger, args.paper_state) if args.paper_ledger
                       else {"status": "NO_PROSPECTIVE_PAPER_EVIDENCE", "ticks": 0}}
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out/"decision.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf8")
    (out/"report.md").write_text(render(result), encoding="utf8")
    print("V3_AUDITOR", result["historical"]["decision"], result["paper"]["status"])
    if __import__("os").environ.get("GITHUB_STEP_SUMMARY"):
        with open(__import__("os").environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf8") as f:
            f.write(render(result))
    return result

if __name__ == "__main__":
    main()
