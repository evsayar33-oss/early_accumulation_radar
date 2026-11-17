"""Original-target alignment + causal, instrument-normalized early-stage research.

These are NEW exploratory hypotheses, deliberately separate from frozen PAPER
and V5 forward evidence. Current-survivor daily OHLCV can NEVER prove
historical low-float, ownership concentration or shallow executable depth.
Future high/low may be used ONLY in outcomes, never to form entry signals.
"""
from __future__ import annotations
import argparse,json,math
from collections import Counter,defaultdict
from pathlib import Path
from statistics import mean,median
from research_v4.multimarket_exploratory import COST,load
from research_v4.v6_portfolio import partition_dates,simulate
from research_v4.v6_bidirectional import structural_gaps

LONG_FAMILIES=("prebreakout_pressure","quiet_base","absorption_probe")
RISK_FAMILIES=("supply_absorption_risk",)
FAMILIES=LONG_FAMILIES+RISK_FAMILIES
HORIZONS=(2,5,10)
MIN_BARS=90
COOLDOWN=10

def q(values,fraction):
    values=sorted(values)
    if not values:raise ValueError("EMPTY_QUANTILE")
    return values[int((len(values)-1)*fraction)]

def universe_fit(manifest):
    if manifest.get("source_class")!="CURRENT_ONLY_NOT_POINT_IN_TIME":
        raise ValueError("UNKNOWN_UNIVERSE_MANIFEST")
    result=[]
    for market in COST:
        rows=manifest["universe"].get(market,[])
        for r in rows:
            # Never infer float, holder concentration, depth, or a historic
            # qualifying universe from market cap / present-day turnover.
            cap=r.get("cap_snapshot_usd")
            if market=="BIST":state="MISSING_BIST_SIZE_FLOAT_AND_DEPTH"
            elif market=="US":state=("CURRENT_CAP_PROXY_FLOAT_DEPTH_MISSING"
                                       if isinstance(cap,(int,float)) and cap>0
                                       else "MISSING_US_CAP_FLOAT_DEPTH")
            else:state=("CURRENT_CEX_ALT_CAP_PROXY_NOT_DEX_OR_FLOAT"
                        if isinstance(cap,(int,float)) and cap>0
                        else "MISSING_CRYPTO_CAP_FLOAT_AND_DEX")
            result.append({"market":market,"symbol":r.get("symbol"),
              "source":r.get("selection_source"),
              "current_cap_usd":cap,"state":state,
              "historical_pit_membership_verified":False,
              "historical_float_verified":False,
              "orderbook_depth_verified":False,
              "original_target_verified":False})
    return result

def features(bars,i):
    if i<MIN_BARS:return None
    x=bars[i];prev=bars[i-60:i];recent=bars[i-10:i]
    volume=[b["volume"] for b in prev]
    medvol=median(volume)
    if medvol<=0 or x["volume"]<0:return None
    rng=[(b["high"]-b["low"])/b["close"] for b in prev]
    atr=median(rng)
    if atr<=0:return None
    prev20=bars[i-20:i]
    hi20=max(b["high"] for b in prev20)
    lo20=min(b["low"] for b in prev20)
    last10range=max(b["high"] for b in recent)/min(b["low"] for b in recent)-1
    historic10range=[]
    for k in range(i-59,i-9):
        window=bars[k:k+10]
        if len(window)==10:
            historic10range.append(max(b["high"] for b in window)/min(b["low"] for b in window)-1)
    close_loc=(x["close"]-x["low"])/(x["high"]-x["low"]) if x["high"]>x["low"] else .5
    close_change=x["close"]/bars[i-1]["close"]-1
    positive=sum(bars[j]["close"]>bars[j-1]["close"] for j in range(i-2,i+1))
    return {"rv":x["volume"]/medvol,
        "volume_spike":x["volume"]>q(volume,.8),
        "volume_normal":x["volume"]>=median(volume),
        "prior_volume_dry":median(b["volume"] for b in bars[i-5:i])<q(volume,.35),
        "narrow_base":last10range<median(historic10range),
        "tight_price":abs(close_change)<=.4*atr,
        "loc":close_loc,"atr":atr,
        "near_unbroken_high":x["close"]<=hi20 and (hi20-x["close"])/x["close"]<=1.5*atr,
        "near_unbroken_low":x["close"]>=lo20 and (x["close"]-lo20)/x["close"]<=1.5*atr,
        "positive_3":positive>=2,"close_change":close_change}

