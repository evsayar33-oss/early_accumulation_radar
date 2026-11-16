import unittest
from radar.notify import format_message,send

class NotificationTest(unittest.TestCase):
    def sample(self,venue="binance",flag=True):
        return {"schema":"EAR.research.v2",
                "quotes":{"assets":[{"asset":"BTC","status":"WATCH_ONLY","venues":3}]},
                "candle_diagnostics":[{"asset":"BTC","source_venue":venue,"accumulation_watch":flag,
                 "distribution_watch":False,"price":100.0,
                 "relative_median_volume_10m_vs_60m":2.0,
                 "taker_buy_quote_fraction_10m":.65}]}
    def test_watch_is_not_buy(self):
        msg=format_message(self.sample())
        self.assertIn("ARAŞTIRMA",msg)
        self.assertIn("emri",msg)
    def test_no_secret_no_network(self):
        self.assertEqual(send(self.sample(),"",""),"NOT_CONFIGURED")
    def test_no_message_if_no_flags(self):
        self.assertIsNone(format_message(self.sample(flag=False)))
    def test_okx_volume_only_not_alerted(self):
        self.assertIsNone(format_message(self.sample(venue="okx")))
    def test_sender_stub(self):
        sent=[]
        self.assertEqual(send(self.sample(),"fake","1",post=lambda body: sent.append(body) or "stub"),"stub")
        self.assertEqual(len(sent),1)
