"""Autonomous learner: no invented winners, locked future-only decisions, exact tests."""
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from radar.ledger import read_verify
from research_v4 import pattern_learner as p
from research_v4.pattern_notify import format_message
from research_v4.preimpulse_study import MOTIFS

BASE=datetime(2026,11,23,10,0,0,tzinfo=timezone.utc)
RULE="relative_oi_contracts_outlier"

def row(day,symbol,case=True,rule=RULE):
    t=datetime(2026,11,15,tzinfo=timezone.utc)+timedelta(days=day)
    motifs={name:False for name in MOTIFS}
    motifs[rule]=case
    return {"observed_utc":t.isoformat(),"symbol":symbol,"venue":"okx",
            "future":{"label":"UPSIDE_EXTREME" if case else "NO_EXTREME_MOVE",
                      "future_end_utc":(t+timedelta(hours=5)).isoformat()},
            "features":{"stratum":"M:CALM","motifs":motifs}}

def cohort(start_day=0,days=4,rule=RULE):
    # 40 genuine case events, 320 contemporaneous non-moving controls.
    # 10 distinct case assets per day and 80 distinct control assets per day.
    return [row(day,"CASE"+str(i),True,rule)
            for day in range(start_day,start_day+days) for i in range(10)]+[
           row(day,"CONTROL"+str(i),False,rule)
            for day in range(start_day,start_day+days) for i in range(80)]

def fake_study(rows):
    return {"scans_in_window":400,"eligible_asof_cohort_count":len(rows),
            "matured_full_control_population":len(rows),
            "future_label_counts":{"UPSIDE_EXTREME":40,"NO_EXTREME_MOVE":320},
            "matured_cohort_rows":rows}

