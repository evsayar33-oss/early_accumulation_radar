"""No-network V5 safeguards: OKX spot, fallback, data gaps and fail-closed triage."""
import unittest
from datetime import date,timedelta
from research_v4.secondary_source_audit import okx_spot,audit
from research_v4.research_triage import evaluate

class V5Contracts(unittest.TestCase):
    def test_okx_spot_parses_utc_close(self):
        def get(url):
            self.assertIn("instId=ALPHA-USDT",url)
            self.assertIn("bar=1Dutc",url)
            return {"code":"0","data":[["1735689600000","1","2",".5","1.5","100"]]}
        self.assertEqual(okx_spot("ALPHAUSDT",get)["2025-01-01"],1.5)
    def test_okx_error_is_explicit(self):
        with self.assertRaisesRegex(ValueError,"OKX_NOT_AVAILABLE"):
            okx_spot("ALPHAUSDT",lambda url:{"code":"51001","data":[]})
    def test_crypto_falls_back_to_okx_with_diagnostics(self):
        d=date(2025,1,1)
        seq=[{"date":d+timedelta(days=i),"close":10.0} for i in range(30)]
        prices={x["date"].isoformat():10.0 for x in seq}
        def bybit(s):raise ValueError("geoblocked")
        r=audit({("CRYPTO","ALPHAUSDT"):seq},get_bybit=bybit,
                get_okx=lambda s:prices,limit=1)
        row=r["comparisons"][0]
        self.assertEqual(row["provider"],"OKX_SPOT")
        self.assertEqual(row["state"],"COMPARED_NOT_PIT_VERIFIED")
        self.assertEqual(row["attempts"][0]["error_detail"],"geoblocked")
        self.assertFalse(r["paper_approved"])
    def test_all_secondary_failures_are_reported(self):
        d=date(2025,1,1)
        seq=[{"date":d+timedelta(days=i),"close":10.0} for i in range(30)]
        def fail(s):raise OSError("network")
        r=audit({("CRYPTO","ALPHAUSDT"):seq},get_bybit=fail,get_okx=fail,limit=1)
        row=r["comparisons"][0]
        self.assertEqual(row["state"],"SECONDARY_SOURCE_UNAVAILABLE_OR_INSUFFICIENT_OVERLAP")
        self.assertEqual(len(row["attempts"]),2)
    def test_triage_no_auto_promotion(self):
        m={"coverage":{x:{"usable":2,"requested":2} for x in ("BIST","US","CRYPTO")}}
        sec={"comparisons":[]}
        e={"paper_approved":False,"trade_authorized":False,
           "results":[{"market":"US","family":"test","status":"EXPLORATORY_ROBUST_NOT_VERIFIED"}]}
        r=evaluate(m,sec,e,e,e)
        self.assertEqual(r["status"],"REVIEW_REQUIRED")
        self.assertFalse(r["paper_approved"])
        self.assertIn("NO_INDEPENDENT_PRICE_COMPARISON_SUCCEEDED",r["problems"])
        self.assertEqual(len(r["exploratory_candidates"]),3)

if __name__=="__main__":unittest.main()
