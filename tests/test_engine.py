import unittest
from radar.providers import Quote,FeedError,url_for,_parse
from radar.engine import analyze
from radar.scan import scan

NOW=1780000000000
def q(v,b=100,ask=101,qty=20):
    return Quote(v,"BTC",b,ask,qty,qty,NOW,NOW,v)
class TestEngine(unittest.TestCase):
    def test_crossed(self):
        with self.assertRaises(FeedError):q("okx",100,99)
    def test_stale(self):
        with self.assertRaises(FeedError):Quote("okx","BTC",100,101,10,10,NOW-130000,NOW,"okx")
    def test_missing(self):
        self.assertFalse(analyze("BTC",[q("okx")])["trade_allowed"])
    def test_watch_only(self):
        x=analyze("BTC",[q("okx",100,100.1),q("binance",100,100.1)])
        self.assertEqual(x["status"],"WATCH_ONLY")
        self.assertFalse(x["trade_allowed"])
    def test_dislocation(self):
        x=analyze("BTC",[q("okx",100,100.1),q("binance",105,105.1)])
        self.assertEqual(x["status"],"CROSS_VENUE_DISLOCATION")
    def test_no_data(self):
        self.assertEqual(analyze("BTC",[])["status"],"NO_DATA")
    def test_urls(self):
        for v in ("binance","okx","bybit","bitget","gate","kraken","coinbase"):
            self.assertTrue(url_for(v,"BTC").startswith("https://"))
    def test_parse_binance(self):
        x=_parse("binance","BTC",{"bidPrice":"100","askPrice":"101","bidQty":"10","askQty":"20"},NOW)
        self.assertEqual(x.top_bid_usd,1000)
    def test_parse_okx(self):
        obj={"data":[{"instId":"BTC-USDT","bidPx":"100","askPx":"101","bidSz":"20","askSz":"20","ts":str(NOW)}]}
        self.assertEqual(_parse("okx","BTC",obj,NOW).venue,"okx")
    def test_no_fake_fallback(self):
        def worker(v,a):raise FeedError("blocked")
        report=scan(assets=("BTC",),venues=("binance","okx"),worker=worker)
        self.assertEqual(report["assets"][0]["status"],"NO_DATA")
        self.assertEqual(len(report["failed_sources"]),2)
        self.assertEqual(report["snapshots"],[])
if __name__=="__main__":unittest.main()
