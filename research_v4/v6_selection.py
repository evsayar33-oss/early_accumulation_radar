"""Train-only, deterministic portfolio-family selection; NO model promotion.

Each market selects ONE historical candidate using training NAV subject to
minimum trade count and drawdown. Validation and already-exposed holdout
are only evaluated after the train choice is locked. This is discovery,
NOT pristine independent validation, statistical alpha, or PAPER approval.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from research_v4.multimarket_exploratory import load,COST

MIN_TRAIN_TRADES=20
MIN_TRAIN_MARKET_EXPOSURE_DAYS=15
MIN_VALID_TRADES=10

def select_train_only(report):
    winners=[]
    for market in COST:
        rows=[r for r in report["results"] if r["market"]==market]
        eligible=[r for r in rows if r["train"]["closed_trades"]>=MIN_TRAIN_TRADES
             and r["train"]["days_in_market"]>=MIN_TRAIN_MARKET_EXPOSURE_DAYS
             and r["train"]["unclosed_positions"]==0
             and r["train"]["max_drawdown_pct"]>=-25
             and r["train"]["net_return_pct"]>0]
        # Deterministic tie-break; nothing from validation/holdout influences selection.
        eligible.sort(key=lambda x:(-x["train"]["net_return_pct"],x["family"]))
        chosen=eligible[0] if eligible else None
        if chosen:
            valid=chosen["validation"]
            hold=chosen["previously_exposed_holdout"]
            meets=(valid["closed_trades"]>=MIN_VALID_TRADES and
                  hold["closed_trades"]>=MIN_VALID_TRADES and
                  valid["net_return_pct"]>0 and hold["net_return_pct"]>0 and
                  valid["max_drawdown_pct"]>=-25 and hold["max_drawdown_pct"]>=-25)
            winners.append({"market":market,"status":"HISTORICAL_REVIEW_ONLY" if meets
                     else "OUT_OF_TRAIN_REJECT_OR_INSUFFICIENT",
                     "selected_family":chosen["family"],"train":chosen["train"],
                     "validation":valid,"previously_exposed_holdout":hold,
                     "selection_rule":"training portfolio NAV highest positive with >=20 closed trades, >=15 exposed days and drawdown >=-25%",
                     "train_eligible_families":len(eligible),
                     "selection_did_not_use_validation_or_holdout":True,
                     "multiple_testing_bias_remains":True})
        else:
            winners.append({"market":market,"selected_family":None,
                            "status":"NO_POSITIVE_TRAIN_ELIGIBLE_FAMILY",
                            "train_eligible_families":0})
    return {"schema":"EAR.v6_train_only_selection.v1",
        "selection_was_training_only":True,
        "holdout_previously_exposed":True,
        "multiple_testing_corrected":False,
        "historical_pit_verified":False,"survivorship_bias_unresolved":True,
        "paper_approved":False,"trade_authorized":False,
        "profitable_strategy_confirmed":False,
        "results":winners}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--portfolio",required=True)
    p.add_argument("--out",default="out/v6_selection")
    a=p.parse_args()
    result=select_train_only(json.loads(Path(a.portfolio).read_text()))
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    lines=["# V6 automated train-only candidate selection","",
           "**Exploratory only**. Validation and the already viewed holdout are never used to choose a family.",
           "Selecting among 15 families creates multiple-testing bias; no pristine data/PIT or PAPER promotion.","",
           "| Market | Train-selected family | Validation NAV % | Exposed holdout NAV % | Status |",
           "|---|---|---:|---:|---|"]
    for r in result["results"]:
        lines.append("| "+ " | ".join((r["market"],str(r["selected_family"]),
            str(r.get("validation",{}).get("net_return_pct")),
            str(r.get("previously_exposed_holdout",{}).get("net_return_pct")),
            r["status"]))+" |")
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("V6_TRAIN_ONLY_SELECTION",[(r["market"],r["status"]) for r in result["results"]])

if __name__=="__main__":main()
