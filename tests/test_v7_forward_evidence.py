"""Isolated V7 forward-only contracts: first seen, no retrofill, no fake SHORT."""
import unittest
from datetime import date,timedelta
from research_v4.v7_forward import signals_from_closed,update,settle,closed_history
from research_v4.prospective_evidence import digest,seal

def bars(n=140):
    start=date(2025,1,1)
    rows=[]
    for i in range(n):
        c=10.0+.0001*i
        rows.append({"date":start+timedelta(days=i),
            "open":c-.001,"high":c+.09,"low":c-.09,
            "close":c,"volume":1000.,"pit":False,"actions":False})
    return rows

def series():
    r=bars()
    r[-1].update({"open":10.005,"low":10.0,"high":10.10,
                  "close":10.075,"volume":1200})
    return {("CRYPTO","ALPHAUSDT"):r}

class ForwardContracts(unittest.TestCase):
    def test_new_families_frozen_only_after_close(self):
        s=series()
        day=s[("CRYPTO","ALPHAUSDT")][-1]["date"]
        observed=(day+timedelta(days=1)).isoformat()+"T12:00:00+00:00"
        signals=signals_from_closed(s,observed,"code","source")
        selected=[x for x in signals if x["family"]=="prebreakout_pressure"]
        self.assertEqual({x["hold_sessions"] for x in selected},{2,5,10})
        self.assertTrue(all(x["entry_strictly_after_utc_date"]>(day.isoformat()) for x in selected))
        self.assertTrue(all(x["trade_authorized"] is False for x in selected))
    def test_latest_bar_on_asof_day_not_closed(self):
        s=series()
        day=s[("CRYPTO","ALPHAUSDT")][-1]["date"]
        asof=day.isoformat()+"T11:00:00+00:00"
        closed=closed_history(s,asof)
        self.assertEqual(len(closed[("CRYPTO","ALPHAUSDT")]),139)
        self.assertFalse(any(x["signal_date"]==day.isoformat()
                             for x in signals_from_closed(s,asof,"code","source")))
    def test_first_seen_only_then_forward_matters(self):
        s=series()
        day=s[("CRYPTO","ALPHAUSDT")][-1]["date"]
        asof=(day+timedelta(days=1)).isoformat()+"T12:00:00+00:00"
        old,settled,report=update(s,[],[],asof,"code","source")
        self.assertGreaterEqual(report["new_signals"],3)
        self.assertEqual(report["new_settlements"],0)
        again,again_set,again_report=update(s,old,settled,asof,"code","source")
        self.assertEqual(again_report["new_signals"],0)
        self.assertEqual(len(again),len(old))
        nextbars=bars(160)
        # Preserve signal price and history verbatim; only FUTURE bars added.
        nextbars[:140]=s[("CRYPTO","ALPHAUSDT")]
        future={("CRYPTO","ALPHAUSDT"):nextbars}
        later=(nextbars[-1]["date"]+timedelta(days=1)).isoformat()+"T12:00:00+00:00"
        _,out,report2=update(future,old,[],later,"code","source")
        self.assertGreaterEqual(report2["new_settlements"],3)
        self.assertTrue(all(r["paper_approved"] is False for r in out))
        self.assertTrue(all(r["short_profit_claimed"] is False for r in out))
    def test_price_scale_jump_blocks_forward_pnl(self):
        s=series()
        day=s[("CRYPTO","ALPHAUSDT")][-1]["date"]
        asof=(day+timedelta(days=1)).isoformat()+"T12:00:00+00:00"
        sig=next(x for x in signals_from_closed(s,asof,"code","source")
                 if x["family"]=="prebreakout_pressure" and x["hold_sessions"]==2)
        prices=bars(160)
        prices[:140]=s[("CRYPTO","ALPHAUSDT")]
        j=142
        prices[j]["open"]=prices[j-1]["close"]*3
        prices[j]["high"]=prices[j]["open"]*1.05
        prices[j]["low"]=prices[j]["open"]*.95
        prices[j]["close"]=prices[j]["open"]
        asof_later=(prices[-1]["date"]+timedelta(days=1)).isoformat()+"T12:00:00+00:00"
        result,reason=settle(sig,closed_history({("CRYPTO","ALPHAUSDT"):prices},asof_later))
        self.assertIsNone(result)
        self.assertEqual(reason,"SUSPECTED_PRICE_SCALE_CHANGE_IN_FORWARD")

if __name__=="__main__":unittest.main()
