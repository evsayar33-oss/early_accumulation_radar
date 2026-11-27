"""V18 broad forward-only perpetual survey; never an order or OHLC backtest.

Observe native venue-qualified contracts in bulk. A real subsequent quote can
settle a 4h endpoint study (not the intraperiod high/low or an executable fill).
All observations, outcomes and state revisions are preserved by non-force Git
commits. No past candles, API key, or minimum history is required.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from radar.ledger import canonical, digest
from research_v4.perp_watch import (public_json, parse_binance, parse_okx, parse_bitget,
    BINANCE_INFO, BINANCE_TICKERS, OKX_INFO, OKX_TICKERS, OKX_OPEN_INTEREST,
    BITGET_INFO, BITGET_TICKERS, optional_microstructure, number, attach_okx_open_interest)
from research_v4.v18_sources import now_ms, CORE

SCHEMA = 'EAR.v18.forward_universe.v1'
HOUR = 3600000
HORIZON = 4 * HOUR
TOLERANCE = 45 * 60000
FRESH = 5 * 60000
MAX_CONTRACTS = 12000  # fail closed on oversized or unexpected source schema
GATE = 'https://api.gateio.ws/api/v4/futures/usdt/'
BINGX = 'https://open-api.bingx.com/openApi/swap/v2/quote/'
BYBIT = 'https://api.bybit.com/v5/market/'
SAFE = re.compile(r'^[A-Z0-9][A-Z0-9_-]{0,48}$')
CLASSES = {'1':'CRYPTO','3':'STOCK','4':'COMMODITY','5':'FX','6':'BOND'}
THRESHOLDS = {'CRYPTO':12.,'STOCK':3.,'COMMODITY':2.,'INDEX':1.5,'FX':.75,'BOND':1.,'ETF':2.5}
GATE_CLASSES = {'stocks':'STOCK','indices':'INDEX','metals':'COMMODITY',
                'commodities':'COMMODITY','forex':'FX','crypto':'CRYPTO'}
BYBIT_CLASSES = {'stock':'STOCK','commodity':'COMMODITY','forex':'FX','ETF':'ETF',
                 'innovation':'STANDARD_PERP','':'STANDARD_PERP'}


def finite(x):
    try:
        return number(x)
    except (ValueError, TypeError, OverflowError):
        return None


def timestamp(v):
    x=finite(v)
    return int(x) if x is not None and x>0 else None


def identity(venue, symbol, meta, typ):
    # Native symbol + listing identity + classification, never display-name aliases.
    # A relisting or metadata-class change cannot settle an older instrument.
    return digest([venue,symbol,meta,typ])


def record(venue, symbol, label, kind, meta, ticker, seen, stamp=None):
    if not isinstance(symbol,str) or not SAFE.fullmatch(symbol):return None
    p=finite(ticker.get('p')); q=finite(ticker.get('q'))
    if p is None or p<=0 or q is None or q<0:return None
    # If venue does not publish per-ticker time, only actual receive clock is
    # known; record its provenance, never invent an exchange timestamp.
    if stamp is not None and not -30000<=seen-stamp<=FRESH:return None
    r={'id':identity(venue,symbol,meta,kind),'venue':venue,'symbol':symbol,
       'display':str(label)[:64],'class':kind,'identity':meta,'seen':seen,
       'exchange_ts':stamp,'price':p,'quote_turnover_24h':q,
       'timestamp_basis':'EXCHANGE_AND_RECEIPT' if stamp is not None else 'RECEIPT_ONLY',
       'low_liquidity':q<100000,'core':str(label).replace('-','').replace('_','') in CORE}
    for key in ('d','funding_rate_pct','spread_bps','range24h_pct','mark_basis_bps','oi_contracts','oi_base'):
        n=finite(ticker.get(key))
        if n is not None:r[key]=n
    if ticker.get('q_proxy'):r['quote_turnover_proxy']=True
    return r


def legacy_venue(venue,get,clock):
    config={'okx':(OKX_INFO,OKX_TICKERS,parse_okx),'bitget':(BITGET_INFO,BITGET_TICKERS,parse_bitget),
            'binance':(BINANCE_INFO,BINANCE_TICKERS,parse_binance)}
    i,t,parse=config[venue]; info=get(i); tick=get(t); seen=clock(); rows=parse(info,tick,seen)
    if venue=='okx':
        # Keep optional OI failure isolated from price coverage.
        try:attach_okx_open_interest({s:{'okx':v} for s,v in rows.items()},get(OKX_OPEN_INTEREST),clock())
        except (ValueError,RuntimeError,TypeError,KeyError,IndexError,OSError):pass
    result={}; meta_rows=info['symbols'] if venue=='binance' else info['data']
    for m in meta_rows:
        if venue=='okx':
            s=m.get('instId','').replace('-USDT-SWAP','USDT'); native=m.get('instId')
            cls=CLASSES.get(str(m.get('instCategory')),'UNCLASSIFIED')
            ident={'native_id':m.get('instIdCode'),'listing_ms':m.get('listTime'),'instCategory':m.get('instCategory')}
        elif venue=='bitget':
            s=native=m.get('symbol'); raw=m.get('isRwa'); cls={'NO':'CRYPTO','YES':'RWA_UNSPECIFIED'}.get(raw,'UNCLASSIFIED')
            ident={'listing_ms':m.get('launchTime') or m.get('openTime'),'isRwa':raw,'base':m.get('baseCoin')}
        else:
            s=native=m.get('symbol');raw=m.get('underlyingType');cls={'COIN':'CRYPTO','EQUITY':'STOCK','INDEX':'INDEX','COMMODITY':'COMMODITY','FOREX':'FX'}.get(raw,'UNCLASSIFIED')
            ident={'listing_ms':m.get('onboardDate'),'underlyingType':raw,'base':m.get('baseAsset')}
        if s not in rows:continue
        r=record(venue,native,s,cls,ident,rows[s],seen,timestamp(rows[s].get('ts')))
        if r:result[r['id']]=r
    return result,len(rows)


def gate_venue(get,clock):
    info=get(GATE+'contracts'); ticks=get(GATE+'tickers'); seen=clock()
    if not isinstance(info,list) or not isinstance(ticks,list):raise ValueError('GATE_SCHEMA')
    active={m['name']:m for m in info if m.get('status')=='trading' and m.get('in_delisting') is False
            and m.get('is_pre_market') is False and m.get('type')=='direct' and m.get('name','').endswith('_USDT')}
    result={}
    for t in ticks:
        s=t.get('contract');m=active.get(s)
        if not m:continue
        raw=m.get('contract_type'); cls=GATE_CLASSES.get(raw,'STANDARD_PERP' if raw=='' else 'UNCLASSIFIED')
        price=finite(t.get('last'))
        if price is None or price<=0:continue
        vals={'p':price,'q':t.get('volume_24h_quote'),'d':t.get('change_percentage'), 'oi_contracts':t.get('total_size'),
              **optional_microstructure(t,price,bid_key='highest_bid',ask_key='lowest_ask',high_key='high_24h',low_key='low_24h',mark_key='mark_price',funding_key='funding_rate')}
        ident={'listing_s':m.get('launch_time') or m.get('create_time'),'contract_type':raw,'multiplier':m.get('quanto_multiplier')}
        r=record('gate',s,s,cls,ident,vals,seen)
        if r:result[r['id']]=r
    return result,len(active)


def bingx_venue(get,clock):
    info=get(BINGX+'contracts');ticks=get(BINGX+'ticker');seen=clock()
    if info.get('code')!=0 or ticks.get('code')!=0 or not isinstance(info.get('data'),list) or not isinstance(ticks.get('data'),list):
        raise ValueError('BINGX_SCHEMA')
    active={m['symbol']:m for m in info['data'] if m.get('status')==1 and m.get('currency')=='USDT'
            and m.get('symbol','').endswith('-USDT') and (timestamp(m.get('launchTime')) or seen)<=seen}
    result={}
    for t in ticks['data']:
        s=t.get('symbol');m=active.get(s)
        if not m:continue
        price=finite(t.get('lastPrice'))
        if price is None or price<=0:continue
        vals={'p':price,'q':t.get('quoteVolume'),'d':t.get('priceChangePercent'),
              **optional_microstructure(t,price,bid_key='bidPrice',ask_key='askPrice',high_key='highPrice',low_key='lowPrice')}
        # The public contract schema does not give a reliable asset class.
        # Do NOT infer it from a friendly display name (AAPL aliases exist).
        ident={'contract_id':m.get('contractId'),'listing_ms':m.get('launchTime'),'asset':m.get('asset')}
        stamp=timestamp(t.get('closeTime'))
        if stamp is None:continue
        r=record('bingx',s,m.get('displayName',s),'UNCLASSIFIED',ident,vals,seen,stamp)
        if r:result[r['id']]=r
    return result,len(active)


def bybit_venue(get,clock):
    active={};cursor=''; seen_cursors=set()
    for _ in range(10):
        url=BYBIT+'instruments-info?category=linear&limit=1000'+('&cursor='+quote(cursor,safe='') if cursor else '')
        raw=get(url)
        if raw.get('retCode')!=0 or raw.get('result',{}).get('category')!='linear':raise ValueError('BYBIT_INSTRUMENTS')
        for m in raw['result']['list']:
            if m.get('contractType')=='LinearPerpetual' and m.get('status')=='Trading' and m.get('quoteCoin')=='USDT' and m.get('settleCoin')=='USDT' and m.get('isPreListing') is False:
                active[m['symbol']]=m
        cursor=raw['result'].get('nextPageCursor') or ''
        if not cursor:break
        if cursor in seen_cursors:raise ValueError('BYBIT_CURSOR_REPEAT')
        seen_cursors.add(cursor)
    else:raise ValueError('BYBIT_PAGINATION_LIMIT')
    ticks=get(BYBIT+'tickers?category=linear');seen=clock();stamp=timestamp(ticks.get('time'))
    if ticks.get('retCode')!=0 or ticks.get('result',{}).get('category')!='linear' or stamp is None:raise ValueError('BYBIT_TICKERS')
    result={}
    for t in ticks['result']['list']:
        s=t.get('symbol');m=active.get(s)
        if not m:continue
        price=finite(t.get('lastPrice'));change=finite(t.get('price24hPcnt'))
        if price is None or price<=0:continue
        vals={'p':price,'q':t.get('turnover24h'),'d':change*100 if change is not None else None,'oi_base':t.get('openInterest'),
              **optional_microstructure(t,price,bid_key='bid1Price',ask_key='ask1Price',high_key='highPrice24h',low_key='lowPrice24h',mark_key='markPrice',funding_key='fundingRate')}
        raw=m.get('symbolType');cls=BYBIT_CLASSES.get(raw,'UNCLASSIFIED')
        ident={'listing_ms':m.get('launchTime'),'symbol_type':raw,'base':m.get('baseCoin'),'underlying':m.get('underlyingTicker')}
        r=record('bybit',s,s,cls,ident,vals,seen,stamp)
        if r:result[r['id']]=r
    return result,len(active)


def collect(get=public_json,clock=now_ms):
    functions={v:lambda get,clock,v=v:legacy_venue(v,get,clock) for v in ('okx','bitget','binance')}
    functions.update(gate=gate_venue,bingx=bingx_venue,bybit=bybit_venue)
    def one(item):
        v,fn=item
        try:
            rows,active=fn(get,clock)
            if not rows:raise ValueError('NO_FRESH_TICKERS')
            return v,rows,{'status':'OBSERVED','observed':len(rows),'active_or_ticker_eligible':active}
        except (ValueError,RuntimeError,TypeError,KeyError,IndexError,OSError,AttributeError,OverflowError) as exc:
            return v,{}, {'status':'SOURCE_UNAVAILABLE','error':type(exc).__name__}
    result={};sources={}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for v,rows,status in pool.map(one,functions.items()):
            result.update(rows);sources[v]=status
    if len(result)>MAX_CONTRACTS:raise ValueError('UNIVERSE_CAPACITY_EXCEEDED')
    return result,sources


def features(current, previous):
    """Only genuinely observed data; absent features are not false signals."""
    f={}; d=current.get('d');fund=current.get('funding_rate_pct');spread=current.get('spread_bps')
    if d is not None:f['quiet_24h']=abs(d)<=3
    if fund is not None:f['negative_funding']=fund<0;f['positive_funding']=fund>0
    if spread is not None:f['tight_spread']=0<=spread<=10
    if previous and 0<current['seen']-previous['seen']<=2*HOUR:
        change=100*(current['price']/previous['price']-1)
        f['quiet_since_last']=abs(change)<=3
        q=previous['quote_turnover_24h']
        if q>0 and not current.get('quote_turnover_proxy') and not previous.get('quote_turnover_proxy'):
            f['turnover_rise_quiet']=current['quote_turnover_24h']/q>=1.2 and abs(change)<=3
        for k in ('oi_contracts','oi_base'):
            oi=previous.get(k);new=current.get(k)
            if oi is not None and oi>0 and new is not None:
                f['oi_rise_quiet']=new/oi>=1.1 and abs(change)<=3;break
    return f


def state_read(path):
    if not path.exists():return {'schema':SCHEMA,'sequence':0,'last_seen':0,'previous_sha':'GENESIS','pending':{},'last':{},'metrics':{},'coverage_totals':{}}
    x=json.loads(path.read_text());sig=x.pop('sha256',None)
    if x.get('schema')!=SCHEMA or digest(x)!=sig:raise ValueError('FORWARD_UNIVERSE_STATE_INTEGRITY')
    x['sha256']=sig
    return x


def settle_and_observe(old, current, sources, asof):
    if asof<=old['last_seen']:raise ValueError('FORWARD_UNIVERSE_CLOCK_REWIND')
    if any(r['seen']>asof for r in current.values()):raise ValueError('FUTURE_RECEIPT')
    pending=dict(old['pending']);last=old['last'];metrics=json.loads(canonical(old['metrics']));outcomes=[];started=[]
    for cid,anchor in list(pending.items()):
        after=asof-anchor['seen']
        if after<HORIZON:continue
        new=current.get(cid)
        delay=new['seen']-anchor['seen'] if new else None
        # Censor rather than use a stale/missing quote or extend window arbitrarily.
        if new is not None and HORIZON<=delay<=HORIZON+TOLERANCE:
            ret=100*(new['price']/anchor['price']-1)
            status='CENSORED_POSSIBLE_REBASE' if abs(ret)>75 else 'COMPLETE_ENDPOINT_MARK_ONLY'
            threshold=THRESHOLDS.get(anchor['class'],12.)
            label='UP' if ret>=threshold else 'DOWN' if ret<=-threshold else 'NONE'
        elif after>HORIZON+TOLERANCE:
            status='CENSORED_NO_TIMELY_SAME_CONTRACT_QUOTE';ret=None;label=None
        else:continue
        out={'id':cid,'venue':anchor['venue'],'symbol':anchor['symbol'],'class':anchor['class'],
             'anchor_seen':anchor['seen'],'anchor_price':anchor['price'],'features':anchor['features'],
             'status':status,'quote_seen':new['seen'] if new and status=='COMPLETE_ENDPOINT_MARK_ONLY' else None,
             'quote_price':new['price'] if new and status=='COMPLETE_ENDPOINT_MARK_ONLY' else None,
             'return_pct':round(ret,8) if status=='COMPLETE_ENDPOINT_MARK_ONLY' else None,
             'label':label if status=='COMPLETE_ENDPOINT_MARK_ONLY' else None,'trade_authorized':False}
        outcomes.append(out); del pending[cid]
        # Separate venue and underlying class to prevent duplicate correlated
        # contracts or unknown stock instruments inflating crypto results.
        k=anchor['venue']+'|'+anchor['class']; m=metrics.setdefault(k,{'outcomes':{},'features':{}})
        m['outcomes'][status]=m['outcomes'].get(status,0)+1
        if status=='COMPLETE_ENDPOINT_MARK_ONLY':
            m['outcomes'][label]=m['outcomes'].get(label,0)+1
            for f,value in anchor['features'].items():
                cells=m['features'].setdefault(f,{})
                cell=('true_' if value else 'false_')+label;cells[cell]=cells.get(cell,0)+1
    for cid,r in current.items():
        if cid not in pending:
            pending[cid]={k:r[k] for k in ('venue','symbol','class','seen','price')};pending[cid]['features']=features(r,last.get(cid));started.append(cid)
    coverage=dict(old['coverage_totals'])
    for venue in sources:
        v=coverage.setdefault(venue,{'observed_runs':0,'unavailable_runs':0})
        field='observed_runs' if sources[venue]['status']=='OBSERVED' else 'unavailable_runs';v[field]+=1
    state={'schema':SCHEMA,'sequence':old['sequence']+1,'last_seen':asof,
           'previous_sha':old.get('sha256','GENESIS'),'pending':pending,'last':current,'metrics':metrics,'coverage_totals':coverage}
    state['sha256']=digest(state)
    priorities=[]
    for cid,r in current.items():
        if r['class']!='CRYPTO' or r['core'] or r['low_liquidity']:continue
        f=features(r,last.get(cid))
        # An increase in rolling turnover or OI while current price stays quiet
        # is an EXPERIMENT scheduling hint, never a signal or validated predictor.
        if f.get('quiet_since_last') and (f.get('turnover_rise_quiet') or f.get('oi_rise_quiet')):
            sym=r['display'].replace('-','').replace('_','')
            if re.fullmatch(r'[A-Z0-9]{2,25}USDT',sym):
                priorities.append({'symbol':sym,'venue':r['venue'],'seen':r['seen'],'features':f})
    priorities.sort(key=lambda r:(not r['features'].get('oi_rise_quiet'),r['symbol'],r['venue']))
    report={'schema':SCHEMA,'asof_ms':asof,'sequence':state['sequence'],'observed_contracts':len(current),
            'new_forward_anchors':len(started),'pending':len(pending),'settled_this_run':len(outcomes),
            'settlement_statuses':dict(Counter(x['status'] for x in outcomes)),
            'asset_classes':dict(Counter(x['class'] for x in current.values())),
            'distinct_native_venue_symbols':len({(x['venue'],x['symbol']) for x in current.values()}),
            'distinct_normalized_symbol_strings_not_unique_assets':len({x['display'].replace('-','').replace('_','') for x in current.values()}),
            'low_liquidity_contracts':sum(x['low_liquidity'] for x in current.values()),
            'timestamp_bases':dict(Counter(x['timestamp_basis'] for x in current.values())),
            'sources':sources,'coverage_totals':coverage,'cumulative_by_venue_class':metrics,'deep_research_priority':priorities[:128],
            'event_thresholds_pct':{**THRESHOLDS,'OTHER_OR_UNCLASSIFIED':12.},
            'history_required':False,'study':'SAME_CONTRACT_4H_ENDPOINT_MARK_NOT_OHLC_OR_FILL',
            'state_sha256':state['sha256'],'previous_state_sha256':state['previous_sha'],
            'trade_authorized':False,'paper_approved':False,'official_gate':'NOT_RUN'}
    return state,report,outcomes


def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    root=Path(a.state);out=Path(a.out);root.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    path=root/'state.json';old=state_read(path)
    current,sources=collect();asof=now_ms()
    state,report,outcomes=settle_and_observe(old,current,sources,asof)
    # Even all-source outages are sealed so missed observations stay visible.
    # Last complete per-venue evidence remains in Git history, never substituted.
    new=path.with_suffix('.tmp');new.write_text(canonical(state)+'\n');verified=state_read(new)
    if verified['sha256']!=state['sha256']:raise ValueError('FORWARD_UNIVERSE_WRITE_INTEGRITY')
    new.replace(path)
    (root/'latest.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    (root/'outcomes.jsonl').write_text(''.join(canonical(r)+'\n' for r in outcomes))
    (out/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print('V18_FORWARD_UNIVERSE',report['observed_contracts'],report['asset_classes'],report['sources'])

if __name__=='__main__':main()
