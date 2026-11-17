"""Offline regression tests for cross-source checks and event hypothesis contracts."""
import unittest
from datetime import date,timedelta
from research_v4.secondary_source_audit import bybit_spot,stooq_us,compare,audit
from research_v4.regime_event_research import indicator,signal,events,study

class SourceAndRegimeContracts(unittest.TestCase):
    def bars(self,n=180):
        start=date(2025,1,1)
        return [{"date":start+timedelta(days=i),
                 "open":10+i*.01,"high":10.2+i*.01,
                 "low":9.8+i*.01,"close":10.1+i*.01,"volume":1000,
                 "pit":False,"actions":False} for i in range(n)]
    def test_bybit_rejects_nonspot_or_wrong_symbol(self):
        with self.assertRaisesRegex(ValueError,"SYMBOL_MISMATCH"):
            bybit_spot("ALPHAUSDT",get=lambda u:{"retCode":0,"result":{
                "category":"spot","symbol":"OTHERUSDT","list":[]}})
    def test_bybit_valid_spot_close(self):
        result=bybit_spot("ALPHAUSDT",get=lambda u:{"retCode":0,
            "result":{"category":"spot","symbol":"ALPHAUSDT",
                      "list":[["1735689600000","1","2",".5","1.5","100","150"]]}})
        self.assertEqual(result["2025-01-01"],1.5)
    def test_stooq_parses_csv_and_rejects_bad_data(self):
        r=stooq_us("ABCD",get_text=lambda u:"Date,Open,High,Low,Close,Volume\n2025-01-01,1,2,1,1.5,500\n")
        self.assertEqual(r,{"2025-01-01":1.5})
        with self.assertRaisesRegex(ValueError,"STOOQ_BAD_SCHEMA"):
            stooq_us("ABCD",get_text=lambda u:"BadResponse")
    def test_overlap_does_not_fabricate_comparison(self):
        r=compare({"2025-01-01":1},{"2025-01-01":1})
        self.assertEqual(r["state"],"INSUFFICIENT_OVERLAP")
    def test_bist_data_provider_gap_explicit(self):
        r=audit({("BIST","AAAA"):self.bars()},get_stooq=lambda _:None)
        self.assertEqual(r["comparisons"][0]["state"],"NO_VERIFIED_SECOND_PROVIDER")
        self.assertFalse(r["paper_approved"])
    def test_gap_not_overnight_crypto(self):
        z={"gap":.05,"body":.05,"rv":2,"trend":True}
        self.assertFalse(signal("overnight_gap_continuation",z,"CRYPTO"))
        self.assertTrue(signal("overnight_gap_continuation",z,"US"))
    def test_future_candle_cannot_change_signal(self):
        base=self.bars()
        original=indicator(base,150)
        changed=[dict(x) for x in base]
        changed[152]["close"]=100000
        self.assertEqual(original,indicator(changed,150))
    def test_short_history_and_no_trading(self):
        s={("US","ABCD"):self.bars(90)}
        self.assertEqual(events(s),[])
        r=study(s)
        self.assertFalse(r["paper_approved"])
        self.assertFalse(r["pristine_holdout"])

if __name__=="__main__":unittest.main()
