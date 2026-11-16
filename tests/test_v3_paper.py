import json,tempfile,unittest
from pathlib import Path
from radar.ledger import read_verify
from radar.providers import Quote
from research_v3.paper import ASSETS,process,tick,usable_quote

NOW=1794851000000
def observation(now=NOW,acc=True,bid=100.,include=True):
    quotes={}
    for asset in ASSETS:
        if not include and asset=="BTC":quotes[asset]=[];continue
        quotes[asset]=[Quote(v,asset,bid,bid+.1,200,200,now,now,v,"SPOT","USDT")
                       for v in ("binance","okx")]
    return {"observed_ms":now,"quotes":quotes,
            "candles":{"BTC":{"status":"HYPOTHESIS_ONLY","source_venue":"binance",
              "last_closed_bar_ms":(now//60000)*60000-60000,"accumulation_watch":acc,
              "distribution_watch":False}},"errors":[]}

class ForwardPaper(unittest.TestCase):
    def test_first_seen_no_retrospective_fill(self):
        state,event=process(None,observation(acc=False),"fp")
        self.assertEqual(event["status"],"MARKED")
        self.assertEqual(event["nav"],10000)
        self.assertEqual(len(event["transactions"]),0)
        self.assertFalse(event["real_orders"])
    def test_actual_observed_ask_entry_and_bid_exit(self):
        state,event=process(None,observation(),"fp")
        self.assertEqual(event["transactions"][0]["type"],"PAPER_ENTRY")
        self.assertLess(state["cash"],10000)
        state,event=process(state,observation(NOW+5*60000,acc=False,bid=108),"fp")
        self.assertEqual(event["transactions"][0]["type"],"PAPER_EXIT")
        self.assertEqual(state["closed_trades"],1)
        self.assertEqual(state["winning_trades"],1)
    def test_incomplete_books_freeze_nav(self):
        state,event=process(None,observation(),"fp")
        previous_nav=state["last_liquidation_nav"]
        state,event=process(state,observation(NOW+60000,include=False),"fp")
        self.assertEqual(event["status"],"UNMARKED_OUTAGE")
        self.assertIsNone(event["nav"])
        self.assertEqual(previous_nav,state["last_liquidation_nav"])
        self.assertFalse(event["summary"]["last_mark_is_current"])
    def test_missing_second_venue_prevents_entry(self):
        obj=observation()
        obj["quotes"]["BTC"]=obj["quotes"]["BTC"][:1]
        state,event=process(None,obj,"fp")
        self.assertEqual(len(event["transactions"]),0)
    def test_cost_assumptions_exposed(self):
        _,event=process(None,observation(),"fp")
        self.assertEqual(event["transactions"][0]["assumed_fee_bps"],10)
        self.assertEqual(event["transactions"][0]["assumed_slippage_bps"],7)
    def test_durable_forward_chain_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            state=Path(d)/"state.json";ledger=Path(d)/"events.jsonl";out=Path(d)/"latest.json"
            tick(str(state),str(ledger),str(out),observation(acc=False),"fp")
            tick(str(state),str(ledger),str(out),observation(NOW+60000,acc=False),"fp")
            self.assertEqual(len(read_verify(ledger)),2)
            ledger.write_text(ledger.read_text().replace("MARKED","FORGED"))
            with self.assertRaises(ValueError):
                tick(str(state),str(ledger),str(out),observation(NOW+120000),"fp")
    def test_change_model_fingerprint_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            s=Path(d)/"state.json";p=Path(d)/"e.jsonl";o=Path(d)/"out.json"
            tick(str(s),str(p),str(o),observation(acc=False),"fp")
            with self.assertRaises(ValueError):
                tick(str(s),str(p),str(o),observation(NOW+60000),"changed-fingerprint")
    def test_cooldown_no_same_bar_reentry(self):
        state,event=process(None,observation(),"fp")
        state,event=process(state,observation(NOW+60000,acc=True,bid=108),"fp")
        self.assertEqual(len(event["transactions"]),1)
if __name__=="__main__":unittest.main()
