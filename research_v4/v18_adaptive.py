"""V18: event discovery, adaptive experiment memory and independent frozen forward studies.

Historical OHLC outcomes are retrospective discovery, NOT first-seen signals.
The immutable forward ledger starts at the actual fetch time, and never uses
an open preceding that time. Existing V3/V8--V17 records are read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import os

from radar.ledger import canonical, digest, read_verify
import base64
import zlib
from research_v4 import v18_sources as source
from research_v4.multimarket_exploratory import COST

VERSION = "EAR.adaptive.v18.1"
DAY = 86_400_000
HORIZON = {"CRYPTO":16,"BIST":5,"US":5}
THRESHOLD = {"CRYPTO":12.0,"BIST":12.0,"US":15.0}
MARKETS = tuple(HORIZON)
DIRECTIONS = ("UP","DOWN")
MAX_EXPERIMENTS = 20
HISTORICAL_WINDOWS = {"CRYPTO":12,"BIST":48,"US":48}
MIN_CASES = 30
MIN_CONTROLS = 200
TRIAL_DAYS = 30
GRACE_DAYS = 14
MAX_HISTORY_ROWS = 30_000
MAX_SHARD_BYTES = 8 * 1024 * 1024
MAX_COMPRESSED_STATE = 96 * 1024 * 1024
NATIVE = ("volume_high","volume_z2","quiet","compression","upper_close","lower_close",
          "range_expansion","prior_drawdown","breakout","breakdown","taker_buy","taker_sell",
          "oi_rise","funding_positive","basis_positive","tight_spread")
MACRO = tuple("macro_"+s+"_inflow" for s in ("SPY","IWM","IBIT","ETHA","GLD","SGOV"))

def utc(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()

def clean_json(x):
    return json.loads(canonical(x))

def catalog(market,generation=0,retained=None,keep=None):
    """Actual Eaverse grammar + indicator evaluator, commit-pinned by workflow.
    Same feature IDs across all runs; deliberately not a claim of exhaustive tests.
    """
    from eaverse import indicator_bank as bank
    result={}
    frames=("1d","1w") if market!="CRYPTO" else ("15m","1h","4h")
    for frame in frames:
        for name in bank.FAMILIES:
            for i in range(2):
                seed=digest([VERSION,market,frame,name,i])
                spec=bank.choose(name,random.Random(seed),default=i==0,frame=frame)
                result["e_"+digest([frame,spec])[:12]]={"frame":frame,"rule":spec}
    if generation:
        for slot in range(6):
            frame=frames[(generation+slot)%len(frames)]
            name=bank.FAMILIES[(generation*6+slot)%len(bank.FAMILIES)]
            spec=bank.choose(name,random.Random(digest([VERSION,market,generation,slot])),frame=frame)
            key="e_"+digest([frame,spec])[:12]
            if key not in result:result[key]={"frame":frame,"rule":spec,"generation":generation}
        # Preserve frozen/active-paper parameters; retire only unneeded old
        # proposals, not observations or negative results.
        for key,spec in (retained or {}).items():
            if key not in result and (spec.get("generation",0)>=generation-8 or key in (keep or set())):
                result[key]=spec
    return result

def compute_flags(bars, market, specs):
    import numpy as np
    import pandas as pd
    from eaverse import indicator_bank as bank
    frame=pd.DataFrame(bars)
    c,h,l,v=frame.close,frame.high,frame.low,frame.volume
    rng=(h-l)/c
    prior_vol=v.shift(1).rolling(20)
    prior_rng=rng.shift(1).rolling(20).median()
    ret=c.pct_change(4)
    location=(c-l)/(h-l).where(h>l)
    def compare(series, op):
        return [(bool(op(x)) if np.isfinite(x) else None) for x in series]
    flags={
        "volume_high":compare(v/prior_vol.median().where(prior_vol.median()>0),lambda x:x>=1.8),
        "volume_z2":compare((v-prior_vol.mean())/prior_vol.std().where(prior_vol.std()>0),lambda x:x>=2),
        "quiet":compare(ret,lambda x:abs(x)<=.03),
        "compression":compare(rng.rolling(4).median()/prior_rng.where(prior_rng>0),lambda x:x<=.65),
        "upper_close":compare(location,lambda x:x>=.8),
        "lower_close":compare(location,lambda x:x<=.2),
        "range_expansion":compare(rng/prior_rng.where(prior_rng>0),lambda x:x>=2),
        "prior_drawdown":compare(c/c.shift(1).rolling(20).max()-1,lambda x:x<=-.1),
        "breakout":compare(c/h.shift(1).rolling(20).max()-1,lambda x:x>0),
        "breakdown":compare(c/l.shift(1).rolling(20).min()-1,lambda x:x<0),
    }
    buy=frame.get("buy_fraction",pd.Series(np.nan,index=frame.index))
    flags["taker_buy"]=compare(buy,lambda x:x>.65)
    flags["taker_sell"]=compare(buy,lambda x:x<.35)
    errors={}
    aggregated={}
    for key,spec in specs.items():
        try:
            tf=spec["frame"]
            if tf in ("1d","15m"):
                f,ok=bank.signal(frame,spec["rule"])
                flags[key]=[bool(x) if bool(y) else None for x,y in zip(f,ok)]
            else:
                if tf not in aggregated:
                    groups=defaultdict(list)
                    width={"1h":3600000,"4h":14400000}.get(tf)
                    for i,b in enumerate(bars):
                        if width:
                            bucket=b["start"]//width
                        else:
                            date=datetime.fromtimestamp(b["start"]/1000,timezone.utc).date()
                            bucket=(date.toordinal()-date.weekday())//7
                        groups[bucket].append(i)
                    blocks=[];ends=[]
                    for indexes in groups.values():
                        chunk=[bars[i] for i in indexes]
                        if width:
                            if len(chunk)!=width//source.BAR_MS or chunk[0]["start"]%width or not valid_path(chunk,market):continue
                        else:
                            # Avoid partially observed calendar weeks.
                            if datetime.fromtimestamp(chunk[-1]["start"]/1000,timezone.utc).weekday()!=4 or len(chunk)<3:continue
                        blocks.append({"open":chunk[0]["open"],"high":max(b["high"] for b in chunk),
                                      "low":min(b["low"] for b in chunk),"close":chunk[-1]["close"],
                                      "volume":sum(b["volume"] for b in chunk)})
                        ends.append(chunk[-1]["end"])
                    aggregated[tf]=(pd.DataFrame(blocks),ends)
                larger,ends=aggregated[tf]
                if larger.empty:
                    flags[key]=[None]*len(bars);continue
                f,ok=bank.signal(larger,spec["rule"])
                from bisect import bisect_right
                vals=[bool(x) if bool(y) else None for x,y in zip(f,ok)]
                positions=[bisect_right(ends,b["end"])-1 for b in bars]
                flags[key]=[vals[i] if i>=0 else None for i in positions]
        except (ValueError,KeyError,TypeError,IndexError,ArithmeticError) as exc:
            flags[key]=[None]*len(frame)
            errors[key]=type(exc).__name__
    return flags,errors

def valid_path(bars,market):
    if not bars:
        return False
    for a,b in zip(bars,bars[1:]):
        if market=="CRYPTO" and b["start"]!=a["end"]:
            return False
        if market!="CRYPTO" and not 0<b["start"]-a["start"]<=7*DAY:
            return False
        if abs(b["open"]/a["close"]-1)>.75:
            return False
    return True

def outcome(bars, market, start_after, *, historical=False, now=None):
    """The first entry is strictly after first observation (or >= next bar for retrospective).
    Return mark-based outcome only. Never infer a missing bar or exact execution.
    """
    n=HORIZON[market]
    available=[b for b in bars if b["start"]>start_after or (historical and b["start"]==start_after)]
    if len(available)<n:
        return None
    window=available[:n]
    start=window[0]["start"]
    # No delayed/stale fill is silently substituted.
    delay=source.BAR_MS*2 if market=="CRYPTO" else 7*DAY
    if start-start_after>delay or not valid_path(window,market):
        return {"status":"CENSORED_GAP_OR_SCALE_CHANGE"}
    if now is not None and window[-1]["end"]>now:
        return None
    entry=window[0]["open"]
    exit_=window[-1]["close"]
    gross=100*(exit_/entry-1)
    up=100*(max(b["high"] for b in window)/entry-1)
    down=100*(min(b["low"] for b in window)/entry-1)
    # Extreme moves are retained unless likely split/rebase; no future-based signal deletion.
    if max(up,-down)>75:
        return {"status":"CENSORED_POSSIBLE_REBASE"}
    t=THRESHOLD[market]
    if market!="CRYPTO":
        up,down=gross,gross
    label="BOTH" if up>=t and down<=-t else "UP" if up>=t else "DOWN" if down<=-t else "NONE"
    return {"status":"COMPLETE_MARK_ONLY","label":label,"entry":start,"end":window[-1]["end"],
            "entry_open":entry,"exit_close":exit_,"gross_pct":round(gross,8),
            "up_pct":round(up,8),"down_pct":round(down,8),
            "bars_sha":digest(window),"bars":window,"first_next_open_is_not_verified_fill":True}

def obs_id(market,symbol,venue,stamp,kind):
    # No re-enrolment after source revisions or code changes.
    return digest([market,symbol,stamp,kind])

def liquidity(bars,i):
    vol=sum(b["volume"]*b["close"] for b in bars[max(0,i-19):i+1])
    return "L" if vol<1e6 else "M" if vol<1e7 else "H"

def firstseen_flags(micro, macro, market, seen):
    result={}
    if micro and abs(micro.get("ts",0)-seen)<=15*60_000:
        for name,key,threshold in (("funding_positive","funding_rate_pct",0),
                                   ("basis_positive","mark_basis_bps",0),("tight_spread","spread_bps",10)):
            x=micro.get(key)
            if isinstance(x,(int,float)) and math.isfinite(x):
                result[name]=x<threshold if name=="tight_spread" else x>threshold
    if macro.get("status")=="DATED_CONTEXT" and macro["seen"]<=seen:
        result.update(macro["flags"])
    return result

def records_from_panel(key,panel,asof,specs,known,allow_forward,macro):
    market,symbol,venue=key
    bars=panel["bars"]
    if not bars or any(b["end"]>asof for b in bars):raise ValueError("FUTURE_BAR_INPUT")
    # A gap/scale discontinuity resets all recursive indicator history.
    last_break=max((i for i in range(1,len(bars)) if not valid_path(bars[i-1:i+1],market)),default=0)
    bars=bars[last_break:]
    if len(bars)<61:return [],{}
    flagrows,errors=compute_flags(bars,market,specs)
    rows=[]
    n=HORIZON[market]
    # Nonoverlapping retrospective blocks; uniformly sample across the available
    # series (not on the realized winners). Crypto uses fixed UTC 4h boundaries.
    anchors=[i for i in range(60,len(bars)-n)
             if (bars[i]["end"]%(n*source.BAR_MS)==0 if market=="CRYPTO" else datetime.fromtimestamp(bars[i]["start"]/1000,timezone.utc).weekday()==4)]
    cap=HISTORICAL_WINDOWS[market]
    if len(anchors)>cap:
        anchors=[anchors[j*(len(anchors)-1)//(cap-1)] for j in range(cap)]
    def flags_at(i):
        return {k:v[i] for k,v in flagrows.items() if v[i] is not None}
    def usable(i):
        return valid_path(bars[max(0,i-90):i+1],market) and bool(flags_at(i))
    def make(i,kind,seen):
        bar=bars[i]
        return {"id":obs_id(market,symbol,venue,bar["end"],kind), "kind":kind,"market":market,
                "symbol":symbol,"venue":venue,"anchor":bar["end"],"seen":seen,"liquidity":liquidity(bars,i),
                "features":flags_at(i),"asof_bar_sha":digest(bars[max(0,i-90):i+1]),
                "corroboration":panel["corroboration"],"source_sha":panel.get("source_sha"),
                "method":VERSION,"feature_catalog_keys":sorted(specs),"prior_move_pct":round(100*(bar["close"]/bars[max(0,i-(8 if market=="CRYPTO" else 1))]["close"]-1),6)}
    for i in anchors:
        if not usable(i):continue
        row=make(i,"HISTORICAL_DISCOVERY",asof)
        if row["id"] in known:continue
        o=outcome(bars[i+1:],market,row["anchor"],historical=True,now=asof)
        if o and o["status"]=="COMPLETE_MARK_ONLY":
            row["outcome"]=o
            rows.append(row)
    i=len(bars)-1
    last=bars[i]
    # Latest completed bar actually received; no stale signal on an old sample.
    age_limit=45*60_000 if market=="CRYPTO" else 4*DAY
    if allow_forward and i>=60 and 0<=asof-last["end"]<=age_limit and usable(i):
        row=make(i,"FIRST_SEEN",asof)
        row["features"].update(firstseen_flags(panel.get("asof_microstructure"),macro,market,asof))
        row["macro_sha"]=macro.get("sha")
        micro=panel.get("asof_microstructure") or {}
        row["micro"]={k:micro[k] for k in ("ts","oi_contracts","funding_rate_pct","spread_bps","mark_basis_bps") if k in micro}
        if row["id"] not in known:
            rows.append(row)
    return rows,errors

def read_state(path):
    root=Path(path)
    if not root.exists():return []
    files=sorted(root.glob("ledger-*.jsonl"))
    if sum(f.stat().st_size for f in files)>MAX_COMPRESSED_STATE:raise ValueError("V18_STATE_CAPACITY_ARCHIVE_REQUIRED")
    result=[];prev="GENESIS";last=0
    for index,file in enumerate(files):
        if file.name!=f"ledger-{index:06d}.jsonl":raise ValueError("V18_MISSING_SHARD")
        for line in file.read_text(encoding="utf8").splitlines():
            r=json.loads(line);h=r.pop("sha256")
            if r["prev_sha256"]!=prev or digest(r)!=h or r["scan_utc_ms"]<=last:
                raise ValueError("V18_LEDGER_HASH_CHAIN_CORRUPT")
            raw=zlib.decompress(base64.b64decode(r["compressed"],validate=True))
            b=json.loads(raw)
            if b["observed_ms"]!=r["observed_ms"]:raise ValueError("V18_LEDGER_CLOCK")
            result.append({**b,"scan_utc_ms":r["scan_utc_ms"],"sha256":h})
            prev=h;last=r["scan_utc_ms"]
    if root.exists() and not result:raise ValueError("V18_EXISTING_STATE_EMPTY")
    return result

def append_batch(path, prior, batch):
    root=Path(path);root.mkdir(parents=True,exist_ok=True)
    stamp=max(batch["observed_ms"],prior[-1]["scan_utc_ms"]+1 if prior else 1)
    record={"observed_ms":batch["observed_ms"],"scan_utc_ms":stamp,
            "prev_sha256":prior[-1]["sha256"] if prior else "GENESIS",
            "compressed":base64.b64encode(zlib.compress(canonical(batch).encode(),9)).decode()}
    record["sha256"]=digest(record)
    files=sorted(root.glob("ledger-*.jsonl"))
    line=canonical(record)+"\n"
    current=files[-1] if files else root/"ledger-000000.jsonl"
    if current.exists() and current.stat().st_size+len(line.encode())>MAX_SHARD_BYTES:
        current=root/f"ledger-{len(files):06d}.jsonl"
    if sum(f.stat().st_size for f in files)+len(line.encode())>MAX_COMPRESSED_STATE:raise ValueError("V18_STATE_CAPACITY_ARCHIVE_REQUIRED")
    if len(line.encode())>MAX_SHARD_BYTES:raise ValueError("V18_BATCH_CAPACITY")
    with current.open("a",encoding="utf8") as f:f.write(line)
    if read_state(root)[-1]["sha256"]!=record["sha256"]:raise ValueError("V18_LEDGER_NOT_VERIFIED")
    return record

def restore(batches):
    observations={};settlements={};attempts={};locks={};decisions={};shadows={}
    cursor=0
    for b in batches:
        if b.get("schema")!=VERSION:
            raise ValueError("V18_LEDGER_SCHEMA")
        for row in b["observations"]:
            if row["id"] in observations:raise ValueError("V18_DUPLICATE_OBSERVATION")
            observations[row["id"]]=row
        for row in b["settlements"]:
            i=row["id"]
            if i not in observations or i in settlements:raise ValueError("V18_INVALID_SETTLEMENT")
            settlements[i]=row["outcome"]
        for a in b["attempts"]:attempts[a["rule_id"]]=a
        for x in b["locks"]:locks[x["id"]]=x
        for x in b["decisions"]:
            decisions[x["lock_id"]]=x
            lock=locks.get(x["lock_id"])
            if lock and lock["rule_id"] in attempts and x["status"]=="FORWARD_FAILED_OR_INSUFFICIENT":
                attempts[lock["rule_id"]]={**attempts[lock["rule_id"]],"forward_failed":True,
                    "forward_checks":x["receipt"]["checks"]}
        for x in b.get("shadows",[]):shadows[x["lock_id"]]=x
        cursor=b["cursor"]
    return observations,settlements,attempts,locks,decisions,shadows,cursor

def predicate(features,rule):
    vals=[]
    for key,wanted in rule["terms"]:
        val=features.get(key)
        if type(val) is not bool:
            return None
        vals.append(val==wanted)
    return all(vals) if rule.get("operator","all")=="all" else any(vals)

def rule_id(rule):
    r=dict(rule);r["terms"]=sorted(r["terms"])
    return digest([VERSION,r])

def rule(market,direction,terms,operator="all"):
    return {"market":market,"direction":direction,"terms":sorted([list(t) for t in terms]),"operator":operator}

ASOF_ONLY=set(MACRO)|{"oi_rise","funding_positive","basis_positive","tight_spread"}

def rows_for_rule(rows,r):
    keys={k for k,_ in r["terms"]}
    return [x for x in rows if (not keys.intersection(ASOF_ONLY) or x.get("kind")=="FIRST_SEEN")
            and all(k in x.get("feature_catalog_keys",x["features"]) for k in keys if k.startswith("e_"))]

def evaluate(rows,r):
    rows=rows_for_rule(rows,r)
    # Complete population denominator, including opposite-side moves.
    p=[]; missing=0
    groups=defaultdict(list)
    for x in rows:
        y=predicate(x["features"],r)
        if y is None:missing+=1;continue
        o=x["outcome"]
        case=o["label"]==r["direction"]
        gross=o["gross_pct"]*(1 if r["direction"]=="UP" else -1)
        trip=COST[r["market"]]
        item=(x,case,y,gross-trip,gross-2*trip)
        p.append(item)
        # Match exact period and liquidity rather than selected past winners.
        period=x["anchor"]//(4*3600000 if r["market"]=="CRYPTO" else DAY)
        groups[(period,x["liquidity"])].append(item)
    a=sum(case and y for _,case,y,_,_ in p);b=sum(case and not y for _,case,y,_,_ in p)
    c=sum(not case and y for _,case,y,_,_ in p);d=sum(not case and not y for _,case,y,_,_ in p)
    precision=a/(a+c) if a+c else None
    base=(a+b)/len(p) if p else None
    recall=a/(a+b) if a+b else None
    fpr=c/(c+d) if c+d else None
    trades=[u[3] for u in p if u[2]]
    stressed=[u[4] for u in p if u[2]]
    paired=[]
    for items in groups.values():
        yes=[u[4] for u in items if u[2]]
        no=[u[4] for u in items if not u[2]]
        if yes and no:paired.append(sum(yes)/len(yes)-sum(no)/len(no))
    s={"rows":len(rows),"valid":len(p),"missing":missing,"tp":a,"fn":b,"fp":c,"tn":d,
       "base_rate":base,"precision":precision,"recall":recall,"fpr":fpr,
       "lift":precision/base if precision is not None and base else None,
       "net_mean":sum(trades)/len(trades) if trades else None,
       "stress_mean":sum(stressed)/len(stressed) if stressed else None,
       "matched_blocks":len(paired),"matched_stress_excess":sum(paired)/len(paired) if paired else None,
       "case_symbols":len({x["symbol"] for x,case,*_ in p if case}),
       "case_days":len({x["anchor"]//DAY for x,case,*_ in p if case})}
    if a+b<MIN_CASES or c+d<MIN_CONTROLS or s["case_symbols"]<5 or s["case_days"]<5:
        reason="INSUFFICIENT_EVIDENCE"
    elif a<5 or recall<.10:
        reason="MISSED_EVENTS"
    elif fpr>.15 or precision is None or s["lift"]<1.5:
        reason="FALSE_ALARMS"
    elif s["stress_mean"] is None or s["stress_mean"]<=0 or s["matched_blocks"]<5 or (s["matched_stress_excess"] or 0)<=0:
        reason="COST_OR_CONTROL_FAILURE"
    else:reason="DISCOVERY_PROMISING"
    s["reason"]=reason
    return s

def proposals(market,specs,attempts,rows,seed,budget=MAX_EXPERIMENTS):
    """40/30/20/10 exploit/explore/missed/invert, with no duplicate dataset replay.
    Negative results choose a different hypothesis, not a lower success gate.
    """
    features=sorted(set(NATIVE+MACRO)|set(specs))
    active_features={k for x in rows for k in x["features"]}
    features=[k for k in features if k in active_features]
    prior=[v for v in attempts.values() if v["rule"]["market"]==market]
    rng=random.Random(seed)
    candidates={"exploit":[],"explore":[],"missed":[],"reverse":[]}
    for k in features:
        for direction in DIRECTIONS:
            candidates["explore"].append(rule(market,direction,[(k,True)]))
    rng.shuffle(candidates["explore"])
    positives=sorted([a for a in prior if a["stats"]["reason"]=="DISCOVERY_PROMISING" and not a.get("forward_failed")],
                     key=lambda a:-(a["stats"]["matched_stress_excess"] or 0))
    failing=[a for a in prior if a.get("forward_failed") or a["stats"]["reason"] in ("MISSED_EVENTS","FALSE_ALARMS","COST_OR_CONTROL_FAILURE")]
    for a in (positives+prior)[:80]:
        r=a["rule"]
        for k in rng.sample(features,min(6,len(features))):
            if k not in {x[0] for x in r["terms"]} and len(r["terms"])<3:
                candidates["exploit"].append(rule(market,r["direction"],r["terms"]+[[k,True]]))
    for a in failing[-80:]:
        r=a["rule"]
        for k in rng.sample(features,min(5,len(features))):
            if k not in {x[0] for x in r["terms"]} and len(r["terms"])<3:
                # Misses: broaden with OR; false alarms: tighten with AND.
                candidates["missed"].append(rule(market,r["direction"],r["terms"]+[[k,True]],
                                      "any" if a["stats"]["reason"]=="MISSED_EVENTS" else "all"))
        candidates["reverse"].append(rule(market,"DOWN" if r["direction"]=="UP" else "UP",r["terms"],r["operator"]))
        if len(r["terms"])==1:
            k,v=r["terms"][0]
            candidates["reverse"].append(rule(market,r["direction"],[(k,not v)]))
    # Initial inverse / interaction controls even before first results.
    for k in features:
        for direction in DIRECTIONS:
            candidates["reverse"].append(rule(market,direction,[(k,False)]))
    allocated=[];selected=set()
    def pick(lane,count):
        for r in candidates[lane]:
            if count<=0:return
            rid=rule_id(r);old=attempts.get(rid)
            if rid in selected:continue
            scoped=rows_for_rule(rows,r)
            if not scoped:continue
            dataset=digest(sorted(x["id"]+":"+x["outcome"]["bars_sha"] for x in scoped))
            if old and (old["dataset"]==dataset or (len(scoped)-old["stats"]["rows"]<max(30,math.ceil(.15*old["stats"]["rows"])) and max(x.get("anchor",0) for x in scoped)-old.get("latest_anchor",0)<30*DAY)):
                continue
            selected.add(rid);allocated.append((lane,rid,r,dataset));count-=1
    for lane,weight in (("exploit",.4),("explore",.3),("missed",.2),("reverse",.1)):
        pick(lane,int(budget*weight))
    for lane in ("explore","missed","exploit","reverse"):
        pick(lane,budget-len(allocated))
    return allocated

def fresh_forward_rows(observations,settlements,lock):
    return [{**r,"outcome":settlements[i]} for i,r in observations.items()
            if r["kind"]=="FIRST_SEEN" and r["market"]==lock["rule"]["market"]
            and lock["start"]<=r["seen"]<lock["end"] and i in settlements
            and settlements[i]["status"]=="COMPLETE_MARK_ONLY"]

def run(state,panels,settle,asof,metadata,macro,specs_by_market,cursor=None,allow_forward=True,legacy=None):
    path=Path(state)
    old=read_state(path)
    obs,outcomes,attempts,locks,decisions,shadows,prior_cursor=restore(old)
    if old and asof<=old[-1]["observed_ms"]:raise ValueError("V18_CLOCK_REWIND")
    new=[];new_out=[];errors={}
    historical_intervals=defaultdict(list)
    for r in obs.values():
        if r["kind"]=="HISTORICAL_DISCOVERY":historical_intervals[(r["market"],r["symbol"])].append((r["outcome"]["entry"],r["outcome"]["end"]))
    occupied={(r["market"],r["symbol"]):r["seen"] for r in sorted(obs.values(),key=lambda v:v["seen"]) if r["kind"]=="FIRST_SEEN"}
    prior_micro={}
    for r in sorted(obs.values(),key=lambda x:x["seen"]):
        if r["kind"]=="FIRST_SEEN" and r.get("micro",{}).get("oi_contracts"):
            prior_micro[(r["symbol"],r["venue"])]=r
    for key,panel in sorted(panels.items()):
        market,symbol,venue=key
        cooldown=5*3600000 if market=="CRYPTO" else 8*DAY
        new_ok=allow_forward and asof-occupied.get((market,symbol),0)>=cooldown
        rows,err=records_from_panel(key,panel,asof,specs_by_market[market],set(obs),new_ok,macro)
        errors.update({market+":"+symbol+":"+k:v for k,v in err.items()})
        for r in rows:
            if r["kind"]=="HISTORICAL_DISCOVERY":
                interval=(r["outcome"]["entry"],r["outcome"]["end"])
                previous=historical_intervals[(market,symbol)]
                if any(interval[0]<b and a<interval[1] for a,b in previous):continue
                previous.append(interval)
            if r["kind"]=="FIRST_SEEN" and market=="CRYPTO":
                micro=r.get("micro",{})
                prev=prior_micro.get((symbol,venue))
                if prev and 0<r["seen"]-prev["seen"]<=48*3600000 and micro.get("oi_contracts") and abs(micro.get("ts",0)-r["seen"])<=15*60_000:
                    r["features"]["oi_rise"]=micro["oi_contracts"]/prev["micro"]["oi_contracts"]>=1.1
            obs[r["id"]]=r;new.append(r)
            if r["kind"]=="FIRST_SEEN":occupied[(market,symbol)]=r["seen"]
    for i,r in obs.items():
        if r["kind"]!="FIRST_SEEN" or i in outcomes:continue
        if r["seen"]>=asof:continue
        bars=settle.get((r["market"],r["symbol"],r["venue"]),[])
        o=outcome(bars,r["market"],r["seen"],now=asof)
        expiry=3*DAY if r["market"]=="CRYPTO" else 30*DAY
        if o is None and asof-r["seen"]>expiry:o={"status":"CENSORED_NO_SOURCE_OUTCOME"}
        if o:
            outcomes[i]=o;new_out.append({"id":i,"outcome":o})
    new_attempts=[];new_locks=[];new_decisions=[];new_shadows=[];event_audits=[]
    from research_v4.v18_validation import validate
    total_attempts=sum(len(b["attempts"]) for b in old)
    for market in MARKETS:
        market_locks=[x for x in locks.values() if x["rule"]["market"]==market]
        def holdout_overlap(r):
            return any(r["outcome"]["entry"]<x["end"]+GRACE_DAYS*DAY and
                       x["start"]<r["outcome"]["end"] for x in market_locks)
        historical=sorted((r for r in obs.values() if r["kind"]=="HISTORICAL_DISCOVERY" and r["market"]==market
                           and not holdout_overlap(r)),key=lambda x:(x["anchor"],x["id"]))[-MAX_HISTORY_ROWS:]
        # Use actual first-seen evidence preferentially, excluding overlapping
        # retrospective marks and never recycling a locked holdout into discovery.
        forward=[{**r,"outcome":outcomes[i]} for i,r in obs.items()
                 if r["kind"]=="FIRST_SEEN" and r["market"]==market and i in outcomes
                 and outcomes[i]["status"]=="COMPLETE_MARK_ONLY"]
        forward=[r for r in forward if not holdout_overlap(r)]
        intervals=defaultdict(list)
        for r in forward:intervals[r["symbol"]].append((r["outcome"]["entry"],r["outcome"]["end"]))
        rows=[r for r in historical if not any(a<r["outcome"]["end"] and r["outcome"]["entry"]<b
                                             for a,b in intervals[r["symbol"]])]+forward
        if not rows:continue
        batches=proposals(market,specs_by_market[market],attempts,rows,digest([market,len(rows),len(attempts)]))
        for lane,rid,r,data in batches:
            stats=evaluate(rows,r)
            a={"rule_id":rid,"rule":r,"lane":lane,"dataset":data,"stats":stats,"tested_at":asof,"latest_anchor":max(x["anchor"] for x in rows_for_rule(rows,r))}
            if attempts.get(rid,{}).get("forward_failed"):
                a["forward_failed"]=True
                a["forward_checks"]=attempts[rid].get("forward_checks",{})
            attempts[rid]=a;new_attempts.append(a)
        # Report actual missed, false-positive and late cases with identifiers;
        # they remain research labels, never Telegram advice.
        bests=[a for a in attempts.values() if a["rule"]["market"]==market and a["stats"]["valid"]>0]
        for direction in DIRECTIONS:
            best=max((a for a in bests if a["rule"]["direction"]==direction),
                     key=lambda a:(a["stats"]["reason"]=="DISCOVERY_PROMISING",a["stats"]["lift"] or 0),default=None)
            if not best:continue
            cats=defaultdict(list)
            for r in rows:
                hit=predicate(r["features"],best["rule"])
                case=r["outcome"]["label"]==direction
                label=("UNKNOWN" if hit is None else "MISSED" if case and not hit else
                       "FALSE_ALARM" if hit and not case else "LATE" if hit and case and abs(r["prior_move_pct"])>3
                       else "CORRECT" if hit and case else "CONTROL")
                if label!="CONTROL":
                    cats[label].append({"symbol":r["symbol"],"anchor":utc(r["anchor"]),"id":r["id"]})
            event_audits.append({"market":market,"direction":direction,"rule_id":best["rule_id"],
                                "counts":{k:len(v) for k,v in cats.items()},"examples":{k:v[-10:] for k,v in cats.items()}})
        active=[x for x in locks.values() if x["rule"]["market"]==market and x["id"] not in decisions]
        # Freeze at most one per market per 30-day cycle; don't relock a failed rule.
        if not active and not any(asof-x["created"]<TRIAL_DAYS*DAY for x in locks.values() if x["rule"]["market"]==market):
            prior={x["rule_id"] for x in locks.values()}
            possible=[a for a in new_attempts if a["rule"]["market"]==market and a["stats"]["reason"]=="DISCOVERY_PROMISING" and a["rule_id"] not in prior]
            for a in sorted(possible,key=lambda x:-(x["stats"]["matched_stress_excess"] or 0))[:3]:
                receipt=validate(a["rule"],rows_for_rule(rows,a["rule"]),stage="DISCOVERY",n_trials=max(1,total_attempts+len(new_attempts)))
                if receipt["verdict"]!="SCREEN_PASSED":continue
                lock={"id":digest([a["rule_id"],asof]),"rule":a["rule"],"rule_id":a["rule_id"],
                      "created":asof,"start":((asof//DAY)+1)*DAY,"end":((asof//DAY)+1+TRIAL_DAYS)*DAY,
                      "discovery_receipt":receipt,"n_trials":max(1,total_attempts+len(new_attempts))}
                locks[lock["id"]]=lock;new_locks.append(lock);break
    for lock in list(locks.values()):
        if lock["id"] in decisions or asof<lock["end"]+GRACE_DAYS*DAY:continue
        rows=fresh_forward_rows(obs,outcomes,lock)
        population=[r for r in obs.values() if r["kind"]=="FIRST_SEEN" and r["market"]==lock["rule"]["market"] and lock["start"]<=r["seen"]<lock["end"]]
        receipt=validate(lock["rule"],rows,stage="FORWARD",n_trials=lock["n_trials"],lock=lock)
        coverage=len(rows)/len(population) if population else 0
        status="FORWARD_REPLICATED_RESEARCH_ONLY" if receipt["verdict"]=="SCREEN_PASSED" and coverage>=.8 else "FORWARD_FAILED_OR_INSUFFICIENT"
        record={"lock_id":lock["id"],"rule":lock["rule"],"evaluated_at":asof,"status":status,"coverage":coverage,"receipt":receipt}
        decisions[lock["id"]]=record;new_decisions.append(record)
        # A research-only shadow candidate, NOT official Quant Superlab ACCEPT.
        # Long-only mark paper excludes unknown short borrow/liquidation and
        # begins after validation. Other directions stay detection studies.
        if status=="FORWARD_REPLICATED_RESEARCH_ONLY" and lock["rule"]["direction"]=="UP":
            shadow={"lock_id":lock["id"],"start":((asof//DAY)+1)*DAY,"initial_nav":10000,
                    "mode":"CONDITIONAL_MARK_PAPER_NOT_EXECUTABLE","duration_days":90,"rule":lock["rule"]}
            shadows[lock["id"]]=shadow;new_shadows.append(shadow)
    shadow_reports=[]
    for x in shadows.values():
        rows=[{**r,"outcome":outcomes[i]} for i,r in obs.items()
              if r["kind"]=="FIRST_SEEN" and r["market"]==x["rule"]["market"]
              and x["start"]<=r["seen"]<x["start"]+90*DAY and i in outcomes
              and outcomes[i]["status"]=="COMPLETE_MARK_ONLY" and predicate(r["features"],x["rule"]) is True]
        # Non-overlapping equal-weight groups; no leverage. Mark research, not fills.
        nav=x["initial_nav"];stress_nav=nav;peak=nav;dd=0.;last_end=0;trades=0;peak_time=x["start"];recovery_days=0
        by=defaultdict(list)
        for r in rows:by[r["outcome"]["entry"]].append(r)
        for entry,rs in sorted(by.items()):
            if entry<last_end:continue
            last_end=max(r["outcome"]["end"] for r in rs)
            net=sum((r["outcome"]["gross_pct"]-COST[r["market"]])/100 for r in rs)/len(rs)
            nav*=max(0,1+net)
            stress_nav*=max(0,1+net-COST[rs[0]["market"]]/100)
            if nav>=peak:
                peak=nav;peak_time=last_end
            else:recovery_days=max(recovery_days,(last_end-peak_time)/DAY)
            dd=max(dd,1-nav/peak);trades+=len(rs)
        shadow_reports.append({"lock_id":x["lock_id"],"nav":nav,"trades":trades,"max_drawdown":dd,
                               "stress_nav":stress_nav,"capital_survives":nav>0 and stress_nav>0,"max_underwater_days":recovery_days,
                               "paper_mode":x["mode"],"complete":asof>=x["start"]+(90+GRACE_DAYS)*DAY,
                               "trade_authorized":False})
    alerts=[]
    for x in decisions.values():
        if x["status"]!="FORWARD_REPLICATED_RESEARCH_ONLY":continue
        l=locks.get(x["lock_id"])
        if l is None or asof-x["evaluated_at"]>90*DAY:continue
        for r in new:
            if r["kind"]!="FIRST_SEEN" or r["market"]!=l["rule"]["market"] or r["seen"]<=x["evaluated_at"]:continue
            # A validated research rule must still trigger before a large move;
            # no signal if independent venue quotes diverge/are unavailable.
            if abs(r["prior_move_pct"])>3 or predicate(r["features"],l["rule"]) is not True:continue
            if r["market"]=="CRYPTO" and r["corroboration"]!="AGREEMENT":continue
            alert={"id":digest([l["id"],r["id"]]),"symbol":r["symbol"],"market":r["market"],
                   "direction":l["rule"]["direction"],"seen":r["seen"],"lock_id":l["id"],
                   "scope":"VALIDATED_ASSOCIATION_RESEARCH_ALERT_NOT_ORDER"}
            alerts.append(alert)
    alerts=alerts[:5]
    batch={"schema":VERSION,"observed_ms":asof,"cursor":prior_cursor if cursor is None else cursor,
           "observations":new,"settlements":new_out,"attempts":new_attempts,"locks":new_locks,
           "decisions":new_decisions,"shadows":new_shadows,"source":metadata,"macro":macro,"v8_recovery":legacy or [],"catalog":specs_by_market,"alerts":alerts}
    append_batch(path,old,batch)
    counts=Counter(r["outcome"]["label"] for r in obs.values() if r["kind"]=="HISTORICAL_DISCOVERY")
    counts.update(o["label"] for o in outcomes.values() if o["status"]=="COMPLETE_MARK_ONLY")
    report={"schema":VERSION,"asof":utc(asof),"source":metadata,"macro":macro,"indicator_errors":errors,
            "historical_observations":sum(r["kind"]=="HISTORICAL_DISCOVERY" for r in obs.values()),
            "first_seen_observations":sum(r["kind"]=="FIRST_SEEN" for r in obs.values()),
            "settlement_statuses":dict(Counter(o["status"] for o in outcomes.values())),
            "event_labels":dict(counts),"new_observations":len(new),"new_settlements":len(new_out),
            "unique_rules":len(attempts),"total_actual_tests":total_attempts+len(new_attempts),
            "new_tests":len(new_attempts),"test_lanes":dict(Counter(a["lane"] for a in new_attempts)),
            "rule_statuses":dict(Counter(a["stats"]["reason"] for a in attempts.values())),
            "event_audits":event_audits,
            "v8_recovery_total":dict(Counter(r["status"] for b in old+[batch] for r in b.get("v8_recovery",[]))),
            "new_locks":new_locks,"new_decisions":new_decisions,"new_shadows":new_shadows,"new_alerts":alerts,
            "active_locks":[x for x in locks.values() if x["id"] not in decisions],"mark_paper":shadow_reports,
            "paper_approved":False,"trade_authorized":False,"official_gate":"NOT_RUN"}
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",required=True);p.add_argument("--out",required=True)
    p.add_argument("--equity-csv");p.add_argument("--equity-quality");p.add_argument("--macro");p.add_argument("--v8-ledger")
    p.add_argument("--symbols",type=int,default=source.MAX_SYMBOLS)
    p.add_argument("--skip-crypto",action="store_true");a=p.parse_args()
    if not 1<=a.symbols<=source.MAX_SYMBOLS:raise ValueError("SYMBOL_BUDGET")
    path=Path(a.state)
    prior=read_state(path);obs,settlements,_,locks,decisions,shadows,cursor=restore(prior)
    t=source.now_ms()
    pending=[r for i,r in obs.items() if r["kind"]=="FIRST_SEEN" and i not in settlements]
    panels={};settle={};meta={}
    if not a.skip_crypto:
        panels,settle,cursor,meta["CRYPTO"]=source.collect_crypto(obs,pending,asof=t,cursor=cursor,limit=a.symbols)
    if a.equity_csv and a.equity_quality:
        ep=source.equity_panels(a.equity_csv,a.equity_quality,t)
        panels.update(ep);settle.update({k:v["bars"] for k,v in ep.items()})
        # Recover off-universe first-seen equity observations for settlement only.
        from research_v4.equity_followthrough import recover_settlement_universe
        from datetime import date
        for market in ("BIST","US"):
            selected={(m,s):[{"date":datetime.fromtimestamp(b["start"]/1000,timezone.utc).date(),
                               **{k:b[k] for k in ("open","high","low","close","volume")}} for b in v["bars"]]
                      for (m,s,_),v in ep.items() if m==market}
            prior_equity=[{**r,"observed_utc":utc(r["seen"])} for r in pending if r["market"]==market]
            rec,diagnostic=recover_settlement_universe(selected,market,prior_equity,datetime.fromtimestamp(t/1000,timezone.utc))
            for (m,s),bars in rec.items():
                if (m,s,"V5_YAHOO") in settle:continue
                settle[(m,s,"V5_YAHOO")]=[{**{k:b[k] for k in ("open","high","low","close","volume")},
                       "start":int(datetime.combine(b["date"],datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000),
                       "end":int(datetime.combine(b["date"],datetime.min.time(),tzinfo=timezone.utc).timestamp()*1000)+DAY} for b in bars]
            meta[market]={"panels":len(selected),"settlement_recovery":diagnostic}
    else:
        meta["EQUITIES"]={"status":"VERIFIED_V5_ARTIFACT_UNAVAILABLE"}
    # Recover a bounded batch of archived V8 pre-event cases without changing
    # any historical V8/V11/V13 labels or claiming executable old fills.
    from research_v4.v18_v8_recovery import recover
    known={r["id"] for b in prior for r in b.get("v8_recovery",[])
           if r["status"]=="COMPLETE_MARK_ONLY" or t-b["observed_ms"]<DAY}
    legacy,meta["V8_RECOVERY"]=recover(a.v8_ledger,known,t)
    if not panels and not settle and not legacy:
        out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
        (out/"source_failure.json").write_text(json.dumps(meta,indent=2)+"\n")
        raise RuntimeError("V18_NO_NATIVE_SOURCE_DATA")
    # Actual first observation time AFTER fetching, never the historical candle timestamp.
    seen=source.now_ms()
    macro=source.macro_context(a.macro,seen)
    if a.macro:
        commit_file=Path(a.macro).with_name("macro_commit.txt")
        if commit_file.is_file():macro["source_commit"]=commit_file.read_text().strip()
    meta["external_code"]={"eaverse":os.environ.get("V18_EAVERSE_PIN","LOCAL_TEST"),
                           "quant_superlab":os.environ.get("V18_SUPERLAB_PIN","LOCAL_TEST")}
    generation=seen//(7*DAY)
    last_catalog=prior[-1].get("catalog",{}) if prior else {}
    keep={k for x in locks.values() if x["id"] not in decisions for k,_ in x["rule"]["terms"]}
    keep.update(k for x in shadows.values() if seen<x["start"]+(90+GRACE_DAYS)*DAY for k,_ in x["rule"]["terms"])
    specs={m:catalog(m,generation,last_catalog.get(m,{}),keep) for m in MARKETS}
    report=run(path,panels,settle,seen,meta,macro,specs,cursor,legacy=legacy)
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    (out/"catalog.json").write_text(json.dumps(specs,indent=2,sort_keys=True)+"\n")
    print("EAR_V18",report["event_labels"],"new tests",report["new_tests"],"settlements",report["new_settlements"])

if __name__=="__main__":main()
