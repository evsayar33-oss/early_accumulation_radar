"""Fully offline historical execution proxy from official public Binance ZIP archives.

Archived SPOT timestamps since 2025 are microseconds; do not misread as ms.
Historical OHLC fills are NOT exchange-confirmed trades or independent live alpha.
"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,re,zipfile
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from .model import UNIVERSE,HIST_MONTHS,MODEL_VERSION,SCENARIOS,conditions,simulate,buyhold

ARCHIVE="https://data.binance.vision/data/spot/monthly/klines"
MAX_ZIP_BYTES=25*1024*1024
MAX_CSV_BYTES=40*1024*1024
STEP_MS=60000

def download(url,max_bytes=MAX_ZIP_BYTES):
    req=Request(url,headers={"User-Agent":"EAR-V3-historical-research/1.0"})
    with urlopen(req,timeout=35) as response:
        if response.status!=200:raise ValueError("HTTP_"+str(response.status))
        data=response.read(max_bytes+1)
        if len(data)>max_bytes:raise ValueError("ARCHIVE_SIZE_LIMIT")
        return data

def timestamp_ms(raw):
    value=int(raw)
    if value>=10**14: # 2025+ SPOT Binance Vision uses microseconds
        if value%1000!=0:raise ValueError("UNALIGNED_MICROSECOND_OPEN")
        value//=1000
    if value<10**12 or value%STEP_MS:raise ValueError("INVALID_UTC_TIMESTAMP")
    return value

def parse_zip(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        valid=[m for m in archive.infolist() if m.filename.endswith(".csv")
               and "/" not in m.filename and not m.is_dir()]
        if len(valid)!=1:raise ValueError("ARCHIVE_MUST_HAVE_SINGLE_CSV")
        info=valid[0]
        if info.file_size>MAX_CSV_BYTES:raise ValueError("UNCOMPRESSED_SIZE_LIMIT")
        bars=[]
        with archive.open(info) as f:
            reader=csv.reader(io.TextIOWrapper(f,encoding="utf8",newline=""))
            for line in reader:
                if not line:continue
                if not line[0].lstrip("-").isdigit():
                    if not bars and line[0].lower() in ("open_time","opentime"):
                        continue
                    raise ValueError("UNEXPECTED_CSV_ROW")
                if len(line)<12:raise ValueError("MISSING_TAKER_BUY_COLUMNS")
                ts=timestamp_ms(line[0])
                o,h,l,c=map(float,(line[1],line[2],line[3],line[4]))
                quote=float(line[7]);buy=float(line[10])
                from math import isfinite
                if not all(isfinite(v) for v in (o,h,l,c,quote,buy)):
                    raise ValueError("NONFINITE_PRICE_OR_VOLUME")
                if min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c) or quote<0 or buy<0 or buy>quote+1e-5:
                    raise ValueError("INVALID_PRICE_OR_VOLUME")
                bars.append({"ts":ts,"o":o,"h":h,"l":l,"c":c,"quote":quote,"buy":buy})
    if len(bars)<1000:raise ValueError("INSUFFICIENT_MONTHLY_HISTORY")
    if any(b["ts"]-a["ts"]!=STEP_MS for a,b in zip(bars,bars[1:])):
        raise ValueError("MONTHLY_CANDLE_GAP_OR_DUPLICATE")
    return bars

def get_month(symbol,month,get=download):
    url=f"{ARCHIVE}/{symbol}/1m/{symbol}-1m-{month}.zip"
    raw=get(url)
    sidecar=get(url+".CHECKSUM")
    m=re.search(rb"\b([a-fA-F0-9]{64})\b",sidecar)
    if not m:raise ValueError("MISSING_OFFICIAL_SHA256")
    expected=m.group(1).decode().lower()
    actual=hashlib.sha256(raw).hexdigest()
    if expected!=actual:raise ValueError("OFFICIAL_CHECKSUM_MISMATCH")
    bars=parse_zip(raw)
    for b in (bars[0],bars[-1]):
        if datetime.fromtimestamp(b["ts"]/1000,timezone.utc).strftime("%Y-%m")!=month:
            raise ValueError("MONTH_LABEL_TIMESTAMP_MISMATCH")
    return bars,{"source_url":url,"source_zip_sha256":actual,"official_checksum_verified":True,
                 "candles":len(bars),"first_ts_ms":bars[0]["ts"],"last_ts_ms":bars[-1]["ts"],
                 "timestamp_unit_in_archive":"MICROSECONDS_2025_PLUS"}

def load_symbol(symbol,months=HIST_MONTHS,get=download):
    if symbol not in UNIVERSE:raise ValueError("not precommitted")
    all_bars=[];source=[]
    for month in months:
        b,meta=get_month(symbol,month,get=get)
        if all_bars and b[0]["ts"]-all_bars[-1]["ts"]!=STEP_MS:
            raise ValueError("CROSS_MONTH_GAP")
        all_bars.extend(b);source.append(meta)
    return all_bars,source

def run(out_dir="out/v3_historical",get=download,universe=UNIVERSE,months=HIST_MONTHS):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    matrix=[];ledger=[];manifest={"model":MODEL_VERSION,"months":list(months),
             "universe":list(universe),"historical_first_seen_only":False,
             "point_in_time_universe_verified":False,
             "source":"OFFICIAL_BINANCE_SPOT_ARCHIVES","source_files":{},
             "data_errors":{},"scenarios":SCENARIOS,
             "historical_execution":"NEXT_1M_OPEN_PROXY_NOT_REAL_FILLS",
             "stop_priority":"STOP_FIRST_IF_SAME_CANDLE_TOUCHES_STOP_AND_TARGET",
             "historical_costs_are_assumed":True}
    for symbol in universe:
        try:
            bars,sources=load_symbol(symbol,months,get=get)
            manifest["source_files"][symbol]=sources
        except (ValueError,HTTPError,OSError,TimeoutError,zipfile.BadZipFile) as err:
            manifest["data_errors"][symbol]=type(err).__name__+":"+str(err)[:180]
            continue
        n=len(bars);cuts=[0,n//2,3*n//4,n]
        signals=[None]*n
        for i in range(70,n):
            signals[i]=conditions(bars,i)
        for group,(start,end) in {"ALL":(0,n),"EARLY":(cuts[0],cuts[1]),
                                  "MIDDLE":(cuts[1],cuts[2]),"TAIL":(cuts[2],cuts[3])}.items():
            if end-start<200:raise ValueError("INVALID_COHORT")
            for scenario in SCENARIOS:
                benchmark=buyhold(bars,scenario,start,end)
                for model in ("acc","breakout"):
                    result=simulate(bars,model,scenario,start,end,signals=signals)
                    trades=result.pop("trades_ledger")
                    item={"symbol":symbol,"cohort":group,
                          "start_ts":bars[start]["ts"],"end_ts":bars[end-1]["ts"],
                          "model":model,"scenario":scenario,**result,
                          "buyhold_return_pct":benchmark["net_return_pct"],
                          "excess_vs_buyhold_pct_points":round(result["net_return_pct"]-benchmark["net_return_pct"],4)}
                    matrix.append(item)
                    for t in trades:
                        ledger.append({"symbol":symbol,"cohort":group,"model":model,"scenario":scenario,**t})
        print("ARCHIVE_RESEARCH",symbol,"bars",n,"rows",len([r for r in matrix if r["symbol"]==symbol]),flush=True)
    manifest["symbols_testable"]=sorted(manifest["source_files"])
    manifest["symbols_untestable"]=sorted(manifest["data_errors"])
    # An untestable precommitted symbol is retained in the audit manifest, never substituted.
    result={"manifest":manifest,"matrix":matrix,"trades":ledger,
            "decision":"EXPLORATORY_BACKTEST_NOT_ALPHA_APPROVAL"}
    (out/"summary.json").write_text(json.dumps({"manifest":manifest,"matrix":matrix},indent=2,sort_keys=True)+"\n",encoding="utf8")
    with (out/"matrix.csv").open("w",newline="",encoding="utf8") as fh:
        cols=["symbol","cohort","model","scenario","start_ts","end_ts","trades",
              "wins","win_rate","profit_factor","max_drawdown_pct","net_return_pct",
              "last_nav","bars_evaluated","buyhold_return_pct","excess_vs_buyhold_pct_points"]
        w=csv.DictWriter(fh,fieldnames=cols);w.writeheader();w.writerows(matrix)
    with (out/"trades.csv").open("w",newline="",encoding="utf8") as fh:
        cols=["symbol","cohort","model","scenario","entry_ts","exit_ts",
              "entry_price","exit_reference","quantity","net_pnl","net_return_pct","reason"]
        w=csv.DictWriter(fh,fieldnames=cols);w.writeheader();w.writerows(ledger)
    lines=["# EAR V3 historical research (not forward execution proof)","",
           "Point-in-time membership NOT reconstructed; current predefined universe creates survivorship risk.",
           "Archives use official SHA-256 checksums. Assumed costs and OHLC execution proxy.",
           "No trading authorization, no tuning on the tail, no statistical alpha claim.","",
           "## Fixed predeclared cohort ALL: baseline-cost comparison","",
           "| Symbol | Model | Trades | Win % | Net % | Max DD % | Buy-and-hold net % |",
           "|---|---|---:|---:|---:|---:|---:|"]
    for m in matrix:
        if m["cohort"]=="ALL" and m["scenario"]=="base":
            win=f'{100*m["win_rate"]:.1f}' if m["win_rate"] is not None else "N/A"
            lines.append(f'| {m["symbol"]} | {m["model"]} | {m["trades"]} | {win} | {m["net_return_pct"]:.2f} | {m["max_drawdown_pct"]:.2f} | {m["buyhold_return_pct"]:.2f} |')
    lines+=["","## Missing datasets / blocked quality checks",""]
    for sym,err in manifest["data_errors"].items():lines.append(f"- {sym}: {err}")
    if not manifest["data_errors"]:lines.append("- None")
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    if not matrix:raise ValueError("NO_TESTABLE_ARCHIVES:NO_RESULTS_PUBLISHED_AS_PROFIT")
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default="out/v3_historical")
    args=ap.parse_args()
    d=run(args.out)
    print("HISTORICAL_DONE symbols="+str(len(d["manifest"]["symbols_testable"]))+
          " untestable="+str(len(d["manifest"]["symbols_untestable"]))+
          " trials="+str(len(d["matrix"]))+" trades="+str(len(d["trades"])))
if __name__=="__main__":main()
