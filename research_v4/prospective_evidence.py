"""Append-only prospective research evidence. NO PAPER/live execution or approval.

Signals are frozen after a fully closed market bar. Entry must occur on a
later UTC calendar day than the actual observation, even if the following
exchange open was already missed. Simulated fills do not imply real fills.
First-recorded outcomes are never overwritten; unresolved delistings remain
explicitly missing. Registry belongs on an isolated GitHub research branch.
"""
from __future__ import annotations
import argparse,hashlib,json
from collections import Counter,defaultdict
from datetime import datetime,date,timezone
from pathlib import Path
from statistics import mean
from research_v4.multimarket_exploratory import (
    load,features as v2_features,signal as v2_signal,FAMILIES as V2_FAMILIES,COST)
from research_v4.historical_discovery import (
    signal as baseline_signal,FAMILIES as BASE_FAMILIES)
from research_v4.new_hypotheses_bias import (
    features as v3_features,selected as v3_selected,FAMILIES as V3_FAMILIES)
from research_v4.regime_event_research import (
    indicator as v4_features,signal as v4_signal,FAMILIES as V4_FAMILIES)

HOLD=5
CODE_FILES=("research_v4/historical_discovery.py",
    "research_v4/multimarket_exploratory.py","research_v4/new_hypotheses_bias.py",
    "research_v4/regime_event_research.py")

def digest(value):
    data=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()

def seal(obj):
    item=dict(obj)
    item["record_digest"]=digest(item)
    return item

def read_ledger(path,kind):
    p=Path(path)
    if not p.exists():return []
    rows=[]
    seen=set()
    for line in p.read_text(encoding="utf8").splitlines():
        if not line.strip():continue
        r=json.loads(line)
        if (r.get("kind")!=kind or r.get("record_digest")!=digest({k:v for k,v in r.items() if k!="record_digest"})):
            raise ValueError("REGISTRY_INTEGRITY_FAILURE")
        if r.get("id") in seen:raise ValueError("REGISTRY_DUPLICATE_ID")
        seen.add(r["id"])
        rows.append(r)
    return rows

def write_ledger(path,rows):
    Path(path).write_text("".join(json.dumps(x,sort_keys=True,separators=(",",":"))+"\n" for x in rows),encoding="utf8")

def method_hash(root="."):
    h=hashlib.sha256()
    for name in CODE_FILES:
        h.update(name.encode())
        h.update((Path(root)/name).read_bytes())
    return h.hexdigest()

def _peers(series):
    peers=defaultdict(list)
    for (market,sym),bars in series.items():
        if len(bars)<101:continue
        i=len(bars)-1
        z=v3_features(bars,i)
        if z is not None:peers[(market,bars[i]["date"])].append((sym,z["r20"]))
    ranks={}
    for key,group in peers.items():
        ordered=sorted(group,key=lambda x:(x[1],x[0]))
        if len(ordered)<5:continue
        for i,(sym,score) in enumerate(ordered):
            ranks[(key[0],key[1],sym)]=(i/(len(ordered)-1),len(ordered))
    return ranks

def emit_signals(series,observed_at,methodology,source_sha):
    now=datetime.fromisoformat(observed_at.replace("Z","+00:00"))
    if now.tzinfo is None:raise ValueError("OBSERVATION_TIMESTAMP_MUST_BE_TZ_AWARE")
    today=now.astimezone(timezone.utc).date()
    latest={m:max((bars[-1]["date"] for (mm,_),bars in series.items()
                    if mm==m and bars),default=None) for m in COST}
    ranks=_peers(series)
    out=[]
    for (market,sym),bars in sorted(series.items()):
        if len(bars)<121 or bars[-1]["date"]!=latest[market]:continue
        if not 0<=(today-bars[-1]["date"]).days<=7:continue
        i=len(bars)-1
        checks=[]
        for fam in BASE_FAMILIES:
            checks.append(("baseline/"+fam,baseline_signal(fam,bars,i)))
        z2=v2_features(bars,i)
        if z2 is not None:
            for fam in V2_FAMILIES:
                checks.append(("v2/"+fam,v2_signal(fam,bars,i,z2)))
        z3=v3_features(bars,i)
        if z3 is not None:
            rank,n=ranks.get((market,bars[i]["date"],sym),(None,0))
            for fam in V3_FAMILIES:
                checks.append(("v3/"+fam,v3_selected(fam,z3,rank,n)))
        z4=v4_features(bars,i)
        if z4 is not None:
            for fam in V4_FAMILIES:
                checks.append(("v4/"+fam,v4_signal(fam,z4,market)))
        for family,selected in checks:
            if not selected:continue
            identity={"market":market,"symbol":sym,"family":family,
                "signal_date":bars[i]["date"].isoformat(),"methodology_sha256":methodology}
            record={"schema":"EAR.prospective_signal.v1","kind":"signal",
                "id":digest(identity),"first_observed_utc":now.isoformat(),
                "entry_strictly_after_utc_date":today.isoformat(),
                "source_sha256":source_sha,**identity,
                "hold_sessions":HOLD,
                "pit_price_adjustments_verified":False,"paper_approved":False,
                "trade_authorized":False}
            out.append(seal(record))
    return out

