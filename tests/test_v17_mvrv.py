import math,unittest
from datetime import date,timedelta
from research_v4.onchain_mvrv import analyze

class MVRVResearchTests(unittest.TestCase):
    def test_real_mvrv_is_chronological_and_cannot_promote(self):
        start=date(2018,1,1);rows=[]
        for i in range(1200):
            realized=50e9+i*110e6
            rows.append({"date":(start+timedelta(days=i)).isoformat(),
             "price":5000*math.exp(i/600)*(1+.08*math.sin(i/17)),"realized_cap":realized,
             "market_cap":realized*(1.1+.45*math.sin(i/70))})
        report=analyze("btc",rows)
        self.assertEqual(report["measurement"],"REAL_MVRV_MARKET_CAP_DIVIDED_BY_REALIZED_CAP")
        self.assertFalse(report["proxy"]);self.assertLess(report["split"]["discovery_end"],report["split"]["validation_start"])
        self.assertFalse(report["paper_eligible"]);self.assertFalse(report["trade_authorized"])
        self.assertEqual(len(report["results"]),4)

if __name__=="__main__":unittest.main()
