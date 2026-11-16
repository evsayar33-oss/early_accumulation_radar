"""Telegram-only observational alerts. Never emit BUY/SELL or trade placement."""
from __future__ import annotations
import argparse,json,os
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError,URLError

def format_message(report):
    if report.get("schema")!="EAR.research.v2":raise ValueError("invalid schema")
    quoted={x["asset"]:x for x in report["quotes"]["assets"]}
    matches=[]
    for x in report["candle_diagnostics"]:
        if not (x.get("accumulation_watch") or x.get("distribution_watch")):continue
        asset=x["asset"]
        q=quoted.get(asset,{})
        if q.get("status")!="WATCH_ONLY":continue
        if x.get("source_venue")!="binance":continue  # Fallback volume-only must not alert.
        kind="BİRİKİM ADAYI" if x["accumulation_watch"] else "DAĞITIM RİSKİ"
        buy=x.get("taker_buy_quote_fraction_10m")
        matches.append(f"{kind} | {asset} | fiyat {x['price']:.6g} | hacim oranı {x['relative_median_volume_10m_vs_60m']:.2f}x | taker alış %{buy*100:.1f} | {q.get('venues',0)} borsa")
    if not matches:return None
    return ("📡 EAR V2 — ARAŞTIRMA UYARISI\n"+
            "\n".join(matches)+
            "\n\nAL/SAT emri veya kanıtlanmış kâr sinyali değildir. PAPER/gerçek emir yok.")

def send(report,token,chat_id,post=None):
    msg=format_message(report)
    if not msg:return "NO_RESEARCH_ALERT"
    if not token or not chat_id:return "NOT_CONFIGURED"
    body=urlencode({"chat_id":chat_id,"text":msg}).encode("utf8")
    if post is not None:return post(body)
    req=Request("https://api.telegram.org/bot"+token+"/sendMessage",data=body,method="POST")
    try:
        with urlopen(req,timeout=12) as resp:
            data=json.load(resp)
            if resp.status!=200 or data.get("ok") is not True:
                raise RuntimeError("TELEGRAM_REJECTED")
    except HTTPError as err:
        # Never expose a URL containing the bot secret in exception logs.
        raise RuntimeError("TELEGRAM_HTTP_"+str(err.code)) from None
    except URLError:
        raise RuntimeError("TELEGRAM_NETWORK") from None
    return "RESEARCH_ALERT_SENT"

def main():
    p=argparse.ArgumentParser();p.add_argument("--input",default="out/research.json")
    a=p.parse_args()
    report=json.loads(Path(a.input).read_text(encoding="utf8"))
    print(send(report,os.environ.get("TELEGRAM_BOT_TOKEN",""),os.environ.get("TELEGRAM_CHAT_ID","")))
if __name__=="__main__":main()
