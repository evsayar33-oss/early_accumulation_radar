import unittest
from research_v3.depth_shadow import decode_levels, vwap_for_notional, evaluate, collect


class DepthShadowTests(unittest.TestCase):
    def test_multiple_levels_fill_without_top_of_book_fiction(self):
        data = {"bids": [["1.0", "10"], ["0.99", "1000"]],
                "asks": [["1.01", "10"], ["1.02", "1000"]]}
        result = evaluate("binance", "SUI", lambda url: data)
        self.assertTrue(result["both_sides_executable"])
        self.assertGreater(result["ask_impact_bps"], 0)
        self.assertGreater(result["bid_impact_bps"], 0)
        self.assertEqual(result["ask"]["levels_used"], 2)

    def test_empty_or_crossed_orderbook_rejected(self):
        with self.assertRaises(ValueError):
            decode_levels("gate", {"bids": [], "asks": [["1.01", "1"]]})
        with self.assertRaises(ValueError):
            decode_levels("gate", {"bids": [["1.02", "10"]],
                                   "asks": [["1.01", "10"]]})

    def test_insufficient_depth_is_not_executable(self):
        x = vwap_for_notional([(1.0, 20), (0.99, 20)])
        self.assertFalse(x["executable"])
        self.assertIsNone(x["vwap"])

    def test_okx_book_schema(self):
        d={"code":"0","data":[{"bids":[["1.0","1000","0","1"]],
                               "asks":[["1.01","1000","0","1"]]}]}
        bids,asks=decode_levels("okx",d)
        self.assertEqual(bids[0][1],1000)
        self.assertEqual(asks[0][0],1.01)

    def test_independent_depth_summary_never_approves_paper_mark(self):
        data={"bids":[["1.0","1000"]],"asks":[["1.01","1000"]]}
        report=collect(assets=("SUI",),venues=("binance",),getter=lambda url:data)
        self.assertEqual(report["summary"]["SUI"]["count"],1)
        self.assertFalse(report["summary"]["SUI"]["two_venue_depth_available"])
        self.assertIsNone(report["summary"]["SUI"]["paper_mark_eligible"])
        self.assertTrue(report["not_a_paper_mark"])

    def test_failure_does_not_impute_liquidity(self):
        report=collect(assets=("SUI",),venues=("gate",),
                       getter=lambda url: (_ for _ in ()).throw(RuntimeError("offline")))
        self.assertTrue(report["not_a_paper_mark"])
        self.assertFalse(report["rows"][0]["both_sides_executable"])
        self.assertIn("offline",report["rows"][0]["error"])


if __name__ == "__main__":
    unittest.main()
