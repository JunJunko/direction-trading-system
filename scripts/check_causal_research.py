import sys,csv,json,time
from pathlib import Path
sys.path.insert(0,'src');sys.path.insert(0,'scripts')
from trading_system.domain import Bar
from trading_system.analysis import adjusted
from trading_system.strategies.qualified_w_retest import QualifiedWRetest
from study_causal_events import ExactPrefixAdjustment
import trading_system.strategies.w_retest as rm
import trading_system.strategies.direct_double_bottom as dm

def main():
    root=Path('runs/20261024-causal-target-verified')
    with (root/'paired_trades.csv').open(encoding='utf-8-sig') as f:trades=list(csv.DictReader(f))
    old={r['trade_id']:r for r in trades if r['arm']=='C0'}
    for r in trades:
        if r['symbol'] in ('603031.SH','603272.SH'):assert r['exit_date']>=old[r['trade_id']]['exit_date']
        if r['symbol']=='002451.SZ' and r['entry_date']=='20251103' and r['arm']!='C0':assert r['decisive_break_at']=='20251104'
    bysym={s:[] for s in ('603031.SH','603272.SH','002451.SZ')}
    with Path('runs/20261024-qualified-w-cohort/bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in bysym:bysym[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    params=json.loads(Path('configs/experiments/double_bottom_v5_19_qualified_w_structure.json').read_text(encoding='utf-8'))['strategies'][0]['params']
    checks={}
    for symbol,bars in bysym.items():
        bars.sort(key=lambda b:b.date);reference=None;times=[]
        for cached in (False,True):
            cache=ExactPrefixAdjustment();rm.adjusted=cache if cached else adjusted;dm.adjusted=cache if cached else adjusted
            s=QualifiedWRetest('check',params);h=[];tape=[];start=time.time()
            for b in bars:
                h.append(b)
                if cached:assert cache(h)==adjusted(h)
                tape.append(s.on_close(h,set()))
            times.append(time.time()-start)
            if cached:assert tape==reference,symbol
            else:reference=tape
        checks[symbol]=dict(all_prefix_bars_exact=True,all_detector_outputs_exact=True,seconds=times)
    rm.adjusted=adjusted;dm.adjusted=adjusted
    (root/'regression.json').write_text(json.dumps(dict(early_exit_removed=True,continuation_002451_preserved=True,cache_equivalence=checks),indent=2),encoding='utf-8')
    print(json.dumps(checks),flush=True)
if __name__=='__main__':main()