def signals(z):
    return {
        # No breakout needed. A plausible lead-up is only a hypothesis.
        "prebreakout_pressure":(z["near_unbroken_high"] and z["positive_3"] and
                                 z["volume_normal"] and z["loc"]>=.60),
        "quiet_base":(z["narrow_base"] and z["prior_volume_dry"] and
                      z["near_unbroken_high"] and z["loc"]>=.55),
        "absorption_probe":(z["volume_spike"] and z["tight_price"] and z["loc"]>=.55),
        # Equal-dollar buy/sell can leave price stationary. Without true signed
        # delta and full orderbook, this is a caution flag, not a short trade.
        "supply_absorption_risk":(z["volume_spike"] and z["tight_price"] and
                                  z["loc"]<=.35)}

def produce(series):
    events=[]
    no_features=Counter();suspects=Counter()
    for (market,symbol),bars in sorted(series.items()):
        flags=structural_gaps(bars)
        last_signal={name:-999 for name in FAMILIES}
        for i in range(MIN_BARS,len(bars)-max(HORIZONS)):
            # Signal eligibility is decided with past and present only.
            # Future scale changes censor an outcome, never a signal.
            if any(j in flags for j in range(max(1,i-60),i+1)):
                suspects[market]+=1
                continue
            z=features(bars,i)
            if z is None:
                no_features[market]+=1
                continue
            for family,active in signals(z).items():
                if not active or i-last_signal[family]<=COOLDOWN:continue
                last_signal[family]=i
                start=bars[i+1]["open"]
                if not math.isfinite(start) or start<=0:continue
                hdata={}
                for hold in HORIZONS:
                    if any(j in flags for j in range(i+1,i+hold+1)):
                        hdata[str(hold)]={"status":"CENSORED_FUTURE_PRICE_DISCONTINUITY",
                            "outcome":bars[i+hold]["date"].isoformat()}
                        continue
                    final=bars[i+hold]["close"]
                    delayed=bars[i+2]["open"]
                    gross=100*(final/start-1)
                    # All historical performance is long-underlying-only.
                    # Bearish family is risk research, not a synthetic short.
                    hdata[str(hold)]={"status":"MEASURED",
                        "outcome":bars[i+hold]["date"].isoformat(),
                        "gross_underlying_pct":round(gross,5),
                        "long_net_pct":round(gross-COST[market],5),
                        "double_cost_long_net_pct":round(gross-2*COST[market],5),
                        "delayed_long_net_pct":round(100*(final/delayed-1)-COST[market],5),
                        "future_max_high_pct_not_executable":round(
                           100*(max(b["high"] for b in bars[i+1:i+hold+1])/start-1),5)}
                events.append({"market":market,"symbol":symbol,"family":family,
                  "direction":"LONG_HYPOTHESIS" if family in LONG_FAMILIES else "RISK_ONLY",
                  "signal":bars[i]["date"].isoformat(),
                  "entry_date":bars[i+1]["date"].isoformat(),
                  "entry_open":start,
                  "relative_volume":round(z["rv"],4),
                  "relative_atr":round(z["atr"],6),
                  "horizons":hdata})
    return events,{"rejected_due_to_price_discontinuity_windows":dict(suspects),
                    "unusable_feature_windows":dict(no_features)}

