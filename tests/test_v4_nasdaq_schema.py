"""Nasdaq's HTTP-200 invalid envelopes must fail closed and use verified fallback."""
import unittest
from research_v4.equity_sources import probe_market,NASDAQ,SEC_MAP
from research_v4.us_fallback import TV_URL

NOW=1794850000000
ST=1794760000000

def candle(symbol):
    return {"chart":{"result":[{"meta":{"symbol":symbol,"currency":"USD"},
        "timestamp":[ST//1000],"indicators":{"quote":[{"open":[1],
        "high":[1.1],"low":[.9],"close":[1],"volume":[50000]}]}}],"error":None}}

class NasdaqSchema(unittest.TestCase):
    def test_http200_data_null_fails_over_to_tv_without_false_zero_universe(self):
        def get(url,headers=None,as_text=False,payload=None):
            if url.startswith(NASDAQ):
                return {"data":None,"message":"unavailable","status":{"rCode":-1}}
            if url==TV_URL:
                return {"data":[{"s":"NASDAQ:ABCD",
                    "d":["ABCD","Example",40000000,2,50000,"NASDAQ","stock"]}]}
            if "/chart/" in url:return candle("ABCD")
            raise AssertionError(url)
        result=probe_market("US",get=get,now_ms=NOW)
        self.assertEqual(result["coverage"]["recent_price_series"],1)
        self.assertEqual(result["coverage"]["smallcap_screened_tickers"],1)
        self.assertEqual([e["error"] for e in result["errors"] if e["stage"].startswith("nasdaq_")],
                         ["UNUSABLE_RESPONSE_SCHEMA"]*3)
        self.assertTrue(any(x["provider"]=="TRADINGVIEW_PUBLIC_SCANNER_UNOFFICIAL" for x in result["sources"]))
        self.assertFalse(result["trade_authorized"])
    def test_http200_empty_rows_are_not_parse_failures(self):
        def get(url,headers=None,as_text=False,payload=None):
            if url.startswith(NASDAQ):return {"data":{"rows":[],"totalRecords":0}}
            if url==TV_URL:return {"data":[]}
            raise RuntimeError("SEC unavailable")
        result=probe_market("US",get=get,now_ms=NOW)
        self.assertFalse(any(e["stage"].startswith("nasdaq_parse") for e in result["errors"]))
        self.assertEqual(result["status"],"SOURCE_UNAVAILABLE_OR_INCOMPLETE_NO_SIGNAL")

if __name__=="__main__":unittest.main()
