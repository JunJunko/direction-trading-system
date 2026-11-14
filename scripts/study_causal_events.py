"""All-stock causal detector scan; descriptive events, not trading returns."""
import sys,csv,json,hashlib,time
from pathlib import Path
from collections import defaultdict,Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
sys.path.insert(0,'src')
from trading_system.domain import Bar
from trading_system.strategies.qualified_w_retest import QualifiedWRetest
from trading_system.strategies.causal_target_w import BaselineClockDecision
from trading_system.target_migration import PositionContext,State,atr_pre,RESEARCH_PARAMETERS
from trading_system.analysis import adjusted
from trading_system.data import save_csv
import trading_system.strategies.w_retest as retest_module
import trading_system.strategies.direct_double_bottom as direct_module

ROOT=Path('runs/20261010-104630-mainboard-double_bottom_v5_11_2-structure')
OUT=Path(sys.argv[1] if len(sys.argv)>1 else 'runs/20261024-causal-events-final')

class ExactPrefixAdjustment:
    """Worker-local memoization, identical Bar arithmetic; rebuild on factor change."""
    def __init__(self):self.raw=None;self.anchor=None;self.values=[]
    def __call__(self,history):
        anchor=history[-1].factor
        if self.raw is not history or self.anchor!=anchor or len(history)<len(self.values):
            self.values=adjusted(history);self.raw=history;self.anchor=anchor
        else:
            for b in history[len(self.values):]:
                self.values.append(Bar(b.symbol,b.date,b.open*b.factor/anchor,b.high*b.factor/anchor,
                    b.low*b.factor/anchor,b.close*b.factor/anchor,b.volume,b.factor,b.up_limit,b.down_limit))
        return self.values

def scan(item):
    symbol,bars,params,eligible,extended=item;s=QualifiedWRetest('event_W',params);history=[];seeds=[];plans=[]
    cache=ExactPrefixAdjustment();retest_module.adjusted=cache;direct_module.adjusted=cache
    for i,b in enumerate(bars):
        history.append(b);ints,events=s.on_close(history,set())
        if b.date<'20240101' or (not extended and b.date not in eligible):continue
        plans.extend(dict(signal_date=x.date,setup_id=x.setup_id) for x in ints)
        seeds.extend((i,e) for e in events if e['event']=='w_retest_registered')
    result=[]
    for start,e in seeds:
        # All forward calculations are outcome labels; detector never sees them.
        ctx=PositionContext(e['setup_id'],start,bars[start].close,0,e['w_floor'],e['w_floor'],e['w_neckline'],e['w_target'])
        decision=BaselineClockDecision('dynamic',.01);touch=None;candidate=None;accepted=None;failed=None;invalid=None;decision_at=None
        expiry=min(start+60,len(bars)-1)
        for i in range(start+1,expiry+1):
            prefix=adjusted(bars[:i+1]);b=prefix[-1];scale=e['factor']/b.factor
            ctx.measured_target=e['w_target']*scale
            if b.close<e['w_floor']*scale:
                invalid=i
                if ctx.state==State.BREAKOUT_CANDIDATE:failed=i
                break
            if touch is None and b.high>=ctx.measured_target:touch=i
            if decision_at is None and b.close>=ctx.measured_target:decision_at=i
            before=ctx.state;reason=decision.close(ctx,i,b,atr_pre(prefix))
            if reason=='breakout_candidate':candidate=i
            if reason=='acceptance_confirmed':accepted=i;break
            if ctx.state==State.EXIT_PENDING:
                if before==State.BREAKOUT_CANDIDATE:failed=i
                break
        anchor=candidate if candidate is not None else touch
        full=anchor is not None and anchor+20<len(bars)
        future=bars[anchor+1:anchor+21] if anchor is not None else []
        price=bars[anchor].close*bars[anchor].factor if anchor is not None else None
        target=e['w_target']*e['factor']
        def date(index):return bars[index].date if index is not None else None
        result.append(dict(symbol=symbol,setup_id=e['setup_id'],formed_at=e['w_known_at'],target=e['w_target'],
            entry_eligibility='eligible' if e['w_known_at'] in eligible else 'unknown_before_20251009' if e['w_known_at']<'20251009' else 'ineligible',
            touch_at=date(touch),baseline_decision_at=date(decision_at),candidate_at=date(candidate),acceptance_at=date(accepted),
            candidate_failed_at=date(failed),structure_invalid_at=date(invalid),
            target_window_observed=expiry-start,target_window_censored=expiry-start<60 and touch is None and invalid is None,
            forward20_complete=full,forward20_observations=len(future),
            forward20_return=(future[-1].close*future[-1].factor/price-1) if full else None,
            forward20_mfe=max(b.high*b.factor/price-1 for b in future) if full else None,
            forward20_mae=min(b.low*b.factor/price-1 for b in future) if full else None,
            forward20_close_above_target=(future[-1].close*future[-1].factor>target) if full else None,
            forward20_failure_below_target=any(b.close*b.factor<target for b in future) if full else None))
    return symbol,len(bars),result,plans

