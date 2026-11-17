"""Offline controls for new non-executable strategy research."""
import csv, tempfile, unittest
from datetime import date,timedelta
from pathlib import Path
from research_v4.multimarket_exploratory import (load,study,features,signal,events,
                                                 STABLE,FAMILIES,COST)

class MultiMarketContracts(unittest.TestCase):
    def test_no_history_no_paper(self):
        r=study({})
        self.assertFalse(r["paper_approved"])
        self.assertFalse(r["trade_authorized"])
        self.assertFalse(r["pristine_holdout"])
        self.assertEqual(r["attempts"],18)
    def test_stablecoin_excluded_but_equity_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"p.csv"
            with p.open("w",newline="") as f:
                w=csv.writer(f)
                w.writerow(["market","symbol","date","open","high","low","close","volume"])
                for market,sym in (("CRYPTO","FDUSDUSDT"),("CRYPTO","TUSDUSDT"),
                                   ("CRYPTO","TESTUSDT"),("BIST","ASELS")):
                    w.writerow([market,sym,"2026-01-01",1,1.1,.9,1,100])
            result=load(p)
            self.assertEqual(set(result),{("CRYPTO","TESTUSDT"),("BIST","ASELS")})
    def test_events_cannot_see_future_bars(self):
        start=date(2025,1,1)
        bars=[{"date":start+timedelta(days=i),"open":10,"high":11,
              "low":9,"close":10,"volume":100,"pit":False,"actions":False}
              for i in range(200)]
        base=features(bars,150)
        for family in FAMILIES:
            old=signal(family,bars,150,base)
            modified=[dict(x) for x in bars]
            modified[155]["close"]=200
            self.assertEqual(old,signal(family,modified,150,features(modified,150)))
    def test_no_approval_on_positive_exploration(self):
        start=date(2024,1,1)
        bars=[{"date":start+timedelta(days=i),"open":10+i*.1,
               "high":11+i*.1,"low":9+i*.1,"close":10+i*.1,
               "volume":100 if i%3 else 1000,"pit":False,"actions":False}
              for i in range(450)]
        report=study({("US","TEST"):bars})
        self.assertFalse(report["paper_approved"])
        self.assertEqual(len(report["results"]),len(FAMILIES))
        self.assertTrue(all(r["pit_approved"] is False for r in report["results"]))
    def test_fails_on_duplicate_bars(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"p.csv"
            p.write_text("market,symbol,date,open,high,low,close,volume\n"
                         "US,ABCD,2024-01-01,1,2,0.8,1,100\n"
                         "US,ABCD,2024-01-01,1,2,0.8,1,100\n")
            with self.assertRaisesRegex(ValueError,"DUPLICATE_DATE"):
                load(p)

if __name__=="__main__":unittest.main()
