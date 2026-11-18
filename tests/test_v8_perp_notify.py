import unittest
from research_v4.perp_notify import format_message,send

class PerpNotifyTests(unittest.TestCase):
    def report(self,stage="EARLY_UPWARD_MOTION_WATCH",confirm="CONSISTENT_TWO_VENUES"):
        return {"schema":"EAR.perp_forward_summary.v1","new_events":[{
            "symbol":"PIPPINUSDT","stage":stage,"price_at_observation":0.0112,
            "interval_minutes":30,"interval_return_pct":2.7,
            "rolling_24h_change_pct":5.1,"cross_venue":confirm}]}
    def test_no_unproven_buy_claim(self):
        msg=format_message(self.report())
        self.assertIn("PIPPINUSDT",msg)
        self.assertIn("AL/SAT önerisi",msg)
        self.assertIn("sonradan".upper(),msg.upper())
        self.assertIn("2 borsa",msg)
    def test_early_and_late_distinguished(self):
        msg=format_message(self.report("UPWARD_IMPULSE_ALREADY_IN_PROGRESS"))
        self.assertIn("ZATEN BAŞLAMIŞ",msg)
    def test_single_source_labeled_unverified(self):
        msg=format_message(self.report(confirm="UNCONFIRMED_SINGLE_VENUE"))
        self.assertIn("TEK BORSA",msg)
        self.assertIn("TEYİTSİZ",msg)
    def test_divergent_not_alerted(self):
        self.assertIsNone(format_message(self.report(confirm="DIVERGENT_TWO_VENUES")))
    def test_no_config_or_empty_message_no_send(self):
        self.assertEqual(send(None,"tok","chat"),"NO_ADVISORY")
        self.assertEqual(send("msg","",""),"TELEGRAM_NOT_CONFIGURED")
    def test_post_stub(self):
        sent=[]
        self.assertEqual(send("msg","fake","chat",post=lambda b:sent.append(b) or "ok"),"ok")
        self.assertEqual(len(sent),1)

if __name__=="__main__":unittest.main()
