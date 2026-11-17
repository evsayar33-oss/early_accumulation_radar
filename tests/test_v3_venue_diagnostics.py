import unittest
from radar.providers import Quote
from research_v3.venue_diagnostics import collect

NOW = 1794900000000

def q(venue, asset, bid=1.0, ask=1.001, qty=1000):
    return Quote(venue, asset, bid, ask, qty, qty, NOW, NOW, venue)


class VenueDiagnosticsTests(unittest.TestCase):
    def test_depth_rejection_does_not_fabricate_mark(self):
        def get(venue, asset):
            return q(venue, asset, qty=10 if venue == "gate" else 1000)
        result = collect(assets=("SUI",), venues=("binance", "gate"), quote_get=get,
                         clock=lambda: NOW)
        self.assertFalse(result["assets"]["SUI"]["mark_eligible"])
        self.assertFalse(result["paper_mark_created"])
        gate = next(x for x in result["assets"]["SUI"]["venues"] if x["venue"]=="gate")
        self.assertIn("TOP_OF_BOOK_DEPTH_BELOW_500_USDT", gate["reasons"])

    def test_two_independent_valid_venues(self):
        result = collect(assets=("XRP",), venues=("binance", "okx"),
                         quote_get=lambda v,a:q(v,a), clock=lambda:NOW)
        self.assertTrue(result["assets"]["XRP"]["mark_eligible"])

    def test_fetch_failure_is_visible(self):
        def get(venue, asset):
            if venue=="okx": raise RuntimeError("HTTP_403")
            return q(venue,asset)
        result=collect(assets=("LINK",),venues=("binance","okx"),
                       quote_get=get,clock=lambda:NOW)
        self.assertEqual(result["assets"]["LINK"]["eligible_venues"],1)
        self.assertTrue(any("HTTP_403" in x.get("error","") for x in result["assets"]["LINK"]["venues"]))


if __name__ == "__main__":
    unittest.main()
