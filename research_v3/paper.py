"""Timestamped prospective PAPER spot portfolio. Never submits exchange orders.

Uses Binance 1m closed-bar accumulation hypothesis and observed USDT bid/ask
quotes, cross-venue quote consensus and explicit assumed costs. No retro fills.
"""
from __future__ import annotations
import argparse,hashlib,json,os,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from radar.providers import fetch_quote,Quote
from radar.accumulation import fetch as fetch_candles
from radar.ledger import canonical,digest,read_verify
from .model import UNIVERSE,MODEL_VERSION,SCENARIOS,STARTING_CASH,STOP_PCT,TAKE_PCT,HOLD_MINUTES

ASSETS=tuple(x.removesuffix("USDT") for x in UNIVERSE)
QUOTE_VENUES=("binance","okx","gate")
MAX_POSITIONS=3
BUDGET_PCT=.10
MAX_EXPOSURE_PCT=.30
COOLDOWN_MS=60*60000
MARK_AGE_MS=120000
MODEL_FILES=("research_v3/paper.py","research_v3/model.py","radar/accumulation.py")
STATE_VERSION="EAR.paper.v1"

def fingerprint(paths=MODEL_FILES):
    h=hashlib.sha256()
    for path in paths:
        h.update(path.encode());h.update(Path(path).read_bytes())
    return h.hexdigest()

def fetch_snapshot(assets=ASSETS,quote_get=fetch_quote,candle_get=fetch_candles,clock=lambda:int(time.time()*1000)):
    quotes={a:[] for a in assets};candles={};errors=[]
    with ThreadPoolExecutor(max_workers=12) as executor:
        jobs={**{executor.submit(quote_get,v,a):("quote",v,a)
                  for a in assets for v in QUOTE_VENUES},
              **{executor.submit(candle_get,a):("candles","binance",a)
                  for a in assets}}
        for f in as_completed(jobs):
            kind,venue,asset=jobs[f]
            try:
                value=f.result()
                if kind=="quote":quotes[asset].append(value)
                else:candles[asset]=value
            except Exception as exc:
                errors.append({"kind":kind,"venue":venue,"asset":asset,
                               "error":type(exc).__name__+":"+str(exc)[:125]})
    now=clock()
    return {"observed_ms":now,"quotes":quotes,"candles":candles,
            "errors":sorted(errors,key=lambda x:(x["asset"],x["kind"],x["venue"]))}