def _reference(series,market,sym,entry_date,exit_date):
    """Frictionless survivor benchmark: conservative relative-excess hurdle."""
    gains=[]
    for (m,other),bars in series.items():
        if m!=market or other==sym:continue
        o=next((b["open"] for b in bars if b["date"].isoformat()==entry_date),None)
        c=next((b["close"] for b in bars if b["date"].isoformat()==exit_date),None)
        if o and c:gains.append(100*(c/o-1))
    return (round(mean(gains),5),len(gains)) if len(gains)>=5 else (None,len(gains))

def settle(signal,series):
    key=(signal["market"],signal["symbol"])
    bars=series.get(key)
    if not bars:return None,"SOURCE_SYMBOL_MISSING"
    if signal["signal_date"]<bars[0]["date"].isoformat():
        return None,"SIGNAL_OUTSIDE_AVAILABLE_PRICE_WINDOW"
    if not any(b["date"].isoformat()==signal["signal_date"] for b in bars):
        return None,"SIGNAL_DATE_ABSENT"
    eligible=[i for i,b in enumerate(bars) if b["date"].isoformat()>signal["entry_strictly_after_utc_date"]]
    if len(eligible)<HOLD:return None,"AWAITING_FUTURE_CLOSED_BARS"
    first=eligible[0]
    final=first+HOLD-1
    if final>=len(bars):return None,"AWAITING_FUTURE_CLOSED_BARS"
    entry=bars[first]["open"]
    exit_close=bars[final]["close"]
    gross=100*(exit_close/entry-1)
    market=signal["market"]
    benchmark,peers=_reference(series,market,signal["symbol"],
                         bars[first]["date"].isoformat(),bars[final]["date"].isoformat())
    result={"schema":"EAR.prospective_settlement.v1","kind":"settlement",
            "id":signal["id"],"signal_id":signal["id"],
            "market":market,"symbol":signal["symbol"],"family":signal["family"],
            "methodology_sha256":signal["methodology_sha256"],
            "first_observed_utc":signal["first_observed_utc"],
            "signal_date":signal["signal_date"],
            "entry_date":bars[first]["date"].isoformat(),
            "exit_date":bars[final]["date"].isoformat(),
            "entry_open":entry,"exit_close":exit_close,
            "gross_pct":round(gross,5),
            "net_pct":round(gross-COST[market],5),
            "double_cost_net_pct":round(gross-2*COST[market],5),
            "benchmark_gross_pct":benchmark,
            "benchmark_peer_count":peers,
            "net_excess_over_frictionless_survivor_benchmark_pct":
                round(gross-COST[market]-benchmark,5) if benchmark is not None else None,
            "max_adverse_pct":round(100*(min(b["low"] for b in bars[first:final+1])/entry-1),5),
            "max_favorable_pct":round(100*(max(b["high"] for b in bars[first:final+1])/entry-1),5),
            "pit_price_adjustments_verified":False,"real_fill_verified":False,
            "paper_approved":False,"trade_authorized":False}
    return seal(result),None

