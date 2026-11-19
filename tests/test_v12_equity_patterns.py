"""V12 no-lookahead, independent market evidence, control cohort and hash integrity."""
import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from radar.ledger import read_verify
from research_v4 import v12_equity_patterns as p
from research_v4.pattern_learner import append_sealed
from research_v4.v12_equity_notify import message

NOW = datetime(2026, 5, 1, 9, tzinfo=timezone.utc)


def prices(n=120, symbol="TEST", market="BIST"):
    first = date(2026, 1, 1)
    data = []
    for i in range(n):
        close = 100 + 0.1 * i
        data.append({
            "date": first + timedelta(days=i), "open": close - 0.1,
            "high": close + 0.2, "low": close - 0.3, "close": close,
            "volume": 1000.0,
            "pit": False, "actions": False,
        })
    return {(market, symbol): data}


def cohort():
    rows = []
    for d in range(4):
        at = (NOW + timedelta(days=d)).isoformat()
        for i in range(5):
            rows.append({
                "observed_utc": at, "symbol": "CASE" + str(i),
                "venue": "BIST",
                "future": {"label": "UPSIDE_EXTREME"},
                "features": {"stratum": "LOW:CALM", "motifs": {
                    name: name == "volume_surge" for name in p.SINGLE_RULES
                }},
            })
        for i in range(30):
            rows.append({
                "observed_utc": at, "symbol": "CONTROL" + str(i),
                "venue": "BIST",
                "future": {"label": "NO_EXTREME_MOVE"},
                "features": {"stratum": "LOW:CALM", "motifs": {
                    name: False for name in p.SINGLE_RULES
                }},
            })
    return rows


class V12Equity(unittest.TestCase):
    def test_closed_bar_only_and_market_isolation(self):
        original = prices()
        rows = p.latest_observations(original, "BIST", NOW, "sha", "1", "v1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["signal_session"], "2026-04-30")
        self.assertFalse(rows[0]["trade_authorized"])
        self.assertFalse(rows[0]["historical_pit_verified"])
        future = prices(131)
        future[("BIST", "TEST")][-1]["close"] *= 4
        extended = p.latest_observations(future, "BIST", NOW, "sha", "1", "v1")
        self.assertEqual(rows[0]["motifs"], extended[0]["motifs"])
        self.assertEqual(p.latest_observations(future, "US", NOW, "sha", "1", "v1"), [])

    def test_separate_future_sessions_and_four_horizons(self):
        s = p.latest_observations(prices(), "BIST", NOW, "sha", "1", "v1")[0]
        self.assertIsNone(p.evaluate_horizon(s, prices()[("BIST", "TEST")], 1))
        updated = prices(133)[("BIST", "TEST")]
        self.assertEqual(
            [p.evaluate_horizon(s, updated, h)["horizon_sessions"]
             for h in p.HORIZONS], list(p.HORIZONS))
        self.assertEqual(p.evaluate_horizon(s, updated, 1)["entry_session"], "2026-05-02")
        self.assertIsNone(p.evaluate_horizon(s, updated, 1)["label"])
        self.assertEqual(p.evaluate_horizon(s, updated, 5)["label"], "NO_EXTREME_MOVE")
        self.assertFalse(p.evaluate_horizon(s, updated, 10)["trade_authorized"])

    def test_forward_state_append_only_and_replay_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            first = p.execute(prices(), "BIST", NOW, "sha1", "1", state, "v1")
            self.assertEqual(first["new_asof_observations"], 1)
            replay = p.execute(prices(), "BIST", NOW, "sha1", "1", state, "v1")
            self.assertEqual(replay["new_asof_observations"], 0)
            self.assertEqual(len(read_verify(state / "BIST" / "observations.jsonl")), 1)
            next_run = p.execute(
                prices(133), "BIST", NOW + timedelta(days=13),
                "sha2", "2", state, "v1")
            self.assertGreaterEqual(next_run["new_forward_outcomes"], 4)
            outcomes = read_verify(state / "BIST" / "outcomes.jsonl")
            first_id = read_verify(state / "BIST" / "observations.jsonl")[0]["id"]
            self.assertEqual(
                {x["horizon_sessions"] for x in outcomes
                 if x["signal_id"] == first_id}, set(p.HORIZONS))
            self.assertEqual(next_run["matured_primary_cohort"], 1)

    def test_corrupted_source_sha_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            csv = Path(d) / "prices.csv"
            csv.write_text("sample", encoding="utf8")
            quality = Path(d) / "report.json"
            quality.write_text(json.dumps({
                "schema": "EAR.non_pit_quality_screen.v1",
                "screened_csv_sha256": hashlib.sha256(b"sample").hexdigest(),
                "trade_authorized": False, "paper_approved": False,
                "source_universe": "CURRENT_SURVIVORS_NOT_PIT",
            }))
            self.assertEqual(p.read_quality(csv, quality)[0],
                             hashlib.sha256(b"sample").hexdigest())
            csv.write_text("tampered", encoding="utf8")
            with self.assertRaises(ValueError):
                p.read_quality(csv, quality)

    def test_fisher_fdr_across_both_directions(self):
        result = p.stats(cohort())
        self.assertEqual(len(result), 2 * len(p.RULES))
        significant = next(x for x in result
                           if x["rule"] == "volume_surge"
                           and x["direction"] == "UPSIDE_EXTREME")
        self.assertTrue(significant["passes_fixed_gates"])
        self.assertLess(significant["bh_fdr_q"], 0.05)
        negative = next(x for x in result
                        if x["rule"] == "volume_surge"
                        and x["direction"] == "DOWNSIDE_EXTREME")
        self.assertFalse(negative["passes_fixed_gates"])

    def test_no_active_trial_replaced_after_method_drift(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p.execute(prices(), "BIST", NOW, "sha1", "1", root, "old")
            lock = {
                "kind": "freeze", "id": "old-trial",
                "direction": "UPSIDE_EXTREME", "rule": "volume_surge",
                "created_utc": NOW.isoformat(),
                "trial_start_utc": (NOW + timedelta(days=1)).isoformat(),
                "trial_end_utc": (NOW + timedelta(days=61)).isoformat(),
                "methodology_sha256": "old",
            }
            append_sealed(root / "BIST" / "frozen.jsonl", [lock],
                          int(NOW.timestamp() * 1000) + 1000)
            report = p.execute(
                prices(), "BIST", NOW + timedelta(days=3),
                "sha2", "2", root, "new")
            self.assertEqual(report["new_frozen_patterns"], 0)
            self.assertEqual(report["active_trials"][0]["status"], "PAUSED_CODE_DRIFT")

    def test_tampering_in_persistent_observations_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p.execute(prices(), "BIST", NOW, "sha", "1", root, "v1")
            path = root / "BIST" / "observations.jsonl"
            path.write_text(path.read_text().replace("TEST", "BAD"), encoding="utf8")
            with self.assertRaises(ValueError):
                p.execute(prices(), "BIST", NOW + timedelta(days=1),
                          "sha2", "2", root, "v1")

    def test_only_new_research_milestones_notify(self):
        base = {"schema": "EAR.v12_equity_discovery.v1", "notices": []}
        self.assertIsNone(message([base, base]))
        self.assertIn("BIST", message([{
            **base, "notices": [{
                "kind": "NEW_FROZEN_PATTERN", "market": "BIST",
                "direction": "UPSIDE_EXTREME", "rule": "volume_surge",
            }],
        }]))


if __name__ == "__main__":
    unittest.main()
