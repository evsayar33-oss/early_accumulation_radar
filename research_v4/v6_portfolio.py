"""Capital-aware, chronological research execution for fixed historical hypotheses.

NOT an executable backtest or investment performance proof: survivor-only data,
daily OHLC-based synthetic fills, missing historical PIT membership/delistings,
and exposed holdout. No signal/hypothesis tuning or automated promotion.
"""
from __future__ import annotations
import argparse,hashlib,json,math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from research_v4.multimarket_exploratory import load,COST
from research_v4.matched_benchmark import aligned_events

START_CAPITAL=10000.0
MAX_SLOTS=5
PARTICIPATION=.005
EXTRA_SLIPPAGE_BPS_PER_SIDE=15.0
MIN_ROUND_TRIPS=20

def partition_dates(series,market):
    days=sorted({b["date"].isoformat() for (m,_),seq in series.items() if m==market for b in seq})
    if len(days)<200:return []
    a=days[int(len(days)*.6)]
    b=days[int(len(days)*.8)]
    return [("train",[d for d in days if d<a]),
            ("validation",[d for d in days if a<=d<b]),
            ("previously_exposed_holdout",[d for d in days if d>=b])]

def simulate(series,events,market,family,days,capital=START_CAPITAL):
    if not days:return {"status":"NO_DATES"}
    # Daily price index; no forward fill for an actual position.
    prices={(sym,bar["date"].isoformat()):bar for (m,sym),seq in series.items()
            if m==market for bar in seq}
    candidates=defaultdict(list)
    first,last=days[0],days[-1]
    for e in events:
        if e["market"]!=market or e["family"]!=family:continue
        if not first<=e["entry_date"]<=last or e["outcome"]>last:continue
        if e["entry_date"]<=e["signal"]:continue
        candidates[e["entry_date"]].append(e)
    for day in candidates:
        # Deterministic allocation, no hindsight by future return/score.
        candidates[day].sort(key=lambda e:hashlib.sha256(
            (e["symbol"]+"|"+e["signal"]+"|"+e["family"]).encode()).hexdigest())
    cash=float(capital)
    positions={}
    equity_curve=[]
    exits=0
    wins=0
    total_costs=0.
    declined={"no_slot":0,"occupied":0,"no_bar":0,"liquidity":0,"bad_prices":0}
    days_in_market=0
    for day in days:
        for e in candidates.get(day,[]):
            symbol=e["symbol"]
            if symbol in positions:
                declined["occupied"]+=1;continue
            if len(positions)>=MAX_SLOTS:
                declined["no_slot"]+=1;continue
            bar=prices.get((symbol,day))
            if bar is None:
                declined["no_bar"]+=1;continue
            op=bar["open"]
            volume=bar["volume"]
            if not math.isfinite(op) or op<=0 or not math.isfinite(volume) or volume<=0:
                declined["bad_prices"]+=1;continue
            # Fractional crypto allowed; equities integer shares. Volume is in base shares/units.
            fees=COST[market]/200 + EXTRA_SLIPPAGE_BPS_PER_SIDE/10000.
            slot=min(capital/MAX_SLOTS, cash/(1+fees))
            max_notional=PARTICIPATION*volume*op
            order_notional=min(slot,max_notional)
            shares=order_notional/op
            if market!="CRYPTO":shares=math.floor(shares)
            notional=shares*op
            if shares<=0 or notional<10 or notional*(1+fees)>cash+1e-8:
                declined["liquidity"]+=1;continue
            cash-=notional*(1+fees)
            total_costs+=notional*fees
            positions[symbol]={"shares":shares,"entry":op,"exit_date":e["outcome"],
                "entry_notional":notional,"entry_fee":notional*fees,
                "last_close":op}
        for symbol,pos in list(positions.items()):
            bar=prices.get((symbol,day))
            if bar is not None:
                pos["last_close"]=bar["close"]
            if day==pos["exit_date"]:
                # Reject apparent exits on absent bars rather than fabricate fills.
                if bar is None:continue
                exit_fee=COST[market]/200+EXTRA_SLIPPAGE_BPS_PER_SIDE/10000.
                proceeds=pos["shares"]*bar["close"]*(1-exit_fee)
                cash+=proceeds
                total_costs+=pos["shares"]*bar["close"]*exit_fee
                pnl=proceeds-pos["entry_notional"]-pos["entry_fee"]
                wins+=pnl>0
                exits+=1
                del positions[symbol]
        if positions:days_in_market+=1
        equity=cash+sum(p["shares"]*p["last_close"] for p in positions.values())
        equity_curve.append(equity)
    if positions:
        # No fictional liquidation or success measure on open positions.
        ending_open=len(positions)
    else:ending_open=0
    high=capital
    max_dd=0.
    for value in equity_curve:
        high=max(high,value)
        max_dd=min(max_dd,value/high-1)
    nav=equity_curve[-1] if equity_curve else capital
    return {"status":"SIMULATED_UNVERIFIED","initial_capital":capital,
        "ending_mark_to_market":round(nav,2),
        "net_return_pct":round((nav/capital-1)*100,4),
        "max_drawdown_pct":round(max_dd*100,4),
        "closed_trades":exits,"win_rate_closed":round(wins/exits,4) if exits else None,
        "unclosed_positions":ending_open,
        "days_in_market":days_in_market,"calendar_bars":len(days),
        "estimated_fees_and_slippage":round(total_costs,2),
        "rejections":declined,
        "fill_assumption":"next daily open / daily close; fixed 15bps per leg additional slippage",
        "liquidity_assumption":"0.5 pct of reported daily base volume, no intraday market impact",
        "pnl_is_unverified":True}

