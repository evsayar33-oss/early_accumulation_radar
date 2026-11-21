"""Regression: preferred venue data gaps may fall back, never cherry-pick."""
import unittest
from unittest.mock import patch
from research_v4.perp_watch import append
from research_v4.preimpulse_study import study, MOTIFS

BASE = 1795100000000

def records():
    ledger=[]
    for i in range(12):
        t=BASE+i*30*60000
        quote={"p":100.,"q":1500000.,"d":0.,"ts":t,"oi_contracts":100}
        sample={"scan_utc_ms":t,
                "market_type":"USDT_LINEAR_PERPETUAL_ONLY",
                "source_unavailable":{},"sources":["okx","bitget"],
                "assets":{"TESTUSDT":{"okx":dict(quote),"bitget":dict(quote)}}}
        ledger.append(append(sample,ledger))
    return ledger

def good_features():
    return {"price_return_2h_pct":0.,"return_24h_pct":0.,
            "turnover_24h_usdt":1500000.,
            "stratum":"MEDIUM:CALM",
            "motifs":{m:False for m in MOTIFS}}

class SourceIsolation(unittest.TestCase):
    def test_fallback_uses_second_venue_own_history_only(self):
        seen=[]
        def actual(history,t,venue):
            seen.append(venue)
            return None if venue=="okx" else good_features()
        with patch("research_v4.preimpulse_study.features",side_effect=actual):
            report=study(records())
        self.assertIn("bitget",seen)
        self.assertGreater(report["eligible_asof_cohort_count"],0)
        self.assertEqual({x["venue"] for x in report["recent_examples"]},{"bitget"})
        self.assertFalse(report["proven_profitable_strategy"])

    def test_do_not_fallback_from_valid_but_already_moving_preferred_venue(self):
        def moving(history,t,venue):
            if venue=="bitget":
                raise AssertionError("A usable preferred venue cannot be cherry-picked away")
            value=good_features()
            value["price_return_2h_pct"]=5
            return value
        with patch("research_v4.preimpulse_study.features",side_effect=moving):
            report=study(records())
        self.assertEqual(report["eligible_asof_cohort_count"],0)
        self.assertGreater(report["skipped_asof_reasons"].get(
            "ALREADY_MOVING_NOT_PRECURSOR",0),0)

    def test_missing_venue_history_is_not_invented(self):
        with patch("research_v4.preimpulse_study.features",return_value=None):
            report=study(records())
        self.assertEqual(report["eligible_asof_cohort_count"],0)
        self.assertGreater(report["skipped_asof_reasons"].get(
            "NO_2H_ASOF_HISTORY_ON_ANY_VENUE",0),0)

if __name__=="__main__":
    unittest.main()
