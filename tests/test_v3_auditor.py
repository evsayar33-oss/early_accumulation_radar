"""Fail-closed auditor regression tests; no network and no historic data fabrications."""
import json
import tempfile
import unittest
from pathlib import Path
from radar.ledger import digest, canonical
from research_v3.auditor import examine_historical, examine_paper
from research_v3.model import MODEL_VERSION, UNIVERSE


def fixture(profit=5, tail=2):
    matrix = []
    for symbol in UNIVERSE:
        for cohort in ("ALL", "EARLY", "MIDDLE", "TAIL"):
            for scenario in ("base", "stress"):
                for model in ("acc", "breakout"):
                    net = (tail if cohort == "TAIL" else profit) if model == "acc" else -1
                    if scenario == "base":
                        net += 2
                    matrix.append({"symbol": symbol, "cohort": cohort, "scenario": scenario,
                                   "model": model, "net_return_pct": net, "trades": 60,
                                   "win_rate": .55, "profit_factor": 1.5,
                                   "max_drawdown_pct": 8, "buyhold_return_pct": 1})
    return {"manifest": {"model": MODEL_VERSION, "universe": list(UNIVERSE),
                         "symbols_testable": list(UNIVERSE), "data_errors": {},
                         "source_files": {s: [{"official_checksum_verified": True}] for s in UNIVERSE}},
            "matrix": matrix}


class HistoricalAuditorTests(unittest.TestCase):
    def test_positive_screen_is_not_live_approval(self):
        result = examine_historical(fixture())
        self.assertEqual(result["decision"], "HISTORICAL_SCREEN_PASS_NOT_ALPHA_APPROVAL")
        self.assertEqual(result["counts"]["stress_positive"], 8)

    def test_cost_stress_failure(self):
        result = examine_historical(fixture(profit=-2, tail=-1))
        self.assertEqual(result["decision"], "HISTORICAL_SCREEN_FAIL")

    def test_incomplete_historical_matrix_blocked(self):
        doc = fixture()
        doc["matrix"].pop()
        self.assertEqual(examine_historical(doc)["decision"], "INSUFFICIENT_EVIDENCE")

    def test_point_in_time_not_claimed(self):
        self.assertIn("NOT_POINT_IN_TIME_UNIVERSE", examine_historical(fixture())["limitations"])

    def test_missing_paper(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(examine_paper(Path(d)/"none.jsonl")["status"], "NO_PROSPECTIVE_PAPER_EVIDENCE")

    def test_one_paper_tick_not_approved(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"events.jsonl"
            event = {"scan_utc_ms": 1794850000000, "status": "MARKED", "nav": 10000.,
                     "transactions": [], "prev_sha256": "GENESIS"}
            event["sha256"] = digest(event)
            path.write_text(canonical(event)+"\n", encoding="utf8")
            state = Path(d)/"state.json"
            state.write_text(json.dumps({"last_event_sha256": event["sha256"],
                                         "last_observed_ms": event["scan_utc_ms"]}), encoding="utf8")
            result = examine_paper(path, state)
            self.assertEqual(result["status"], "INSUFFICIENT_FORWARD_EVIDENCE")
            self.assertEqual(result["checkpoint_days"]["30"], "PENDING")

    def test_corrupt_paper_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"events.jsonl"
            path.write_text('{"scan_utc_ms":1794850000000,"sha256":"tampered","prev_sha256":"GENESIS"}\n')
            with self.assertRaises(ValueError):
                examine_paper(path)


if __name__ == "__main__":
    unittest.main()
