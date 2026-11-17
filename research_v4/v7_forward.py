"""Isolated V7 forward-only, SHA-verified evidence (no order routing).

New V7 families are NOT mixed into previously frozen V5 source-code-hashed
signal registries. No retrospective signal reconstruction from price history.
Daily snapshots must be CLOSED before first observation and settlements.
"""
from __future__ import annotations
import argparse,hashlib,json
from collections import Counter,defaultdict
from datetime import datetime,timezone,date
from pathlib import Path
from statistics import mean
from research_v4.multimarket_exploratory import load,COST
from research_v4.v7_target_fit import latest_watchlist,HORIZONS
from research_v4.v6_bidirectional import structural_gaps
from research_v4.prospective_evidence import seal,digest,read_ledger,write_ledger

def closed_history(series,asof):
    today=datetime.fromisoformat(asof.replace("Z","+00:00")).astimezone(timezone.utc).date()
    return {key:[b for b in seq if b["date"]<today] for key,seq in series.items()}

def source_version():
    return hashlib.sha256(Path("research_v4/v7_target_fit.py").read_bytes()).hexdigest()

def signals_from_closed(series,observed_at,code_sha,source_sha):
    t=datetime.fromisoformat(observed_at.replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("OBSERVATION_MUST_BE_TIMEZONED")
    now=t.astimezone(timezone.utc).date()
    out=[]
    for row in latest_watchlist(closed_history(series,observed_at)):
        day=datetime.fromisoformat(row["signal_date"]).date()
        if not 0<=(now-day).days<=7:continue
        for horizon in HORIZONS:
            ident={"market":row["market"],"symbol":row["symbol"],
                   "family":row["family"],"signal_date":row["signal_date"],
                   "code_sha256":code_sha,"hold_sessions":horizon}
            record={"schema":"EAR.v7_forward_signal.v1","kind":"signal",
                "id":digest(ident),**ident,"first_observed_utc":t.astimezone(timezone.utc).isoformat(),
                "entry_strictly_after_utc_date":now.isoformat(),
                "source_sha256":source_sha,"direction":row["direction"],
                "paper_approved":False,"trade_authorized":False,
                "not_historical_pit":True}
            out.append(seal(record))
    return out

def settle(signal,series):
    key=(signal["market"],signal["symbol"])
    rows=series.get(key)
    if not rows:return None,"SOURCE_SYMBOL_MISSING"
    if not any(b["date"].isoformat()==signal["signal_date"] for b in rows):
        return None,"SIGNAL_DATE_NOT_IN_CURRENT_HISTORY"
    eligible=[i for i,b in enumerate(rows) if b["date"].isoformat()>signal["entry_strictly_after_utc_date"]]
    hold=signal["hold_sessions"]
    if not eligible or eligible[0]+hold-1>=len(rows):
        return None,"AWAITING_FUTURE_CLOSED_SESSIONS"
    entryidx=eligible[0]
    exitidx=entryidx+hold-1
    first_gap=(rows[entryidx]["date"]-date.fromisoformat(signal["entry_strictly_after_utc_date"])).days
    if first_gap>(3 if signal["market"]=="CRYPTO" else 7):
        return None,"FIRST_ENTRY_TOO_DELAYED_OR_MISSING"
    signalidx=next(i for i,b in enumerate(rows) if b["date"].isoformat()==signal["signal_date"])
    flags=structural_gaps(rows)
    if any(j in flags for j in range(signalidx+1,exitidx+1)):
        return None,"SUSPECTED_PRICE_SCALE_CHANGE_IN_FORWARD"
    op=rows[entryidx]["open"]
    close=rows[exitidx]["close"]
    gross=100*(close/op-1)
    cost=COST[signal["market"]]
    row={"schema":"EAR.v7_forward_settlement.v1","kind":"settlement",
        "id":signal["id"],"signal_id":signal["id"],"market":signal["market"],
        "symbol":signal["symbol"],"family":signal["family"],
        "direction":signal["direction"],
        "code_sha256":signal["code_sha256"],"hold_sessions":hold,
        "signal_date":signal["signal_date"],
        "first_observed_utc":signal["first_observed_utc"],
        "entry_date":rows[entryidx]["date"].isoformat(),
        "exit_date":rows[exitidx]["date"].isoformat(),
        "entry_open_unfilled":op,"exit_close_unfilled":close,
        "underlying_return_pct":round(gross,5),
        "long_net_pct":round(gross-cost,5),
        "long_double_cost_net_pct":round(gross-2*cost,5),
        "short_profit_claimed":False,"real_fills_verified":False,
        "paper_approved":False,"trade_authorized":False}
    return seal(row),None

def update(series,old_signals,old_settlements,observed_at,code_sha,source_sha):
    existing={r["id"] for r in old_signals}
    new=[r for r in signals_from_closed(series,observed_at,code_sha,source_sha) if r["id"] not in existing]
    all_signals=old_signals+new
    closed=closed_history(series,observed_at)
    already={r["id"] for r in old_settlements}
    matured=[];pending=Counter()
    for signal in all_signals:
        if signal["id"] in already:continue
        result,reason=settle(signal,closed)
        if result:matured.append(result)
        else:pending[reason]+=1
    all_settlements=old_settlements+matured
    group=defaultdict(list)
    for r in all_settlements:
        group[(r["market"],r["family"],r["hold_sessions"],r["code_sha256"])].append(r)
    stats=[]
    for (market,family,hold,version),rows in sorted(group.items()):
        stats.append({"market":market,"family":family,"hold_sessions":hold,
            "code_sha256":version,"n":len(rows),
            "mean_long_net_pct":round(mean(x["long_net_pct"] for x in rows),5),
            "distinct_symbols":len({x["symbol"] for x in rows}),
            "status":"RESEARCH_INSUFFICIENT" if len(rows)<30 else "RESEARCH_REQUIRES_INDEPENDENT_RISK_REVIEW"})
    return all_signals,all_settlements,{"schema":"EAR.v7_forward_summary.v1",
       "asof_utc":observed_at,"new_signals":len(new),
       "total_signals":len(all_signals),"new_settlements":len(matured),
       "total_settlements":len(all_settlements),"pending":dict(pending),
       "by_family":stats,"code_sha256":code_sha,
       "paper_approved":False,"trade_authorized":False,
       "profitable_strategy_confirmed":False,
       "historical_pit_verified":False,"short_execution_model":False,
       "notes":"No old signals backfilled; entry day strictly after first observation UTC date, with closed daily bars only. Old V5 ledger untouched."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--old-signals",required=True)
    p.add_argument("--old-settlements",required=True)
    p.add_argument("--asof")
    p.add_argument("--out",default="out/v7_forward")
    a=p.parse_args()
    now=a.asof or datetime.now(timezone.utc).isoformat()
    source_sha=hashlib.sha256(Path(a.csv).read_bytes()).hexdigest()
    signals,settled,report=update(load(a.csv),
        read_ledger(a.old_signals,"signal"),read_ledger(a.old_settlements,"settlement"),
        now,source_version(),source_sha)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    write_ledger(out/"signals.jsonl",signals)
    write_ledger(out/"settlements.jsonl",settled)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# V7 NEW early-accumulation hypotheses: independent forward evidence","",
      f"New first-observed: {report['new_signals']}, all: {report['total_signals']}.",
      f"New completed: {report['new_settlements']}, all: {report['total_settlements']}.",
      "Pending: "+json.dumps(report["pending"],sort_keys=True),
      "No real fills, historically PIT, verified float/depth or historical delisted sample.",
      "RISK_ONLY is NOT executable short. NO PAPER/live or proven profitability."]
    (out/"report.md").write_text("\n\n".join(lines)+"\n")
    print("V7_FORWARD",report["new_signals"],"new signals",report["new_settlements"],"new completed",report["pending"])

if __name__=="__main__":main()
