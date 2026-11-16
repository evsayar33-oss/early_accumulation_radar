import unittest
from research_v3.loss_diagnostic import analyze
from research_v3.model import UNIVERSE,SCENARIOS

class AttributionTests(unittest.TestCase):
    def test_complete_all_cohort_and_sizing_mismatch(self):
        rows=[];trades=[]
        for sym in UNIVERSE:
            for scenario in SCENARIOS:
                rows.append({"symbol":sym,"cohort":"ALL","model":"acc","scenario":scenario,
                             "trades":1,"net_return_pct":-1,"max_drawdown_pct":2})
                trades.append({"symbol":sym,"cohort":"ALL","model":"acc","scenario":scenario,
                               "net_pnl":"-5","net_return_pct":"-0.5","reason":"STOP_FIRST"})
        doc={"manifest":{"symbols_testable":list(UNIVERSE)},"matrix":rows}
        r=analyze(doc,trades)
        self.assertEqual(len(r["per_symbol"]),len(UNIVERSE)*len(SCENARIOS))
        self.assertTrue(r["historical_paper_allocation_not_comparable"])
        self.assertEqual(r["reason_counts_by_scenario"]["stress"]["STOP_FIRST"],len(UNIVERSE))

    def test_mismatch_fails_closed(self):
        doc={"manifest":{"symbols_testable":list(UNIVERSE)},"matrix":[]}
        with self.assertRaises(ValueError):
            analyze(doc,[])

if __name__=="__main__":unittest.main()
