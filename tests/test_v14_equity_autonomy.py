"""Offline regression for V14 chained schedule recovery and risk separation."""
import unittest
from datetime import datetime, timedelta, timezone
from research_v4.equity_autonomy import recovery_plan, v5_matured_slot

NOW = datetime(2026, 11, 21, 17, 30, tzinfo=timezone.utc)  # Saturday

def run(n, created, success=True, event="schedule", status="completed", duration=3):
    return {"id": n, "created_at":created.isoformat(),
            "updated_at":(created + timedelta(minutes=duration)).isoformat(),
            "status":status, "conclusion":"success" if success else "failure",
            "event":event,"head_branch":"main"}

class V14Continuity(unittest.TestCase):
    def test_saturday_v5_matured_slot_and_no_future_peek(self):
        slot = v5_matured_slot(NOW)
        self.assertEqual(slot.weekday(), 5)
        self.assertEqual((slot.hour, slot.minute), (3, 47))

    def test_only_v5_recovery_when_upstream_missing(self):
        last = run(1, NOW - timedelta(days=1))
        result = recovery_plan({"V5":[last], "V12":[], "V13":[]}, NOW)
        self.assertEqual([a["key"] for a in result["recoveries"]], ["V5"])
        self.assertFalse(result["trade_authorized"])

    def test_healthy_chain_never_restarts_and_no_trades(self):
        r5=run(5, NOW-timedelta(hours=6))
        r12=run(12, NOW-timedelta(hours=4))
        r13=run(13, NOW-timedelta(hours=2))
        result=recovery_plan({"V5":[r5], "V12":[r12], "V13":[r13]}, NOW)
        self.assertEqual(result["recoveries"], [])
        self.assertFalse(result["paper_approved"])

    def test_v12_missing_dependent_success_triggers_dispatch_exact_id(self):
        r5=run(567, NOW-timedelta(hours=5))
        r12=run(8, NOW-timedelta(days=1))
        result=recovery_plan({"V5":[r5], "V12":[r12], "V13":[]}, NOW)
        self.assertEqual([a["key"] for a in result["recoveries"]], ["V12"])
        self.assertEqual(result["recoveries"][0]["inputs"]["source_run_id"],"567")

    def test_v13_missing_triggers_only_v13(self):
        r5=run(5, NOW-timedelta(hours=5))
        r12=run(12, NOW-timedelta(hours=3))
        result=recovery_plan({"V5":[r5], "V12":[r12], "V13":[]}, NOW)
        self.assertEqual([a["key"] for a in result["recoveries"]], ["V13"])

    def test_active_v5_never_duplicate_dispatch(self):
        r=run(6,NOW-timedelta(hours=1),False,status="in_progress")
        result=recovery_plan({"V5":[r], "V12":[], "V13":[]}, NOW)
        self.assertEqual(result["recoveries"],[])

    def test_recent_failed_run_respects_backoff(self):
        old=run(6,NOW-timedelta(days=1))
        attempt=run(7,NOW-timedelta(hours=1),False,event="workflow_dispatch")
        result=recovery_plan({"V5":[attempt,old],"V12":[],"V13":[]},NOW)
        self.assertEqual(result["recoveries"],[])

    def test_weekend_does_not_assume_new_sunday_slot(self):
        sunday=NOW + timedelta(days=1)
        self.assertEqual(v5_matured_slot(sunday),v5_matured_slot(NOW))

if __name__=="__main__":
    unittest.main()
