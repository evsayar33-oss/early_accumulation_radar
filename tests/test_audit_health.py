import unittest,tempfile,subprocess,sys,json
from pathlib import Path
from radar.ledger import append,read_verify
from radar.audit import audit
from radar.telegram_health import validate
from radar.providers import Quote
from radar.engine import analyze
from radar.tape import parse as parse_tape

T=1794849423713
def sample(ts=T):
    return {"schema":"EAR.research.v2","scan_utc_ms":ts,
      "quotes":{"assets":[{"asset":a,"status":"WATCH_ONLY","trade_allowed":False} for a in ("BTC","ETH","SOL")],
                "failed_sources":[]},"sampled_tape":[],
      "candle_diagnostics":[{"asset":a,"status":"HYPOTHESIS_ONLY","last_closed_bar_ms":ts-60000} for a in ("BTC","ETH","SOL")],
      "errors":[],"zero_valid_candle_sources":False}
class Integrity(unittest.TestCase):
    def test_two_entries_full_chain_and_gap(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"state.jsonl"
            append(sample(),p);append(sample(T+100*60000),p)
            result=audit(p,now_ms=T+101*60000)
            self.assertTrue(result["ok"]);self.assertTrue(result["chain_valid"])
            self.assertEqual(result["entries"],2);self.assertEqual(result["prior_gap_count"],1)
            self.assertFalse(result["trade_allowed"])
    def test_weak_quote_is_degraded_but_candles_are_good(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"state.jsonl";row=sample()
            row["quotes"]["assets"][1]["status"]="INSUFFICIENT_VERIFIED_LIQUIDITY"
            append(row,p)
            result=audit(p,now_ms=T+2000)
            self.assertFalse(result["ok"])
            self.assertTrue(result["candle_observation_ok"])
            self.assertFalse(result["quote_quality_ok"])
            self.assertEqual(result["unhealthy_quote_assets"],["ETH"])
            self.assertFalse(result["trade_allowed"])
    def test_cli_allows_only_quote_degradation_not_staleness(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"state.jsonl";output=Path(d)/"health.json"
            row=sample();row["quotes"]["assets"][1]["status"]="INSUFFICIENT_VERIFIED_LIQUIDITY"
            append(row,p)
            # Historical timestamp is stale relative to today: CLI must refuse to mask it.
            cmd=[sys.executable,"-m","radar.audit","--ledger",str(p),
                 "--allow-quote-degraded","--output",str(output)]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertFalse(json.loads(output.read_text())["candle_observation_ok"])
    def test_corrupt_historical_chain_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"state.jsonl";append(sample(),p)
            p.write_text(p.read_text().replace("WATCH_ONLY","ALTERED"))
            with self.assertRaises(ValueError):audit(p,now_ms=T+2000)
    def test_expired_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"state.jsonl";append(sample(),p)
            self.assertFalse(audit(p,now_ms=T+125*60000)["ok"])
    def test_usd_excluded_from_usdt_crossvenue(self):
        def q(v,c):
            return Quote(v,"BTC",100,100.1,100,100,T,T,v,"SPOT",c)
        self.assertEqual(analyze("BTC",[q("coinbase","USD"),q("kraken","USD")])["status"],"INSUFFICIENT_VERIFIED_LIQUIDITY")
        self.assertEqual(analyze("BTC",[q("binance","USDT"),q("okx","USDT")])["status"],"WATCH_ONLY")
    def test_gate_spot_tape(self):
        records=[{"id":"12","create_time_ms":str(T-100),"price":"100","amount":"2",
                  "side":"buy","currency_pair":"BTC_USDT"}]
        result=parse_tape("gate","BTC",records,T)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].notional,200)
    def test_optional_telegram_not_configured(self):
        self.assertEqual(validate("",""),"NOT_CONFIGURED")
        with self.assertRaises(ValueError):validate("secret","")
    def test_telegram_probe_and_delivery_receipt(self):
        calls=[]
        def mock(token,method,params):
            calls.append(method)
            return {"is_bot":True} if method=="getMe" else {"id":"123"} if method=="getChat" else {"message_id":42}
        self.assertEqual(validate("secret","123",True,call=mock),"TEST_MESSAGE_ACCEPTED_BY_TELEGRAM")
        self.assertEqual(calls,["getMe","getChat","sendMessage"])
if __name__=="__main__":unittest.main()
