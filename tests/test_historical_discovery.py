"""Historical discovery safety contracts."""
import tempfile
from pathlib import Path
import unittest
from datetime import date,timedelta
from research_v4.historical_discovery import load_csv,discover,events,FAMILIES

class HistoricalDiscoveryTests(unittest.TestCase):
    def test_no_input_does_not_create_fictitious_profits(self):
        result=discover({})
        self.assertEqual(result["candidate_results"],[])
        self.assertFalse(result["paper_approved"])
        self.assertFalse(result["trade_authorized"])
    def test_short_history_rejected(self):
        start=date(2025,1,1)
        rows=[{"date":start+timedelta(days=i),"open":10.0,"high":11.0,
               "low":9.0,"close":10.0,"volume":100.0,"pit":False,"adjusted":False}
              for i in range(60)]
        result=discover({("US","TEST"):rows})
        self.assertEqual(result["candidate_results"][0]["status"],"INSUFFICIENT_HISTORY")
    def test_candidate_cannot_be_promoted_by_unverified_history(self):
        start=date(2024,1,1)
        rows=[{"date":start+timedelta(days=i),"open":10+i*.1,"high":11+i*.1,
               "low":9+i*.1,"close":10+i*.1,"volume":100 if i%3 else 500,
               "pit":False,"adjusted":False} for i in range(180)]
        result=discover({("US","TEST"):rows})
        self.assertEqual(len(result["candidate_results"]),len(FAMILIES))
        self.assertTrue(all(x["status"]!="HISTORICAL_CANDIDATE_REQUIRES_INDEPENDENT_REVIEW"
                            for x in result["candidate_results"]))
        self.assertFalse(result["paper_approved"])
    def test_duplicate_dates_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"prices.csv"
            p.write_text("market,symbol,date,open,high,low,close,volume\n"
                         "US,AAA,2025-01-01,1,2,1,1.5,100\n"
                         "US,AAA,2025-01-01,1,2,1,1.5,100\n")
            with self.assertRaisesRegex(ValueError,"DUPLICATE_SESSION"):
                load_csv(p)
    def test_future_prices_never_enter_signal(self):
        start=date(2024,1,1)
        rows=[{"date":start+timedelta(days=i),"open":10.0,"high":11.0,
               "low":9.0,"close":10.0,"volume":100.0,"pit":False,"adjusted":False}
              for i in range(80)]
        self.assertEqual(events({("BIST","TEST"):rows}),[])

if __name__=="__main__":unittest.main()
