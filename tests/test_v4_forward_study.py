"""Event study must use future first-seen observations, never next-bar lookahead."""
from datetime import date,timedelta,timezone,datetime
from pathlib import Path
import tempfile
import unittest
from radar.ledger import digest,canonical
from research_v4.forward_study import study, WARMUP_SESSIONS, FORWARD_SESSIONS

def make_ledger(path,days):
    prev="GENESIS"
    rows=[]
    for i in range(days):
        day=date(2026,1,1)+timedelta(days=i)
        ts=int(datetime(day.year,day.month,day.day,tzinfo=timezone.utc).timestamp()*1000)
        # Signal at day 20 only; never an executable fill.
        volume=5000 if i==20 else 100
        close=1.1 if i==25 else 1.0
        rec={"schema":"EAR.V4.equity.firstseen.v1","scan_utc_ms":ts+3600000,
             "markets":{"BIST":{"sample":[{"symbol":"TEST","last_bar":{
                "ts_ms":ts,"session_utc":day.isoformat(),"open":1.0,
                "close":close,"volume":volume}}]},
                "US":{"sample":[]}},"no_orders":True}
        rec["prev_sha256"]=prev
        rec["sha256"]=digest(rec)
        prev=rec["sha256"]
        rows.append(canonical(rec))
    Path(path).write_text("\n".join(rows)+"\n")
    
class ForwardStudyTests(unittest.TestCase):
    def test_forward_outcome_needs_all_future_observations(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"events.jsonl"
            make_ledger(path,WARMUP_SESSIONS+FORWARD_SESSIONS)
            early=study(path)
            self.assertEqual(early["by_market"]["BIST"]["event_count"],0)
            make_ledger(path,WARMUP_SESSIONS+FORWARD_SESSIONS+1)
            later=study(path)
            self.assertEqual(later["by_market"]["BIST"]["event_count"],1)
            e=later["events"][0]
            self.assertEqual(e["signal_session"],"2026-01-21")
            self.assertEqual(e["next_open_to_fifth_close_raw_move_pct"],10.0)
            self.assertLess(e["signal_first_observed_ms"],e["next_open_first_observed_ms"])
            self.assertLess(e["next_open_first_observed_ms"],e["outcome_first_observed_ms"])
            self.assertFalse(later["alpha_approved"])
            self.assertFalse(later["paper_approved"])

    def test_hash_corruption_blocks_study(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"events.jsonl"
            make_ledger(path,5)
            path.write_text(path.read_text().replace('"no_orders":true','"no_orders":false'))
            with self.assertRaises(ValueError):
                study(path)
if __name__=="__main__":unittest.main()