def latest_watchlist(series):
    """Signals from most recent available closed daily bar. No future returns."""
    latest={m:max((bars[-1]["date"] for (mm,_),bars in series.items()
                   if mm==m and bars),default=None) for m in COST}
    output=[]
    for (market,symbol),bars in sorted(series.items()):
        if len(bars)<MIN_BARS+1 or bars[-1]["date"]!=latest[market]:
            continue
        i=len(bars)-1
        if any(j in structural_gaps(bars) for j in range(max(1,i-60),i+1)):
            continue
        z=features(bars,i)
        if z is None:continue
        for family,present in signals(z).items():
            if not present:continue
            output.append({"market":market,"symbol":symbol,
                "family":family,"signal_date":bars[-1]["date"].isoformat(),
                "direction":"LONG_HYPOTHESIS" if family in LONG_FAMILIES else "RISK_ONLY",
                "signal_close_unfilled":bars[-1]["close"],
                "paper_approved":False,"trade_authorized":False,
                "original_target_verified":False})
    return output

def stats(records,hold):
    records=[e for e in records if e["horizons"][str(hold)]["status"]=="MEASURED"]
    x=[e["horizons"][str(hold)] for e in records]
    if not x:return {"n":0,"symbols":0,"mean_net_pct":None,
                      "median_net_pct":None,"positive_fraction":None,
                      "double_cost_mean_pct":None,"delayed_mean_pct":None,
                      "max_high_hit_rate_not_executable":None}
    from statistics import median as med
    return {"n":len(x),"symbols":len({e["symbol"] for e in records}),
        "mean_net_pct":round(mean(z["long_net_pct"] for z in x),4),
        "median_net_pct":round(med(z["long_net_pct"] for z in x),4),
        "positive_fraction":round(mean(z["long_net_pct"]>0 for z in x),4),
        "double_cost_mean_pct":round(mean(z["double_cost_long_net_pct"] for z in x),4),
        "delayed_mean_pct":round(mean(z["delayed_long_net_pct"] for z in x),4),
        # The 2*ATR threshold is from the signal, not tuned on future results;
        # high within hold may be unreachable and is never counted as PnL.
        "max_high_hit_rate_not_executable":round(mean(
            z["future_max_high_pct_not_executable"]>200*e["relative_atr"]
            for e,z in zip(records,x)),4)}

