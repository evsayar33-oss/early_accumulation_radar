"""Frozen causal hypotheses shared by 1m historical backtest and forward paper.

Same 70-minute warmup and V2 feature semantics. Last completed bar is i-1;
any historical order is entered at bar i open, never at a known past close.
"""
from __future__ import annotations
from statistics import median

UNIVERSE=("BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","ADAUSDT","LINKUSDT","SUIUSDT")
MODEL_VERSION="EAR-V3-FIXED-20261116"
HIST_MONTHS=("2026-08","2026-09","2026-10")
STARTING_CASH=10_000.0
HOLD_MINUTES=240
COOLDOWN_MINUTES=10
STOP_PCT=.03
TAKE_PCT=.06
ALLOCATION=.95
SCENARIOS={
    "base":{"fee_bps":10,"half_spread_bps":3,"slippage_bps":7},
    "stress":{"fee_bps":20,"half_spread_bps":8,"slippage_bps":20},
}

def conditions(bars,i):
    """Use observations strictly before index i; return watch flags and controls."""
    if i<70: raise ValueError("70 strictly previous bars required")
    previous=bars[i-70:i-10]
    recent=bars[i-10:i]
    base=median(x["quote"] for x in previous)
    recent_med=median(x["quote"] for x in recent)
    total=sum(x["quote"] for x in recent)
    if base<=0 or total<=0: return {"acc":False,"dist":False,"breakout":False}
    buy=sum(x["buy"] for x in recent)
    ratio=recent_med/base
    fraction=buy/total
    change=recent[-1]["c"]/previous[-1]["c"]-1
    return {
        "acc": ratio>=1.8 and fraction>=.56 and -.03<=change<=.025,
        "dist":ratio>=1.5 and fraction<=.38 and change<=-.01,
        "breakout":ratio>=1.8 and recent[-1]["c"]>max(x["h"] for x in bars[i-61:i-1]),
    }

def metrics(trades,navs):
    pnl=[t["net_pnl"] for t in trades]
    winners=sum(x>0 for x in pnl)
    gains=sum(x for x in pnl if x>0)
    losses=-sum(x for x in pnl if x<0)
    top=navs[0];drawdown=0.
    for n in navs:
        top=max(top,n)
        drawdown=max(drawdown,(top-n)/top)
    return {"trades":len(trades),"wins":winners,
            "win_rate":round(winners/len(trades),5) if trades else None,
            "profit_factor":round(gains/losses,5) if losses else None,
            "max_drawdown_pct":round(drawdown*100,4),
            "net_return_pct":round((navs[-1]/navs[0]-1)*100,4) if len(navs)>1 else 0.,
            "last_nav":round(navs[-1],4)}

def simulate(bars,entry_mode="acc",scenario="base",start=0,end=None):
    if entry_mode not in ("acc","breakout"):raise ValueError("mode")
    cfg=SCENARIOS[scenario]
    end=len(bars) if end is None else min(end,len(bars))
    if end-start<100:raise ValueError("segment too short")
    cash=STARTING_CASH;pos=None;trades=[];navs=[STARTING_CASH]
    cooldown=start+70
    # Price impact beyond half-spread and fixed slippage is NOT measured.
    buy_markup=(cfg["half_spread_bps"]+cfg["slippage_bps"])/10000
    sell_markdown=buy_markup;fee=cfg["fee_bps"]/10000
    for i in range(start+70,end):
        b=bars[i]
        signal=conditions(bars,i)
        if pos:
            reason=None; exit_reference=None
            stop=pos["entry_reference"]*(1-STOP_PCT)
            take=pos["entry_reference"]*(1+TAKE_PCT)
            if b["l"]<=stop:
                reason="STOP_FIRST";exit_reference=min(stop,b["o"])
            elif b["h"]>=take:
                reason="TAKE";exit_reference=take
            elif signal["dist"]:
                reason="DISTRIBUTION";exit_reference=b["o"]
            elif i-pos["entry_index"]>=HOLD_MINUTES:
                reason="TIME";exit_reference=b["o"]
            if reason is not None:
                proceeds=pos["qty"]*exit_reference*(1-sell_markdown)*(1-fee)
                cash+=proceeds
                pnl=proceeds-pos["cost"]
                trades.append({"entry_ts":pos["entry_ts"],"exit_ts":b["ts"],
                    "entry_price":round(pos["entry_effective"],10),
                    "exit_reference":round(exit_reference,10),
                    "quantity":round(pos["qty"],10),
                    "net_pnl":round(pnl,6),
                    "net_return_pct":round(100*pnl/pos["cost"],5),"reason":reason})
                pos=None;cooldown=i+COOLDOWN_MINUTES
        # No same-bar exit and reentry. Historical entry uses NEXT candle open.
        if pos is None and i>=cooldown and signal[entry_mode] and cash>=100:
            allocation=cash*ALLOCATION
            fill=b["o"]*(1+buy_markup)
            qty=allocation/(fill*(1+fee))
            pos={"entry_index":i,"entry_ts":b["ts"],"entry_reference":b["o"],
                 "entry_effective":fill,"qty":qty,"cost":allocation}
            cash-=allocation
            cooldown=i+1
        mark=cash+(pos["qty"]*b["c"]*(1-sell_markdown)*(1-fee) if pos else 0)
        navs.append(mark)
    if pos:
        b=bars[end-1]
        proceeds=pos["qty"]*b["c"]*(1-sell_markdown)*(1-fee)
        cash+=proceeds
        pnl=proceeds-pos["cost"]
        trades.append({"entry_ts":pos["entry_ts"],"exit_ts":b["ts"],
            "entry_price":round(pos["entry_effective"],10),"exit_reference":b["c"],
            "quantity":round(pos["qty"],10),"net_pnl":round(pnl,6),
            "net_return_pct":round(100*pnl/pos["cost"],5),"reason":"SEGMENT_END"})
        navs[-1]=cash
    out=metrics(trades,navs)
    out["entry_mode"]=entry_mode
    out["scenario"]=scenario
    out["trades_ledger"]=trades
    out["bars_evaluated"]=end-(start+70)
    return out

def buyhold(bars,scenario="base",start=0,end=None):
    end=len(bars) if end is None else end
    cfg=SCENARIOS[scenario]
    impact=(cfg["half_spread_bps"]+cfg["slippage_bps"])/10000
    fee=cfg["fee_bps"]/10000
    enter=bars[start+70]["o"]*(1+impact)
    qty=(STARTING_CASH*ALLOCATION)/(enter*(1+fee))
    cash=STARTING_CASH*(1-ALLOCATION)
    navs=[STARTING_CASH]
    for b in bars[start+70:end]:
        navs.append(cash+qty*b["c"]*(1-impact)*(1-fee))
    return {"net_return_pct":round((navs[-1]/STARTING_CASH-1)*100,4),
            "max_drawdown_pct":metrics([],navs)["max_drawdown_pct"],
            "last_nav":round(navs[-1],4)}
