"""Offline regression tests: no look-ahead, no missing-value optimism."""
import unittest
from research_v4.v16_indicator_controls import (
    RULES, candidate_flags, asof_features, matched_stats,
)


class V16IndicatorControls(unittest.TestCase):
    def test_funding_flip_only_when_genuinely_observed(self):
        old = {"p": 100, "funding_rate_pct": -0.01}
        new = {"p": 100.2, "funding_rate_pct": 0.01}
        self.assertIs(candidate_flags(new, old)["funding_sign_flip"], True)
        del new["funding_rate_pct"]
        self.assertIsNone(candidate_flags(new, old)["funding_sign_flip"])

    def test_spread_cannot_substitute_missing_orderbook(self):
        old = {"p": 100, "spread_bps": 10, "q": 1000}
        new = {"p": 100.3, "spread_bps": 5, "q": 1500}
        self.assertIs(candidate_flags(new, old)["spread_compression_with_activity"], True)
        new["p"] = 105
        self.assertIs(candidate_flags(new, old)["spread_compression_with_activity"], False)
        del new["spread_bps"]
        self.assertIsNone(candidate_flags(new, old)["spread_compression_with_activity"])

    def test_basis_measures_mark_not_spot(self):
        old = {"p": 100, "mark_basis_bps": -30}
        new = {"p": 100.3, "mark_basis_bps": -12}
        self.assertIs(candidate_flags(new, old)["mark_basis_normalization"], True)

    def test_no_future_peeking_and_no_cross_venue_merge(self):
        t = 1800000000000
        history = [
            (t - 60 * 60000, {"bitget": {"p": 100, "spread_bps": 10, "q": 1000}}),
            (t, {"bitget": {"p": 100.2, "spread_bps": 5, "q": 1500}}),
            (t + 60 * 60000, {"bitget": {"p": 101, "funding_rate_pct": -0.01}}),
        ]
        z = asof_features(history, t, "bitget")
        self.assertIs(z["spread_compression_with_activity"], True)
        self.assertIsNone(z["funding_sign_flip"])
        self.assertTrue(all(x is None for x in asof_features(history, t, "okx").values()))

    def test_stale_prior_is_missing_not_false(self):
        t = 1800000000000
        history = [
            (t - 4 * 3600000, {"bitget": {"p": 100, "spread_bps": 10, "q": 1000}}),
            (t, {"bitget": {"p": 100.2, "spread_bps": 5, "q": 1500}}),
        ]
        self.assertEqual(asof_features(history, t, "bitget"), {name: None for name in RULES})

    def test_case_control_requires_exact_matching_stratum_and_time(self):
        def row(hour, stratum, label, value):
            return {"observed_utc": hour, "features": {"stratum": stratum},
                    "future": {"label": label}, "v16": {"funding_sign_flip": value}}
        x = [
            row("2026-11-20T10:00:00+00:00", "L:CALM", "UPSIDE_EXTREME", True),
            row("2026-11-20T10:00:00+00:00", "L:CALM", "NO_EXTREME_MOVE", False),
            row("2026-11-20T11:00:00+00:00", "L:CALM", "NO_EXTREME_MOVE", False),
            row("2026-11-20T10:00:00+00:00", "H:CALM", "NO_EXTREME_MOVE", True),
        ]
        r = matched_stats(x, "UPSIDE_EXTREME", "funding_sign_flip")
        self.assertEqual(r["matched_cases_available"], 1)
        self.assertEqual(r["matched_nonmover_controls_available"], 1)
        self.assertEqual(r["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertIs(r["validated_alpha"], False)


if __name__ == "__main__":
    unittest.main()
