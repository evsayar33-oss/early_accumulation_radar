"""V15 validates source cadence, retries and research provenance offline."""
import unittest
from datetime import datetime,timedelta,timezone
from research_v4.crypto_autonomy import decide,coverage_windows

NOW=datetime(2026,11,21,14,0,tzinfo=timezone.utc)
NOW_MS=int(NOW.timestamp()*1000)

def run(id,old_hours=0,conclusion="success",status="completed"):
    t=NOW-timedelta(hours=old_hours)
    return {"id":id,"created_at":t.isoformat(),
            "updated_at":(t+timedelta(minutes=2)).isoformat(),
            "status":status,"conclusion":conclusion,"head_branch":"main"}
def src(age_m=15):
    return {"last_scan_utc":(NOW-timedelta(minutes=age_m)).isoformat(),
            "sha256":"current_sha"}
def v13(active=True):
    return {"source_v8_last_sha256":"current_sha" if active else "old_sha",
            "source_status":"FRESH_V8_RESEARCH_OBSERVATIONS" if active else
                            "STALE_UPSTREAM_V8_WATCH_ONLY",
            "asof_observations":0,"modeled_outcomes":0}

class CryptoContinuity(unittest.TestCase):
    def test_regular_30_min_tape_has_real_4h_windows(self):
        stamps=[NOW_MS+i*30*60000 for i in range(20)]
        stats=coverage_windows(stamps)
        self.assertGreater(stats["observed_cadence_viable_windows"],0)
        self.assertLessEqual(stats["observed_cadence_viable_windows"],
                             stats["eligible_completed_windows"])

    def test_sparse_scans_cannot_fabricate_4h_matured_cohort(self):
        stamps=[NOW_MS+i*3*3600000 for i in range(20)]
        stats=coverage_windows(stamps)
        self.assertEqual(stats["observed_cadence_viable_windows"],0)

    def test_fully_healthy_never_requests_runs_or_trades(self):
        r=decide(NOW,src(),{"V8":[run(1)],"V11":[run(2,10)],
                 "V13":[run(3)]},{"matured_case_control_samples":0},v13())
        self.assertEqual(r["recoveries"],[])
        self.assertFalse(r["trade_authorized"])

    def test_v8_stale_requests_real_scan_not_fake_backfill(self):
        r=decide(NOW,src(180),{"V8":[run(1,5)],"V11":[run(2,10)],
                        "V13":[]},{},v13(False))
        self.assertEqual([x["key"] for x in r["recoveries"]],["V8"])
        self.assertEqual(r["health"]["V13"],"WAITING_V8_RECOVERY")

    def test_active_producer_not_double_dispatched(self):
        r=decide(NOW,src(180),{"V8":[run(1,2,None,"in_progress")],
                 "V11":[run(2,10)],"V13":[]},{},v13(False))
        self.assertEqual(r["recoveries"],[])
        self.assertEqual(r["health"]["V8"],"PRODUCER_ACTIVE")

    def test_recovery_debounced_after_recent_failed_job(self):
        r=decide(NOW,src(100),{"V8":[run(1,.3,"failure")],
                 "V11":[run(2,10)],"V13":[]},{},v13(False))
        self.assertEqual(r["recoveries"],[])
        self.assertEqual(r["health"]["V8"],"RECENT_PRODUCER_ATTEMPT_WAIT")

    def test_v13_missing_fresh_source_triggers_only_costed_research(self):
        r=decide(NOW,src(25),{"V8":[run(1,1)],"V11":[run(2,10)],
                  "V13":[run(3,3)]},{},v13(False))
        self.assertEqual([x["key"] for x in r["recoveries"]],["V13"])

    def test_v13_new_source_gets_settlement_grace(self):
        r=decide(NOW,src(5),{"V8":[run(1,1)],"V11":[run(2,10)],
                 "V13":[run(3,3)]},{},v13(False))
        self.assertEqual(r["health"]["V13"],"WAITING_V8_PERSISTENCE")
        self.assertEqual(r["recoveries"],[])

    def test_v11_daily_research_recovers_separately(self):
        r=decide(NOW,src(20),{"V8":[run(1,1)],"V11":[run(2,50)],
                 "V13":[run(3)]},{},v13())
        self.assertEqual([x["key"] for x in r["recoveries"]],["V11"])

    def test_stale_v8_blocks_new_v13_sample_even_if_v11_old(self):
        r=decide(NOW,src(180),{"V8":[run(1,10)],"V11":[run(2,50)],
                 "V13":[]},{},v13(False))
        self.assertNotIn("V13",[x["key"] for x in r["recoveries"]])

if __name__=="__main__":
    unittest.main()
