"""V13 costed profitability screen and strictly later verification contracts."""
import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.ledger import read_verify
from research_v4.pattern_learner import append_sealed
from research_v4 import v13_profitability as p

BASE = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)


def case(day, symbol, rule=True, pnl=3.0, horizon=3):
    now = BASE + timedelta(days=day)
    entered = now + timedelta(days=1)
    exited = entered + timedelta(days=horizon)
    return {
        "id": p.stable_id("BIST", symbol, now.isoformat()),
        "market": "BIST", "symbol": symbol, "observed_utc": now.isoformat(),
        "stratum": "LOW:CALM",
        "motifs": {"volume_surge": rule, "quiet_price": rule},
        "entry_session": entered.date().isoformat(),
        "exit_session": exited.date().isoformat(),
        "horizon": horizon, "net_pct": pnl,
        "stressed_net_pct": pnl - p.STRESS_EXTRA_COST_PCT,
    }


def sample(days=42, pnl=3.0):
    rows = []
    for k in range(days):
        day = k * 4
        rows.append(case(day, "C" + str(k % 12), pnl=(-1.5 if k % 11 == 0 else pnl)))
        for i in range(2):
            rows.append(case(day, f"N{i}", rule=False, pnl=-0.6))
    return rows


def source_signal(stamp, symbol="ABC", version="v1"):
    return {
        "schema": "EAR.v12_equity_observation.v1", "kind": "first_seen",
        "id": p.stable_id("BIST", symbol, stamp.isoformat()),
        "market": "BIST", "symbol": symbol,
        "observed_utc": stamp.isoformat(), "stratum": "LOW:CALM",
        "motifs": {"volume_surge": True},
        "entry_strictly_after_utc_date": stamp.date().isoformat(),
        "methodology_sha256": version,
        "round_trip_cost_proxy_pct": 2.0,
        "paper_approved": False, "trade_authorized": False,
    }


def source_outcome(sig, horizon=1, pct=8.0):
    entry = datetime.fromisoformat(sig["observed_utc"]) + timedelta(days=1)
    end = entry + timedelta(days=horizon-1)
    return {
        "schema": "EAR.v12_equity_outcome.v1", "kind": "outcome",
        "id": p.stable_id(sig["id"], horizon), "signal_id": sig["id"],
        "market": sig["market"], "symbol": sig["symbol"],
        "horizon_sessions": horizon,
        "status": "OBSERVED_FUTURE_CLOSED_SESSIONS",
        "methodology_sha256": sig["methodology_sha256"],
        "entry_session": entry.date().isoformat(),
        "last_session": end.date().isoformat(),
        "entry_open_price_unverified_fill": 100.,
        "exit_close_price_unverified_fill": 100 + pct,
        "gross_return_pct": pct,
        "long_costed_diagnostic_pct": pct - 2.0,
        "trade_authorized": False, "paper_approved": False,
    }


