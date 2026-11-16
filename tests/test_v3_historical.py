import hashlib,io,zipfile,unittest
from datetime import datetime,timezone
from research_v3.historical import timestamp_ms,parse_zip,get_month
from research_v3.model import conditions,simulate,buyhold,SCENARIOS

def rows(n=1100):
    t=int(datetime(2026,10,1,tzinfo=timezone.utc).timestamp()*1000)
    out=[]
    for i in range(n):
        ts=t+i*60000
        out.append([str(ts*1000),"100","101","99","100","1",str((ts+59999)*1000+999),
                    "100","15","0","60","0"])
    return out

def archive(data):
    buff=io.BytesIO()
    with zipfile.ZipFile(buff,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("BTCUSDT-1m-2026-10.csv","\n".join(",".join(x) for x in data))
    return buff.getvalue()

def bars(n=240):
    ts=1794840000000//60000*60000
    return [{"ts":ts+i*60000,"o":100.,"h":100.1,"l":99.9,"c":100.,
             "quote":300. if i>=120 else 100.,
             "buy":210. if i>=120 else 50.} for i in range(n)]

class Historical(unittest.TestCase):
    def test_timestamp_microseconds(self):
        self.assertEqual(timestamp_ms(1793491200000000),1793491200000)
    def test_bad_micro_timestamp(self):
        with self.assertRaises(ValueError):timestamp_ms(1793491200000001)
    def test_verified_official_zip(self):
        blob=archive(rows())
        expected=hashlib.sha256(blob).hexdigest()
        def fake(url):return (expected+"  BTCUSDT-1m-2026-10.zip\n").encode() if url.endswith(".CHECKSUM") else blob
        result,meta=get_month("BTCUSDT","2026-10",get=fake)
        self.assertEqual(len(result),1100)
        self.assertTrue(meta["official_checksum_verified"])
    def test_tampered_official_zip_rejected(self):
        blob=archive(rows())
        def fake(url):return (("f"*64)+"  file.zip\n").encode() if url.endswith(".CHECKSUM") else blob
        with self.assertRaises(ValueError):get_month("BTCUSDT","2026-10",get=fake)
    def test_broken_consecutive_bars_rejected(self):
        data=rows();data[500][0]=data[499][0]
        with self.assertRaises(ValueError):parse_zip(archive(data))
    def test_frozen_accumulation_hypothesis(self):
        d=bars()
        self.assertTrue(conditions(d,135)["acc"])
        self.assertFalse(conditions(d,70)["acc"])
    def test_following_open_used_not_signal_close(self):
        d=bars()
        x=simulate(d,"acc","base")
        self.assertGreater(x["trades"],0)
        self.assertTrue(all(t["exit_ts"]>=t["entry_ts"] for t in x["trades_ledger"]))
    def test_trade_cannot_get_better_with_higher_cost(self):
        d=bars()
        a=simulate(d,"acc","base")
        b=simulate(d,"acc","stress")
        self.assertLessEqual(b["net_return_pct"],a["net_return_pct"])
    def test_no_return_guaranteed(self):
        x=simulate(bars(110),"acc","base")
        self.assertEqual(x["trades"],0)
        self.assertIsNone(x["win_rate"])
    def test_buy_hold_calculated(self):
        result=buyhold(bars())
        self.assertIn("net_return_pct",result)
        self.assertLess(result["net_return_pct"],0)
if __name__=="__main__":unittest.main()
