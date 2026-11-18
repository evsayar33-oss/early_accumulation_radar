"""V9 precise temporal-causality and nonmover-control regressions."""
import unittest
from research_v4.perp_watch import (
    append,pack,attach_okx_open_interest,OKX_OPEN_INTEREST,scan,
    BINANCE_INFO,OKX_INFO,OKX_TICKERS,BITGET_INFO,BITGET_TICKERS,
)
from research_v4.preimpulse_study import study,features,forward
def info_o():
    return {"code":"0","data":[{"instId":"PIPPIN-USDT-SWAP","state":"live",
             "ctType":"linear","settleCcy":"USDT"}]}
def tick_o(now=BASE):
    return {"code":"0","data":[{"instId":"PIPPIN-USDT-SWAP","last":".011",
             "open24h":".0109","volCcy24h":"200000000","ts":str(now-1000)}]}
def info_g():
    return {"code":"00000","data":[{"symbol":"PIPPINUSDT","quoteCoin":"USDT",
             "symbolType":"perpetual","symbolStatus":"normal"}]}
def tick_g(now=BASE):
    return {"code":"00000","data":[{"symbol":"PIPPINUSDT","lastPr":".011",
             "open24h":".0109","quoteVolume":"2500000","ts":str(now-1000)}]}

BASE=1795100000000

def snap(i):
    ts=BASE+i*30*60000
    a=.01 if i<8 else .013
    down=1.0 if i<8 else .82
    own={}
    for sym,price,oi in (("PIPPINUSDT",a,100+10*max(0,i-2)),
                         ("QUIETUSDT",.01,100),("FALLUSDT",down,100)):
        own[sym]={"okx":{"p":price,"q":1000000 if i<2 else (1300000 if sym=="PIPPINUSDT" and i>=4 else 1000000),
                         "d":0 if i<8 else (20 if sym=="PIPPINUSDT" else 0),
                         "ts":ts,"oi_contracts":oi}}
    return {"scan_utc_ms":ts,"sources":["okx"],"market_type":"USDT_LINEAR_PERPETUAL_ONLY",
            "source_unavailable":{},"assets":own}

class V9Controls(unittest.TestCase):
    def test_asof_features_never_depend_on_future_pump(self):
        base=[snap(i) for i in range(5)]
        history=[(r["scan_utc_ms"],r["assets"]["PIPPINUSDT"]) for r in base]
        before=features(history,BASE+4*30*60000,"okx")
        base.append(snap(9))
        history2=[(r["scan_utc_ms"],r["assets"]["PIPPINUSDT"]) for r in base]
        self.assertEqual(before,features(history2,BASE+4*30*60000,"okx"))
        self.assertTrue(before["motifs"]["oi_contracts_up_10pct"])
        self.assertTrue(before["motifs"]["activity_up_flat_3pct"])
    def test_hindsight_only_pippin_has_NO_early_signal(self):
        data=[append(snap(8),[])]
        r=study(data)
        self.assertEqual(r["eligible_asof_cohort_count"],0)
        self.assertEqual(r["matured_full_control_population"],0)
        self.assertFalse(r["significant_common_metric_discovered"])
    def test_full_cross_section_has_frozen_positive_and_negative(self):
        rows=[]
        for i in range(18):
            rows.append(append(snap(i),rows))
        report=study(rows)
        self.assertGreaterEqual(report["eligible_asof_cohort_count"],3)
        self.assertIn("UPSIDE_EXTREME",report["future_label_counts"])
        self.assertIn("NO_EXTREME_MOVE",report["future_label_counts"])
        self.assertIn("DOWNSIDE_EXTREME",report["future_label_counts"])
        stats=report["case_control_stats"]
        matched=[x for x in stats if x["target"]=="UPSIDE_EXTREME"
                 and x["motif"]=="activity_up_20pct"]
        self.assertEqual(len(matched),1)
        self.assertGreaterEqual(matched[0]["matched_nonmover_controls"],1)
        self.assertFalse(report["proven_profitable_strategy"])
    def test_future_gaps_must_remain_pending(self):
        s=[snap(0),snap(8),snap(9)]
        scans=[(x["scan_utc_ms"],x["assets"]) for x in s]
        out=forward(scans,0,"QUIETUSDT","okx",.01)
        self.assertEqual(out["status"],"PENDING_INCOMPLETE_FUTURE_SNAPSHOTS")
    def test_missing_oi_remains_null_not_negative_evidence(self):
        rows=[snap(i) for i in range(5)]
        for row in rows:
            del row["assets"]["PIPPINUSDT"]["okx"]["oi_contracts"]
        history=[(r["scan_utc_ms"],r["assets"]["PIPPINUSDT"]) for r in rows]
        f=features(history,BASE+4*30*60000,"okx")
        self.assertIsNone(f["motifs"]["oi_contracts_up_10pct"])
    def test_okx_oi_is_unit_checked_and_not_artificial_value_from_price(self):
        raw={"code":"0","data":[{"instId":"PIPPIN-USDT-SWAP","oi":"123000",
                "oiUsd":"3000000","ts":str(BASE+5000)}]}
        assets={"PIPPINUSDT":{"okx":{"p":0.01,"q":1000000,"d":0,"ts":BASE+5000}}}
        updated=attach_okx_open_interest(assets,raw,BASE+10000)
        self.assertEqual(updated,1)
        self.assertEqual(assets["PIPPINUSDT"]["okx"]["oi_contracts"],123000)
        self.assertEqual(assets["PIPPINUSDT"]["okx"]["oi_usd"],3000000)
        self.assertNotEqual(assets["PIPPINUSDT"]["okx"]["oi_usd"],
                            assets["PIPPINUSDT"]["okx"]["oi_contracts"])
    def test_oi_api_unavailable_does_not_block_futures_prices(self):
        def get(url):
            if url==BINANCE_INFO:raise RuntimeError("geo")
            if url==OKX_INFO:return info_o()
            if url==OKX_TICKERS:return tick_o(now=BASE)
            if url==OKX_OPEN_INTEREST:raise RuntimeError("oi")
            if url==BITGET_INFO:return info_g()
            if url==BITGET_TICKERS:return tick_g(now=BASE)
            raise RuntimeError("unknown")
        data=scan(get=get,clock=lambda:BASE)
        self.assertIn("PIPPINUSDT",data["assets"])
        self.assertIn("okx_open_interest",data["source_unavailable"])
        self.assertEqual(data["open_interest_instruments_with_fresh_oi"],0)

if __name__=="__main__":unittest.main()
