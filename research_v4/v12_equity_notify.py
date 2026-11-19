"""One-off optional research notifications; no routine noisy scans or order advice."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VALID = {"NEW_FROZEN_PATTERN", "FUTURE_HOLDOUT_CLOSED"}


def message(reports):
    notices = []
    for report in reports:
        if report.get("schema") != "EAR.v12_equity_discovery.v1":
            raise ValueError("INVALID_V12_REPORT")
        for n in report["notices"]:
            if n.get("kind") not in VALID:
                raise ValueError("UNKNOWN_NOTICE_KIND")
            notices.append(n)
    if not notices:
        return None
    parts = ["EAR V12 | BIST / ABD BAGIMSIZ ARASTIRMA"]
    for n in notices[:10]:
        prefix = "Yeni sabitlenen oncu oruntu" if n["kind"] == "NEW_FROZEN_PATTERN" else "Gelecek veri testi tamamlandi"
        parts.append(prefix + ": " + n["market"] + " | " +
                     n["direction"] + " | " + n["rule"] +
                     (" | " + n["status"] if n.get("status") else ""))
    parts.append("Nedensellik veya kar kaniti degildir. PAPER ya da gercek emir yoktur.")
    return "\n".join(parts)


def deliver(msg, token, chat):
    if msg is None:
        return "NO_NEW_RESEARCH_EVENTS"
    if not token or not chat:
        return "NOT_CONFIGURED"
    body = urlencode({"chat_id": chat, "text": msg[:3800]}).encode("utf8")
    req = Request("https://api.telegram.org/bot" + token + "/sendMessage",
                  data=body, method="POST")
    try:
        with urlopen(req, timeout=15) as response:
            payload = json.load(response)
            if response.status != 200 or payload.get("ok") is not True:
                raise RuntimeError("TELEGRAM_REJECTED")
    except HTTPError as exc:
        raise RuntimeError("TELEGRAM_HTTP_" + str(exc.code)) from None
    except URLError:
        raise RuntimeError("TELEGRAM_NETWORK") from None
    return "DELIVERED"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reports", nargs="+", required=True)
    a = p.parse_args()
    reports = [json.loads(Path(x).read_text(encoding="utf8")) for x in a.reports]
    print(deliver(message(reports), os.environ.get("TELEGRAM_BOT_TOKEN"),
                  os.environ.get("TELEGRAM_CHAT_ID")))


if __name__ == "__main__":
    main()
