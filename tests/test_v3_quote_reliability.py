"""Quote retry regression: no synthetic marks, no provenance substitution."""
import unittest
from radar.providers import fetch_quote, FeedError


class QuoteReliability(unittest.TestCase):
    def test_gate_empty_book_then_valid_book(self):
        calls = []
        def get(url):
            calls.append(url)
            if len(calls) == 1:
                return {"bids": [], "asks": []}
            return {"bids": [["1.00", "1000"]], "asks": [["1.01", "1000"]]}
        q = fetch_quote("gate", "XRP", get=get, clock=lambda: 1794910000000)
        self.assertEqual(len(calls), 2)
        self.assertEqual(q.venue, "gate")
        self.assertEqual(q.bid_qty, 1000)
        self.assertEqual(q.source, calls[-1])

    def test_no_fabricated_quote_when_both_attempts_fail(self):
        calls = []
        def get(url):
            calls.append(url)
            raise FeedError("HTTP_503")
        with self.assertRaises(FeedError):
            fetch_quote("okx", "LINK", get=get)
        self.assertEqual(len(calls), 2)

    def test_binance_fallback_provenance(self):
        calls = []
        def get(url):
            calls.append(url)
            if "data-api.binance.vision" in url:
                raise FeedError("HTTP_403")
            return {"bidPrice": "100", "askPrice": "101",
                    "bidQty": "20", "askQty": "20"}
        q = fetch_quote("binance", "BTC", get=get, clock=lambda: 1794910000000)
        self.assertIn("api.binance.com", q.source)
        self.assertEqual(q.source, calls[-1])


if __name__ == "__main__":
    unittest.main()
