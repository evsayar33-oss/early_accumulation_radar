"""V13 crypto pre-entry evidence, future-only mark and cost profitability contracts."""
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

from radar.ledger import canonical,digest,read_verify
from research_v4 import v13_crypto_profit as c
from research_v4.perp_watch import pack
from research_v4.pattern_learner import append_sealed

START=datetime(2026,11,19,0,tzinfo=timezone.utc)
T=int(START.timestamp()*1000)


def quote(price=100,spread=10,turn=2000000):
    return {"p":price,"q":turn,"d":0,"spread_bps":spread,"q_proxy":False}


def frame(price=100,spread=10):
    return {"COINUSDT":{"okx":quote(price,spread),
                        "bitget":quote(price,spread)}}


def tape(offsets=(0,30,60,90,120,150,180,210,240,270,300),prices=None):
    prices=prices or {}
    return [(T+i*60000,frame(prices.get(i,100)),f"sha-{i}") for i in offsets]


def observation():
    return {
        "schema":"EAR.v13_crypto_asof.v1","kind":"asof",
        "id":"coin1","market":c.MARKET,"symbol":"COINUSDT","venue":"okx",
        "bucket":T//(4*3600000),"observed_utc":c.iso_ms(T),
        "entry_after_ms":T,
        "source_scan_sha256":"source","methodology_sha256":"v1",
        "stratum":"M:CALM","motifs":{"activity_up_20pct":True,
                                     "quiet_price_2pct":False},
        "paper_approved":False,"trade_authorized":False,
    }


def candidate(d,i,enabled=True,pnl=1.7):
    t=START+timedelta(days=d)
    return {
        "id":f"{d}-{i}","symbol":f"COIN{i%14}USDT","venue":"okx",
        "observed_utc":t.isoformat(),
        "stratum":"M:CALM",
        "motifs":{"activity_up_20pct":enabled},
        "entry_utc":(t+timedelta(hours=1)).isoformat(),
        "exit_utc":(t+timedelta(hours=2)).isoformat(),
        "net_pct":pnl,"stressed_pct":pnl-c.EXTRA_STRESS_PCT,
    }


def cohort(pnl=2.0):
    rows=[]
    for d in range(12):
        for i in range(4):
            rows.append(candidate(d,d*4+i,True,-1.5 if (d*4+i)%13==0 else pnl))
        for i in range(10):
            rows.append(candidate(d,100+i,False,-.8))
    return rows


def make_sha_v8(path,stamps):
    prev="GENESIS"
    with Path(path).open("w",encoding="utf8") as f:
        for k,stamp in enumerate(stamps):
            row={
                "schema":"EAR.perp_forward.v1","scan_utc_ms":stamp,
                "market_type":"USDT_LINEAR_PERPETUAL_ONLY",
                "scope":"FUTURES_RESEARCH_ONLY_NO_ORDERS",
                "packed_assets":pack(frame()),"source_unavailable":{},
                "venue_counts":{"okx":1,"bitget":1},"events":[],
                "prev_sha256":prev,"trade_authorized":False,
                "paper_approved":False,
            }
            row["sha256"]=digest(row)
            f.write(canonical(row)+"\n")
            prev=row["sha256"]


