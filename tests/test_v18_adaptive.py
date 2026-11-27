import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from research_v4 import v18_sources as s
from research_v4 import v18_adaptive as a
from research_v4.v18_notify import message

EXT=all(importlib.util.find_spec(n) for n in ("pandas","numpy","eaverse","research","scipy"))
T=1800000000000//s.BAR_MS*s.BAR_MS

def bars(n,start=T):
    return [{"start":start+i*s.BAR_MS,"end":start+(i+1)*s.BAR_MS,
             "open":100.0+i*.01,"high":101.0+i*.01,"low":99.0+i*.01,
             "close":100.25+i*.01,"volume":1000.0+i} for i in range(n)]

class Sources(unittest.TestCase):
    def test_completed_only_validated(self):
        data={"code":"0","data":[[str(T),"100","102","99","101","2","4","400","1"],
                 [str(T+s.BAR_MS),"101","105","100","102","3","5","500","0"]]}
        r=s.parse_bars(data,"okx",T+2*s.BAR_MS)
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]["volume"],4)
        data["data"][0][3]="110"
        with self.assertRaisesRegex(ValueError,"INVALID_CANDLE"):
            s.parse_bars(data,"okx",T+2*s.BAR_MS)
    def test_underlying_identity_is_not_symbol_name(self):
        assets={x:{"okx":{"q":200000},"bitget":{"q":200000}} for x in ("AAAUSDT","AAPLUSDT","MYSTERYUSDT","CLASHUSDT")}
        info={"okx":{"data":[{"instId":"AAA-USDT-SWAP","instCategory":"1"},{"instId":"AAPL-USDT-SWAP","instCategory":"3"},{"instId":"CLASH-USDT-SWAP","instCategory":"1"}]},
              "bitget":{"data":[{"symbol":"AAAUSDT","isRwa":"NO"},{"symbol":"AAPLUSDT","isRwa":"YES"},{"symbol":"CLASHUSDT","isRwa":"YES"}]}}
        result, excluded=s.classified_assets(assets,info)
        self.assertEqual(set(result),{"AAAUSDT"})
        self.assertEqual(set(excluded),{"AAPLUSDT","MYSTERYUSDT","CLASHUSDT"})
        self.assertTrue(a.qualified({"market":"BIST"}))
        self.assertFalse(a.qualified({"market":"CRYPTO"}))
        self.assertTrue(a.qualified({"market":"CRYPTO","cohort":s.COHORT}))
    def test_rotating_small_universe(self):
        assets={f"COIN{i}USDT":{"okx":{"q":200000}} for i in range(7)}
        assets["BTCUSDT"]={"okx":{"q":10000000}}
        first,c=s.select_assets(assets,0,3);second,c=s.select_assets(assets,c,3)
        self.assertEqual(len(set(first+second)),6)
        self.assertNotIn("BTCUSDT",first+second)
    def test_native_outcome_not_dependent_on_snapshot_schedule(self):
        b=bars(32)
        result=a.outcome(b,"CRYPTO",T+5,now=b[-1]["end"])
        self.assertEqual(result["entry"],T+s.BAR_MS)
        self.assertEqual(len(result["bars"]),16)
        self.assertEqual(result["status"],"COMPLETE_MARK_ONLY")
        self.assertIsNone(a.outcome(b[:4],"CRYPTO",T+5,now=b[3]["end"]))
        g=b[:6]+b[7:]
        self.assertEqual(a.outcome(g,"CRYPTO",T+5)["status"],"CENSORED_GAP_OR_SCALE_CHANGE")
    def test_macro_only_known_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"macro.json"
            p.write_text(json.dumps({"seen_at":"2026-01-02T00:00:00+00:00",
                "assets":[{"symbol":"IBIT","error":"403","flow_asof":"2026-01-01","horizons":{"1H":{"net_usd_m":100}}}],
                "continuity":{"assets":{"IBIT":{"selected":{"status":"OBSERVED","stale":False,"symbol":"IBIT","provider":"test",
                  "flow_asof":"2026-01-01","horizons":{"1H":{"net_usd_m":-20}}}}}}}))
            ms=int(__import__("datetime").datetime.fromisoformat("2026-01-02T01:00:00+00:00").timestamp()*1000)
            self.assertEqual(s.macro_context(p,ms)["flags"],{"macro_IBIT_inflow":False})
            self.assertEqual(s.macro_context(p,ms-8*3600000)["status"],"STALE_OR_FUTURE")
    def test_archive_tampering_and_no_reset(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/"ledger"
            batch={"schema":a.VERSION,"observed_ms":T,"cursor":0,"observations":[],"settlements":[],"attempts":[],"locks":[],"decisions":[]}
            a.append_batch(state,[],batch)
            rows=a.read_state(state)
            a.append_batch(state,rows,{**batch,"observed_ms":T+1})
            self.assertEqual(len(a.read_state(state)),2)
            p=state/"ledger-000000.jsonl"
            p.write_text(p.read_text().replace('"prev_sha256":"GENESIS"','"prev_sha256":"BROKEN"'))
            with self.assertRaisesRegex(ValueError,"HASH_CHAIN"):
                a.read_state(state)
    def test_recovery_uses_same_venue_after_seen(self):
        from research_v4.v18_v8_recovery import native_range
        data={"code":"0","data":[[str(T+i*s.BAR_MS),"100","102","99","101","2","4","400","1"] for i in range(24)]}
        urls=[]
        def fetch(url):
            urls.append(url);return data
        r=native_range("TESTUSDT","okx",T+1,T+25*s.BAR_MS,fetch)
        self.assertEqual(len(r),16)
        self.assertEqual(r[0]["start"],T+s.BAR_MS)
        self.assertIn("history-candles",urls[0])
    def test_missing_flag_not_negative(self):
        r=a.rule("CRYPTO","UP",[("volume_high",False)])
        self.assertIsNone(a.predicate({},r))
        self.assertTrue(a.predicate({"volume_high":False},r))
    def test_telegram_silent(self):
        self.assertIsNone(message({"schema":a.VERSION,"new_decisions":[{"status":"FORWARD_FAILED_OR_INSUFFICIENT"}],"new_shadows":[]}))

@unittest.skipUnless(EXT,"Dedicated V18 workflow installs and pins real Eaverse/Superlab")
class Research(unittest.TestCase):
    def test_catalog_actual_multiframe_and_causal(self):
        specs=a.catalog("CRYPTO")
        self.assertEqual({v["frame"] for v in specs.values()},{"15m","1h","4h"})
        self.assertEqual(len(specs),144)
        b=bars(300)
        f1,e1=a.compute_flags(b[:200],"CRYPTO",specs)
        f2,e2=a.compute_flags(b,"CRYPTO",specs)
        self.assertFalse(e1);self.assertFalse(e2)
        for k in f1:self.assertEqual(f1[k],f2[k][:200],k)
    def test_progressive_parameters_retained_for_frozen_rules(self):
        base=a.catalog("CRYPTO");week=a.catalog("CRYPTO",100)
        extras=set(week)-set(base)
        self.assertTrue(extras)
        chosen=next(iter(extras))
        later=a.catalog("CRYPTO",120,week,{chosen})
        self.assertIn(chosen,later)
        self.assertNotEqual(set(week),set(later))
    def test_persistent_learning_no_repeated_data(self):
        row={"id":"1","market":"CRYPTO","features":{"volume_high":True},"outcome":{"bars_sha":"x","label":"UP"}}
        p=a.proposals("CRYPTO",{}, {},[row],"seed")
        self.assertEqual(len(p),4)
        memory={rid:{"rule":r,"dataset":data,"stats":{"rows":1,"reason":"INSUFFICIENT_EVIDENCE","matched_stress_excess":None}} for _,rid,r,data in p}
        self.assertEqual(a.proposals("CRYPTO",{},memory,[row],"seed"),[])
    def test_mixed_underlying_ledger_quarantine_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/"state"
            old_rule=a.rule("CRYPTO","UP",[("volume_high",True)])
            obs={"market":"CRYPTO","id":"old","kind":"HISTORICAL_DISCOVERY"}
            attempt={"rule":old_rule,"rule_id":a.rule_id(old_rule)}
            batch={"schema":a.VERSION,"observed_ms":T,"cursor":32,"observations":[obs],"settlements":[],"attempts":[attempt],"locks":[],"decisions":[]}
            saved=a.append_batch(state,[],batch)
            report=a.run(state,{},{},T+1,{}, {"status":"MISSING"}, {m:{} for m in a.MARKETS})
            self.assertEqual(report["quarantined_legacy_mixed_underlying"],{"observations":1,"rules":1,"locks":0})
            self.assertEqual(report["unique_rules"],0)
            self.assertEqual(report["total_actual_tests"],1)
            self.assertEqual(a.read_state(state)[0]["sha256"],saved["sha256"])
    def test_real_engine_state_survives_second_round(self):
        with tempfile.TemporaryDirectory() as d:
            key=("CRYPTO","TESTUSDT","okx")
            b=bars(300)
            t=b[-1]["end"]+100
            state=Path(d)/"state"
            panel={key:{"bars":b,"corroboration":"AGREEMENT","cohort":s.COHORT}}
            specs={m:a.catalog(m) for m in a.MARKETS}
            first=a.run(state,panel,{key:b},t,{},{"status":"MISSING"},specs)
            self.assertGreater(first["historical_observations"],0)
            self.assertEqual(first["first_seen_observations"],1)
            self.assertGreater(first["new_tests"],0)
            b2=bars(324)
            t2=b2[-1]["end"]+100
            second=a.run(state,{key:{"bars":b2,"corroboration":"AGREEMENT","cohort":s.COHORT}},{key:b2},t2,{},{"status":"MISSING"},specs)
            self.assertEqual(second["settlement_statuses"]["COMPLETE_MARK_ONLY"],1)
            self.assertFalse(second["trade_authorized"])
            self.assertEqual(second["official_gate"],"NOT_RUN")
            self.assertEqual(len(a.read_state(state)),2)

if __name__=="__main__":unittest.main()