def usable_quote(asset,snapshot):
    now=snapshot["observed_ms"]
    q=[x for x in snapshot["quotes"].get(asset,[]) if x.symbol==asset
       and x.market_type=="SPOT" and x.quote_currency=="USDT"
       and 0<=now-x.retrieved_ms<=MARK_AGE_MS and x.spread_bps<=25
       and min(x.top_bid_usd,x.top_ask_usd)>=500]
    if len({x.venue for x in q})<2:
        return None,"LESS_THAN_TWO_FRESH_USDT_VENUES"
    mids=sorted(x.mid for x in q);mid=mids[len(mids)//2]
    if max(abs(x.mid/mid-1)*10000 for x in q)>60:
        return None,"INCONSISTENT_CROSS_VENUE_QUOTES"
    for name in QUOTE_VENUES:
        choice=next((x for x in q if x.venue==name),None)
        if choice:return choice,None
    return None,"NO_QUOTE"

def fresh_signal(asset,snapshot):
    f=snapshot["candles"].get(asset)
    if not f or f.get("status")!="HYPOTHESIS_ONLY" or f.get("source_venue")!="binance":
        return None
    ts=f.get("last_closed_bar_ms")
    if not isinstance(ts,int) or ts>snapshot["observed_ms"] or snapshot["observed_ms"]-(ts+60000)>180000:
        return None
    return f

def initial_state(now,fp):
    return {"schema":STATE_VERSION,"model_version":MODEL_VERSION,"model_sha256":fp,
            "paper_start_ms":now,"first_seen_ms":now,
            "cash":STARTING_CASH,"positions":{},"last_observed_ms":0,
            "last_event_sha256":"GENESIS","last_liquidation_nav":STARTING_CASH,
            "peak_liquidation_nav":STARTING_CASH,"max_drawdown_pct":0.,
            "realized_pnl":0.,"closed_trades":0,"winning_trades":0,
            "gross_wins":0.,"gross_losses":0.,"outages":0,"last_exit_ms":{},
            "last_status":"STARTED","last_valid_mark_ms":None}

def validate_state(state,ledger_path,fp):
    rows=read_verify(ledger_path)
    if state is None:
        if rows:raise ValueError("EVIDENCE_PRESENT_WITHOUT_PAPER_STATE")
        return []
    if state.get("schema")!=STATE_VERSION:raise ValueError("INVALID_PAPER_STATE")
    if state.get("model_sha256")!=fp or state.get("model_version")!=MODEL_VERSION:
        raise ValueError("FROZEN_MODEL_CHANGED_STOP_PAPER_NO_SILENT_REBASE")
    if not rows or rows[-1]["sha256"]!=state.get("last_event_sha256"):
        raise ValueError("STATE_AND_EVENT_HASH_MISMATCH")
    if int(rows[-1]["scan_utc_ms"])!=int(state["last_observed_ms"]):
        raise ValueError("STATE_CLOCK_MISMATCH")
    return rows

def process(state,snapshot,fp):
    now=int(snapshot["observed_ms"])
    if state is None:state=initial_state(now,fp)
    if now<=state["last_observed_ms"]:raise ValueError("DUPLICATE_OR_REORDERED_PAPER_TICK")
    if state["model_sha256"]!=fp:raise ValueError("MODEL_FINGERPRINT_MISMATCH")
    cfg=SCENARIOS["base"];fee=cfg["fee_bps"]/10000;slip=cfg["slippage_bps"]/10000
    positions=state["positions"]
    selected={};missing={}
    for asset in ASSETS:
        q,reason=usable_quote(asset,snapshot)
        if q:selected[asset]=q
        else:missing[asset]=reason
    result={"schema":"EAR.paper.event.v1","scan_utc_ms":now,"model_sha256":fp,
            "real_orders":False,"paper_only":True,"transactions":[],
            "source_failures":snapshot["errors"],
            "no_quote_assets":missing,
            "quote_sources":{a:{"venue":q.venue,"source":q.source,
                                 "bid":q.bid,"ask":q.ask,"observed_ms":q.observed_ms}
                             for a,q in selected.items()},
            "signal_sources":{a:{"last_closed_bar_ms":f.get("last_closed_bar_ms"),
                                  "venue":f.get("source_venue"),
                                  "accumulation_watch":f.get("accumulation_watch"),
                                  "distribution_watch":f.get("distribution_watch")}
                              for a in ASSETS if (f:=fresh_signal(a,snapshot)) is not None}}
    if any(a not in selected for a in positions):
        state["outages"]+=1;state["last_status"]="UNMARKED_OUTAGE"
        result["status"]="UNMARKED_OUTAGE"
        result["nav"]=None  # never carry forward last NAV as a new mark
    else:
        # Mark at observed bids net of hypothetical liquidation fee/slippage.
        pre_nav=state["cash"]+sum(
           p["qty"]*selected[a].bid*(1-slip)*(1-fee) for a,p in positions.items())
        exited=set()
        for asset in list(positions):
            p=positions[asset];q=selected[asset]
            s=fresh_signal(asset,snapshot)
            reason=None
            if q.bid<=p["entry_reference"]*(1-STOP_PCT):reason="STOP_OBSERVED_BID"
            elif q.bid>=p["entry_reference"]*(1+TAKE_PCT):reason="TAKE_OBSERVED_BID"
            elif now-p["entry_ms"]>=HOLD_MINUTES*60000:reason="MAX_HOLD_OBSERVED"
            elif s and s["distribution_watch"]:reason="DISTRIBUTION_OBSERVED"
            if reason:
                proceeds=p["qty"]*q.bid*(1-slip)*(1-fee)
                pnl=proceeds-p["cost_usdt"]
                state["cash"]+=proceeds;state["realized_pnl"]+=pnl
                state["closed_trades"]+=1
                if pnl>0:
                    state["winning_trades"]+=1;state["gross_wins"]+=pnl
                elif pnl<0:state["gross_losses"]-=pnl
                result["transactions"].append({"asset":asset,"type":"PAPER_EXIT",
                   "reason":reason,"bid":q.bid,"venue":q.venue,
                   "entry_ms":p["entry_ms"],"qty":p["qty"],
                   "proceeds_usdt":round(proceeds,6),"net_pnl_usdt":round(pnl,6)})
                del positions[asset]
                state["last_exit_ms"][asset]=now;exited.add(asset)
        nav_after_exits=state["cash"]+sum(
           p["qty"]*selected[a].bid*(1-slip)*(1-fee) for a,p in positions.items())
        # One portfolio, not one fictitious separate portfolio per asset.
        for asset in ASSETS:
            if asset in positions or asset in exited or asset not in selected:continue
            if len(positions)>=MAX_POSITIONS:break
            s=fresh_signal(asset,snapshot)
            if not s or not s["accumulation_watch"]:continue
            if now-state["last_exit_ms"].get(asset,-10**15)<COOLDOWN_MS:continue
            q=selected[asset]
            desired=min(state["cash"],nav_after_exits*BUDGET_PCT)
            exposure=sum(p["cost_usdt"] for p in positions.values())
            if desired<100 or exposure+desired>nav_after_exits*MAX_EXPOSURE_PCT+1e-6:continue
            if q.top_ask_usd<desired or q.top_bid_usd<desired:
                result.setdefault("rejected_for_depth",[]).append(asset);continue
            effective_ask=q.ask*(1+slip)
            qty=desired/(effective_ask*(1+fee))
            positions[asset]={"qty":qty,"cost_usdt":desired,"entry_ms":now,
                "entry_reference":q.ask,"entry_venue":q.venue,
                "entry_effective":effective_ask}
            state["cash"]-=desired
            result["transactions"].append({"asset":asset,"type":"PAPER_ENTRY",
                "ask":q.ask,"venue":q.venue,"qty":round(qty,10),
                "cost_usdt":round(desired,6),"assumed_fee_bps":cfg["fee_bps"],
                "assumed_slippage_bps":cfg["slippage_bps"]})
        liquidation_nav=state["cash"]+sum(
           p["qty"]*selected[a].bid*(1-slip)*(1-fee) for a,p in positions.items())
        state["last_liquidation_nav"]=liquidation_nav
        state["last_valid_mark_ms"]=now
        state["peak_liquidation_nav"]=max(state["peak_liquidation_nav"],liquidation_nav)
        state["max_drawdown_pct"]=max(state["max_drawdown_pct"],
             100*(state["peak_liquidation_nav"]-liquidation_nav)/state["peak_liquidation_nav"])
        state["last_status"]="MARKED"
        result.update({"status":"MARKED","nav":round(liquidation_nav,6),
                       "pre_decision_nav":round(pre_nav,6),
                       "cash":round(state["cash"],6)})
    state["last_observed_ms"]=now
    result["positions"]={a:{"qty":round(p["qty"],10),"entry_ms":p["entry_ms"],
                            "cost_usdt":round(p["cost_usdt"],6)}
                         for a,p in state["positions"].items()}
    result["summary"]=summary(state,now)
    return state,result

def summary(s,now):
    n=s["closed_trades"];loss=s["gross_losses"]
    return {"paper_start_ms":s["paper_start_ms"],"elapsed_days":round((now-s["paper_start_ms"])/86400000,4),
         "initial_cash_usdt":STARTING_CASH,"last_liquidation_nav_usdt":round(s["last_liquidation_nav"],4),
         "last_mark_is_current":s["last_valid_mark_ms"]==now,
         "return_pct":round((s["last_liquidation_nav"]/STARTING_CASH-1)*100,5),
         "max_drawdown_pct":round(s["max_drawdown_pct"],5),
         "closed_trades":n,"winning_trades":s["winning_trades"],
         "win_rate":round(s["winning_trades"]/n,5) if n else None,
         "profit_factor":round(s["gross_wins"]/loss,5) if loss>0 else None,
         "open_positions":len(s["positions"]),"outage_ticks":s["outages"],
         "checkpoint_days":{str(x):"REACHED" if now-s["paper_start_ms"]>=x*86400000 else "PENDING"
                             for x in (30,60,90)},
         "interpretation":"PROSPECTIVE_PAPER_COST_PROXY_NOT_EXECUTABLE_ALPHA"}

def tick(state_file="paper_state/state.json",ledger_file="paper_state/events.jsonl",
         output_file="out/v3_paper/latest.json",snapshot=None,
         model_fp=None):
    state_path=Path(state_file);ledger_path=Path(ledger_file)
    model_fp=model_fp or fingerprint()
    state=json.loads(state_path.read_text(encoding="utf8")) if state_path.exists() else None
    validate_state(state,ledger_path,model_fp)
    snapshot=snapshot if snapshot is not None else fetch_snapshot()
    state,event=process(state,snapshot,model_fp)
    event["prev_sha256"]=state["last_event_sha256"]
    event["sha256"]=digest(event)
    state["last_event_sha256"]=event["sha256"]
    ledger_path.parent.mkdir(parents=True,exist_ok=True)
    with ledger_path.open("a",encoding="utf8") as handle:
        handle.write(canonical(event)+"\n")
    tmp=state_path.with_suffix(".tmp");tmp.write_text(json.dumps(state,sort_keys=True,indent=2)+"\n",encoding="utf8")
    tmp.replace(state_path)
    validate_state(state,ledger_path,model_fp)
    output=Path(output_file);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(event,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print("PAPER_EVENT",event["status"],"NAV",event["nav"],"tx",len(event["transactions"]),
          "outages",state["outages"],"SHA",event["sha256"])
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf8") as f:
            f.write("## EAR V3 PAPER (no real orders)\n\n"+
                    json.dumps(event["summary"],indent=2)+"\n")
    return event

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",default="paper_state/state.json")
    p.add_argument("--ledger",default="paper_state/events.jsonl")
    p.add_argument("--out",default="out/v3_paper/latest.json")
    a=p.parse_args();tick(a.state,a.ledger,a.out)
if __name__=="__main__":main()