def evaluate(series):
    events,_=aligned_events(series)
    output={"schema":"EAR.v6_capital_aware_research.v1",
        "paper_approved":False,"trade_authorized":False,"profitable_strategy_confirmed":False,
        "historical_pit_verified":False,"survivorship_bias_unresolved":True,
        "exposed_holdout":True,"performance_is_simulated":True,
        "overlapping_positions_limited_to":MAX_SLOTS,"liquidity_participation_limit":PARTICIPATION,
        "additional_slippage_bps_per_side":EXTRA_SLIPPAGE_BPS_PER_SIDE,
        "multiple_hypothesis_tests":45,"results":[]}
    families=sorted({e["family"] for e in events})
    for market in COST:
        groups=partition_dates(series,market)
        for family in families:
            if not groups:continue
            sims={name:simulate(series,events,market,family,days)
                  for name,days in groups}
            valid=sims["validation"]
            hold=sims["previously_exposed_holdout"]
            # Screening, not final evidence: realistic independent prospective data required.
            promising=(valid["closed_trades"]>=MIN_ROUND_TRIPS and
                 hold["closed_trades"]>=MIN_ROUND_TRIPS and
                 valid["net_return_pct"]>0 and hold["net_return_pct"]>0 and
                 valid["max_drawdown_pct"]>-25 and hold["max_drawdown_pct"]>-25 and
                 not valid["unclosed_positions"] and not hold["unclosed_positions"])
            output["results"].append({"market":market,"family":family,
                "train":sims["train"],"validation":valid,
                "previously_exposed_holdout":hold,
                "screen":"REQUIRES_INDEPENDENT_PROSPECTIVE_VALIDATION" if promising
                    else "REJECT_OR_INSUFFICIENT",
                "paper_approved":False})
    return output

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--out",default="out/v6_portfolio")
    a=p.parse_args()
    result=evaluate(load(a.csv))
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    lines=["# V6 capital-aware historical candidate screen","",
           "Research simulation only: surviving current assets; no delisted, historical PIT, verified market impact or live fills.",
           "The historically exposed holdout remains exposed. Positive returns do not authorize PAPER.","",
           "| Market | Family | Validation NAV % / DD % / trades | Exposed holdout NAV % / DD % / trades | Screen |",
           "|---|---|---|---|---|"]
    for r in result["results"]:
        fmt=lambda x:f'{x["net_return_pct"]} / {x["max_drawdown_pct"]} / {x["closed_trades"]}'
        lines.append("| "+" | ".join((r["market"],r["family"],fmt(r["validation"]),
                          fmt(r["previously_exposed_holdout"]),r["screen"]))+" |")
    (out/"report.md").write_text("\n".join(lines)+"\n")
    print("V6_PORTFOLIO_RESEARCH",len(result["results"]),"cells; no PAPER authorization")

if __name__=="__main__":main()