class CryptoContracts(unittest.TestCase):
    def test_multiple_crypto_rule_duration_direction_strategies(self):
        self.assertGreater(len(c.RULES),20)
        self.assertEqual(len(c.RULES)*len(c.DIRECTIONS)*len(c.HORIZONS_MIN),92)
        self.assertEqual(set(c.HORIZONS_MIN),{60,240})

    def test_first_seen_no_backfilled_training(self):
        scan=tape((0,))
        z={"price_return_2h_pct":0,"stratum":"M:CALM",
           "turnover_proxy":False,
           "motifs":{"activity_up_20pct":True}}
        with patch.object(c,"features",return_value=z):
            obs,miss=c.asof_signals(scan,T+5*60000,set(),"v1")
            self.assertEqual(len(obs),1)
            self.assertEqual(obs[0]["source_scan_sha256"],"sha-0")
            self.assertEqual(obs[0]["observed_utc"],c.iso_ms(T))
            replay,_=c.asof_signals(scan,T+5*60000,{obs[0]["id"]},"v1")
            self.assertEqual(replay,[])
            self.assertFalse(obs[0]["trade_authorized"])
        with self.assertRaises(ValueError):
            c.asof_signals(scan,T+91*60000,set(),"v1")

    def test_future_prices_not_event_extrema_and_fees_nonzero(self):
        s=observation()
        snap=tape(prices={30:100,90:104,270:109})
        early=c.future_mark(s,snap,60,T+300*60000)
        self.assertEqual(early["entry_snapshot_utc"],c.iso_ms(T+30*60000))
        self.assertEqual(early["exit_snapshot_utc"],c.iso_ms(T+90*60000))
        self.assertAlmostEqual(early["gross_long_pct"],4.)
        self.assertLess(early["modeled_net_long_pct"],4.)
        self.assertLess(early["modeled_net_short_pct"],0)
        self.assertTrue(early["actual_funding_not_collected"])
        late=c.future_mark(s,snap,240,T+300*60000)
        self.assertAlmostEqual(late["gross_long_pct"],9.)
        self.assertFalse(late["trade_authorized"])

    def test_stale_and_undocumented_quote_is_censored_not_flat(self):
        s=observation()
        self.assertIsNone(c.future_mark(s,tape((0,)),60,T+60000))
        result=c.future_mark(s,tape((0,)),60,T+49*3600000)
        self.assertEqual(result["status"],"CENSORED_NO_VERIFIABLE_NEXT_QUOTE")
        invalid=tape((0,30,90))
        invalid[1][1]["COINUSDT"]["okx"].pop("spread_bps")
        invalid[2][1]["COINUSDT"]["okx"].pop("spread_bps")
        self.assertEqual(c.future_mark(s,invalid,60,T+49*3600000)["status"],
                         "CENSORED_NO_VERIFIABLE_NEXT_QUOTE")

    def test_profitability_requires_costs_stress_and_matched_controls(self):
        yes=c.candidate_summary(cohort(),"activity_up_20pct","LONG",60)
        self.assertTrue(yes["fixed_costed_research_gates_pass"])
        self.assertGreater(yes["hypothetical_mark_trades"],35)
        self.assertGreater(yes["controls"],100)
        self.assertGreater(yes["multiplicity_screen_lower_pct"],0)
        nope=c.candidate_summary(cohort(pnl=.03),"activity_up_20pct","LONG",60)
        self.assertFalse(nope["fixed_costed_research_gates_pass"])
        no_controls=[r for r in cohort() if r["motifs"]["activity_up_20pct"]]
        self.assertFalse(c.candidate_summary(
            no_controls,"activity_up_20pct","LONG",60)["fixed_costed_research_gates_pass"])

    def test_future_holdout_filters_training_without_retro_results(self):
        sample=cohort()
        start=c.ms(sample[0]["observed_utc"])+6*86400000
        train=c.candidate_summary(sample,"activity_up_20pct","LONG",60,before=start)
        hold=c.candidate_summary(sample,"activity_up_20pct","LONG",60,since=start)
        self.assertEqual(train["hypothetical_mark_trades"]+
                         hold["hypothetical_mark_trades"],48)

    def test_sha_v8_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"v8.jsonl"
            make_sha_v8(p,[T,T+30*60000])
            self.assertEqual(len(c.source_rows(p)),2)
            p.write_text(p.read_text().replace("COINUSDT","BADUSDT"))
            # The compressed payload does not contain plain symbol; corrupt
            # a signed field instead, preserving well-formed JSON.
            p.write_text(p.read_text().replace('"scope":"FUTURES_RESEARCH_ONLY_NO_ORDERS"',
                                                '"scope":"BAD"',1))
            with self.assertRaises(ValueError):
                c.source_rows(p)

    def test_existing_evidence_hash_tamper_not_hidden(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"observations.jsonl"
            append_sealed(p,[observation()],T)
            self.assertEqual(len(read_verify(p)),1)
            p.write_text(p.read_text().replace("COINUSDT","BADUSDT"))
            with self.assertRaises(ValueError):read_verify(p)


if __name__=="__main__":unittest.main()