def evaluate(series,manifest):
    align=universe_fit(manifest)
    events,exclusions=produce(series)
    watch=latest_watchlist(series)
    report={"schema":"EAR.v7_target_fit_research.v1","paper_approved":False,
      "trade_authorized":False,"profitability_confirmed":False,
      "original_target_universe_verified":False,
      "historical_pit_verified":False,"pristine_holdout":False,
      "market_profiles_not_parameter_optimized":True,
      "historically_delisted_assets_missing":True,
      "backtested_instrument_type":"CEX_SPOT_AND_LISTED_EQUITY_DAILY_BARS_NOT_DEX_TAPE",
      "parameters":"rolling prior-60 quantiles; relative ATR, volume and 10-day base; frozen 2/5/10-bar horizons",
      "missing_original_target_inputs":["BIST_FLOAT_CAP","US_ASOF_FLOAT","DEX_TOKEN_HOLDER_DISTRIBUTION",
                                        "VERIFIED_DEPTH_AND_LIQUIDITY","HISTORICAL_PIT_DELISTED_UNIVERSE"],
      "latest_closed_daily_watchlist":watch,
      "selection":{"manifest_count":len(align),"states":dict(Counter(x["state"] for x in align)),
                   "full_original_target_verified":0,
                   "rows":align},
      "exclusions":exclusions,"families":list(FAMILIES),"results":[],"portfolio_results":[]}
    for market in COST:
        partitions=partition_dates(series,market)
        if not partitions:continue
        periods={name:(part[0],part[-1]) for name,part in partitions if part}
        for family in FAMILIES:
            subset=[e for e in events if e["market"]==market and e["family"]==family]
            for hold in HORIZONS:
                groups={}
                for name,(start,stop) in periods.items():
                    # Neither signal nor outcome may cross partition.
                    filtered=[e for e in subset if start<=e["signal"]<=stop
                              and e["horizons"][str(hold)]["outcome"]<=stop]
                    groups[name]=stats(filtered,hold)
                report["results"].append({"market":market,"family":family,"hold_bars":hold,
                  "direction":"LONG_HYPOTHESIS" if family in LONG_FAMILIES else "RISK_ONLY",
                  **groups,"status":"EXPLORATORY_NOT_PIT_OR_TARGET_VERIFIED"})
            if family not in LONG_FAMILIES:continue
            # Use V6's shared cash/position/liquidity simulator, NOT independent
            # event means. Five-bar horizon is one fixed predeclared comparison.
            executable_candidates=[{"market":e["market"],"symbol":e["symbol"],"family":family,
                  "signal":e["signal"],"entry_date":e["entry_date"],
                  "outcome":e["horizons"]["5"]["outcome"]} for e in subset
                  if e["horizons"]["5"]["status"]=="MEASURED"]
            sims={name:simulate(series,executable_candidates,market,family,dates)
                  for name,dates in partitions}
            report["portfolio_results"].append({"market":market,"family":family,
                "simulated_5bar":sims,"status":"MODELLED_ONLY_NO_PAPER_OR_REAL_FILLS"})
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--csv",required=True)
    p.add_argument("--manifest",required=True)
    p.add_argument("--out",default="out/v7_target_fit")
    a=p.parse_args()
    manifest=json.loads(Path(a.manifest).read_text(encoding="utf8"))
    result=evaluate(load(a.csv),manifest)
    path=Path(a.out);path.mkdir(parents=True,exist_ok=True)
    (path/"report.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    lines=["# V7 original-target fit and early-stage hypothesis diagnostics","",
      "**NO historical alpha/PIT, target-float/depth verification or PAPER authorization.**",
      "BIST target cap/float missing; US current small-cap proxy lacks historical float; Binance CEX altcoins are not the DEX first-seen cohort.",
      "Frozen rolling-relative, per-instrument features; 2/5/10-bar forward studies and 5-bar simulated cash NAV.",
      "Only LONG_HYPOTHESIS families enter NAV. Bearish supply absorption is RISK_ONLY.","",
      "## Universe eligibility evidence","",
      "| Eligibility class | Count |","|---|---:|"]
    lines.extend(f"| {k} | {v} |" for k,v in sorted(result["selection"]["states"].items()))
    lines+=["","## Exploratory event diagnostics","","| Market | Family | Hold | Train n/net % | Valid n/net % | Exposed n/net % |",
          "|---|---|---:|---:|---:|---:|"]
    for r in result["results"]:
        fmt=lambda n:f"{r[n]['n']} / {r[n]['mean_net_pct']}"
        lines.append("| "+" | ".join((r["market"],r["family"],str(r["hold_bars"]),
            fmt("train"),fmt("validation"),fmt("previously_exposed_holdout")))+" |")
    lines+=["",f"## Latest daily closed-bar hypotheses (not entry alerts): {len(result['latest_closed_daily_watchlist'])}","",
            "These are from current survivor proxies, NOT real-time DEX orderflow or executable fills.",
            "", "## Capital-aware 5-bar diagnostics","","| Market | Long family | Validation NAV % | Exposed NAV % |",
          "|---|---|---:|---:|"]
    for r in result["portfolio_results"]:
        h=r["simulated_5bar"]
        lines.append(f"| {r['market']} | {r['family']} | {h['validation'].get('net_return_pct')} | {h['previously_exposed_holdout'].get('net_return_pct')} |")
    lines+=["","**No strategy may be promoted from this report.** Previously-exposed history, current survivor sample, unavailable delisted symbols, missing verified float and depth."]
    (path/"report.md").write_text("\n".join(lines)+"\n")
    print("V7_TARGET_FIT",len(result["results"]),"study cells",
          "NAV studies",len(result["portfolio_results"]),
          "target_verified",result["selection"]["full_original_target_verified"])

if __name__=="__main__":main()
