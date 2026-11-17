"""V7 point-in-time feature gates, original-target evidence and DEX integrity."""
import json,unittest
from datetime import date,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from radar.ledger import canonical
from research_v4.original_universe import classify_pair
from research_v4.v7_target_fit import (
    features,signals,universe_fit,produce,evaluate)
from research_v4.dex_firstseen import (
    append_discovery,ledger_read,forward_report,tracked)

DAY=86400000
START=1794800000000

def bars(n=140):
    start=date(2025,1,1)
    result=[]
    for i in range(n):
        close=10.0+.0001*i
        result.append({"date":start+timedelta(days=i),
            "open":close-.001,"high":close+.09,"low":close-.09,
            "close":close,"volume":1000.,"pit":False,"actions":False})
    return result

def market_manifest():
    return {"source_class":"CURRENT_ONLY_NOT_POINT_IN_TIME",
        "universe":{"BIST":[{"symbol":"FOO","selection_source":"KAP","cap_snapshot_usd":None}],
        "US":[{"symbol":"BAR","selection_source":"TV","cap_snapshot_usd":50000000}],
        "CRYPTO":[{"symbol":"BAZUSDT","selection_source":"COINGECKO","cap_snapshot_usd":60000000}]}}

def pair(price=1.0):
    return {"chain":"solana","pair_address":"solpair","token_address":"soltoken",
        "base_symbol":"SOLO","quote_symbol":"USDC",
        "liquidity_usd":30000.,"volume_24h_usd":40000.,
        "price_usd_snapshot_unverified":price,"screen_watch":True,
        "float_verified":False,"holder_concentration_verified":False,
        "trade_authorized":False}

class V7Fit(unittest.TestCase):
    def test_target_cap_is_not_historical_float(self):
        r=universe_fit(market_manifest())
        self.assertTrue(all(x["original_target_verified"] is False for x in r))
        self.assertIn("MISSING_BIST_SIZE_FLOAT",r[0]["state"])
        self.assertIn("NOT_DEX",r[2]["state"])
    def test_strict_manifest_gate(self):
        with self.assertRaises(ValueError):universe_fit({"source_class":"PIT","universe":{}})
    def test_features_cannot_look_into_future(self):
        seq=bars()
        f=features(seq,108)
        modified=[dict(x) for x in seq]
        modified[120]["close"]=990
        self.assertEqual(f,features(modified,108))
    def test_prebreakout_precedes_actual_break(self):
        s=bars()
        i=110
        s[i].update({"open":10.005,"low":10.0,"high":10.10,
                     "close":10.075,"volume":1200})
        z=features(s,i)
        self.assertTrue(z["near_unbroken_high"])
        self.assertTrue(signals(z)["prebreakout_pressure"])
        self.assertFalse(z["price"]>z["prior_high"] if "price" in z else False)
    def test_future_rebase_censors_outcome_not_prior_signal(self):
        s=bars()
        i=110
        s[i].update({"open":10.005,"low":10.0,"high":10.10,
                     "close":10.075,"volume":1200})
        a,_=produce({("CRYPTO","AAAUSDT"):s})
        picked=next(x for x in a if x["signal"]==s[i]["date"].isoformat()
                    and x["family"]=="prebreakout_pressure")
        s2=[dict(x) for x in s]
        s2[i+2]["open"]=s2[i+1]["close"]*3
        s2[i+2]["high"]=s2[i+2]["open"]*1.1
        s2[i+2]["low"]=s2[i+2]["open"]*.9
        s2[i+2]["close"]=s2[i+2]["open"]
        b,_=produce({("CRYPTO","AAAUSDT"):s2})
        same=next(x for x in b if x["signal"]==s[i]["date"].isoformat()
                  and x["family"]=="prebreakout_pressure")
        self.assertEqual(picked["entry_date"],same["entry_date"])
        self.assertEqual(same["horizons"]["2"]["status"],"CENSORED_FUTURE_PRICE_DISCONTINUITY")
    def test_no_paper_promotion_even_if_synthetic_positive(self):
        seq=bars(220)
        r=evaluate({("US","BAR"):seq},market_manifest())
        self.assertFalse(r["paper_approved"])
        self.assertFalse(r["original_target_universe_verified"])
        self.assertTrue(all(x["direction"]=="LONG_HYPOTHESIS"
                           for x in r["results"] if x["family"] in ("quiet_base","prebreakout_pressure","absorption_probe")))

class V7Dex(unittest.TestCase):
    def test_target_must_be_base_side_to_use_price(self):
        raw={"chainId":"solana","dexId":"x","pairAddress":"pair1",
            "baseToken":{"address":"base1","symbol":"A"},
            "quoteToken":{"address":"quote1","symbol":"B"},
            "priceUsd":"2.25","liquidity":{"usd":20000},
            "volume":{"h24":22000},"pairCreatedAt":START-36*3600000,
            "fdv":200000}
        self.assertIsNone(classify_pair(raw,START,"solana","quote1"))
        self.assertEqual(classify_pair(raw,START,"solana","base1")["price_usd_snapshot_unverified"],2.25)
    def test_hash_chain_and_price_maturity(self):
        snap={"observed_ms":START,"observations":[pair(1.0)],
              "status":"RESEARCH_OBSERVATIONS_NOT_VALIDATED_ALPHA","errors":[]}
        one=append_discovery([],snap,[])
        two=append_discovery([one],{"observed_ms":START+DAY,
                    "observations":[pair(1.20)],"errors":[]},[])
        with TemporaryDirectory() as d:
            p=Path(d)/"ledger.jsonl"
            p.write_text(canonical(one)+"\n"+canonical(two)+"\n")
            rows=ledger_read(p)
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[-1]["new_pairs_radar_first_seen_count"],0)
            self.assertEqual(tracked(rows,START+DAY),[("solana","solpair","soltoken")])
            r=forward_report(rows)
            self.assertAlmostEqual(r["pairs"][0]["horizons_hours"]["24"]["underlying_snapshot_return_pct"],20)
            self.assertEqual(r["pairs"][0]["horizons_hours"]["72"]["status"],"NO_OBSERVED_FOLLOWUP_NEAR_HORIZON")
            altered=p.read_text().replace('"watch_count":1','"watch_count":6',1)
            p.write_text(altered)
            with self.assertRaises(ValueError):ledger_read(p)
    def test_first_seen_requires_monotonic_clock(self):
        one=append_discovery([],{"observed_ms":START,"observations":[pair()],"errors":[]},[])
        with self.assertRaises(ValueError):
            append_discovery([one],{"observed_ms":START,"observations":[pair()],"errors":[]},[])

if __name__=="__main__":unittest.main()
