"""Append-only first-seen DEX evidence, separately from CEX historic backtests.

'First seen' is first recorded by THIS radar, not token creation/listing.
DexScreener samples are not executable quotes, verified custody, holder
concentration, securities, or continuous OHLCV. Missing followups stay missing.
Never reuse pair symbols as unique identity; chain and pair address are required.
"""
from __future__ import annotations
import argparse,json,math
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from statistics import median
from urllib.parse import quote
from radar.ledger import read_verify,digest,canonical
from research_v4.original_universe import (
    PAIRS,classify_pair,fetch_json,ALLOWED_CHAINS)

TRACK_MAX=8
TRACK_DAYS=14
HORIZONS_H=(24,72,168)
MAX_LATE_H=36

def identity(row):
    chain=row.get("chain")
    pair=row.get("pair_address")
    token=row.get("token_address")
    if chain not in ALLOWED_CHAINS or not isinstance(pair,str) or not pair or not isinstance(token,str) or not token:
        raise ValueError("INVALID_DEX_IDENTITY")
    return (chain,pair,token)

def ledger_read(path):
    entries=read_verify(path)
    for row in entries:
        if row.get("schema")!="EAR.dex_first_seen.v1" or not isinstance(row.get("pairs"),list):
            raise ValueError("DEX_LEDGER_SCHEMA_MISMATCH")
        for pair in row["pairs"]:
            identity(pair)
    return entries

