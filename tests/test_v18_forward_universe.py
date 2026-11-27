import tempfile
import unittest
from pathlib import Path

from research_v4 import v18_forward_universe as u
from radar.ledger import canonical

T=1800000000000

def rec(venue='gate',sym='NEW_USDT',seen=T,price=1.,cls='STANDARD_PERP',listing=1,volume=500):
    return u.record(venue,sym,sym,cls,{'listing':listing},{'p':price,'q':volume,'d':0.,'funding_rate_pct':-.01},seen)

def mapping(*rows):return {r['id']:r for r in rows}

def empty():
    return u.state_read(Path('/this_path_does_not_exist_ear_v18'))

class ForwardUniverse(unittest.TestCase):
    def test_new_listing_zero_history_and_low_volume(self):
        r=rec();state,report,outcomes=u.settle_and_observe(empty(),mapping(r),{},T)
        self.assertEqual(report['new_forward_anchors'],1)
        self.assertEqual(report['low_liquidity_contracts'],1)
        self.assertFalse(report['history_required']);self.assertFalse(report['paper_approved'])
        self.assertEqual(outcomes,[]);self.assertIn('negative_funding',state['pending'][r['id']]['features'])
    def test_correct_same_contract_outcome_and_no_overlap(self):
        state,_,_=u.settle_and_observe(empty(),mapping(rec()),{},T)
        state,report,out=u.settle_and_observe(state,mapping(rec(seen=T+u.HOUR,price=1.1)),{},T+u.HOUR)
        self.assertFalse(out);self.assertEqual(report['new_forward_anchors'],0)
        state,report,out=u.settle_and_observe(state,mapping(rec(seen=T+u.HORIZON,price=1.15)),{},T+u.HORIZON)
        self.assertEqual(out[0]['label'],'UP');self.assertEqual(out[0]['status'],'COMPLETE_ENDPOINT_MARK_ONLY');self.assertEqual(report['new_forward_anchors'],1)
        self.assertEqual(report['cumulative_by_venue_class']['gate|STANDARD_PERP']['features']['negative_funding']['true_UP'],1)
    def test_no_cross_exchange_or_relisting(self):
        state,_,_=u.settle_and_observe(empty(),mapping(rec()),{},T)
        t=T+u.HORIZON+u.TOLERANCE+1
        state,report,out=u.settle_and_observe(state,mapping(rec(venue='bingx',seen=t,price=5),rec(seen=t,listing=2,price=5)),{},t)
        self.assertEqual(out[0]['status'],'CENSORED_NO_TIMELY_SAME_CONTRACT_QUOTE');self.assertIsNone(out[0]['return_pct']);self.assertEqual(report['pending'],2)
    def test_class_separation_and_threshold(self):
        state,_,_=u.settle_and_observe(empty(),mapping(rec(cls='STOCK'),rec(cls='CRYPTO')),{},T)
        t=T+u.HORIZON
        _,r,out=u.settle_and_observe(state,mapping(rec(cls='STOCK',seen=t,price=1.04),rec(cls='CRYPTO',seen=t,price=1.04)),{},t)
        self.assertEqual({x['class']:x['label'] for x in out},{'STOCK':'UP','CRYPTO':'NONE'})
        self.assertIn('gate|STOCK',r['cumulative_by_venue_class']);self.assertIn('gate|CRYPTO',r['cumulative_by_venue_class'])
    def test_gate_real_schema_and_missing_category(self):
        info=[{'name':s,'status':'trading','in_delisting':False,'is_pre_market':False,'type':'direct','contract_type':c,'launch_time':1,'quanto_multiplier':'1'} for s,c in [('NEW_USDT',''),('AAPL_USDT','stocks')]]
        ticks=[{'contract':s['name'],'last':'1','volume_24h_quote':'20','change_percentage':'0','funding_rate':'0.0001'} for s in info]
        r,n=u.gate_venue(lambda url:info if url.endswith('contracts') else ticks,lambda:T)
        self.assertEqual(n,2);self.assertEqual({v['class'] for v in r.values()},{'STANDARD_PERP','STOCK'})
        self.assertTrue(all(v['timestamp_basis']=='RECEIPT_ONLY' for v in r.values()))
    def test_unknown_bingx_class_and_stale_ticks(self):
        info={'code':0,'data':[{'symbol':'SYNTH-USDT','status':1,'currency':'USDT','launchTime':1,'contractId':'1','displayName':'AAPL-USDT','asset':'SYNTH'}]}
        ticks={'code':0,'data':[{'symbol':'SYNTH-USDT','lastPrice':'5','quoteVolume':'1','closeTime':T}]}
        r,n=u.bingx_venue(lambda url:info if url.endswith('contracts') else ticks,lambda:T)
        self.assertEqual(next(iter(r.values()))['class'],'UNCLASSIFIED')
        self.assertEqual(next(iter(r.values()))['symbol'],'SYNTH-USDT')
        r,_=u.bingx_venue(lambda url:info if url.endswith('contracts') else ticks,lambda:T+u.FRESH+1);self.assertFalse(r)
    def test_state_integrity_and_missing_feature(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json';state,_,_=u.settle_and_observe(empty(),mapping(rec()),{},T)
            p.write_text(canonical(state));self.assertEqual(u.state_read(p)['sha256'],state['sha256'])
            p.write_text(p.read_text().replace('STANDARD_PERP','CRYPTO'))
            with self.assertRaisesRegex(ValueError,'INTEGRITY'):u.state_read(p)
        self.assertNotIn('oi_rise_quiet',u.features(rec(),None))
    def test_bounded_priority_not_starving_rotation(self):
        import json
        from research_v4 import v18_sources as s
        assets={f"COIN{i:02}USDT":{"okx":{"q":200000}} for i in range(16)}
        picked,c=s.select_assets(assets,0,8,["COIN15USDT","COIN14USDT","COIN13USDT"])
        self.assertEqual(len(picked),8);self.assertEqual(c,6)
        self.assertTrue(all(f"COIN{i:02}USDT" in picked for i in range(6)))
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.json';p.write_text(json.dumps({'schema':u.SCHEMA,'asof_ms':T,'deep_research_priority':[{'symbol':'COIN15USDT','seen':T}]}))
            self.assertEqual(s.read_forward_priority(p,T),['COIN15USDT'])
            self.assertEqual(s.read_forward_priority(p,T+3*u.HOUR),[])
            self.assertEqual(s.read_forward_priority(p,T-1),[])
    def test_outage_and_clock(self):
        state,_,_=u.settle_and_observe(empty(),mapping(rec()),{},T)
        with self.assertRaisesRegex(ValueError,'CLOCK'):u.settle_and_observe(state,{}, {},T)
        _,r,out=u.settle_and_observe(state,{}, {'gate':{'status':'SOURCE_UNAVAILABLE'}},T+u.HORIZON+u.TOLERANCE+1)
        self.assertEqual(r['observed_contracts'],0);self.assertEqual(out[0]['status'],'CENSORED_NO_TIMELY_SAME_CONTRACT_QUOTE')

if __name__=='__main__':unittest.main()
