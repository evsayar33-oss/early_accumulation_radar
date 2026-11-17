"""V6 no-network tests: capital conservation, liquidity, overlap and proof flags."""
import unittest
from datetime import date,timedelta
from research_v4.v6_portfolio import simulate,evaluate,partition_dates,START_CAPITAL

class V6PortfolioTests(unittest.TestCase):
    def make_series(self, n=220, volume=100000):
        start=date(2023,1,1)
        bars=[{"date":start+timedelta(days=i),"open":10.0,"high":10.4,
               "low":9.6,"close":10.0,"volume":volume,
               "pit":False,"actions":False} for i in range(n)]
        return {("US","AA"):bars,("US","BB"):[dict(x) for x in bars]}
    def event(self,symbol="AA",entry=110,exitday=115):
        start=date(2023,1,1)
        return {"market":"US","symbol":symbol,"family":"test",
            "signal":(start+timedelta(days=entry-1)).isoformat(),
            "entry_date":(start+timedelta(days=entry)).isoformat(),
            "outcome":(start+timedelta(days=exitday)).isoformat()}
    def days(self):
        return [x["date"].isoformat() for x in self.make_series()[("US","AA")]][100:140]
    def test_no_trades_are_flat(self):
        a=simulate(self.make_series(),[],"US","test",self.days())
        self.assertEqual(a["net_return_pct"],0)
        self.assertEqual(a["ending_mark_to_market"],START_CAPITAL)
        self.assertEqual(a["closed_trades"],0)
    def test_fees_reduce_flat_price_return(self):
        a=simulate(self.make_series(),[self.event()],"US","test",self.days())
        self.assertEqual(a["closed_trades"],1)
        self.assertLess(a["net_return_pct"],0)
        self.assertGreater(a["estimated_fees_and_slippage"],0)
    def test_no_negative_cash_position_overallocation(self):
        e=[self.event("AA"),self.event("BB")]
        a=simulate(self.make_series(),e,"US","test",self.days())
        self.assertEqual(a["closed_trades"],2)
        self.assertLess(a["estimated_fees_and_slippage"],START_CAPITAL)
    def test_volume_exclusion_not_fabricated_fill(self):
        a=simulate(self.make_series(volume=1),[self.event()],"US","test",self.days())
        self.assertEqual(a["closed_trades"],0)
        self.assertGreater(a["rejections"]["liquidity"],0)
    def test_partition_no_date_overlap(self):
        groups=partition_dates(self.make_series(),"US")
        self.assertEqual(len(groups),3)
        self.assertTrue(set(groups[0][1]).isdisjoint(groups[1][1]))
        self.assertTrue(set(groups[1][1]).isdisjoint(groups[2][1]))
    def test_approval_always_false(self):
        a=evaluate(self.make_series())
        self.assertFalse(a["paper_approved"])
        self.assertFalse(a["profitable_strategy_confirmed"])
        self.assertFalse(a["historical_pit_verified"])

if __name__=="__main__":unittest.main()
