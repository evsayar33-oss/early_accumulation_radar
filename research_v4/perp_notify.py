"""Advisory-only perpetual research notifications; never an order or buy signal."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

MAX_ALERTS=3
ALERT_STAGES={"EARLY_UPWARD_MOTION_WATCH",
              "EARLY_DOWNWARD_MOTION_WATCH",
              "UPWARD_IMPULSE_ALREADY_IN_PROGRESS",
              "DOWNWARD_IMPULSE_ALREADY_IN_PROGRESS"}

def format_message(report):
    if report.get("schema")!="EAR.perp_forward_summary.v1":
        raise ValueError("WRONG_PERP_REPORT_SCHEMA")
    events=[e for e in report.get("new_events",[])
            if e.get("stage") in ALERT_STAGES]
    if not events:return None
    # Prefer still-early intervals and corroborated prices; this is not an
    # alpha ranking and ignores OI, funding, carry, trade depth, and fees.
    events.sort(key=lambda e:(
        not e["stage"].startswith("EARLY_"),
        e["cross_venue"]!="CONSISTENT_TWO_VENUES",
        abs(e["interval_return_pct"]),e["symbol"]))
    selected=events[:MAX_ALERTS]
    lines=["📡 EAR V8 — PERPETUAL PİYASA HAREKETİ (ARAŞTIRMA)"]
    for e in selected:
        if e["cross_venue"]=="DIVERGENT_TWO_VENUES":
            continue  # No alert on inconsistent identities.
        mark=("ERKEN HAREKET GÖZLEMİ" if e["stage"].startswith("EARLY_")
              else "HAREKET ZATEN BAŞLAMIŞ")
        sign="+" if e["interval_return_pct"]>=0 else ""
        confirm=("2 borsa fiyatı uyumlu" if e["cross_venue"]=="CONSISTENT_TWO_VENUES"
                 else "TEK BORSA — TEYİTSİZ")
        lines.append(f"{mark} | {e['symbol']} | {e['price_at_observation']:.8g} USDT "
           f"| {e['interval_minutes']:.0f} dk {sign}{e['interval_return_pct']:.2f}% "
           f"| 24s {e['rolling_24h_change_pct']:+.2f}% | {confirm}")
    if len(lines)==1:return None
    lines.append("Bu fiyat hareketi SONRADAN gözlemlendi; önceden tahmin edildiği kanıtlanmadı.")
    lines.append("Vadeli kontrat: yüksek likidasyon/funding riski. AL/SAT önerisi, PAPER veya gerçek emir değildir.")
    return "\n".join(lines)

def send(message,token,chat_id,post=None):
    if not message:return "NO_ADVISORY"
    if not token or not chat_id:return "TELEGRAM_NOT_CONFIGURED"
    payload=urlencode({"chat_id":chat_id,"text":message}).encode("utf8")
    if post is not None:return post(payload)
    url="https://api.telegram.org/bot"+token+"/sendMessage"
    try:
        with urlopen(Request(url,data=payload,method="POST"),timeout=10) as response:
            if response.status!=200 or json.load(response).get("ok") is not True:
                raise RuntimeError("TELEGRAM_REJECTED")
    except HTTPError as exc:
        raise RuntimeError("TELEGRAM_HTTP_"+str(exc.code)) from None
    except URLError:
        raise RuntimeError("TELEGRAM_NETWORK") from None
    return "ADVISORY_DELIVERED"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--report",required=True)
    a=p.parse_args()
    report=json.loads(Path(a.report).read_text(encoding="utf8"))
    print(send(format_message(report),
          os.environ.get("TELEGRAM_BOT_TOKEN",""),
          os.environ.get("TELEGRAM_CHAT_ID","")))

if __name__=="__main__":main()
