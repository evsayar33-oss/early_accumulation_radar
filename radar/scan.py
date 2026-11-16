"""One independent UTC scan, no fabricated bars, no real orders."""
from __future__ import annotations
import argparse,json,time,os
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from .providers import VENUES,SYMBOLS,fetch_quote
from .engine import analyze

def scan(assets=("BTC","ETH","SOL"),venues=VENUES,worker=fetch_quote):
    snapshots=[]; failures=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures={pool.submit(worker,v,a):(v,a) for a in assets for v in venues}
        for f in as_completed(futures):
            v,a=futures[f]
            try:
                q=f.result()
                snapshots.append(q.__dict__ | {"spread_bps":q.spread_bps,"top_bid_usd":q.top_bid_usd,"top_ask_usd":q.top_ask_usd})
            except Exception as exc:
                failures.append({"venue":v,"asset":a,"error":type(exc).__name__+":"+str(exc)[:130]})
    from .providers import Quote
    qq=[Quote(**{k:s[k] for k in ("venue","symbol","bid","ask","bid_qty","ask_qty","observed_ms","retrieved_ms","source","market_type")}) for s in snapshots]
    report={"schema":"EAR.v1","scan_utc_ms":int(time.time()*1000),
            "scope":"PUBLIC_SPOT_TOP_OF_BOOK_ONLY_NOT_FULL_CVD","real_orders":False,
            "assets":[analyze(a,[q for q in qq if q.symbol==a]) for a in assets],
            "snapshots":sorted(snapshots,key=lambda s:(s["symbol"],s["venue"])),
            "failed_sources":sorted(failures,key=lambda s:(s["asset"],s["venue"]))}
    return report

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",default="out/latest.json")
    ap.add_argument("--smoke",action="store_true",help="exit nonzero if no healthy asset")
    args=ap.parse_args()
    report=scan()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    summary="\n".join(f"{a['asset']}: {a['status']} venues={a.get('venues',0)}" for a in report["assets"])
    print(summary+"\nfailed="+str(len(report["failed_sources"])))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as fh:
            fh.write("## Multi-venue research-only scan\n\n"+summary.replace("\n","  \n")+"\n\nNo real trading signals or orders.\n")
    if args.smoke and not any(a["status"]=="WATCH_ONLY" for a in report["assets"]):
        raise SystemExit(2)
if __name__=="__main__":main()
