"""V8: broad futures coverage, PIPPIN-style move and forward-only test contracts."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from radar.ledger import canonical
from research_v4.perp_watch import (
    BINANCE_INFO,BINANCE_TICKERS,OKX_INFO,OKX_TICKERS,
    BITGET_INFO,BITGET_TICKERS,parse_bitget,append,
    classify,pack,unpack,parse_binance,parse_okx,read,report,scan)

NOW=1795000000000

def info_b():
    return {"symbols":[
        {"symbol":"PIPPINUSDT","contractType":"PERPETUAL","status":"TRADING",
          "quoteAsset":"USDT","marginAsset":"USDT"},
        {"symbol":"PIPPINUSDT_261231","contractType":"CURRENT_QUARTER","status":"TRADING",
          "quoteAsset":"USDT","marginAsset":"USDT"},
        {"symbol":"BTCUSDT","contractType":"PERPETUAL","status":"TRADING",
          "quoteAsset":"USDT","marginAsset":"USDT"},
        {"symbol":"DELISTEDUSDT","contractType":"PERPETUAL","status":"BREAK",
          "quoteAsset":"USDT","marginAsset":"USDT"}]}
def tick_b(now=NOW,price=.0109,change=0):
    return [{"symbol":"PIPPINUSDT","lastPrice":str(price),"quoteVolume":"4000000",
            "priceChangePercent":str(change),"closeTime":now-1000},
            {"symbol":"BTCUSDT","lastPrice":"90000","quoteVolume":"500000000",
            "priceChangePercent":"1","closeTime":now-1000},
            {"symbol":"DELISTEDUSDT","lastPrice":"1","quoteVolume":"1000000",
            "priceChangePercent":"20","closeTime":now-1000}]
def info_o():
    return {"code":"0","data":[{"instId":"PIPPIN-USDT-SWAP","state":"live",
       "ctType":"linear","settleCcy":"USDT"},
       {"instId":"PIPPIN-USDC-SWAP","state":"live","ctType":"linear","settleCcy":"USDC"},
       {"instId":"NOTLIVE-USDT-SWAP","state":"suspend","ctType":"linear","settleCcy":"USDT"}]}
def tick_o(now=NOW,price=.01091):
    return {"code":"0","data":[{"instId":"PIPPIN-USDT-SWAP","last":str(price),
        "volCcy24h":"320000000","open24h":"0.0107","ts":str(now-1000)}]}
def info_g():
    return {"code":"00000","data":[{"symbol":"PIPPINUSDT","quoteCoin":"USDT",
        "symbolType":"perpetual","symbolStatus":"normal"},
        {"symbol":"DELUSDT","quoteCoin":"USDT","symbolType":"perpetual","symbolStatus":"off"}]}
def tick_g(now=NOW,price=.01092):
    return {"code":"00000","data":[{"symbol":"PIPPINUSDT","lastPr":str(price),
        "open24h":".0108","quoteVolume":"3700000","ts":str(now-1000)},
        {"symbol":"DELUSDT","lastPr":"2","open24h":"1","quoteVolume":"2000000",
        "ts":str(now-1000)}]}
def shot(ts,p,delta=5.0):
    return {"schema":"EAR.perp_observations.v1","scan_utc_ms":ts,
        "sources":["binance","okx"],"source_unavailable":{},
        "assets":{"PIPPINUSDT":{
          "binance":{"p":p,"q":3000000.0,"d":delta,"ts":ts-1000},
          "okx":{"p":p*1.001,"q":2800000.0,"d":delta,"ts":ts-1000}}},
        "market_type":"USDT_LINEAR_PERPETUAL_ONLY",
        "trade_authorized":False,"paper_approved":False}

class PerpCoverage(unittest.TestCase):
    def test_pippin_is_futures_candidate_even_if_not_spot_universe(self):
        b=parse_binance(info_b(),tick_b(),NOW)
        o=parse_okx(info_o(),tick_o(),NOW)
        self.assertIn("PIPPINUSDT",b)
        self.assertIn("PIPPINUSDT",o)
        self.assertNotIn("DELISTEDUSDT",b)
        self.assertEqual(set(o),{"PIPPINUSDT"})
        self.assertGreater(o["PIPPINUSDT"]["q"],3000000)
        self.assertTrue(o["PIPPINUSDT"]["q_proxy"])
    def test_okx_quote_volume_field_when_present_is_not_recalculated(self):
        t=tick_o()
        t["data"][0]["volCcyQuote24h"]="2500000"
        row=parse_okx(info_o(),t,NOW)["PIPPINUSDT"]
        self.assertEqual(row["q"],2500000)
        self.assertFalse(row["q_proxy"])
    def test_bitget_usdt_perp_metadata_and_real_quote_turnover(self):
        out=parse_bitget(info_g(),tick_g(),NOW)
        self.assertEqual(set(out),{"PIPPINUSDT"})
        self.assertEqual(out["PIPPINUSDT"]["q"],3700000)
        self.assertFalse(out["PIPPINUSDT"]["q_proxy"])
        self.assertAlmostEqual(out["PIPPINUSDT"]["d"],100*(.01092/.0108-1),places=4)
    def test_two_venues_survive_binance_geoblock(self):
        def fake(url):
            if url==BINANCE_INFO:raise RuntimeError("blocked")
            return {OKX_INFO:info_o(),OKX_TICKERS:tick_o(),
                BITGET_INFO:info_g(),BITGET_TICKERS:tick_g()}[url]
        r=scan(get=fake,clock=lambda:NOW)
        self.assertEqual(r["sources"],["okx","bitget"])
        self.assertIn("binance",r["source_unavailable"])
        self.assertEqual(len(r["assets"]["PIPPINUSDT"]),2)
    def test_no_source_backfilled_if_one_is_missing(self):
        def fake(url):
            if url==BINANCE_INFO:raise RuntimeError("403")
            if url==OKX_INFO:return info_o()
            if url==OKX_TICKERS:return tick_o()
            raise RuntimeError("Bitget unavailable")
        s=scan(get=fake,clock=lambda:NOW)
        self.assertEqual(s["sources"],["okx"])
        self.assertIn("binance",s["source_unavailable"])
        self.assertEqual(list(s["assets"]["PIPPINUSDT"]),["okx"])
    def test_both_sources_missing_fails_closed(self):
        with self.assertRaises(RuntimeError):
            scan(get=lambda _: (_ for _ in ()).throw(RuntimeError("offline")),clock=lambda:NOW)
    def test_stale_ticker_not_fake_fresh(self):
        with self.assertRaises(ValueError):
            parse_binance(info_b(),tick_b(now=NOW-400000),NOW)
    def test_cross_venue_first_scan_no_retrospective_alpha(self):
        first=append(shot(NOW,.01090),[])
        self.assertEqual(first["events"],[])
        self.assertFalse(first["trade_authorized"])
    def test_catches_modest_early_move_and_costs_not_fake(self):
        first=append(shot(NOW,.0109),[])
        second=append(shot(NOW+30*60000,.01112,5),[first])
        self.assertEqual(len(second["events"]),1)
        e=second["events"][0]
        self.assertEqual(e["symbol"],"PIPPINUSDT")
        self.assertEqual(e["stage"],"EARLY_UPWARD_MOTION_WATCH")
        self.assertEqual(e["cross_venue"],"CONSISTENT_MULTI_VENUE")
        self.assertTrue(e["signal_is_price_motion_observation_not_prediction"])
        self.assertFalse(e["trade_authorized"])
    def test_late_impulse_is_not_mislabelled_early(self):
        first=append(shot(NOW,.0109),[])
        second=append(shot(NOW+30*60000,.01856,66),[first])
        self.assertEqual(second["events"][0]["stage"],"UPWARD_IMPULSE_ALREADY_IN_PROGRESS")
    def test_extreme_pump_is_recorded_but_quarantined_not_dropped(self):
        first=append(shot(NOW,.0109),[])
        second=append(shot(NOW+30*60000,.02197,105),[first])
        self.assertEqual(second["events"][0]["stage"],"EXTREME_PRICE_MOVE_SCALE_UNVERIFIED")
        r=report([first,second])
        # This is the event scan itself; no matured future fills.
        self.assertEqual(r["forward_observations"][0]["horizons_min"]["30"]["status"],"SCALE_EVENT_UNVERIFIED")
    def test_cooldown_avoids_perp_alert_spam(self):
        first=append(shot(NOW,.0109),[])
        second=append(shot(NOW+30*60000,.01112,5),[first])
        third=append(shot(NOW+60*60000,.0122,12),[first,second])
        self.assertEqual(third["events"],[])
    def test_forward_returns_require_future_same_venue_snapshot(self):
        first=append(shot(NOW,.0109),[])
        second=append(shot(NOW+30*60000,.01112),[first])
        third=append(shot(NOW+60*60000,.0113),[first,second])
        r=report([first,second,third])
        event=r["forward_observations"][0]
        self.assertEqual(event["horizons_min"]["30"]["status"],"OBSERVED_SNAPSHOT_PRICE_CHANGE_NOT_EXECUTABLE")
        self.assertIsNone(event["horizons_min"]["240"]["underlying_return_pct"])
    def test_canonical_compressed_ledger_hash(self):
        one=append(shot(NOW,.0109),[])
        with TemporaryDirectory() as d:
            path=Path(d)/"scans.jsonl"
            path.write_text(canonical(one)+"\n")
            self.assertEqual(len(read(path)),1)
            x=json.loads(path.read_text());x["venue_counts"]["binance"]=999
            path.write_text(canonical(x)+"\n")
            with self.assertRaises(ValueError):read(path)
    def test_truncated_compressed_blob_rejected(self):
        b=pack({"PIPPINUSDT":{"binance":{"p":.011,"q":120000,"d":1,"ts":NOW}}})
        self.assertIn("PIPPINUSDT",unpack(b))
        with self.assertRaises(Exception):unpack(b[:-8])
    def test_marketwide_no_hardcoded_watchlist(self):
        def fake(url):
            return {BINANCE_INFO:info_b(),BINANCE_TICKERS:tick_b(),
                OKX_INFO:info_o(),OKX_TICKERS:tick_o()}[url]
        s=scan(get=fake,clock=lambda:NOW)
        self.assertEqual(set(s["assets"]),{"PIPPINUSDT","BTCUSDT"})
        self.assertEqual(s["market_type"],"USDT_LINEAR_PERPETUAL_ONLY")

if __name__=="__main__":unittest.main()
