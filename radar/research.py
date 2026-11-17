"""Research V2: independent public quotes, sampled trades, and completed 1m candles."""
from __future__ import annotations
import argparse,json,os,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from .scan import scan
from .tape import TRADE_VENUES,fetch as fetch_tape
from .accumulation import fetch as fetch_candles
from .providers import SYMBOLS
from .flow_coherence import annotate

def collect(assets=("BTC","ETH","SOL"),tape=fetch_tape,candles=fetch_candles,quotes=scan):
    quotes_report=quotes(assets=assets)
    flow=[];candle_features=[];errors=[]
    with ThreadPoolExecutor(max_workers=9) as pool:
        futures={**{pool.submit(tape,v,a):("tape",v,a) for a in assets for v in TRADE_VENUES},
                 **{pool.submit(candles,a):("candles","binance",a) for a in assets}}
        for f in as_completed(futures):
            typ,venue,asset=futures[f]
            try:
                value=f.result()
                (flow if typ=="tape" else candle_features).append(value)
            except Exception as exc:
                errors.append({"type":typ,"venue":venue,"asset":asset,"error":type(exc).__name__+":"+str(exc)[:120]})
    annotate(candle_features,flow)
    features={f["asset"]:f for f in candle_features}
    # Preserve independent quote health as gate; never turn candle diagnostics into order signals.
    for q in quotes_report["assets"]:
        f=features.get(q["asset"])
        if f:
            f["multi_venue_quote_status"]=q["status"]
            f["liquidity_gate_passed"]=q["status"]=="WATCH_ONLY"
            f["trade_allowed"]=False
    return {"schema":"EAR.research.v2","scan_utc_ms":int(time.time()*1000),
            "scope":"RESEARCH_ONLY_NO_EXECUTION_OR_PNL","quotes":quotes_report,
            "sampled_tape":sorted(flow,key=lambda r:(r["asset"],r["venue"])),
            "candle_diagnostics":sorted(candle_features,key=lambda r:r["asset"]),
            "errors":sorted(errors,key=lambda r:(r["asset"],r["type"],r["venue"])),
            "zero_valid_candle_sources":len(candle_features)==0}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="out/research.json")
    args=parser.parse_args()
    report=collect()
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
    msg="research: "+str(len(report["candle_diagnostics"]))+" valid candle assets, "+str(len(report["sampled_tape"]))+" sampled tape feeds; "+str(len(report["errors"]))+" flow errors"
    print(msg)
    print("Research only: NO TRADE SIGNAL OR ORDER.")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf8") as f:
            f.write("## Early Accumulation Research V2\n\n"+msg+"\n\nEvery candidate remains HYPOTHESIS_ONLY.\n")
if __name__=="__main__":main()
