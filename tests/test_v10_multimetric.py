"""V10 multi-metric, strictly historical per-asset baseline contracts."""
import unittest
from research_v4.perp_anomaly import (
    METRICS, analyze_one, metric_sequence, score_metric, latest_cohort, MIN_PRIOR)
from research_v4.perp_watch import (
    append, optional_microstructure, parse_okx, parse_bitget)
from research_v4.preimpulse_study import features

BASE=1795100000000
INTERVAL=30*60000

def series(n=34,spike=False,oi=True,funding=True):
    out=[]
    for i in range(n):
        t=BASE+i*INTERVAL
        exceptional=(i==n-1 and spike)
        p=.01000
        okx={"p":p,"q":3300000 if exceptional else 1100000,"d":0.0,"ts":t,
             "spread_bps":40 if exceptional else 5,"range24h_pct":18 if exceptional else 4,
             "mark_basis_bps":40 if exceptional else 1,
             "funding_rate_pct":.09 if exceptional else .004}
        if oi:okx["oi_contracts"]=175 if exceptional else 100.
        if not funding:okx.pop("funding_rate_pct")
        venues={"okx":okx,"bitget":{"p":.01008 if exceptional else .010001,
                 "q":1000000,"d":0.0,"ts":t}}
        out.append((t,venues))
    return out