def main():
    extended='--long-history' in sys.argv
    OUT.mkdir();params=json.loads(Path('configs/experiments/double_bottom_v5_19_qualified_w_structure.json').read_text(encoding='utf-8'))['strategies'][0]['params']
    u=json.loads((ROOT/'universe.json').read_text(encoding='utf-8'));stocks={r['ts_code']:r for r in u['stocks']}
    dump=lambda name,data:(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    dump('protocol.json',dict(detector='unchanged QualifiedWRetest',parameters=params,target_parameters=RESEARCH_PARAMETERS,
        observation_start='20240101',end='20260930',warmup_start='20230103',target_horizon=60,forward_horizon=20,
        population='500 symbols selected by lowest SHA256(symbol), no outcome selection; eligibility tagged, not filtered' if extended else 'all 3214 input symbols, dated eligibility at structure registration',independent_holdout=False,
        scope='structure-event study; no actual entry requirement; overlapping W events retained and identified',
        tuning=False,continuation='20th subsequent available bar close above T0',failure='any subsequent 20-bar close below T0',
        caveat='forward horizon counts available stock bars; suspended days are not fabricated; historical ST eligibility unavailable before 20251009'))
    selected=set(sorted(stocks,key=lambda symbol:hashlib.sha256(symbol.encode()).hexdigest())[:500]) if extended else set(stocks)
    grouped=defaultdict(list)
    with (ROOT/'bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in selected:grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    tasks=[]
    for symbol,bars in sorted(grouped.items()):
        stock=stocks[symbol];bars.sort(key=lambda b:b.date)
        eligible={d for d,st in u['st_by_date'].items() if d>=stock['list_date'] and (not stock.get('delist_date') or d<stock['delist_date']) and symbol not in st}
        tasks.append((symbol,bars,params,eligible,extended))
    dump('symbols.json',sorted(grouped))
    print('loaded '+str(len(tasks))+' symbols',flush=True);events=[];plans=[];start=time.time()
    with ProcessPoolExecutor(max_workers=8) as pool:
        pending=[pool.submit(scan,t) for t in tasks]
        for n,f in enumerate(as_completed(pending),1):
            symbol,count,ev,ps=f.result();events.extend(ev);plans.extend(ps)
            if n%100==0:
                dump('progress.json',dict(done=n,total=len(tasks),events=len(events),seconds=round(time.time()-start)))
                print(json.dumps(dict(done=n,total=len(tasks),events=len(events),seconds=round(time.time()-start))),flush=True)
    events.sort(key=lambda x:(x['formed_at'],x['symbol'],x['setup_id']))
    save_csv(OUT/'events.csv',events);save_csv(OUT/'entry_signal_inventory.csv',plans)
    def stats(es):
        touched=[e for e in es if e['touch_at']];candidates=[e for e in es if e['candidate_at']];complete=[e for e in candidates if e['forward20_complete']]
        return dict(structures=len(es),symbols=len({e['symbol'] for e in es}),touches=len(touched),candidates=len(candidates),
            accepted=sum(bool(e['acceptance_at']) for e in es),candidate_failed=sum(bool(e['candidate_failed_at']) for e in es),
            invalidated=sum(bool(e['structure_invalid_at']) for e in es),target_window_censored=sum(e['target_window_censored'] for e in es),
            candidates_complete20=len(complete),candidates_censored20=len(candidates)-len(complete),
            continued20=sum(e['forward20_close_above_target'] for e in complete),failed_below_target20=sum(e['forward20_failure_below_target'] for e in complete),
            mean_candidate_forward20=sum(e['forward20_return'] for e in complete)/len(complete) if complete else None)
    dump('summary.json',dict(all=stats(events),years={y:stats([e for e in events if e['formed_at'].startswith(y)]) for y in ('2024','2025','2026')},
        eligibility_groups={key:stats([e for e in events if e['entry_eligibility']==key]) for key in sorted({e['entry_eligibility'] for e in events})},
        input_symbols=len(tasks),input_bars=sum(len(b) for b in grouped.values()),entry_signals=len(plans),
        input_sha256=hashlib.sha256((ROOT/'bars.csv').read_bytes()).hexdigest()))
    print(json.dumps(stats(events)),flush=True)
if __name__=='__main__':main()
