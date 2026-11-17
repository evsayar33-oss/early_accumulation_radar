"""No-network bidirectional research and discontinuity guards."""
import unittest
from datetime import date,timedelta
from research_v4.v6_bidirectional import structural_gaps,features,active,side,detect,evaluate

class BidirectionalTests(unittest.TestCase):
    def bars(self,n=240):
        d=date(2025,1,1)
        return [{"date":d+timedelta(days=i),"open":10+.012*i,
             "high":10.2+.012*i,"low":9.8+.012*i,"close":10.1+.012*i,
             "volume":1000,"pit":False,"actions":False} for i in range(n)]
    def test_future_candle_does_not_change_features(self):
        seq=self.bars()
        a=features(seq,150)
        changed=[dict(x) for x in seq]
        changed[151]["close"]=200
        self.assertEqual(features(changed,150),a)
    def test_mirrored_positive_and_negative_event_rules(self):
        base={"uptrend":True,"downtrend":False,"price":15,
              "prior_high":12,"prior_low":8,"rv":2,"location":.9,
              "range_expansion":2,"r5":.25,"r1":.05}
        self.assertTrue(active("upside_expansion",base))
        mirrored=dict(base,uptrend=False,downtrend=True,price=7,location=.1)
        self.assertTrue(active("downside_expansion",mirrored))
        self.assertEqual(side("downside_expansion"),"DOWNSIDE_RISK_ONLY")
        self.assertEqual(side("upside_expansion"),"LONG")
    def test_detect_both_structural_gap_directions(self):
        seq=self.bars()
        seq[100]["open"]=seq[99]["close"]*3
        seq[140]["open"]=seq[139]["close"]*.3
        self.assertEqual(structural_gaps(seq),{100,140})
    def test_not_mislabel_price_jumps_as_verified_rebase(self):
        seq=self.bars()
        seq[110]["open"]=seq[109]["close"]*3
        r=evaluate({("CRYPTO","ALPHAUSDT"):seq})
        self.assertFalse(r["historical_rebase_events_verified"])
        self.assertFalse(r["spot_short_allowed"])
        self.assertFalse(r["paper_approved"])
        self.assertEqual(len(r["results"]),4)
    def test_historical_close_watchlist_no_future_needed(self):
        seq=self.bars(82)
        # the final close breakout has high relative volume and large candle range
        i=len(seq)-1
        seq[i].update({"close":17.0,"open":15.0,"high":17.1,
                       "low":14.4,"volume":5000})
        old=seq[-1].copy()
        events,blocked,latest=detect({("US","ALPHA"):seq})
        self.assertEqual(seq[-1],old)
        self.assertTrue(any(x["family"]=="upside_expansion" for x in latest))
        self.assertTrue(all(x["trade_authorized"] is False for x in latest))
    def test_block_unverified_discontinuity_before_trading(self):
        seq=self.bars()
        seq[141].update({"close":30.0,"open":30.0,"high":32.0,"low":29.0,"volume":10000})
        # the previous day has a >2x open ratio; signal is quarantined
        seq[140]["open"]=seq[139]["close"]*3
        events,blocked,latest=detect({("US","ALPHA"):seq})
        self.assertTrue(any(k[0]=="US" for k in blocked) or not events)

if __name__=="__main__":unittest.main()
