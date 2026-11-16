"""Forward-only equity event outcomes from *previously committed* first-seen snapshots.

This is NOT historical OHLC backtest, no survivorship/PIT float validation,
no executable fills and no PAPER NAV. Each event signal uses only t and prior
observations; the next-session reference open and the fifth-session reference
close are observed strictly after that event.
"""
from __future__ import annotations
import argparse
from datetime import date
import json
from pathlib import Path
from statistics import mean, median
from radar.ledger import read_verify

MARKETS = ("BIST","US")
WARMUP_SESSIONS = 20
FORWARD_SESSIONS = 5
RVOL_THRESHOLD = 2.0
MAX_5SESSION_CHANGE = .08
STRESS_ROUND_TRIP_COST_PCT = {"BIST":2.0,"US":1.0}
MIN_EVENTS_FOR_RESEARCH = 30

def collect(ledger):
    rows = read_verify(ledger)
    series = {}
    for event in rows:
        seen = int(event["scan_utc_ms"])
        for market in MARKETS:
            payload = event.get("markets", {}).get(market, {})
            for sample in payload.get("sample", []):
                symbol = sample.get("symbol")
                bar = sample.get("last_bar")
                if not isinstance(symbol,str) or not isinstance(bar,dict):
                    continue
                day = bar.get("session_utc")
                if not isinstance(day,str):
                    continue
                try:
                    dt=date.fromisoformat(day)
                    o,c,v=float(bar["open"]),float(bar["close"]),float(bar["volume"])
                    ts=int(bar["ts_ms"])
                except (ValueError,KeyError,TypeError):
                    continue
                from math import isfinite
                if not all(isfinite(x) for x in (o,c,v)) or min(o,c)<=0 or v<0 or ts>seen:
                    continue
                key=(market,symbol)
                dest=series.setdefault(key,{})
                # Preserve the FIRST observer only. Later backfills/revisions
                # cannot rewrite an already-seen session.
                dest.setdefault(day,{"session":day,"date":dt,"open":o,"close":c,
                                     "volume":v,"seen_ms":seen,"bar_ms":ts})
    return {key:sorted(days.values(),key=lambda bar:bar["date"])
            for key,days in series.items()}, len(rows)

def consecutive_observed(segments):
    return all(0 < (b["date"]-a["date"]).days <= 5 for a,b in zip(segments,segments[1:]))

