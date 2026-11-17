"""Concise governance report for unattended V5 research.

Signals, event means and source agreement NEVER grant PAPER or trade authority.
No invisible fallback to synthetic data or future-filled results.
"""
from __future__ import annotations
import argparse,json
from collections import Counter
from pathlib import Path

def summarize(base,quality,sources,matched,prospective):
    counts=base["coverage"]
    historical=sum(x["usable"] for x in counts.values())
    original=sum(x["requested"] for x in counts.values())
    audit_states=Counter((x["market"],x["state"]) for x in sources["comparisons"])
    independently_compared=sum(v for (m,s),v in audit_states.items()
                               if s in ("CONSISTENT_REFERENCE_NOT_PIT","DISAGREEMENT_REVIEW"))
    source_attempts=sum(1 for x in sources["comparisons"] if x["market"]!="BIST")
    caveats=[
       "ALL_BACKTEST_MARKETS_CURRENT_SURVIVORS_NOT_HISTORICAL_PIT",
       "DELISTED_PRICES_AND_HISTORICAL_CAP_FLOAT_MISSING",
       "ADJUSTED_OHLCV_AND_REAL_FILLS_UNVERIFIED",
       "HISTORICAL_HOLDOUT_EXPOSED",
       "MULTIPLE_HYPOTHESIS_RESEARCH_NOT_INDEPENDENT",
       "PROSPECTIVE_LEDGER_NOT_LIVE_TRADING"]
    healthy=(all(x["screened"]>=2 for x in quality["coverage"].values()) and
             historical>=10)
    robust=[x for x in matched["results"] if x["status"]=="EXPLORATORY_ROBUST_NOT_PIT"]
    status="RESEARCH_OK_UNVERIFIED" if healthy else "BLOCKED_DATA_COVERAGE"
    if source_attempts and independently_compared==0:status="RESEARCH_DEGRADED_SECONDARY_SOURCES"
    return {"schema":"EAR.unattended_research_governance.v1",
        "status":status,"historical_symbols_usable":historical,
        "historical_symbols_requested":original,
        "coverage":counts,
        "quality_quarantine_count":len(quality["quarantined"]),
        "source_history_comparisons":independently_compared,
        "source_history_audit_attempts":source_attempts,
        "secondary_comparison_states":{m+"|"+s:v for (m,s),v in sorted(audit_states.items())},
        "historical_family_market_trials":len(matched["results"]),
        "exploratory_robust_not_verified":len(robust),
        "new_prospective_signals":prospective["new_signals"],
        "cumulative_prospective_signals":prospective["all_signals"],
        "new_settled_forward_observations":prospective["new_settlements"],
        "total_settled_forward_observations":prospective["all_settlements"],
        "unsettled_reasons":prospective["unsettled_reasons"],
        "governance_blockers":caveats,
        "profitable_strategy_independently_confirmed":False,
        "paper_approved":False,"trade_authorized":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--history",required=True)
    p.add_argument("--quality",required=True)
    p.add_argument("--sources",required=True)
    p.add_argument("--matched",required=True)
    p.add_argument("--prospective",required=True)
    p.add_argument("--out",default="out/research_governance")
    a=p.parse_args()
    obj=lambda x:json.loads(Path(x).read_text(encoding="utf8"))
    report=summarize(obj(a.history),obj(a.quality),obj(a.sources),
                     obj(a.matched),obj(a.prospective))
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# Autonomous BIST / US / altcoin research — simulation only","",
        "| Check | Result |","|---|---|",
        f'| Research status | {report["status"]} |',
        f'| Usable current survivors | {report["historical_symbols_usable"]} / {report["historical_symbols_requested"]} |',
        f'| Quarantined anomaly series | {report["quality_quarantine_count"]} |',
        f'| Independent historical price comparisons | {report["source_history_comparisons"]} / {report["source_history_audit_attempts"]} US/crypto attempts |',
        f'| Existing research hypothesis cells | {report["historical_family_market_trials"]} |',
        f'| Historically robust-looking (unverified) | {report["exploratory_robust_not_verified"]} |',
        f'| New forward signals | {report["new_prospective_signals"]} |',
        f'| Forward settlements, total | {report["total_settled_forward_observations"]} |',
        "","**NO confirmed profitability, PAPER approval, or live trading.**",
        "Current-survivor bias, adjustment uncertainty and exposed historical holdout remain."]
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("RESEARCH_GOVERNANCE",report["status"],report["new_prospective_signals"],
          "new signals, verified secondary references",report["source_history_comparisons"],flush=True)

if __name__=="__main__":main()
