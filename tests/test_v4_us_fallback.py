"""Offline validation: Nasdaq outage must not turn SEC directory into fake smallcap alpha."""
import unittest
from research_v4.equity_sources import probe_market, NASDAQ, SEC_MAP, SEC_FACTS
from research_v4.us_fallback import TV_URL, parse_tv, sec_universe, sec_sample

NOW=1794850000000
ST=1794760000000

def bars(sym):
    return {"chart":{"result":[{"meta":{"symbol":sym,"currency":"USD"},"timestamp":[ST//1000],
        "indicators":{"quote":[{"open":[1],"high":[1.1],"low":[.9],
                                "close":[1],"volume":[50000]}]}}],"error":None}}

def sec_map():
    return {"fields":["cik","name","ticker","exchange"],
            "data":[[1,"One","AAAA","Nasdaq"],[2,"Two","BBBB","NYSE"],
                    [3,"OTC Issuer","CCCC","OTC"],[4,"Four","DDDD","NYSE"]]}

class Fallback(unittest.TestCase):
    def test_tv_current_cap_positive_and_no_trading(self):
        raw={"data":[{"s":"NASDAQ:ABCD","d":["ABCD","ABCD Inc",20000000,1.5,45000,"NASDAQ","stock"]},
                     {"s":"NASDAQ:BAD","d":["BAD","Bad",None,1,50000,"NASDAQ","stock"]}]}
        rows=parse_tv(raw)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["market_cap_usd_screen"],20000000)
        self.assertFalse(rows[0]["trade_authorized"])
    def test_sec_only_not_smallcap(self):
        rows=sec_universe(sec_map())
        self.assertEqual(len(rows),3)
        self.assertTrue(all(r["market_cap_usd_screen"] is None for r in rows))
        self.assertEqual(sec_sample(rows,NOW),sec_sample(rows,NOW))
    def test_nasdaq_outage_tv_success(self):
        def get(url,headers=None,as_text=False,payload=None):
            if url.startswith(NASDAQ): raise RuntimeError("NASDAQ_403")
            if url==TV_URL:
                self.assertIsNotNone(payload)
                return {"data":[{"s":"NYSE:ABCD","d":["ABCD","Example",50000000,2,100000,"NYSE","stock"]}]}
            if url==SEC_MAP:return sec_map()
            if url.startswith(SEC_FACTS):return {"facts":{}}
            if "/chart/" in url:return bars("ABCD")
            raise AssertionError(url)
        r=probe_market("US",get=get,now_ms=NOW,sec_agent="Research contact@example.org")
        self.assertEqual(r["coverage"]["recent_price_series"],1)
        self.assertEqual(r["coverage"]["smallcap_screened_tickers"],1)
        self.assertEqual(r["status"],"RECENT_DATA_AVAILABLE_NOT_PIT_READY")
        self.assertFalse(r["trade_authorized"])
    def test_nasdaq_and_tv_outage_sec_diagnostic_prices_only(self):
        def get(url,headers=None,as_text=False,payload=None):
            if url.startswith(NASDAQ) or url==TV_URL:raise RuntimeError("BLOCKED")
            if url==SEC_MAP:return sec_map()
            if url.startswith(SEC_FACTS):return {"facts":{}}
            if "/chart/" in url:
                from urllib.parse import unquote
                ticker=unquote(url.split("/chart/")[1].split("?")[0])
                return bars(ticker)
            raise AssertionError(url)
        r=probe_market("US",get=get,now_ms=NOW,sec_agent="Research contact@example.org")
        self.assertGreater(r["coverage"]["recent_price_series"],0)
        self.assertEqual(r["coverage"]["smallcap_screened_tickers"],0)
        self.assertEqual(r["status"],"SEC_DIAGNOSTIC_PRICE_ONLY_NO_SMALLCAP_VALIDATION")
        self.assertFalse(r["historical_pit_backtest_allowed"])
        self.assertFalse(r["paper_entries_allowed"])
    def test_total_outage_never_signal(self):
        def get(url,headers=None,as_text=False,payload=None):
            raise RuntimeError("BLOCKED")
        r=probe_market("US",get=get,now_ms=NOW,sec_agent="Research contact@example.org")
        self.assertEqual(r["coverage"]["recent_price_series"],0)
        self.assertEqual(r["status"],"SOURCE_UNAVAILABLE_OR_INCOMPLETE_NO_SIGNAL")

if __name__=="__main__":unittest.main()