class V11Contracts(unittest.TestCase):
    def test_rule_family_contains_single_metrics_and_independent_pairs(self):
        self.assertIn(RULE,p.RULES)
        self.assertIn("relative_turnover_24h_outlier + relative_oi_contracts_outlier",p.RULES)
        self.assertNotIn("relative_any_metric_outlier + relative_oi_contracts_outlier",p.RULES)
        self.assertEqual(len(p.RULES),len(set(p.RULES)))
    def test_fisher_and_bh_known_significance(self):
        matched=p.case_control(cohort(),"UPSIDE_EXTREME")
        a=p.measure(matched,RULE,"UPSIDE_EXTREME")
        self.assertEqual(a["matched_case_total"],40)
        self.assertEqual(a["matched_nonmover_controls"],320)
        self.assertEqual(a["case_with_rule"],40)
        self.assertEqual(a["control_with_rule_false_alarms"],0)
        self.assertEqual(a["case_symbols"],10)
        self.assertEqual(a["case_days"],4)
        self.assertLess(a["fisher_one_sided_p"],1e-12)
        report=p.summarize(cohort())
        positive=next(x for x in report if x["direction"]=="UPSIDE_EXTREME" and x["rule"]==RULE)
        self.assertLess(positive["bh_fdr_q"],.05)
        self.assertTrue(p.qualifies(positive))
        negative=next(x for x in report if x["direction"]=="DOWNSIDE_EXTREME" and x["rule"]==RULE)
        self.assertFalse(p.qualifies(negative))
    def test_common_but_not_discriminating_is_rejected(self):
        rows=cohort()
        for r in rows:r["features"]["motifs"][RULE]=True
        report=p.summarize(rows)
        a=next(x for x in report if x["direction"]=="UPSIDE_EXTREME" and x["rule"]==RULE)
        self.assertEqual(a["sampled_false_alarm_rate"],1.)
        self.assertFalse(p.qualifies(a))
    def test_insufficient_event_variety_rejected(self):
        rows=cohort(days=1)
        report=p.summarize(rows)
        a=next(x for x in report if x["direction"]=="UPSIDE_EXTREME" and x["rule"]==RULE)
        self.assertFalse(p.qualifies(a))
    def test_missing_oi_is_not_control_no_vote(self):
        rows=cohort()
        for r in rows:
            if r["future"]["label"]=="NO_EXTREME_MOVE":
                r["features"]["motifs"][RULE]=None
        a=p.measure(p.case_control(rows,"UPSIDE_EXTREME"),RULE,"UPSIDE_EXTREME")
        self.assertEqual(a["matched_nonmover_controls"],0)
        self.assertFalse(p.qualifies({**a,"bh_fdr_q":0.0}))
    def test_untouched_source_no_training_alpha_from_just_two_scans(self):
        from research_v4.perp_watch import append
        base=1763200000000
        rows=[]
        for i in range(2):
            ts=base+i*30*60000
            obj={"scan_utc_ms":ts,"market_type":"USDT_LINEAR_PERPETUAL_ONLY",
                "assets":{"PIPPINUSDT":{"okx":{"p":.011,"q":1000000,"d":1,"ts":ts}}},
                "sources":["okx"],"source_unavailable":{}}
            rows.append(append(obj,rows))
        asof=datetime.fromtimestamp((base+3600000)/1000,timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            r=p.infer_report(rows,Path(tmp),asof,"frozen-version")
            self.assertEqual(r["eligible_asof_samples"],0)
            self.assertEqual(r["notices"],[])
            self.assertEqual(r["new_hypotheses_frozen"],0)
    def test_candidate_does_not_lock_outside_weekly_precommitted_checkpoint(self):
        source=[{"scan_utc_ms":int((BASE-timedelta(minutes=1)).timestamp()*1000),
                 "sha256":"source"}]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(p,"study",return_value=fake_study(cohort())):
                t=BASE+timedelta(days=1)  # Tuesday
                result=p.infer_report(source,Path(tmp),t.isoformat(),"v1")
                self.assertFalse(result["is_new_lock_checkpoint_now"])
                self.assertEqual(result["new_hypotheses_frozen"],0)
                self.assertEqual(result["notices"],[])
    def test_no_second_lock_for_same_direction_during_active_trial(self):
        source=[{"scan_utc_ms":int((BASE-timedelta(minutes=1)).timestamp()*1000),
                 "sha256":"source"}]
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            with patch.object(p,"study",return_value=fake_study(cohort())):
                first=p.infer_report(source,state,BASE.isoformat(),"v1")
                next_monday=BASE+timedelta(days=7)
                again=p.infer_report(source,state,next_monday.isoformat(),"v1")
            self.assertEqual(first["new_hypotheses_frozen"],1)
            self.assertEqual(again["new_hypotheses_frozen"],0)
            self.assertEqual(again["notices"],[])
    def test_freeze_never_backfills_and_holdout_closes_once(self):
        first=cohort()
        start=BASE
        source=[{"scan_utc_ms":int((start-timedelta(minutes=1)).timestamp()*1000),
                 "sha256":"sourcehash"}]
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            with patch.object(p,"study",return_value=fake_study(first)):
                report=p.infer_report(source,state,start.isoformat(),"v1")
            self.assertEqual(report["new_hypotheses_frozen"],1)
            self.assertEqual(report["new_prospective_rows"],0)
            self.assertEqual(report["notices"][0]["kind"],"NEW_RESEARCH_CANDIDATE")
            original=read_verify(state/"frozen.jsonl")
            self.assertEqual(len(original),1)
            self.assertEqual(original[0]["trial_start_utc"],"2026-11-24T00:00:00+00:00")
            self.assertEqual(original[0]["trial_end_utc"],"2026-12-01T00:00:00+00:00")
            # All new observations were first timestamped AFTER the freeze,
            # never taken from the pre-freeze 15-18 November training sample.
            future=cohort(start_day=10,days=4) # Nov 25–28 inclusive
            closed=datetime(2026,12,1,6,tzinfo=timezone.utc)
            source2=[{"scan_utc_ms":int((closed-timedelta(minutes=1)).timestamp()*1000),
                      "sha256":"sourcehash2"}]
            with patch.object(p,"study",return_value=fake_study(future)):
                result=p.infer_report(source2,state,closed.isoformat(),"v1")
                repeat=p.infer_report(source2,state,(closed+timedelta(minutes=1)).isoformat(),"v1")
            self.assertEqual(result["new_prospective_rows"],360)
            self.assertEqual(result["decisions_total"],1)
            self.assertEqual(result["completed_decisions_now"][0]["status"],
                "PROSPECTIVE_ASSOCIATION_REPLICATED_NOT_TRADING_ALPHA")
            self.assertEqual(repeat["completed_decisions_now"],[])
            self.assertEqual(repeat["new_prospective_rows"],0)
            self.assertEqual(repeat["notices"],[])
            self.assertEqual(len(read_verify(state/"decisions.jsonl")),1)
            msg=format_message(result)
            self.assertIn("İLERİ VERİDE TEKRARLANDI",msg)
            self.assertIn("Nedensellik",msg)
            self.assertFalse(result["claims"]["paper_approved"])
    def test_drift_keeps_old_locked_protocol_paused(self):
        start=BASE
        source=[{"scan_utc_ms":int((start-timedelta(minutes=1)).timestamp()*1000),
                 "sha256":"sourcehash"}]
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp)
            with patch.object(p,"study",return_value=fake_study(cohort())):
                p.infer_report(source,state,start.isoformat(),"old-version")
                tomorrow=start+timedelta(days=9)
                r=p.infer_report([{"scan_utc_ms":int((tomorrow-timedelta(minutes=1)).timestamp()*1000),
                                   "sha256":"sourcehash2"}],
                                 state,tomorrow.isoformat(),"new-version")
            self.assertIn("PAUSED_CODE_DRIFT",[x["status"] for x in r["active_trials"]])
            self.assertEqual(len(read_verify(state/"decisions.jsonl")),0)
    def test_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"x.jsonl"
            p.append_sealed(path,[{"kind":"freeze"}],1762000000000)
            self.assertEqual(len(read_verify(path)),1)
            data=path.read_text().replace('"freeze"','"tampered"')
            path.write_text(data)
            with self.assertRaises(ValueError):read_verify(path)
    def test_empty_notices_never_notify(self):
        self.assertIsNone(format_message({"schema":"EAR.v11_automatic_pattern_discovery.v1","notices":[]}))
        with self.assertRaises(ValueError):format_message({"schema":"NOPE","notices":[]})

if __name__=="__main__":unittest.main()
