import unittest

import numpy as np
import pandas as pd

from research_v4.onchain_mvrv import analyze


class MVRVResearchTests(unittest.TestCase):
    def test_real_mvrv_is_chronological_and_cannot_promote(self):
        n = 1200
        index = pd.date_range("2018-01-01", periods=n, freq="D")
        wave = 1.1 + .45*np.sin(np.arange(n)/70)
        realized = np.linspace(50e9, 180e9, n)
        price = 5000*np.exp(np.linspace(0, 2.0, n))*(1+.08*np.sin(np.arange(n)/17))
        frame = pd.DataFrame({"PriceUSD":price,
                              "CapRealUSD":realized,
                              "CapMrktCurUSD":realized*wave}, index=index)
        report = analyze("btc", frame)
        self.assertEqual(report["measurement"], "REAL_MVRV_MARKET_CAP_DIVIDED_BY_REALIZED_CAP")
        self.assertFalse(report["proxy"])
        self.assertLess(report["split"]["discovery_end"], report["split"]["validation_start"])
        self.assertFalse(report["paper_eligible"])
        self.assertFalse(report["trade_authorized"])
        self.assertEqual(len(report["results"]), 4)


if __name__ == "__main__":
    unittest.main()