class V13Contracts(unittest.TestCase):
    def test_many_strategy_variants_and_costed_net_positive(self):
        rows = sample()
        metrics = p.summarize(rows, "volume_surge", 3)
        self.assertEqual(metrics["hypothetical_closed_trades"], 42)
        self.assertEqual(metrics["matched_control_events"], 84)
        self.assertTrue(metrics["passes_fixed_research_gates"])
        self.assertGreater(metrics["stressed_net_mean_pct"], 0)
        self.assertGreater(metrics["excess_vs_matched_control_pct"], 0)
        self.assertGreater(metrics["closed_profit_factor"], 1.25)
        self.assertGreater(metrics["stressed_ten_day_block_lower_bound_pct"], 0)
        self.assertEqual(len(p.RULES) * len(p.HORIZONS), 64)

    def test_no_profit_if_costs_exceed_edge_or_no_matched_controls(self):
        rows = sample(pnl=.15)
        self.assertFalse(p.summarize(rows, "volume_surge", 3)["passes_fixed_research_gates"])
        rows = [x for x in sample() if x["motifs"]["volume_surge"]]
        self.assertEqual(p.summarize(rows, "volume_surge", 3)["matched_control_events"], 0)
        self.assertFalse(p.summarize(rows, "volume_surge", 3)["passes_fixed_research_gates"])

    def test_no_outcome_lookahead_and_cost_fraud(self):
        now = BASE + timedelta(days=10)
        s = source_signal(BASE)
        o = source_outcome(s)
        records = {"observations": [s], "outcomes": [o]}
        with self.assertRaises(ValueError):
            p.mature_rows(records, "BIST", 1, BASE, "v1")
        self.assertEqual(len(p.mature_rows(records, "BIST", 1, now, "v1")), 1)
        altered = {**records, "outcomes": [{**o, "long_costed_diagnostic_pct": 999}]}
        with self.assertRaises(ValueError):
            p.mature_rows(altered, "BIST", 1, now, "v1")
        s2 = {**s, "methodology_sha256": "new"}
        self.assertEqual(p.mature_rows(
            {"observations": [s2], "outcomes": [o]},
            "BIST", 1, now, "v1"), [])

    def test_overlapping_same_symbol_or_portfolio_slots_rejected(self):
        rows = [case(1, "A"), case(2, "A"), case(3, "A")]
        fills, decline = p.chronological_fills(rows)
        self.assertEqual(len(fills), 1)
        self.assertEqual(decline["same_symbol_overlap"], 2)
        rows = [case(1, "S" + str(i)) for i in range(11)]
        fills, decline = p.chronological_fills(rows)
        self.assertEqual(len(fills), p.MAX_SLOTS)
        self.assertEqual(decline["portfolio_slots"], 11 - p.MAX_SLOTS)

    def test_censored_unknown_future_outcome_is_not_a_winner(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "BIST"
            root.mkdir(parents=True)
            s = source_signal(BASE)
            censored = {
                "kind": "outcome", "id": p.stable_id(s["id"], 1),
                "signal_id": s["id"], "horizon_sessions": 1,
                "market": "BIST", "symbol": "ABC",
                "status": "SUSPECTED_CORPORATE_ACTION_OR_PRICE_GAP",
                "label": None,
            }
            append_sealed(root / "observations.jsonl", [s], int(BASE.timestamp()*1000))
            append_sealed(root / "outcomes.jsonl", [censored],
                          int((BASE+timedelta(days=3)).timestamp()*1000))
            read = p.assert_source(Path(d), "BIST", BASE+timedelta(days=5))
            self.assertEqual(len(read["outcomes"]), 1)
            self.assertEqual(p.mature_rows(
                read,"BIST",1,BASE+timedelta(days=5),"v1"), [])

    def test_corrupt_prior_v12_sha_chain_refuses_all_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"BIST"
            root.mkdir()
            s=source_signal(BASE)
            append_sealed(root/"observations.jsonl",[s],int(BASE.timestamp()*1000))
            path=root/"observations.jsonl"
            path.write_text(path.read_text().replace("ABC","FAKE"))
            with self.assertRaises(ValueError):
                p.assert_source(Path(d),"BIST",BASE+timedelta(days=5))

    def test_zero_first_seen_means_no_promised_profitable_strategy(self):
        with tempfile.TemporaryDirectory() as d:
            out=p.run(Path(d)/"missing",Path(d)/"profit",
                      BASE,v13_version="v13",source_version="v12")
            self.assertFalse(out["profitable_strategy_proven"])
            self.assertFalse(out["paper_approved"])
            for market in p.MARKETS:
                m=out["markets"][market]
                self.assertEqual(m["exploratory_positive_candidates"],[])
                self.assertEqual(m["new_frozen"],[])
                self.assertEqual(m["completed_forward_decisions_total"],0)
            replay=p.run(Path(d)/"missing",Path(d)/"profit",
                         BASE,v13_version="v13",source_version="v12")
            self.assertEqual(replay["markets"]["BIST"]["new_frozen"],[])

    def test_changed_code_does_not_approve_incompatible_existing_trial(self):
        with tempfile.TemporaryDirectory() as d:
            st=Path(d)/"alpha"
            p.run(Path(d)/"missing",st,BASE,
                  v13_version="old",source_version="v12")
            lock={
                "kind":"freeze","id":"OLD","rule":"volume_surge",
                "horizon_sessions":1,"market":"BIST",
                "created_utc":BASE.isoformat(),
                "trial_start_utc":BASE.isoformat(),
                "trial_end_utc":(BASE+timedelta(days=1)).isoformat(),
                "methodology_sha256":"old",
                "v12_methodology_sha256":"v12",
            }
            append_sealed(st/"BIST"/"frozen.jsonl",
                          [lock],int(BASE.timestamp()*1000))
            result=p.run(Path(d)/"missing",st,BASE+timedelta(days=120),
                         v13_version="new",source_version="v12")
            m=result["markets"]["BIST"]
            self.assertEqual(m["new_frozen"],[])
            self.assertEqual(m["new_forward_decisions"],[])
            self.assertEqual(m["active_trials"][0]["status"],"PAUSED_VERSION_DRIFT")


if __name__=="__main__":
    unittest.main()
