"""Telegram bot/chat reachability and optional one-off delivery test, without exposing token."""
from __future__ import annotations
import argparse,json,os
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

def _call(token,method,params,opener=urlopen):
    # Bot token appears only inside HTTPS URL, never in log/error or returned payload.
    req=Request("https://api.telegram.org/bot"+token+"/"+method,
                data=urlencode(params).encode("utf8"),method="POST")
    try:
        with opener(req,timeout=12) as response:
            data=json.load(response)
            if response.status != 200 or data.get("ok") is not True:
                raise ValueError("TELEGRAM_API_REJECTED")
            return data.get("result")
    except HTTPError as exc:raise RuntimeError("TELEGRAM_HTTP_"+str(exc.code)) from None
    except URLError:raise RuntimeError("TELEGRAM_NETWORK_UNREACHABLE") from None

def validate(token,chat_id,send_test=False,call=_call):
    if not token and not chat_id:return "NOT_CONFIGURED"
    if not token or not chat_id:raise ValueError("TELEGRAM_SECRETS_INCOMPLETE")
    bot=call(token,"getMe",{})
    if not isinstance(bot,dict) or not bot.get("is_bot"):raise ValueError("INVALID_TELEGRAM_BOT")
    chat=call(token,"getChat",{"chat_id":chat_id})
    if not isinstance(chat,dict) or str(chat.get("id"))!=str(chat_id):
        raise ValueError("TELEGRAM_CHAT_NOT_ACCESSIBLE")
    if send_test:
        receipt=call(token,"sendMessage",{"chat_id":chat_id,
                        "text":"📡 Early Accumulation Radar: Telegram bağlantı testi başarılı. Bu mesaj işlem sinyali değildir."})
        if not isinstance(receipt,dict) or not receipt.get("message_id"):
            raise ValueError("TELEGRAM_DELIVERY_NOT_ACKNOWLEDGED")
        return "TEST_MESSAGE_ACCEPTED_BY_TELEGRAM"
    return "BOT_AND_CHAT_ACCESSIBLE_NO_MESSAGE_SENT"

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--send-test",action="store_true")
    args=p.parse_args()
    print(validate(os.environ.get("TELEGRAM_BOT_TOKEN",""),
                   os.environ.get("TELEGRAM_CHAT_ID",""),args.send_test))
if __name__=="__main__":main()
