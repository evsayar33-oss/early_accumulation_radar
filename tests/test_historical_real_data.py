"""Offline data-provider fixture tests: real endpoints are not called in CI."""
from datetime import datetime,timezone,timedelta
import tempfile
from pathlib import Path
import json
from unittest import TestCase
from unittest.mock import patch
from research_v4.historical_real_data import (
    validate,yahoo_bars,binance_bars,fetch_all,discover_current_altcoins,DAY_MS,YAHOO,BINANCE,COINGECKO,BINANCE_INFO
)

NOW=int(datetime(2026,11,17,tzinfo=timezone.utc).timestamp()*1000)

class RealDataSourceTests(TestCase):
    def test_yahoo_excludes_open_session_and_null_bars(self):
        old=NOW-2*DAY_MS
        raw={"chart":{"result":[{"meta":{"symbol":"TEST.IS"},
            "timestamp":[old//1000, (NOW-DAY_MS)//1000, NOW//1000],
            "indicators":{"quote":[{"open":[10,11,12],"high":[11,12,13],
                "low":[9,10,11],"close":[10,11,12],"volume":[100,None,100]}]}}],"error":None}}
        values,host=yahoo_bars("TEST","BIST",NOW,download=lambda url:raw)
        self.assertEqual(len(values),1)
        self.assertEqual(host,YAHOO[0])
    def test_binance_closed_daily_bars_and_pagination(self):
        def getter(url):
            self.assertTrue(url.startswith(BINANCE))
            start=int(url.split("startTime=")[1].split("&")[0])
            # Stub first query only: one closed bar, no future bar.
            return [[start,"10","11","9","10","123",start+DAY_MS-1]]
        bars=binance_bars("BTCUSDT",NOW,download=getter,years=1)
        self.assertEqual(len(bars),1)
    def test_invalid_ohlc_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"BAD_BAR"):
            validate([("2025-01-01",10,9,8,10,500)],"TEST","US",min_bars=1)
    def test_no_fictitious_history_when_provider_fails(self):
        with patch("research_v4.historical_real_data.current_equity_symbols",
                   return_value=({"BIST":["TEST","FOO"],"US":["ABCD","WXYZ"]},"sha")):
            with tempfile.TemporaryDirectory() as tmp:
                def blocked(url):raise OSError("blocked")
                with self.assertRaises(ValueError):
                    fetch_all("ledger",tmp,download=blocked,now_ms=NOW)
                self.assertFalse((Path(tmp)/"prices.csv").exists())
    def test_current_altcoin_cap_and_binance_spot_filter(self):
        def fake(url):
            if url==BINANCE_INFO:
                return {"symbols":[{"symbol":"SMALLUSDT","status":"TRADING","quoteAsset":"USDT"},
                                   {"symbol":"BTCUSDT","status":"TRADING","quoteAsset":"USDT"}]}
            if url.startswith(COINGECKO):
                return [{"id":"small-token","symbol":"small","market_cap":40000000},
                        {"id":"bitcoin","symbol":"btc","market_cap":1000000000000}]
            raise AssertionError(url)
        selected=discover_current_altcoins(download=fake)
        self.assertEqual([x["symbol"] for x in selected],["SMALLUSDT"])
    def test_data_never_marks_pit_or_adjustments_verified(self):
        rows=[("2025-01-01",10,11,9,10,100)]
        item=validate(rows,"ABCD","US",min_bars=1)[0]
        self.assertEqual(item[-2:],("false","false"))

if __name__=="__main__":
    import unittest
    unittest.main()