def update(signals_series,settlement_series,signals_old,settled_old,observed_at,
           methodology,source_sha,recover=None,max_recover=10):
    existing={x["id"] for x in signals_old}
    new=[x for x in emit_signals(signals_series,observed_at,methodology,source_sha)
         if x["id"] not in existing]
    all_signals=signals_old+new
    recorded={x["id"] for x in settled_old}
    needed=[r for r in all_signals if r["id"] not in recorded]
    unavailable={key for key in {(x["market"],x["symbol"]) for x in needed} if key not in settlement_series}
    recovery_errors={}
    if recover and unavailable:
        # Rotate provider recovery attempts so permanently unavailable delistings
        # cannot starve other missing symbols across future scheduled runs.
        missing=sorted(unavailable)
        offset=date.fromisoformat(observed_at[:10]).toordinal()%len(missing)
        for key in (missing[offset:]+missing[:offset])[:max_recover]:
            try:
                value=recover(*key)
                if value:settlement_series[key]=value
            except (ValueError,OSError,KeyError,IndexError,TypeError) as ex:
                recovery_errors[key[0]+":"+key[1]]=type(ex).__name__
    new_settlements=[]
    pending=Counter()
    for r in needed:
        result,reason=settle(r,settlement_series)
        if result:new_settlements.append(result)
        else:pending[reason]+=1
    all_settled=settled_old+new_settlements
    distribution=defaultdict(list)
    for x in all_settled:distribution[(x["market"],x["family"],x["methodology_sha256"])].append(x)
    grouped=[]
    for (market,family,version),items in sorted(distribution.items()):
        grouped.append({"market":market,"family":family,"methodology_sha256":version,
             "n":len(items),"symbols":len({x["symbol"] for x in items}),
             "mean_net_pct":round(mean(x["net_pct"] for x in items),5),
             "mean_excess_pct":round(mean(x["net_excess_over_frictionless_survivor_benchmark_pct"]
                                     for x in items if x["net_excess_over_frictionless_survivor_benchmark_pct"] is not None),5)
                if any(x["net_excess_over_frictionless_survivor_benchmark_pct"] is not None for x in items) else None})
    summary={"schema":"EAR.prospective_research_ledger.v1","asof_utc":observed_at,
        "methodology_sha256":methodology,"current_source_csv_sha256":source_sha,
        "new_signals":len(new),"all_signals":len(all_signals),
        "new_settlements":len(new_settlements),"all_settlements":len(all_settled),
        "unsettled_reasons":dict(sorted(pending.items())),
        "recovery_errors":recovery_errors,"historical_pit_verified":False,
        "real_fill_verified":False,"paper_approved":False,"trade_authorized":False,
        "profitable_strategy_confirmed":False,
        "notes":"First-observed signals only; entry strictly AFTER observation UTC date. Survivorship and data-provider revisions unresolved.",
        "by_family":grouped}
    return all_signals,all_settled,summary

def fetch_missing_series(market,symbol):
    from datetime import datetime,timezone
    from research_v4.historical_real_data import yahoo_bars,binance_bars
    from research_v4.multimarket_exploratory import COST as known
    if market not in known:raise ValueError("UNKNOWN_MARKET")
    now=int(datetime.now(timezone.utc).timestamp()*1000)
    if market=="CRYPTO":rows=binance_bars(symbol,now)
    else:rows,_=yahoo_bars(symbol,market,now)
    # Independent of current selection: recover a once-observed disappearing symbol.
    out=[]
    for d,o,h,l,c,v in rows:
        out.append({"date":date.fromisoformat(d),"open":o,"high":h,"low":l,
                    "close":c,"volume":v,"pit":False,"actions":False})
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--signal-csv",required=True)
    p.add_argument("--settlement-csv",required=True)
    p.add_argument("--old-signals",required=True)
    p.add_argument("--old-settlements",required=True)
    p.add_argument("--out",default="out/prospective_evidence")
    p.add_argument("--asof")
    p.add_argument("--max-recover",type=int,default=10)
    a=p.parse_args()
    if not 0<=a.max_recover<=20:raise ValueError("INVALID_RECOVERY_LIMIT")
    now=a.asof or datetime.now(timezone.utc).isoformat()
    from hashlib import sha256
    source_sha=sha256(Path(a.signal_csv).read_bytes()).hexdigest()
    signals,settlements,report=update(load(a.signal_csv),load(a.settlement_csv),
        read_ledger(a.old_signals,"signal"),read_ledger(a.old_settlements,"settlement"),
        now,method_hash(),source_sha,recover=fetch_missing_series,max_recover=a.max_recover)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    write_ledger(out/"signals.jsonl",signals)
    write_ledger(out/"settlements.jsonl",settlements)
    (out/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# Prospective, as-of evidence (SIMULATION ONLY)","",
           f'New signals: {report["new_signals"]}; total: {report["all_signals"]}',
           f'New first-seen settlements: {report["new_settlements"]}; total: {report["all_settlements"]}',
           "Unsettled: "+json.dumps(report["unsettled_reasons"],sort_keys=True),
           "No real fills, PAPER approval, historical PIT proof, or confirmed profitable system."]
    (out/"report.md").write_text("\n\n".join(lines)+"\n")
    print("PROSPECTIVE_EVIDENCE",report["new_signals"],"new signals;",
          report["new_settlements"],"new matured; pending",report["unsettled_reasons"],flush=True)

if __name__=="__main__":main()
