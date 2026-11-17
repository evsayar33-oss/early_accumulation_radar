import unittest
from radar.flow_coherence import annotate
from radar.notify import format_message

class FlowCoherenceTests(unittest.TestCase):
    def candle(self):
        return {"asset":"ETH","source_venue":"binance","instrument":"BINANCE_SPOT",
                "price":1801.05,"relative_median_volume_10m_vs_60m":1.81,
                "taker_buy_quote_fraction_10m":.60546,
                "accumulation_watch":True,"distribution_watch":False}
    def test_opposing_short_sample_is_flagged_but_does_not_flip(self):
        candle=self.candle()
        result=annotate([candle],[{"asset":"ETH","venue":"binance","status":"SAMPLED",
            "sample_span_s":54,"count":500,"taker_buy_fraction":.39926,
            "coverage":"RECENT_SAMPLE_NOT_CONTINUOUS"}])[0]
        self.assertTrue(result["accumulation_watch"])
        self.assertIn("BINANCE_RECENT_SAMPLED_FLOW_OPPOSES_10M_CANDLE_FLOW_DIFFERENT_TIME_WINDOWS",result["flow_quality_warnings"])
        self.assertFalse(result["multi_venue_taker_confirmation"])
        report={"schema":"EAR.research.v2","quotes":{"assets":[{"asset":"ETH","status":"WATCH_ONLY","venues":3}]},
                "candle_diagnostics":[result]}
        m=format_message(report)
        self.assertIn("Binance 10dk",m)
        self.assertIn("fiyat/likidite",m)
        self.assertIn("DİKKAT",m)
    def test_agreement_not_claimed_cross_venue(self):
        c=annotate([self.candle()],[{"asset":"ETH","venue":"okx","status":"SAMPLED",
            "sample_span_s":30,"count":100,"taker_buy_fraction":.9}])[0]
        self.assertFalse(c["multi_venue_taker_confirmation"])
        self.assertEqual(c["flow_confidence"],"TIME_WINDOWS_NOT_COMPARABLE")
        self.assertFalse(c["flow_quality_warnings"])
    def test_no_tape_is_not_fabricated(self):
        c=annotate([self.candle()],[])[0]
        self.assertIn("NO_RECENT_TRADE_SAMPLE",c["flow_quality_warnings"])
    def test_fallback_cannot_gain_confirmation(self):
        c=self.candle();c["source_venue"]="okx"
        out=annotate([c],[])[0]
        self.assertEqual(out["signal_evidence_scope"],"VOLUME_ONLY_FALLBACK")
        self.assertFalse(out["multi_venue_taker_confirmation"])

if __name__=="__main__":unittest.main()
