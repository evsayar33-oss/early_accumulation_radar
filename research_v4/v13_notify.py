"""Telegram milestones only: frozen positive-net research or closed future test."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def message(report):
    if report.get("schema") != "EAR.v13_costed_profitability_discovery.v1":
        raise ValueError("INVALID_V13_REPORT")
    lines = []
    for market, x in sorted(report["markets"].items()):
        for f in x["new_frozen"]:
            lines.append(
                f"{market}: Net maliyetli aday donduruldu "
                f"{f['rule']} / {f['horizon_sessions']} seans. "
                "90 gunluk ileri test basliyor.")
        for d in x["new_forward_decisions"]:
            lines.append(
                f"{market}: Ileri test {d['status']}: "
                f"{d['rule']} / {d['horizon_sessions']} seans")
    if not lines:
        return None
    return ("EAR V13 | NET KARLILIK ARASTIRMASI\n"
            + "\n".join(lines[:8])
            + "\nGercek emir, kanitlanmis aracilik maliyeti veya "
              "garanti getiri degildir.")


def deliver(msg, token, chat_id, post=None):
    if msg is None:
        return "NO_NEW_ALPHA_MILESTONE"
    if not token or not chat_id:
        return "NOT_CONFIGURED"
    payload = urlencode({"chat_id":chat_id,"text":msg}).encode("utf8")
    if post is not None:
        return post(payload)
    req = Request("https://api.telegram.org/bot" + token + "/sendMessage",
                  data=payload, method="POST")
    try:
        with urlopen(req,timeout=15) as response:
            data=json.load(response)
            if response.status!=200 or data.get("ok") is not True:
                raise RuntimeError("TELEGRAM_REJECTED")
    except HTTPError as ex:
        raise RuntimeError("TELEGRAM_HTTP_" + str(ex.code)) from None
    except URLError:
        raise RuntimeError("TELEGRAM_NETWORK") from None
    return "ALPHA_RESEARCH_MILESTONE_DELIVERED"


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    a=ap.parse_args()
    report=json.loads(Path(a.input).read_text(encoding="utf8"))
    print(deliver(message(report),os.environ.get("TELEGRAM_BOT_TOKEN"),
                  os.environ.get("TELEGRAM_CHAT_ID")))


if __name__=="__main__":
    main()
