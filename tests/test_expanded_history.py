"""No-network regression tests for expanded historical universe selection."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from research_v4.expanded_history import stable,altcoins,bist_symbols,us_symbols,collect
from research_v4.historical_real_data import BINANCE_INFO,COINGECKO

NOW=int(datetime(2026,11,17,tzinfo=timezone.utc).timestamp()*1000)

class ExpandedUniverseTests(unittest.TestCase):
    def test_stablecoin_catalog_excluded(self):
        self.assertTrue(stable({"symbol":"USDE","name":"Ethena USDe","id":"ethena-usde"}))
        self.assertTrue(stable({"symbol":"TUSD","name":"TrueUSD","id":"true-usd"}))
        self.assertFalse(stable({"symbol":"ALPHA","name":"Example Governance Token","id":"alpha"}))
    def test_altcoins_exclude_pegs_and_ambiguous_tickers(self):
        def mock(url):
            if url==BINANCE_INFO:
                return {"symbols":[{"symbol":s+"USDT","quoteAsset":"USDT","status":"TRADING"}
                                   for s in ("ALPHA","BETA","USDE","DUP")]}
            if url.startswith(COINGECKO):
                return [{"id":"a","symbol":"alpha","market_cap":50000000,"name":"Alpha"},
                        {"id":"b","symbol":"beta","market_cap":90000000,"name":"Beta"},
                        {"id":"peg","symbol":"usde","market_cap":100000000,"name":"Stablecoin"},
                        {"id":"dup1","symbol":"dup","market_cap":30000000,"name":"Dup 1"},
                        {"id":"dup2","symbol":"dup","market_cap":40000000,"name":"Dup 2"}]
            raise AssertionError(url)
        got=altcoins(mock)
        self.assertEqual({x["symbol"] for x in got},{"ALPHAUSDT","BETAUSDT"})
    def test_bist_source_declares_unverified_size(self):
        # KAP parser accepts strict table cells only; no synthetic current cap
        html="<table><tr><td>ABCD</td><td>EFGH</td></tr></table>"
        result=bist_symbols(html,limit=2)
        self.assertEqual(len(result),2)
        self.assertTrue(all(r["cap_snapshot_usd"] is None for r in result))
    def test_us_current_market_cap_filter(self):
        raw={"data":[
            {"s":"NASDAQ:ABCD","d":["ABCD","Example",40000000,5,200000,"NASDAQ","stock"]},
            {"s":"NYSE:WXYZ","d":["WXYZ","Example2",30000000,2,180000,"NYSE","stock"]},
            {"s":"NASDAQ:BIG","d":["BIG","Big",10000000000,50,200000,"NASDAQ","stock"]}]}
        result=us_symbols(raw)
        self.assertEqual({x["symbol"] for x in result},{"ABCD","WXYZ"})
    def test_source_outage_does_not_fabricate_csv(self):
        def bad(*args,**kwargs):
            raise OSError("offline")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(OSError):
                collect(td,get=bad,get_equity=bad,timestamp_ms=NOW)
            self.assertFalse((Path(td)/"prices.csv").exists())
    def test_fetch_partial_keeps_explicit_outage_count(self):
        def get_equity(url,**kwargs):
            if "kap.org" in url:
                return "<td>ABCD</td><td>EFGH</td>"
            return {"data":[
                {"s":"NASDAQ:ABCD","d":["ABCD","Example",40000000,5,200000,"NASDAQ","stock"]},
                {"s":"NYSE:WXYZ","d":["WXYZ","Example",30000000,2,180000,"NYSE","stock"]}]}
        def get_json(url):
            if url==BINANCE_INFO:
                return {"symbols":[{"symbol":s+"USDT","quoteAsset":"USDT","status":"TRADING"} for s in ("ALPHA","BETA")]}
            if url.startswith(COINGECKO):
                return [{"id":"a","symbol":"alpha","market_cap":40000000,"name":"Alpha"},
                        {"id":"b","symbol":"beta","market_cap":50000000,"name":"Beta"}]
            raise OSError("provider offline")
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError,"COVERAGE_BELOW_MINIMUM"):
                collect(td,get=get_json,get_equity=get_equity,timestamp_ms=NOW,limits={"BIST":2,"US":2,"CRYPTO":2})
            self.assertFalse((Path(td)/"prices.csv").exists())
            self.assertTrue((Path(td)/"manifest.json").exists())

if __name__=="__main__":unittest.main()
