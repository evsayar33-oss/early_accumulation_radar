"""V4 immutable first-seen research snapshots and fail-closed test/PAPER gates."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from radar.ledger import canonical, digest, read_verify

REQUIRED_MARKETS = ("BIST", "US")
MIN_FORWARD_SESSIONS = 30

def quality(doc):
    if doc.get("schema") != "EAR.V4.equity.source_probe.v1":
        raise ValueError("UNKNOWN_EQUITY_PROBE_SCHEMA")
    issues=[]
    if doc.get("market") not in REQUIRED_MARKETS:
        issues.append("WRONG_MARKET")
    if doc.get("status") != "RECENT_DATA_AVAILABLE_NOT_PIT_READY":
        issues.append("PRICE_SOURCE_UNAVAILABLE")
    if not doc.get("observations"):
        issues.append("NO_CURRENT_UNIVERSE")
    for item in doc.get("observations",[]):
        bars=item.get("daily_bars_recent",[])
        if not bars:
            issues.append("MISSING_RECENT_PRICE_SERIES")
            continue
        if any(int(b["ts_ms"])>=int(c["ts_ms"]) for b,c in zip(bars,bars[1:])):
            issues.append("DUPLICATE_OR_OUT_OF_ORDER_BAR")
        if int(bars[-1]["ts_ms"])>int(doc["observed_ms"]):
            issues.append("FUTURE_BAR")
        if int(doc["observed_ms"])-int(bars[-1]["ts_ms"])>10*86400000:
            issues.append("STALE_LAST_SESSION")
        cross=item.get("price_crosscheck")
        if cross is not None and not cross.get("consistent_under_2pct"):
            issues.append("PRICE_SOURCE_DISAGREEMENT_OR_NO_OVERLAP")
    if not doc.get("float_ownership_verified"):
        issues.append("UNVERIFIED_FLOAT_AND_OWNERSHIP")
    if not doc.get("corporate_actions_verified"):
        issues.append("UNVERIFIED_SPLITS_DIVIDENDS")
    if not doc.get("universe_point_in_time_verified"):
        issues.append("NO_POINT_IN_TIME_UNIVERSE")
    if not doc.get("sampling_is_representative"):
        issues.append("PARTIAL_CURRENT_UNIVERSE_SAMPLE")
    return {"market":doc.get("market"),"issues":sorted(set(issues)),
            "historical_backtest_approved":False,"paper_authorized":False,
            "trade_authorized":False,
            "label":"DATA_SOURCE_RESEARCH_ONLY_NO_ALPHA_APPROVAL"}

def compact(bist,us):
    if bist.get("market")!="BIST" or us.get("market")!="US":
        raise ValueError("MARKET_MISMATCH")
    if bist.get("schema")!=us.get("schema"):
        raise ValueError("INCOMPATIBLE_SOURCE_REPORTS")
    now=max(int(bist["observed_ms"]),int(us["observed_ms"]))
    if abs(int(bist["observed_ms"])-int(us["observed_ms"]))>30*60000:
        raise ValueError("SOURCE_OBSERVATIONS_MORE_THAN_30_MINUTES_APART")
    data={}
    for doc in (bist,us):
        data[doc["market"]]={"status":doc["status"],"coverage":doc["coverage"],
                             "quality":quality(doc),
                             "raw_payload_sha256":hashlib.sha256(canonical(doc).encode("utf8")).hexdigest(),
                             "sample":[{"symbol":p.get("symbol"),
                                        "source":p.get("price_source"),
                                        "last_bar":(p.get("daily_bars_recent") or [None])[-1],
                                        "market_cap_usd_screen":p.get("market_cap_usd_screen"),
                                        "sec_cik":p.get("sec_cik"),
                                        "sec_public_float_usd_filing":p.get("sec_public_float_usd_filing"),
                                        "float_pct_verified":False,
                                        "ownership_concentration_verified":False}
                                       for p in doc.get("observations",[])]}
    return {"schema":"EAR.V4.equity.firstseen.v1","scan_utc_ms":now,
            "scope":"FIRST_SEEN_DIAGNOSTIC_NO_HISTORICAL_RECONSTRUCTION",
            "markets":data,"no_orders":True,"no_retro_fill":True}

def append(bist,us,ledger):
    path=Path(ledger)
    rows=read_verify(path)
    record=compact(bist,us)
    if rows and record["scan_utc_ms"]<=rows[-1]["scan_utc_ms"]:
        raise ValueError("NON_MONOTONIC_EQUITY_OBSERVATION")
    record["prev_sha256"]=rows[-1]["sha256"] if rows else "GENESIS"
    record["sha256"]=digest(record)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf8") as f:
        f.write(canonical(record)+"\n")
    if read_verify(path)[-1]["sha256"] != record["sha256"]:
        raise ValueError("HASH_VERIFY_FAILED")
    return record

def evaluate(bist,us,ledger=None):
    docs=(bist,us)
    checks={doc["market"]:quality(doc) for doc in docs}
    ticks=read_verify(ledger) if ledger else []
    sessions={m:{(rec["sample"][i].get("last_bar") or {}).get("session_utc",
                    str((rec["sample"][i].get("last_bar") or {}).get("ts_ms", ""))[:10])
                  for rec in ticks for i in range(len(rec.get("markets",{}).get(m,{}).get("sample",[])))
                  if rec.get("markets",{}).get(m,{}).get("sample",[])[i].get("last_bar")}
              for m in REQUIRED_MARKETS}
    # No historical profitability, annualized returns, win rate or backfilled universe.
    return {"schema":"EAR.V4.equity.integrity_gate.v1","markets":checks,
            "forward_observation_ticks":len(ticks),
            "observed_session_counts":{m:len(sessions[m]) for m in REQUIRED_MARKETS},
            "minimum_independent_forward_sessions":MIN_FORWARD_SESSIONS,
            "pit_historical_profitability_test":"BLOCKED_PENDING_VALID_POINT_IN_TIME_HISTORY",
            "forward_paper_test":"BLOCKED_PENDING_FLOAT_LIQUIDITY_AND_COST_VALIDATION",
            "trade_authorized":False,
            "do_not_use_historical_btc_eth_sol_results_as_equity_alpha":True,
            "decision":"INSUFFICIENT_EQUITY_EVIDENCE"}

def render(report):
    lines=["# V4 BIST / US free data source audit","",
           "**Decision: "+report["decision"]+"**","",
           "NO order routing, NO historical alpha approval, NO new PAPER entries.","",
           "| Market | Source status | Tickers | Daily series | PIT approved |",
           "|---|---|---:|---:|---|"]
    for m in REQUIRED_MARKETS:
        s=report["sources"][m]
        lines.append(f"| {m} | {s['status']} | {s['coverage']['observed_tickers']} | {s['coverage']['recent_price_series']} | NO |")
    lines += ["","## Evidence gates",""]
    for m in REQUIRED_MARKETS:
        lines.append("**"+m+"**: "+", ".join(report["gate"]["markets"][m]["issues"]))
    lines += ["",f"Forward evidence ticks: {report['gate']['forward_observation_ticks']}",
              "Historical PIT test: "+report["gate"]["pit_historical_profitability_test"],
              "PAPER status: "+report["gate"]["forward_paper_test"],"",
              "These current, partial free-source samples can support connection health tests, NOT survivorship-free backtests or live trading."]
    return "\n".join(lines)+"\n"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input-dir",default="out/v4_equities")
    ap.add_argument("--ledger",default="")
    ap.add_argument("--out",default="out/v4_equity_audit")
    a=ap.parse_args()
    base=Path(a.input_dir)
    b=json.loads((base/"bist.json").read_text(encoding="utf8"))
    u=json.loads((base/"us.json").read_text(encoding="utf8"))
    result={"schema":"EAR.V4.equity.audit.report.v1","sources":{"BIST":b,"US":u},
            "gate":evaluate(b,u,a.ledger or None),"decision":"INSUFFICIENT_EQUITY_EVIDENCE"}
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"decision.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf8")
    (out/"report.md").write_text(render(result),encoding="utf8")
    print("V4_EQUITY_AUDIT",result["decision"],"ticks",result["gate"]["forward_observation_ticks"])
    return result

if __name__=="__main__":
    main()
