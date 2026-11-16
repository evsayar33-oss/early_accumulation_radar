"""Read-only loss attribution for frozen V3 historical evidence."""
import argparse
import collections
import csv
import json
import statistics
from pathlib import Path
from .model import ALLOCATION, SCENARIOS
from .paper import BUDGET_PCT, MAX_EXPOSURE_PCT

def analyze(summary, trades):
    rows=summary["matrix"]
    reasons=collections.Counter()
    buckets={}
    for t in trades:
        if t.get("cohort")!="ALL" or t.get("model")!="acc":
            continue
        key=(t["symbol"],t["scenario"])
        b=buckets.setdefault(key,{"n":0,"wins":0,"net_pnl_usdt":0.,
                                  "gross_positive_usdt":0.,"gross_negative_usdt":0.,
                                  "reason_counts":collections.Counter(),
                                  "trade_return_pct":[]})
        pnl=float(t["net_pnl"])
        b["n"]+=1;b["wins"]+=pnl>0;b["net_pnl_usdt"]+=pnl
        b["gross_positive_usdt"]+=max(0,pnl)
        b["gross_negative_usdt"]+=min(0,pnl)
        b["reason_counts"][t["reason"]]+=1
        b["trade_return_pct"].append(float(t["net_return_pct"]))
        reasons[(t["scenario"],t["reason"])]+=1
    per=[]
    for (symbol,scenario),b in sorted(buckets.items()):
        matching=next((r for r in rows if r["symbol"]==symbol and r["cohort"]=="ALL" and r["model"]=="acc" and r["scenario"]==scenario),None)
        if not matching:raise ValueError("MISSING_MATRIX_ROW")
        if b["n"]!=matching["trades"]:raise ValueError("TRADE_COUNT_MISMATCH")
        per.append({"symbol":symbol,"scenario":scenario,"trades":b["n"],
                    "win_rate":round(b["wins"]/b["n"],5) if b["n"] else None,
                    "total_net_pnl_usdt":round(b["net_pnl_usdt"],2),
                    "average_trade_return_pct":round(statistics.mean(b["trade_return_pct"]),4) if b["n"] else None,
                    "median_trade_return_pct":round(statistics.median(b["trade_return_pct"]),4) if b["n"] else None,
                    "reason_counts":dict(b["reason_counts"]),
                    "matrix_net_return_pct":matching["net_return_pct"],
                    "matrix_max_drawdown_pct":matching["max_drawdown_pct"]})
    if len(per)!=len(summary["manifest"]["symbols_testable"])*len(SCENARIOS):
        raise ValueError("INCOMPLETE_DIAGNOSTIC_COVERAGE")
    return {"schema":"EAR.V3.loss_attribution.v1",
            "historical_trades_not_independent_across_cohorts":True,
            "only_all_cohort_accumulation":True,
            "historical_allocation_pct":100*ALLOCATION,
            "paper_per_entry_budget_pct":100*BUDGET_PCT,
            "paper_max_exposure_pct":100*MAX_EXPOSURE_PCT,
            "historical_paper_allocation_not_comparable":ALLOCATION!=BUDGET_PCT,
            "reason_counts_by_scenario":{s:{reason:n for (scenario,reason),n in reasons.items() if scenario==s}
                                         for s in SCENARIOS},
            "per_symbol":per,
            "conclusions":["Do not lower PASS thresholds to fit a failed model.",
                           "The historical 95% single-position allocation and prospective 10% per-entry/30% maximum exposure are not comparable.",
                           "Net PnL and exit reasons alone cannot causally separate poor signals from spread/slippage assumptions.",
                           "No parameters optimized or changed; further candidates must be tested on fresh held-out data.",
                           "The existing forward PAPER cohort remains frozen and independent."]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--summary",required=True)
    p.add_argument("--trades",required=True)
    p.add_argument("--out",default="out/v3_diagnostic")
    args=p.parse_args()
    summary=json.loads(Path(args.summary).read_text())
    with open(args.trades,newline="",encoding="utf8") as f:trades=list(csv.DictReader(f))
    report=analyze(summary,trades)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    (out/"attribution.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# V3 loss attribution — diagnostic only","",
           "**No strategy change, no live approval.**","",
           f"Historical allocation: {100*ALLOCATION:.0f}%; PAPER entry budget: {100*BUDGET_PCT:.0f}%; PAPER max exposure: {100*MAX_EXPOSURE_PCT:.0f}%.",
           "These position-sizing assumptions are not comparable.","",
           "| Symbol | Cost scenario | Trades | Win % | Avg trade % | Median trade % | Net % | Max DD % |",
           "|---|---|---:|---:|---:|---:|---:|---:|"]
    for x in report["per_symbol"]:
        lines.append(f"| {x['symbol']} | {x['scenario']} | {x['trades']} | {100*x['win_rate']:.2f} | {x['average_trade_return_pct']:.3f} | {x['median_trade_return_pct']:.3f} | {x['matrix_net_return_pct']:.2f} | {x['matrix_max_drawdown_pct']:.2f} |")
    lines+=["","## Exit reason counts (ALL cohort, accumulation)",""]
    for scenario,counts in report["reason_counts_by_scenario"].items():
        lines.append(f"**{scenario}**: "+", ".join(f"{k}={v}" for k,v in sorted(counts.items())))
    lines+=["","## Limits"]+["- "+s for s in report["conclusions"]]
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("V3_DIAGNOSTIC_DONE",len(per) if False else len(report["per_symbol"]))
    return report

if __name__=="__main__":
    main()
