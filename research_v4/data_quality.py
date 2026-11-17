"""Auditable anomaly screening. Deliberately NOT a split-adjustment/PIT repair.

Always retain raw input. For research only, exclude ambiguous series rather than
retroactively modifying OHLCV or classifying genuine price moves as splits.
"""
from __future__ import annotations
import argparse,csv,hashlib,json
from collections import defaultdict
from datetime import date
from pathlib import Path
from research_v4.multimarket_exploratory import load

def classify(market,seq,asof=None):
    reasons=[]
    if len(seq)<(180 if market=="CRYPTO" else 300):
        reasons.append("SHORT_HISTORY")
    if len(seq)>1 and asof:
        age=(asof-seq[-1]["date"]).days
        if age>14:reasons.append("STALE_LAST_BAR")
    if market in ("BIST","US"):
        # May be a legitimate extraordinary move, not necessarily a split.
        # No automatic adjustment or claim to have repaired corporate actions.
        for i in range(1,len(seq)):
            before=seq[i-1]["close"]
            op=seq[i]["open"]
            if op/before>2.4 or op/before<.42:
                reasons.append("POSSIBLE_UNADJUSTED_CORPORATE_ACTION_OR_REAL_GAP")
                break
    zero=0
    for b in seq:
        if b["volume"]==0:
            zero+=1
            if zero>=15:
                reasons.append("EXTENDED_ZERO_VOLUME")
                break
        else:zero=0
    return sorted(set(reasons))

def screen(input_csv,manifest_path,output):
    original=Path(input_csv).read_bytes()
    manifest=json.loads(Path(manifest_path).read_text(encoding="utf8"))
    if manifest.get("csv_sha256")!=hashlib.sha256(original).hexdigest():
        raise ValueError("SOURCE_MANIFEST_HASH_MISMATCH")
    if manifest.get("trade_authorized") is not False or manifest.get("paper_approved") is not False:
        raise ValueError("UNEXPECTED_AUTHORIZATION_FLAGS")
    asof=date.fromisoformat(manifest["asof_utc"][:10])
    series=load(input_csv)
    excluded={}
    rows=[]
    for (market,sym),seq in sorted(series.items()):
        reasons=classify(market,seq,asof)
        if reasons:excluded[market+":"+sym]=reasons
        else:
            for b in seq:
                rows.append((market,sym,b["date"].isoformat(),
                             *[b[k] for k in ("open","high","low","close","volume")],
                             "false","false"))
    coverage={}
    for market in ("BIST","US","CRYPTO"):
        total=sum(m==market for m,s in series)
        usable=sum(m==market and m+":"+s not in excluded for m,s in series)
        coverage[market]={"original":total,"screened":usable,"quarantined":total-usable}
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    report={"schema":"EAR.non_pit_quality_screen.v1",
        "source_csv_sha256":manifest["csv_sha256"],
        "source_universe":"CURRENT_SURVIVORS_NOT_PIT",
        "corporate_actions_verified":False,"quarantined_not_corrected":True,
        "sample_selection_bias_unresolved":True,
        "paper_approved":False,"trade_authorized":False,
        "coverage":coverage,"quarantined":excluded}
    if any(item["screened"]<2 for item in coverage.values()):
        report["status"]="BLOCKED_MINIMUM_COVERAGE"
        (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        raise ValueError("QUALITY_SCREEN_INSUFFICIENT_MARKET_COVERAGE")
    with (out/"screened_prices.csv").open("w",newline="",encoding="utf8") as f:
        writer=csv.writer(f)
        writer.writerow(("market","symbol","date","open","high","low","close",
                         "volume","pit_universe_verified","corporate_actions_verified"))
        writer.writerows(rows)
    report["screened_csv_sha256"]=hashlib.sha256((out/"screened_prices.csv").read_bytes()).hexdigest()
    report["status"]="RESEARCH_ONLY_WITH_UNRESOLVED_PIT"
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# Data quality (not a point-in-time or split-adjustment fix)","",
           "| Market | Original | Screened | Quarantined |",
           "|---|---:|---:|---:|"]
    for m,c in coverage.items():
        lines.append(f'| {m} | {c["original"]} | {c["screened"]} | {c["quarantined"]} |')
    lines+=["","Possible split-like jumps are **quarantined**, not automatically adjusted.",
            "Results on remaining symbols still suffer selection/survivorship bias."]
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("QUALITY_SCREEN",coverage,flush=True)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--manifest",required=True)
    p.add_argument("--out",default="out/data_quality")
    a=p.parse_args()
    screen(a.csv,a.manifest,a.out)

if __name__=="__main__":main()
