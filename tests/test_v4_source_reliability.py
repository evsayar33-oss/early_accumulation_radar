"""Offline reliability tests. No credentials, sockets, or production mutations."""
import io
import json
import unittest
from contextlib import redirect_stdout
from urllib.error import HTTPError
from research_v4.equity_sources import (probe_market,parse_cedar,KAP,CEDAR,NASDAQ,YAHOO)

NOW=1794850000000
ST=1794760000000
def candle(sym):
    return {"chart":{"result":[{"meta":{"symbol":sym,"currency":"TRY" if sym.endswith(".IS") else "USD"},
        "timestamp":[ST//1000],"indicators":{"quote":[{"open":[1],"high":[1.1],
        "low":[.9],"close":[1],"volume":[50000]}]}}],"error":None}
def cedar(sym):
    return {"data":[{"sid":sym,"ts_ms":str(ST),"open":1,"high":1.1,"low":.9,
                     "close":1,"volume":"50000"}],"meta":{"currency":"TRY"}}

class SourceReliability(unittest.TestCase):
    def test_cedar_parser_provides_session_for_forward_study(self):
        bar=parse_cedar(cedar("bist:KFEIN"),"KFEIN.IS")["bars"][0]
        self.assertIn("session_utc",bar)
        self.assertEqual(bar["volume"],50000)
    def test_explorer_rate_limiter_and_retry_429(self):
        clock=[0.0]
        pauses=[]
        times=[]
        attempt={"KFEIN":0}
        def sleep(seconds):
            pauses.append(seconds)
            clock[0]+=seconds
        def get(url,headers=None,as_text=False,payload=None):
            if url==KAP:
                return "<table><td>KFEIN</td><td>JANTS</td></table>"
            if "/chart/" in url:
                symbol=url.split("/chart/")[1].split("?")[0]
                return candle(symbol)
            if url.startswith(CEDAR):
                times.append(clock[0])
                if "KFEIN" in url:
                    attempt["KFEIN"]+=1
                    if attempt["KFEIN"]==1:
                        raise HTTPError(url,429,"rate limited",None,None)
                return cedar("bist:TEST")
            raise AssertionError(url)
        r=probe_market("BIST",get=get,now_ms=NOW,cedar_key="fake",
                       sleep=sleep,monotonic=lambda:clock[0])
        self.assertEqual(r["coverage"]["recent_price_series"],2)
        self.assertEqual(len(times),3)
        self.assertGreaterEqual(times[1]-times[0],2.2)
        self.assertGreaterEqual(times[2]-times[1],1.12-1e-6)
        self.assertEqual(sum(e["stage"].startswith("cedar_") for e in r["errors"]),0)
    def test_us_cedar_recovery_when_yahoo_fails(self):
        from research_v4.us_fallback import TV_URL
        def get(url,headers=None,as_text=False,payload=None):
            if url.startswith(NASDAQ):
                return {"data":{"rows":[{"symbol":"TEST","name":"Test Inc",
                                        "marketCap":"50000000","volume":"100000",
                                        "lastsale":"1.25"}]}}
            if "/chart/" in url:
                raise RuntimeError("YAHOO_UNAVAILABLE")
            if url.startswith(CEDAR):
                self.assertIn("nasdaq:TEST",url)
                return cedar("nasdaq:TEST")
            raise AssertionError(url)
        r=probe_market("US",get=get,now_ms=NOW,cedar_key="fake",
                       sleep=lambda s:None,monotonic=lambda:0)
        self.assertEqual(r["coverage"]["recent_price_series"],1)
        self.assertEqual(r["observations"][0]["price_source"],"DATACEDAR_OPTIONAL_FREE_KEY")
        self.assertTrue(r["observations"][0]["daily_bars_recent"][0]["session_utc"])
        self.assertFalse(r["paper_entries_allowed"])

if __name__=="__main__":unittest.main()
