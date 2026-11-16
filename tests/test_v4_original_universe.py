import unittest
from research_v4.original_universe import scan, classify_pair, PROFILES, PAIRS

NOW=1794850000000
PAIR={"chainId":"solana","dexId":"raydium","pairAddress":"pair1",
      "baseToken":{"address":"token1","symbol":"NEW"},"quoteToken":{"address":"USDC","symbol":"USDC"},
      "liquidity":{"usd":50000},"volume":{"h24":40000},
      "fdv":450000,"marketCap":400000,"pairCreatedAt":NOW-48*3600000}

class OriginalUniverse(unittest.TestCase):
    def test_watch_never_trading_approval(self):
        r=classify_pair(PAIR,NOW,"solana","token1")
        self.assertTrue(r["screen_watch"])
        self.assertFalse(r["trade_authorized"])
        self.assertFalse(r["float_verified"])
        self.assertFalse(r["holder_concentration_verified"])
        self.assertFalse(r["fundamentals_verified"])

    def test_wrong_chain_or_token_blocked(self):
        self.assertIsNone(classify_pair(PAIR,NOW,"ethereum","token1"))
        self.assertIsNone(classify_pair(PAIR,NOW,"solana","not_token"))

    def test_missing_liquidity_rejected_not_invented(self):
        p={**PAIR,"liquidity":{}}
        r=classify_pair(p,NOW,"solana","token1")
        self.assertIsNone(r["liquidity_usd"])
        self.assertFalse(r["screen_watch"])

    def test_end_to_end_discovery_and_untouched_equities(self):
        def get(url):
            if url==PROFILES:
                return [{"chainId":"solana","tokenAddress":"token1"},{"chainId":"solana","tokenAddress":"token1"}]
            if url==PAIRS+"/solana/token1":
                return [PAIR]
            raise AssertionError(url)
        r=scan(fetch=get,now_ms=NOW)
        self.assertEqual(r["discovered_tokens"],1)
        self.assertEqual(r["research_watch_count"],1)
        self.assertEqual(r["coverage"]["us_equities"],"NOT_CONNECTED")
        self.assertEqual(r["coverage"]["bist_equities"],"NOT_CONNECTED")
        self.assertFalse(r["trading_authorized"])

    def test_source_outage_fails_closed(self):
        def fail(url):raise RuntimeError("HTTP 429")
        r=scan(fetch=fail,now_ms=NOW)
        self.assertEqual(r["status"],"SOURCE_OUTAGE_NO_SIGNAL")
        self.assertEqual(r["observations"],[])
        self.assertFalse(r["trading_authorized"])

if __name__=="__main__":unittest.main()
