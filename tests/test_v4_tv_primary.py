"""Working US source first; known-unusable Nasdaq is not polled unnecessarily."""
import unittest
from research_v4.equity_sources import probe_market,NASDAQ
from research_v4.us_fallback import TV_URL
def bars(sym):
    return {"chart":{"result":[{"meta":{"symbol":sym,"currency":"USD"},
        "timestamp":[1794760000],
        "indicators":{"quote":[{"open":[1],"high":[1.1],"low":[.9],
        "close":[1],"volume":[50000]}]}}],"error":None}}

class TvPrimary(unittest.TestCase):
    def test_primary_success_skips_nasdaq(self):
        calls=[]
        def get(url,headers=None,as_text=False,payload=None):
            calls.append(url)
            if url==TV_URL:
                return {"data":[{"s":"NYSE:ABCD","d":["ABCD","Example",50000000,2,100000,"NYSE","stock"]}]}
            if "/chart/" in url:return bars("ABCD")
            if url.startswith(NASDAQ):raise AssertionError("Nasdaq must not be called")
            raise AssertionError(url)
        result=probe_market("US",get=get,now_ms=1794850000000,tv_primary=True)
        self.assertEqual(result["coverage"]["recent_price_series"],1)
        self.assertEqual(result["coverage"]["smallcap_screened_tickers"],1)
        self.assertFalse(any(url.startswith(NASDAQ) for url in calls))
        self.assertFalse(result["paper_entries_allowed"])

if __name__=="__main__":unittest.main()
