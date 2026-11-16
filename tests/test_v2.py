import json,tempfile,unittest
from pathlib import Path
from radar.tape import parse as parse_tape,summarize
from radar.accumulation import parse_candles,features,fetch as fetch_candle
from radar.ledger import append,read_verify
from radar.providers import FeedError

T=(1780000400000//60000)*60000
def candle(i,buy=.60,vol=100):
    t=T-120*60000+i*60000
    p=100+i*.001
    return [t,str(p),str(p+1),str(p-1),str(p),str(vol),t+59999,str(vol),10,"0",str(vol*buy),"0"]
class V2Test(unittest.TestCase):
    def test_taker_direction(self):
        r=[{"a":2,"T":T-1000,"p":"100","q":"2","m":True},{"a":3,"T":T-900,"p":"101","q":"2","m":False}]
        v=parse_tape("binance","BTC",r,T)
        self.assertEqual([x.taker_side for x in v],["sell","buy"])
        self.assertEqual(summarize("binance","BTC",v,T)["count"],2)
    def test_sample_dedup(self):
        x={"a":7,"T":T-1,"p":"100","q":"1","m":False}
        self.assertEqual(len(parse_tape("binance","BTC",[x,x],T)),1)
    def test_tape_future_rejected(self):
        with self.assertRaises(FeedError):parse_tape("binance","BTC",[{"a":1,"T":T+60000,"p":"1","q":"1","m":True}],T)
    def test_bybit_spot(self):
        d={"retCode":0,"result":{"list":[{"execId":"a","time":str(T-100),"price":"100","size":"1","side":"Buy","symbol":"BTCUSDT"}]}}
        self.assertEqual(parse_tape("bybit","BTC",d,T)[0].taker_side,"buy")
    def test_okx_spot(self):
        d={"code":"0","data":[{"tradeId":"a","ts":str(T-10),"px":"100","sz":"2","side":"sell","instId":"BTC-USDT"}]}
        self.assertEqual(parse_tape("okx","BTC",d,T)[0].notional,200)
    def test_candle_close_and_no_future(self):
        raw=[candle(i) for i in range(120)]
        self.assertEqual(len(parse_candles(raw,T)),120)
    def test_candle_gap(self):
        raw=[candle(i) for i in range(120) if i!=35]
        with self.assertRaises(FeedError):parse_candles(raw,T)
    def test_volume_flag_is_non_trading(self):
        raw=[candle(i,vol=100 if i<110 else 300) for i in range(120)]
        v=features("BTC",parse_candles(raw,T))
        self.assertTrue(v["accumulation_watch"])
        self.assertFalse(v["trade_allowed"])
    def test_okx_volume_only_no_fake_taker(self):
        raw={"code":"0","data":[[str(candle(i)[0]),"100","101","99","100","1","100","100","1"] for i in range(120)]}
        bars=parse_candles(raw,T,venue="okx")
        v=features("BTC",bars,"okx")
        self.assertEqual(v["status"],"VOLUME_CONTEXT_ONLY")
        self.assertIsNone(v["taker_buy_quote_fraction_10m"])
        self.assertFalse(v["accumulation_watch"])
        self.assertFalse(v["trade_allowed"])
    def test_binance_block_falls_back_to_okx(self):
        raw={"code":"0","data":[[str(candle(i)[0]),"100","101","99","100","1","100","100","1"] for i in range(120)]}
        called=[]
        def fake_get(url):
            called.append(url)
            if "okx.com" in url:return raw
            raise FeedError("HTTP_451")
        result=fetch_candle("BTC",get=fake_get,clock=lambda:T)
        self.assertEqual(result["source_venue"],"okx")
        self.assertEqual(len(called),3)
        self.assertEqual(len(result["attempted_source_failures"]),2)
    def test_ledger_tamper_and_duplicate(self):
        report={"schema":"EAR.research.v2","scan_utc_ms":T,
                "quotes":{"assets":[],"failed_sources":[]},"sampled_tape":[],"candle_diagnostics":[],"errors":[],"zero_valid_candle_sources":True}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.jsonl"
            append(report,p)
            self.assertEqual(len(read_verify(p)),1)
            with self.assertRaises(ValueError):append(report,p)
            p.write_text(p.read_text().replace("OBSERVED_RESEARCH","FAKE_PROFIT"))
            with self.assertRaises(ValueError):read_verify(p)
if __name__=="__main__":unittest.main()
