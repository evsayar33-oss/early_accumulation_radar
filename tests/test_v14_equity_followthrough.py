"""V12 out-of-sample symbol recovery; no fabricated price, no new signal."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from research_v4.equity_followthrough import recover_settlement_universe
from research_v4 import v12_equity_patterns as v12
from radar.ledger import read_verify

NOW = datetime(2026, 11, 21, 9, tzinfo=timezone.utc)

def bars(symbol, market, now_ms):
    first = date(2026, 10, 1)
    from datetime import timedelta
    return ([((first + timedelta(days=i)).isoformat(), 100., 103., 99.,
              100. + i * .05, 1000.) for i in range(51)],
            "public_unauthenticated")

class OffUniverseFollowThrough(unittest.TestCase):
    def test_recover_only_prior_symbols_for_settlement(self):
        observations = [
            {"market":"BIST", "symbol":"FORMER", "observed_utc":"2026-11-15T09:00:00+00:00"},
            {"market":"US", "symbol":"OTHER", "observed_utc":"2026-11-15T09:00:00+00:00"},
        ]
        output, report = recover_settlement_universe({}, "BIST", observations, NOW, fetch=bars)
        self.assertEqual(report["symbols_recovered"], ["FORMER"])
        self.assertNotIn(("US","OTHER"), output)
        self.assertTrue(report["not_executable_fill"])
        self.assertLess(output[("BIST","FORMER")][-1]["date"], NOW.date())
        self.assertEqual(report["attempted"], 1)

    def test_provider_failure_never_invents_settlement(self):
        def offline(*args):
            raise ValueError("no_data")
        out, r = recover_settlement_universe({}, "US",
            [{"market":"US","symbol":"DELIST","observed_utc":"2026-11-01T00:00:00+00:00"}],
            NOW, fetch=offline)
        self.assertEqual(out,{})
        self.assertEqual(r["symbols_recovered"],[])
        self.assertIn("DELIST",r["missing_symbols"])

    def test_prior_out_of_sample_settles_but_never_generates_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            t0 = datetime(2026, 5, 1, 9, tzinfo=timezone.utc)
            original = {("BIST","FORMER"):[
               {"date":date(2026,1,1)+timedelta(days=i),
                "open":100.,"high":101.,"low":99.,"close":100.,"volume":1000.,
                "pit":False,"actions":False}
               for i in range(120)]}
            r = v12.execute(original, "BIST", t0, "src", "1", state, version="v1")
            self.assertEqual(r["new_asof_observations"], 1)
            # V5's current sample dropped FORMER; recovery is settlement only.
            newer = {("BIST","FORMER"):original[("BIST","FORMER")] + [
                {"date":date(2026,5,2)+timedelta(days=i),
                 "open":100.,"high":101.,"low":99.,"close":100.,"volume":1000.,
                 "pit":False,"actions":False} for i in range(12)]}
            r = v12.execute({}, "BIST", t0 + timedelta(days=15),
                "src2", "2", state, version="v1",
                settlement_series=newer,
                recovery={"symbols_recovered":["FORMER"],"missing_symbols":[],"errors":{}})
            self.assertEqual(r["new_asof_observations"], 0)
            self.assertGreaterEqual(r["new_forward_outcomes"],1)
            self.assertEqual(r["recovery"]["symbols_recovered"],["FORMER"])
            self.assertTrue(all(o.get("settlement_source")=="FUTURE_YAHOO_RECOVERY_NOT_V5_ARTIFACT"
                for o in read_verify(state/"BIST"/"outcomes.jsonl")))

if __name__=="__main__":
    unittest.main()
