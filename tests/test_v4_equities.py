"""Offline source and PIT gate contract tests, never touch public endpoints."""
import json
import tempfile
import unittest
from pathlib import Path

from radar.ledger import read_verify
from research_v4.equity_sources import (number, parse_kap, parse_nasdaq, parse_yahoo,
    parse_sec_map, latest_sec_fact, probe_market, KAP, NASDAQ, YAHOO)
from research_v4.equity_evidence import append, evaluate, quality

NOW = 1794850000000
ST = 1794760000000

def chart(symbol):
    return {"chart":{"result":[{"meta":{"symbol":symbol,"currency":"TRY" if symbol.endswith(".IS") else "USD"},
        "timestamp":[int(ST/1000)],"indicators":{"quote":[{"open":[1.],"high":[1.1],
        "low":[.9],"close":[1.0],"volume":[100000.]}]}}],"error":None}}

class SourceContract(unittest.TestCase):
    def test_kap_listing_and_non_company_text(self):
        self.assertEqual(parse_kap("<table><tr><td>KFEIN</td><td>KAFEIN</td><td>İSTANBUL</td></tr></table>"),
                         ["KAFEIN","KFEIN"])

    def test_nasdaq_screen_has_no_verified_float(self):
        data={"data":{"rows":[{"symbol":"TEST","name":"Test Co","marketCap":"$120,000,000",
                               "volume":"50,000","lastsale":"$4.25"}],"totalRecords":3210}}
        rows,scanned,total=parse_nasdaq(data,"NASDAQ")
        self.assertEqual((scanned,total),(1,3210))
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]["float_pct"])
        self.assertFalse(rows[0]["point_in_time_membership_verified"])

    def test_bad_symbol_or_negative_cannot_screen(self):
        data={"data":{"rows":[{"symbol":"ABC/XYZ","marketCap":"3M",
                               "volume":"40000","lastsale":"$1"}]}}
        self.assertEqual(parse_nasdaq(data,"NYSE")[0],[])
        self.assertIsNone(number(-5))

    def test_yahoo_candle_schema(self):
        rows=parse_yahoo(chart("KFEIN.IS"),"KFEIN.IS")
        self.assertEqual(rows["bars"][0]["volume"],100000)
        with self.assertRaises(ValueError):
            parse_yahoo(chart("NOT_MATCH"),"KFEIN.IS")

    def test_sec_mapping_and_asof_filing(self):
        m={"fields":["cik","name","ticker","exchange"],
           "data":[[12345,"Test","TEST","NASDAQ"]]}
        self.assertEqual(parse_sec_map(m)["TEST"],12345)
        facts={"facts":{"dei":{"EntityPublicFloat":{"units":{"USD":[
            {"val":1000000,"filed":"2025-09-20","end":"2025-06-30","form":"10-K"},
            {"val":2000000,"filed":"2027-01-01","end":"2026-09-30","form":"10-K"}
        ]}}}}}
        self.assertEqual(latest_sec_fact(facts,"dei","EntityPublicFloat","USD","2026-11-16")["value"],1000000)

    def test_bist_source_probe_one_valid_price_no_float(self):
        def get(url, headers=None, as_text=False):
            if url==KAP:
                return "<table><tr><td>KFEIN</td><td>COMPANY NAME</td></tr></table>"
            if "chart/" in url:
                return chart("KFEIN.IS")
            raise AssertionError(url)
        r=probe_market("BIST",get=get,now_ms=NOW)
        self.assertEqual(r["coverage"]["recent_price_series"],1)
        self.assertFalse(r["historical_pit_backtest_allowed"])
        self.assertFalse(r["float_ownership_verified"])

    def test_us_source_probe_without_sec_agent_keeps_cik_unverified(self):
        def get(url, headers=None, as_text=False):
            if url.startswith(NASDAQ):
                return {"data":{"rows":[{"symbol":"TEST","marketCap":"120000000",
                                         "volume":"50000","lastsale":"$4.25","name":"Test Co"}]}}
            if "chart/" in url:
                return chart("TEST")
            raise AssertionError(url)
        r=probe_market("US",get=get,now_ms=NOW)
        self.assertEqual(r["coverage"]["recent_price_series"],1)
        self.assertEqual(r["observations"][0]["float_pct"],None)
        self.assertFalse(r["paper_entries_allowed"])
        self.assertTrue(any(x["stage"]=="sec_companyfacts" for x in r["errors"]))

    def test_all_network_sources_down_fails_closed(self):
        def bad(url, headers=None, as_text=False):
            raise RuntimeError("429")
        r=probe_market("BIST",get=bad,now_ms=NOW)
        self.assertEqual(r["coverage"]["recent_price_series"],0)
        self.assertEqual(r["status"],"SOURCE_UNAVAILABLE_OR_INCOMPLETE_NO_SIGNAL")

class EvidenceContract(unittest.TestCase):
    def doc(self,market,t):
        return {"schema":"EAR.V4.equity.source_probe.v1","market":market,
                "observed_ms":t,"status":"RECENT_DATA_AVAILABLE_NOT_PIT_READY",
                "observations":[{"symbol":"AAA","daily_bars_recent":[{"ts_ms":ST,
                   "session_utc":"2026-11-15","close":1.,"volume":2000}]}],
                "coverage":{"observed_tickers":1,"recent_price_series":1},
                "float_ownership_verified":False,"corporate_actions_verified":False,
                "universe_point_in_time_verified":False,"sampling_is_representative":False}

    def test_hash_chain_append_and_no_backtest_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"ledger.jsonl"
            b=self.doc("BIST",NOW);u=self.doc("US",NOW)
            first=append(b,u,p)
            self.assertEqual(len(read_verify(p)),1)
            self.assertEqual(first["prev_sha256"],"GENESIS")
            with self.assertRaises(ValueError):
                append(b,u,p)
            b["observed_ms"]+=3600000;u["observed_ms"]+=3600000
            second=append(b,u,p)
            self.assertEqual(second["prev_sha256"],first["sha256"])
            report=evaluate(b,u,p)
            self.assertEqual(report["decision"],"INSUFFICIENT_EQUITY_EVIDENCE")
            self.assertEqual(report["forward_observation_ticks"],2)
            self.assertFalse(report["trade_authorized"])

    def test_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"ledger.jsonl"
            b=self.doc("BIST",NOW);u=self.doc("US",NOW)
            append(b,u,p)
            content=p.read_text().replace('"no_orders":true','"no_orders":false')
            p.write_text(content)
            with self.assertRaises(ValueError):
                evaluate(b,u,p)

    def test_incompatible_market_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=self.doc("US",NOW)
            with self.assertRaises(ValueError):
                append(d,d,Path(tmp)/"ledger")

    def test_split_float_and_pit_remain_blocked(self):
        q=quality(self.doc("BIST",NOW))
        self.assertIn("NO_POINT_IN_TIME_UNIVERSE",q["issues"])
        self.assertIn("UNVERIFIED_FLOAT_AND_OWNERSHIP",q["issues"])
        self.assertFalse(q["historical_backtest_approved"])

if __name__=="__main__": unittest.main()
