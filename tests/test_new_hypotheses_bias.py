"""Offline anti-lookahead and provenance controls for new hypotheses."""
import unittest
from datetime import date,timedelta
from research_v4.new_hypotheses_bias import features,selected,make_events,audit,FAMILIES

class NewHypothesesBiasTests(unittest.TestCase):
    def bars(self,n=260):
        start=date(2024,1,1)
        return [{"date":start+timedelta(days=i),"open":10+i*.02,
                 "high":10.4+i*.02,"low":9.8+i*.02,
                 "close":10.1+i*.02,"volume":1000 if i%9 else 3500,
                 "pit":False,"actions":False} for i in range(n)]
    def test_no_future_data_in_signal(self):
        a=self.bars()
        before=features(a,170)
        b=[dict(x) for x in a]
        b[171]["close"]=99999
        self.assertEqual(before,features(b,170))
        for f in FAMILIES:
            self.assertEqual(selected(f,before,.9,10),selected(f,features(b,170),.9,10))
    def test_relative_strength_requires_peer_count(self):
        z={"trend":True,"vol":2,"r20":.1}
        self.assertFalse(selected("relative_strength_rotation",z,1,4))
        self.assertTrue(selected("relative_strength_rotation",z,.9,5))
        self.assertFalse(selected("relative_strength_rotation",z,.6,5))
    def test_no_automatic_approval(self):
        series={("US","AAAA"):self.bars(),("US","BBBB"):self.bars()}
        report=audit(series)
        self.assertFalse(report["paper_approved"])
        self.assertFalse(report["trade_authorized"])
        self.assertFalse(report["pristine_holdout"])
        self.assertEqual(report["market_family_tests"],9)
        self.assertTrue(all(r["pit_approved"] is False for r in report["results"] if "pit_approved" in r))
    def test_no_future_events_on_short_history(self):
        self.assertEqual(make_events({("BIST","ABCD"):self.bars(99)}),[])
    def test_cross_market_independence(self):
        s={("US","AAAA"):self.bars()}
        base=make_events(s)
        s[("BIST","AAAA")]=self.bars()
        extended=make_events(s)
        self.assertEqual([x for x in extended if x["market"]=="US"],base)

if __name__=="__main__":unittest.main()
