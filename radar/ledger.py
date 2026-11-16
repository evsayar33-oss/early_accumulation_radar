"""Append-only SHA-256 linked UTC observations. Missing ticks never backfilled."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

def canonical(row):
    return json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)

def digest(row):return hashlib.sha256(canonical(row).encode("utf8")).hexdigest()

def read_verify(path):
    p=Path(path)
    if not p.exists():return []
    entries=[];prev="GENESIS";last_ms=0
    for line in p.read_text(encoding="utf8").splitlines():
        row=json.loads(line)
        record={k:v for k,v in row.items() if k!="sha256"}
        if record.get("prev_sha256")!=prev or row.get("sha256")!=digest(record):
            raise ValueError("LEDGER_HASH_CHAIN_CORRUPT")
        if int(row["scan_utc_ms"])<=last_ms:raise ValueError("LEDGER_TIME_NOT_MONOTONIC")
        last_ms=int(row["scan_utc_ms"])
        prev=row["sha256"];entries.append(row)
    return entries

def compact(report):
    if report.get("schema")!="EAR.research.v2":raise ValueError("INCORRECT_REPORT_SCHEMA")
    stamp=int(report["scan_utc_ms"])
    if stamp<=0:raise ValueError("BAD_TIMESTAMP")
    return {"schema":"EAR.forward.v1","scan_utc_ms":stamp,
        "scope":"OBSERVED_RESEARCH_NO_RETRO_FILLS",
        "quote_health":report["quotes"]["assets"],
        "tape":[{k:x.get(k) for k in ("venue","asset","status","count","sample_span_s","taker_buy_fraction","coverage")} for x in report["sampled_tape"]],
        "candle_diagnostics":report["candle_diagnostics"],
        "failed_source_count":len(report["errors"])+len(report["quotes"]["failed_sources"]),
        "zero_valid_candle_sources":report["zero_valid_candle_sources"],
        "trade_allowed":False}

def append(report,path):
    p=Path(path);old=read_verify(p)
    item=compact(report)
    if old and item["scan_utc_ms"]<=old[-1]["scan_utc_ms"]:
        raise ValueError("STALE_OR_DUPLICATE_SCAN")
    item["prev_sha256"]=old[-1]["sha256"] if old else "GENESIS"
    item["sha256"]=digest(item)
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf8") as f:f.write(canonical(item)+"\n")
    return item["sha256"]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True)
    parser.add_argument("--ledger",required=True)
    args=parser.parse_args()
    report=json.loads(Path(args.input).read_text(encoding="utf8"))
    print("APPEND_SHA256="+append(report,args.ledger))
if __name__=="__main__":main()