def tracked(entries,now_ms,limit=TRACK_MAX):
    first={}
    for r in entries:
        for pair in r["pairs"]:
            key=identity(pair)
            if key not in first and pair.get("screen_watch") is True:
                first[key]=r["scan_utc_ms"]
    active=[key for key,at in first.items() if 0<=now_ms-at<=TRACK_DAYS*86400000]
    # Fair rotation without future outcomes: oldest age and lexical identity.
    active.sort(key=lambda key:(first[key],key))
    if not active:return []
    rotation=(now_ms//86400000)%len(active)
    return (active[rotation:]+active[:rotation])[:limit]

def fetch_followups(entries,now_ms,get=fetch_json,limit=TRACK_MAX):
    observations=[];errors=[]
    for chain,pair,token in tracked(entries,now_ms,limit=limit):
        url=PAIRS+"/"+quote(chain,safe="")+"/"+quote(token,safe="")
        try:
            rows=get(url)
            if not isinstance(rows,list):raise ValueError("DEX_PAIR_SCHEMA")
            hit=next((x for x in rows
                if isinstance(x,dict) and x.get("pairAddress")==pair and
                x.get("chainId")==chain),None)
            if hit is None:
                errors.append({"chain":chain,"pair":pair,"status":"PAIR_MISSING_IN_PROVIDER"})
                continue
            candidate=classify_pair(hit,now_ms,chain,token)
            if candidate is None:
                errors.append({"chain":chain,"pair":pair,"status":"WRONG_PRICE_IDENTITY"})
                continue
            observations.append(candidate)
        except (ValueError,TypeError,KeyError,OSError,RuntimeError) as exc:
            errors.append({"chain":chain,"pair":pair,"status":"SOURCE_UNAVAILABLE",
                "error_type":type(exc).__name__})
    return observations,errors

def snapshots(entries):
    first={}
    seen=defaultdict(list)
    for r in entries:
        for p in r["pairs"]:
            key=identity(p)
            first.setdefault(key,r["scan_utc_ms"])
            val=p.get("price_usd_snapshot_unverified")
            if isinstance(val,(int,float)) and not isinstance(val,bool) and math.isfinite(val) and val>0:
                seen[key].append((r["scan_utc_ms"],float(val)))
    return first,seen

def forward_report(entries):
    first,seen=snapshots(entries)
    results=[];counts=Counter()
    for key,at in sorted(first.items()):
        history=seen.get(key,[])
        original=next(((t,price) for t,price in history if t==at),None)
        metrics={}
        for hours in HORIZONS_H:
            maturity=at+hours*3600000
            later=next(((t,price) for t,price in history
                if maturity<=t<=maturity+MAX_LATE_H*3600000),None)
            if original is None:
                status="NO_PRICE_AT_RADAR_FIRST_SEEN"
            elif later is None:
                status="NO_OBSERVED_FOLLOWUP_NEAR_HORIZON"
            else:
                status="OBSERVED_SNAPSHOT_CHANGE_NOT_EXECUTABLE"
            counts[status]+=1
            metrics[str(hours)]={"status":status,
                "underlying_snapshot_return_pct":round(100*(later[1]/original[1]-1),5)
                  if status=="OBSERVED_SNAPSHOT_CHANGE_NOT_EXECUTABLE" else None,
                "followup_scan_utc":datetime.fromtimestamp(later[0]/1000,timezone.utc).isoformat()
                  if later is not None else None}
        results.append({"chain":key[0],"pair_address":key[1],"token_address":key[2],
             "first_seen_utc":datetime.fromtimestamp(at/1000,timezone.utc).isoformat(),
             "first_price_usd_unverified":original[1] if original else None,
             "horizons_hours":metrics})
    return {"schema":"EAR.dex_forward_snapshots.v1",
        "first_observed_by_radar_only":True,
        "not_token_listing_time":True,
        "samples_are_not_continuous_price_bars":True,
        "real_fills_verified":False,"security_verified":False,
        "paper_approved":False,"trade_authorized":False,
        "counts":dict(counts),"pairs":results}

def append_discovery(old,snapshot,followups):
    ts=snapshot.get("observed_ms")
    if not isinstance(ts,int) or ts<=0:raise ValueError("INVALID_DEX_SCAN_TIME")
    if old and ts<=old[-1]["scan_utc_ms"]:
        raise ValueError("DEX_OBSERVATION_TIME_NOT_MONOTONIC")
    combined={}
    for p in snapshot.get("observations",[]):
        if not isinstance(p,dict):continue
        try:key=identity(p)
        except ValueError:continue
        combined[key]=p
    for p in followups:
        if not isinstance(p,dict):continue
        try:key=identity(p)
        except ValueError:continue
        combined.setdefault(key,p)
    prior,_=snapshots(old)
    first_new=[key for key in combined if key not in prior]
    record={"schema":"EAR.dex_first_seen.v1","scan_utc_ms":ts,
      "provider_status":snapshot.get("status","UNKNOWN"),
      "provider_errors":len(snapshot.get("errors",[])),
      "pairs":[combined[key] for key in sorted(combined)],
      "new_pairs_radar_first_seen_count":len(first_new),
      "watch_count":sum(p.get("screen_watch") is True for p in combined.values()),
      "record_status":"RESEARCH_ONLY_NOT_PIT",
      "trade_authorized":False,"paper_approved":False,
      "prev_sha256":old[-1]["sha256"] if old else "GENESIS"}
    record["sha256"]=digest(record)
    return record

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--discovery",required=True)
    p.add_argument("--ledger",required=True)
    p.add_argument("--out",default="out/dex_forward_evidence")
    p.add_argument("--no-network",action="store_true",help="offline test/reprocess only, no followup calls")
    a=p.parse_args()
    old=ledger_read(a.ledger)
    discovery=json.loads(Path(a.discovery).read_text())
    followups,errors=([],[]) if a.no_network else fetch_followups(
        old,int(discovery["observed_ms"]))
    new=append_discovery(old,discovery,followups)
    ledger=Path(a.ledger);ledger.parent.mkdir(parents=True,exist_ok=True)
    with ledger.open("a",encoding="utf8") as f:f.write(canonical(new)+"\n")
    report=forward_report(old+[new])
    report["latest_first_seen_pairs"]=new["new_pairs_radar_first_seen_count"]
    report["latest_followup_errors"]=errors
    report["current_ledger_ticks"]=len(old)+1
    output=Path(a.out);output.mkdir(parents=True,exist_ok=True)
    (output/"report.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["# Early-stage DEX first-observed cohort and subsequent snapshots","",
       "**Causal first-seen ledger**: source snapshots persist, no retroactive token history.",
       "Only BASE-token price may be matched. Real liquidity, float, holder distribution, security and fills are NOT verified.",
       f'Existing scans: {len(old)+1}; newly observed pairs: {new["new_pairs_radar_first_seen_count"]}.',
       "24/72/168-hour observation return requires a subsequent independent scan; absence is PENDING, not 0% or a win.","",
       "## Outcome availability","",
       "| State | Number |","|---|---:|"]
    lines.extend(f"| {k} | {v} |" for k,v in sorted(report["counts"].items()))
    (output/"report.md").write_text("\n".join(lines)+"\n")
    print("DEX_FIRST_SEEN",len(old)+1,"ticks",new["new_pairs_radar_first_seen_count"],
        "new pairs",len(errors),"followup source gaps")

if __name__=="__main__":main()
