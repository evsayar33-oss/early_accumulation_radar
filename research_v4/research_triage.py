"""Single-pass research integrity and actionable triage, never alpha approval."""
from __future__ import annotations
import argparse,json
from collections import Counter
from pathlib import Path

def evaluate(manifest,secondary,exploratory,novel,events):
    coverage=manifest.get("coverage",{})
    failures=[]
    for market in ("BIST","US","CRYPTO"):
        item=coverage.get(market,{})
        usable=int(item.get("usable",0))
        requested=int(item.get("requested",0))
        if usable<2:failures.append(f"{market}_TOO_FEW_PRICE_SERIES")
        elif requested and usable/requested<.65:failures.append(f"{market}_COVERAGE_BELOW_65_PERCENT")
    states=Counter(r.get("state","UNKNOWN") for r in secondary.get("comparisons",[]))
    compared=sum(n for state,n in states.items() if state=="COMPARED_NOT_PIT_VERIFIED")
    if compared==0:failures.append("NO_INDEPENDENT_PRICE_COMPARISON_SUCCEEDED")
    market_coverage=Counter(r.get("market") for r in secondary.get("comparisons",[])
                            if r.get("state")=="COMPARED_NOT_PIT_VERIFIED")
    for market in ("US","CRYPTO"):
        if market_coverage[market]==0:failures.append(f"{market}_SECONDARY_SOURCE_UNAVAILABLE")
    all_reports=(exploratory,novel,events)
    candidates=[]
    for source,report in zip(("v2","v3","v4"),all_reports):
        if report.get("paper_approved") is not False or report.get("trade_authorized") is not False:
            failures.append(f"{source}_UNEXPECTED_APPROVAL")
        for row in report.get("results",[]):
            if row.get("status") in ("EXPLORATORY_ROBUST_NOT_VERIFIED","EXPLORATORY_POSITIVE_NOT_VERIFIED"):
                candidates.append({"study":source,"market":row.get("market"),"family":row.get("family"),
                                   "status":"EXPLORATORY_ONLY_REQUIRES_NEW_BLIND_DATA"})
    return {"schema":"EAR.research_triage.v1","status":"REVIEW_REQUIRED" if failures else "DIAGNOSTICS_COMPLETE",
        "coverage":coverage,"source_states":dict(states),"verified_price_source_comparisons":compared,
        "problems":sorted(set(failures)),"exploratory_candidates":candidates,
        "paper_approved":False,"trade_authorized":False,"pit_verified":False,
        "limitations":["current survivor universe","historical delistings unavailable",
          "historical size/float unavailable","unverified corporate actions",
          "previous holdout exposed","not portfolio NAV"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",default="out")
    p.add_argument("--out",default="out/research_triage")
    a=p.parse_args()
    root=Path(a.root)
    def read(name):return json.loads((root/name/"report.json").read_text())
    manifest=json.loads((root/"expanded_history"/"manifest.json").read_text())
    report=evaluate(manifest,read("secondary_source_audit"),read("expanded_families"),
                    read("new_hypotheses_bias"),read("regime_events"))
    dest=Path(a.out);dest.mkdir(parents=True,exist_ok=True)
    (dest/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# Unified research triage","",
        "**"+report["status"]+"** — No automatic PAPER/live approval.","",
        "## Actionable gaps"]
    lines.extend("- "+x for x in report["problems"])
    if not report["problems"]:lines.append("- No new source/coverage blockers under current thresholds.")
    lines+=["","## Exploratory signals (not validated)"]
    lines.extend("- "+r["study"]+" "+str(r["market"])+" / "+str(r["family"]) for r in report["exploratory_candidates"])
    if not report["exploratory_candidates"]:lines.append("- None meets the exploratory diagnostic.")
    lines+=["","Current survivors, no delisted/PIT universe, historical size/float or independent holdout. No portfolio NAV."]
    (dest/"report.md").write_text("\n".join(lines)+"\n")
    print("RESEARCH_TRIAGE",report["status"],len(report["problems"]),"gaps",
          len(report["exploratory_candidates"]),"exploratory candidates")

if __name__=="__main__":main()