class MetricTests(unittest.TestCase):
    def test_multiple_spikes_are_compared_to_only_prior_history(self):
        history=series(spike=True)
        t,current=history[-1]
        data=analyze_one("PIPPINUSDT",t,current,history)
        self.assertEqual(data["stage"],"PREMOVE_ANOMALY_OBSERVED_RESEARCH_ONLY")
        self.assertEqual(data["baseline_status"],"PROVISIONAL")
        self.assertGreaterEqual(data["distinct_metric_outliers"],5)
        self.assertIn("oi_contracts_level",data["outlier_metrics"])
        self.assertIn("turnover_24h_level_usdt",data["outlier_metrics"])
        self.assertIn("bid_ask_spread_bps",data["outlier_metrics"])
        self.assertEqual(data["metric_results"]["oi_contracts_level"]["baseline_median"],100)
        self.assertEqual(data["metric_results"]["oi_contracts_level"]["current_value"],175)
        self.assertEqual(data["prior_2h_return_pct"],0.0)
        self.assertFalse(data["early_prediction_proven"])
    def test_only_single_metric_abnormal_not_rejected(self):
        history=series()
        t,current=history[-1]
        only={k:dict(v) for k,v in current.items()}
        only["okx"]["oi_contracts"]=180.
        result=analyze_one("COINUSDT",t,only,history)
        self.assertEqual(result["stage"],"PREMOVE_ANOMALY_OBSERVED_RESEARCH_ONLY")
        self.assertEqual(result["outlier_metrics"],["oi_contracts_level","oi_contracts_accel_1h_pct"])
        # Two derived stats from one source remain one independent dimension.
        self.assertEqual(result["distinct_information_group_outliers"],1)
        v9=features(history,t,"okx")
        self.assertFalse(v9["motifs"]["relative_multiple_metrics_outlier"])
    def test_baseline_established_only_after_96_historic_samples(self):
        history=series(n=100,spike=True)
        t,current=history[-1]
        result=analyze_one("MATUREUSDT",t,current,history)
        self.assertEqual(result["baseline_status"],"ESTABLISHED")
        self.assertEqual(result["metric_results"]["oi_contracts_level"]["prior_samples"],99)
    def test_price_range_requires_valid_positive_high_low(self):
        bad=optional_microstructure({"high24h":"0","low24h":"0",
            "bidPx":"0.012","askPx":"0.01"},.01,
            high_key="high24h",low_key="low24h",bid_key="bidPx",ask_key="askPx")
        self.assertNotIn("range24h_pct",bad)
        self.assertNotIn("spread_bps",bad)
    def test_fresh_coin_has_no_anomaly_and_no_invented_baseline(self):
        history=series(n=4,spike=True)
        t,current=history[-1]
        result=analyze_one("NEWUSDT",t,current,history)
        self.assertEqual(result["baseline_status"],"BUILDING")
        self.assertEqual(result["outlier_metrics"],[])
        self.assertEqual(result["stage"],"NO_ANOMALY_OR_BASELINE_BUILDING")
        self.assertLess(result["available_metrics"],1)
    def test_missing_oi_and_funding_never_become_zero(self):
        history=series(spike=True,oi=False,funding=False)
        t,current=history[-1]
        result=analyze_one("NONEUSDT",t,current,history)
        self.assertEqual(result["metric_results"]["oi_contracts_level"]["status"],"MISSING_VALUE")
        self.assertEqual(result["metric_results"]["funding_abs_pct"]["status"],"MISSING_VALUE")
        self.assertNotIn("oi_contracts_level",result["outlier_metrics"])
    def test_future_variation_cannot_recompute_old_score(self):
        history=series(spike=True)
        t,current=history[-1]
        a=analyze_one("PIPPINUSDT",t,current,history)
        future=series(n=40,spike=True)[-6:]
        b=analyze_one("PIPPINUSDT",t,current,history+future)
        self.assertEqual(a,b)
    def test_other_coins_do_not_supply_missing_baseline(self):
        history=series(spike=True)
        t,current=history[-1]
        unrelated=series()
        hist_other=[(ts,{"okx":dict(x["okx"],q=1000)}) for ts,x in unrelated]
        a=analyze_one("PIPPINUSDT",t,current,history)
        b=analyze_one("PIPPINUSDT",t,current,history+[(ts,{"othercoin":x}) for ts,x in hist_other])
        self.assertEqual(a,b)
    def test_scalar_prior_z_and_percentile_both_needed(self):
        a=score_metric("oi_contracts_level",105,[100.0]*MIN_PRIOR)
        self.assertEqual(a["status"],"WITHIN_OWN_BASELINE")
        b=score_metric("oi_contracts_level",180,[100.0]*MIN_PRIOR)
        self.assertEqual(b["status"],"OUTLIER_ABOVE_OWN_BASELINE")
        self.assertEqual(b["baseline_median"],100)
    def test_cross_venue_divergence_blocks_pre_move_label(self):
        history=series(spike=True)
        t,current=history[-1]
        corrupted={k:dict(v) for k,v in current.items()}
        corrupted["bitget"]["p"]=.011
        a=analyze_one("BADUSDT",t,corrupted,history)
        self.assertEqual(a["stage"],"OUTLIER_WITH_PRIOR_MOTION_OR_UNVERIFIED_PRICE")
    def test_optional_ticker_fields_calculate_real_units(self):
        r=optional_microstructure({"bidPx":".0099","askPx":".0101",
                "high24h":".012","low24h":".008","fundingRate":".0005",
                "markPrice":".01005"},.01,
                bid_key="bidPx",ask_key="askPx",high_key="high24h",low_key="low24h",
                funding_key="fundingRate",mark_key="markPrice")
        self.assertAlmostEqual(r["spread_bps"],200,places=4)
        self.assertAlmostEqual(r["range24h_pct"],50,places=4)
        self.assertAlmostEqual(r["funding_rate_pct"],.05,places=4)
        self.assertLess(r["mark_basis_bps"],0)
        self.assertNotIn("spread_bps",optional_microstructure(
            {"bid":".011","ask":".009"},.01,bid_key="bid",ask_key="ask"))
    def test_v9_uses_multi_metric_in_no_hindsight_motifs(self):
        history=series(spike=True)
        t,current=history[-1]
        result=features(history,t,"okx")
        self.assertTrue(result["motifs"]["relative_any_metric_outlier"])
        self.assertTrue(result["motifs"]["relative_multiple_metrics_outlier"])
        self.assertTrue(result["motifs"]["relative_oi_contracts_outlier"])
        self.assertTrue(result["motifs"]["relative_spread_outlier"])
        self.assertEqual(result["price_return_2h_pct"],0)
    def test_v9_missing_history_motif_is_null_not_negative(self):
        history=series(n=5,spike=True)
        t,current=history[-1]
        x=features(history,t,"okx")
        self.assertIsNone(x["motifs"]["relative_any_metric_outlier"])
    def test_cohort_contains_all_nonmovers_not_only_hot_coins(self):
        history=series(spike=True)
        rows=[]
        for ts,prices in history:
            c=({"PIPPINUSDT":prices,
               "QUIETUSDT":{"okx":{"p":.01,"q":1000000,"d":0,"ts":ts}}})
            rows.append(append({"scan_utc_ms":ts,"assets":c,"sources":["okx","bitget"],
              "source_unavailable":{},"market_type":"USDT_LINEAR_PERPETUAL_ONLY"},rows))
        result=latest_cohort(rows)
        self.assertEqual(result["coins_in_snapshot"],2)
        self.assertEqual(len(result["full_cohort"]),2)
        self.assertIn("PIPPINUSDT",[x["symbol"] for x in result["top_research_observations"]])
        self.assertFalse(result["trade_authorized"])
    def test_outlier_without_price_break_is_not_proven_alpha(self):
        history=series(spike=True)
        t,current=history[-1]
        z=analyze_one("XUSDT",t,current,history)
        self.assertFalse(z["early_prediction_proven"])
        self.assertFalse(z["trade_authorized"])

if __name__=="__main__":unittest.main()