def study(ledger):
    series,ticks=collect(ledger)
    observed={m:len({p["session"] for (market,_),seq in series.items() if market==m for p in seq})
              for m in MARKETS}
    events=[]
    eligible=0
    for (market,symbol), seq in sorted(series.items()):
        if len(seq) >= WARMUP_SESSIONS+FORWARD_SESSIONS+1:
            eligible+=1
        last_event_index=-999
        for i in range(WARMUP_SESSIONS,len(seq)-FORWARD_SESSIONS):
            lookback=seq[i-WARMUP_SESSIONS:i+1]
            forward=seq[i+1:i+FORWARD_SESSIONS+1]
            # Do not bridge prolonged observation outages with invented sessions.
            if not consecutive_observed(lookback+forward):
                continue
            if i-last_event_index<=FORWARD_SESSIONS:
                continue
            baseline=median(x["volume"] for x in lookback[:-1])
            if baseline<=0:
                continue
            rvol=lookback[-1]["volume"]/baseline
            price_change=seq[i]["close"]/seq[i-5]["close"]-1
            if rvol < RVOL_THRESHOLD or abs(price_change)>MAX_5SESSION_CHANGE:
                continue
            # A signal is observable at the CLOSE of session i; event outcome
            # uses next session OPEN and the fifth following session CLOSE.
            start=forward[0]["open"]
            end=forward[-1]["close"]
            raw_pct=100*(end/start-1)
            cost_pct=STRESS_ROUND_TRIP_COST_PCT[market]
            events.append({"market":market,"symbol":symbol,
                           "signal_session":seq[i]["session"],
                           "signal_first_observed_ms":seq[i]["seen_ms"],
                           "next_open_first_observed_ms":forward[0]["seen_ms"],
                           "outcome_first_observed_ms":forward[-1]["seen_ms"],
                           "forward_sessions":FORWARD_SESSIONS,
                           "trigger_rvol":round(rvol,4),
                           "trigger_5session_price_change_pct":round(100*price_change,4),
                           "next_open_to_fifth_close_raw_move_pct":round(raw_pct,4),
                           "stress_cost_envelope_pct":cost_pct,
                           "raw_move_minus_assumed_cost_pct_NOT_FILL":round(raw_pct-cost_pct,4),
                           "not_executable":True})
            last_event_index=i
    by_market={}
    for market in MARKETS:
        subset=[e for e in events if e["market"]==market]
        vals=[e["next_open_to_fifth_close_raw_move_pct"] for e in subset]
        by_market[market]={"firstseen_sessions":observed[market],
                           "event_count":len(subset),"median_raw_move_pct":round(median(vals),4) if vals else None,
                           "mean_raw_move_pct":round(mean(vals),4) if vals else None,
                           "positive_raw_move_fraction":round(sum(x>0 for x in vals)/len(vals),4) if vals else None,
                           "decision":"RESEARCH_ONLY_NO_ALPHA_APPROVAL" if len(vals)>=MIN_EVENTS_FOR_RESEARCH
                                      else "INSUFFICIENT_PROSPECTIVE_EVENTS"}
    return {"schema":"EAR.V4.forward_event_diagnostic.v1",
            "ticks":ticks,"eligible_symbol_series":eligible,
            "minimum_warmup_sessions":WARMUP_SESSIONS,
            "forward_outcome_sessions":FORWARD_SESSIONS,
            "minimum_events_for_research":MIN_EVENTS_FOR_RESEARCH,
            "predeclared_trigger":{"relative_volume_min":RVOL_THRESHOLD,
                                   "absolute_previous_5session_return_max":MAX_5SESSION_CHANGE},
            "by_market":by_market,"events":events,
            "historical_backtest":False,"alpha_approved":False,"paper_approved":False,
            "trade_authorized":False,
            "limitations":["CURRENT_SCREENING_SAMPLE_NOT_COMPLETE_PIT_UNIVERSE",
                           "FIRST_SEEN_SERIES_MAY_HAVE_SURVIVORSHIP_AND_COVERAGE_BIAS",
                           "RAW_UNADJUSTED_PRICES_MAY_HAVE_SPLITS_DIVIDENDS",
                           "CLOSE_TO_CLOSE_OBSERVATION_CANNOT_PROVE_EXECUTION",
                           "ASSUMED_COSTS_NOT_MEASURED_SPREAD_OR_MARKET_IMPACT",
                           "NO_CAUSAL_ALPHA_OR_INDEPENDENT_BENCHMARK"]}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ledger",required=True)
    ap.add_argument("--out",default="out/v4_equity_audit")
    a=ap.parse_args()
    result=study(a.ledger)
    path=Path(a.out);path.mkdir(parents=True,exist_ok=True)
    (path/"forward_event_study.json").write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
    lines=["# First-seen forward event diagnostics", "",
           "**Observational study only. Not an executable strategy, verified backtest or new PAPER.**", "",
           f"SHA-verified evidence ticks: {result['ticks']}; eligible ticker series: {result['eligible_symbol_series']}", "",
           "| Market | First-seen sessions | Completed events | Median raw move % | Status |",
           "|---|---:|---:|---:|---|"]
    for market in MARKETS:
        x=result["by_market"][market]
        lines.append(f"| {market} | {x['firstseen_sessions']} | {x['event_count']} | {x['median_raw_move_pct']} | {x['decision']} |")
    (path/"forward_report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    print("V4_EQUITY_FORWARD_STUDY",result["ticks"],"events",len(result["events"]))
    return result

if __name__=="__main__":
    main()
