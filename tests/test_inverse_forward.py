"""Offline tests; no hindsight, no fake shorts, pending missing bars."""
import unittest
from radar.inverse_forward import study,observation,HORIZONS_MIN

BASE=1800000000000
def snap(minute,price,asset="ETH",watch=False,distribution=False,venue="binance"):
    t=BASE+minute*60000
    return {"scan_utc_ms":t,"quote_health":[{"asset":asset,"status":"WATCH_ONLY"}],
      "candle_diagnostics":[{"asset":asset,"instrument":"BINANCE_SPOT",
        "source_venue":venue,"price":price,"last_closed_bar_ms":t-120000,
        "accumulation_watch":watch,"distribution_watch":distribution}]}

class InverseTests(unittest.TestCase):
    def test_no_future_record_means_pending(self):
        r=study([snap(0,100,watch=True)])
        self.assertEqual(len(r["events"]),1)
        self.assertTrue(all(x["status"]=="PENDING_MISSING_VALID_ENTRY" for x in r["events"][0]["horizons"]))
        self.assertFalse(r["profitability_confirmed"])
    def test_normal_and_inverse_are_opposite_less_friction(self):
        r=study([snap(0,100,watch=True),snap(12,99),snap(45,97)])
        x=r["events"][0]["horizons"][0]
        self.assertEqual(x["status"],"OBSERVED_DIRECTIONAL_COMPARISON")
        self.assertLess(x["normal_directional_net_pct"],0)
        self.assertGreater(x["inverse_directional_net_pct"],0)
        self.assertAlmostEqual(x["normal_directional_net_pct"]+x["inverse_directional_net_pct"],-.6,places=4)
        self.assertFalse(x["executable_short_verified"])
    def test_only_future_entries_no_signal_close_fill(self):
        r=study([snap(0,100,watch=True),snap(10,110),snap(41,111)])
        self.assertEqual(r["events"][0]["entry_price"],110)
    def test_stale_or_wrong_venue_is_rejected(self):
        r=snap(0,100,venue="okx",watch=True)
        self.assertIsNone(observation(r,"ETH"))
    def test_missing_exit_not_fabricated(self):
        r=study([snap(0,100,watch=True),snap(10,99)])
        self.assertTrue(all(x["status"]=="PENDING_NO_EXIT_OBSERVATION" for x in r["events"][0]["horizons"]))
    def test_distribution_inverse_long(self):
        r=study([snap(0,100,distribution=True),snap(10,100),snap(41,110)])
        e=r["events"][0]
        self.assertEqual(e["horizons"][0]["inverse_direction"],"LONG")
        self.assertGreater(e["horizons"][0]["inverse_directional_net_pct"],0)
    def test_cooldown_no_double_count(self):
        r=study([snap(0,100,watch=True),snap(10,101,watch=True),snap(70,102,watch=True)])
        self.assertEqual(len(r["events"]),2)

if __name__=="__main__":unittest.main()
