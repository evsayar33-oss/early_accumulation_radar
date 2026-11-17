"""Offline contracts for automated V5 research, source recovery and prospective proof."""
import csv,hashlib,json,tempfile,unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError,URLError
from research_v4.secondary_source_audit import (
    okx_spot,mexc_spot,nasdaq_us,compare,audit,tradingview_quote_snapshot)
from research_v4.data_quality import classify,screen
from research_v4.prospective_evidence import (
    seal,digest,read_ledger,write_ledger,emit_signals,settle,update)
from research_v4.matched_benchmark import matched_peer,study as matched_study

class AutonomousV5(unittest.TestCase):
    def bars(self,n=155,offset=0):
        d=date(2025,1,1)
        return [{"date":d+timedelta(days=i),"open":10+i*.01+offset,
              "high":10.3+i*.01+offset,"low":9.8+i*.01+offset,
              "close":10.1+i*.01+offset,"volume":1000+(i%7)*200,
              "pit":False,"actions":False} for i in range(n)]
    def test_okx_utc_only_closed_bar(self):
        o=okx_spot("ALPHAUSDT",get=lambda url:{
            "code":"0","data":[["1735689600000","1","2",".5","1.5","1","1","1","1"],
                                ["1735776000000","1","2",".5","1.6","1","1","1","0"]]})
        self.assertEqual(o,{"2025-01-01":1.5})
    def test_mexc_utc_daily_schema(self):
        r=mexc_spot("ALPHAUSDT",get=lambda url:[
            [1735689600000,"1","2",".5","1.5","1",1735775999999]])
        self.assertEqual(r["2025-01-01"],1.5)
    def test_nasdaq_currency_and_dates(self):
        r=nasdaq_us("ABCD",get=lambda url:{
            "data":{"tradesTable":{"rows":[{"date":"01/02/2025","close":"$12.55"},
                                            {"date":"2025-01-03","close":"$13.12"}]}}})
        self.assertEqual(r["2025-01-02"],12.55)
        self.assertEqual(r["2025-01-03"],13.12)
    def test_fallback_to_second_provider_not_fabricated(self):
        bars=self.bars()
        mapping={b["date"].isoformat():b["close"] for b in bars}
        def fail(_):raise URLError("blocked")
        r=audit({("US","ABCD"):bars},get_stooq=fail,
                get_nasdaq=lambda sym:mapping)
        self.assertEqual(r["comparisons"][0]["provider"],"NASDAQ_US")
        self.assertEqual(r["comparisons"][0]["state"],"CONSISTENT_REFERENCE_NOT_PIT")
        self.assertEqual(r["comparisons"][0]["tried"][0]["state"],"UNAVAILABLE")
    def test_provider_wide_circuit_breaker(self):
        bars=self.bars()
        calls=[]
        def blocked(sym):
            calls.append(sym)
            raise HTTPError("https://example.test",403,"denied",{},None)
        r=audit({("CRYPTO",s):bars for s in ("ALPHAUSDT","BETAUSDT","GAMMAUSDT")},
               get_bybit=blocked,get_okx=lambda x:{},get_mexc=lambda x:{})
        self.assertEqual(len(calls),1)
        self.assertIn("BYBIT_SPOT",r["provider_health"]["disabled_due_to_failures"])
        self.assertTrue(all(x["state"]=="SECONDARY_HISTORY_UNAVAILABLE" for x in r["comparisons"]))
    def test_bist_same_day_quote_is_only_snapshot(self):
        bars=self.bars()
        last=bars[-1]
        t=int(datetime.combine(last["date"],datetime.min.time(),timezone.utc).timestamp())
        def tv(url,payload):
            return {"data":[{"s":"BIST:ABCD","d":[last["close"],t]}]}
        response=tradingview_quote_snapshot("BIST",["ABCD"],get_post=tv)
        self.assertEqual(response["ABCD"]["date"],last["date"].isoformat())
        r=audit({("BIST","ABCD"):bars},get_snapshot=lambda m,s:response)
        self.assertEqual(r["comparisons"][0]["state"],"NO_VERIFIED_SECOND_PROVIDER")
        self.assertEqual(r["comparisons"][0]["snapshot_state"],"SAME_DATE_SNAPSHOT_ONLY")
    def test_quality_quarantines_not_adjusts(self):
        bars=self.bars(n=315)
        bars[200]["open"]=200
        reasons=classify("US",bars,asof=bars[-1]["date"])
        self.assertIn("POSSIBLE_UNADJUSTED_CORPORATE_ACTION_OR_REAL_GAP",reasons)
        self.assertFalse(classify("CRYPTO",self.bars(315),asof=self.bars(315)[-1]["date"]))
    def test_quality_manifest_hash_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/"prices.csv").write_text("market,symbol,date,open,high,low,close,volume\n")
            (p/"manifest.json").write_text(json.dumps({
                "csv_sha256":"0"*64,"asof_utc":"2026-11-17T00:00:00Z",
                "trade_authorized":False,"paper_approved":False}))
            with self.assertRaisesRegex(ValueError,"SOURCE_MANIFEST_HASH_MISMATCH"):
                screen(p/"prices.csv",p/"manifest.json",p/"out")
    def test_record_seal_and_tamper_rejection(self):
        rec=seal({"kind":"signal","id":"abc","signal_date":"2025-04-01"})
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/"signals.jsonl"
            write_ledger(file,[rec])
            self.assertEqual(read_ledger(file,"signal")[0],rec)
            file.write_text(file.read_text().replace("2025-04-01","2025-04-02"))
            with self.assertRaisesRegex(ValueError,"REGISTRY_INTEGRITY_FAILURE"):
                read_ledger(file,"signal")
    def test_signal_first_seen_and_idempotent_update(self):
        bars=self.bars(151)
        observed=(bars[-1]["date"]+timedelta(days=1)).isoformat()+"T03:47:00+00:00"
        series={("US","ABCD"):bars}
        with patch("research_v4.prospective_evidence.baseline_signal",return_value=True):
            signals=emit_signals(series,observed,"method1","source1")
            self.assertGreaterEqual(len(signals),3)
            self.assertTrue(all(s["entry_strictly_after_utc_date"]==observed[:10] for s in signals))
            self.assertTrue(all(s["paper_approved"] is False for s in signals))
            a,b,report=update(series,dict(series),[],[],observed,"method1","source1")
            c,d,report2=update(series,dict(series),a,b,observed,"method1","source1")
            self.assertEqual(len(c),len(a))
            self.assertEqual(report2["new_signals"],0)
            self.assertFalse(report["profitable_strategy_confirmed"])
    def test_settlement_never_uses_past_or_same_day_open(self):
        b=self.bars(151)
        obs_day=b[-1]["date"]+timedelta(days=1)
        one=seal({"kind":"signal","id":"a","market":"US","symbol":"ABCD",
           "family":"base/quiet_accumulation","methodology_sha256":"m",
           "first_observed_utc":obs_day.isoformat()+"T03:47:00+00:00",
           "signal_date":b[-1]["date"].isoformat(),
           "entry_strictly_after_utc_date":obs_day.isoformat()})
        incomplete=b+[dict(b[-1],date=obs_day,open=15,close=15)]
        got,reason=settle(one,{("US","ABCD"):incomplete})
        self.assertIsNone(got)
        self.assertEqual(reason,"AWAITING_FUTURE_CLOSED_BARS")
        added=[dict(b[-1],date=obs_day+timedelta(days=j),open=11+j,close=11.1+j)
               for j in range(1,6)]
        got,reason=settle(one,{("US","ABCD"):incomplete+added})
        self.assertIsNone(reason)
        self.assertEqual(got["entry_date"],added[0]["date"].isoformat())
        self.assertFalse(got["real_fill_verified"])
        self.assertFalse(got["paper_approved"])
    def test_missing_delisted_symbol_unsettled(self):
        b=self.bars(151)
        obs=b[-1]["date"]+timedelta(days=1)
        item=seal({"kind":"signal","id":"a","market":"BIST","symbol":"ABCD",
           "family":"v2/high_volume_trend","methodology_sha256":"m",
           "first_observed_utc":obs.isoformat()+"T03:47:00+00:00",
           "signal_date":b[-1]["date"].isoformat(),
           "entry_strictly_after_utc_date":obs.isoformat()})
        res,reason=settle(item,{})
        self.assertIsNone(res)
        self.assertEqual(reason,"SOURCE_SYMBOL_MISSING")
    def test_frictionless_peers_exclude_subject(self):
        dt=date(2025,1,1)
        b0={"date":dt,"open":10,"close":11}
        b1={"date":dt+timedelta(days=1),"open":10,"close":12}
        maps={("US",str(i)):{"2025-01-01":(0,b0),"2025-01-02":(1,b1)} for i in range(7)}
        maps[("US","0")]["2025-01-02"]=(1,{"date":dt+timedelta(days=1),"close":999})
        value,n=matched_peer(maps,"US","0","2025-01-01","2025-01-02")
        self.assertAlmostEqual(value,20)
        self.assertEqual(n,6)
    def test_historical_benchmark_never_approves_trading(self):
        s={("US","ABCD"):self.bars(210)}
        report=matched_study(s)
        self.assertFalse(report["paper_approved"])
        self.assertFalse(report["pristine_holdout"])
        self.assertEqual(report["trial_count"],45)

if __name__=="__main__":unittest.main()
