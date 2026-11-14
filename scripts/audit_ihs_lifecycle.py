"""Independent causal rule checks, fee reconciliation and setup-level attribution."""
import math
from datetime import datetime
from collections import Counter
from backtest_ihs_lifecycle import OUT,CASES,load,rows,dump
from audit_pattern_trade_paths import history,save

def key(pid):return pid.split(':',1)[-1]
def near(a,b):assert math.isclose(a,b,abs_tol=1e-7),(a,b)
def economic_neck(p,h,date):
    day=lambda d:datetime.strptime(d,'%Y%m%d').toordinal()
    scale=next(b.factor for b in h if b.date==p['date'])
    a,b=float(p['ihs_peak1_price']),float(p['ihs_peak2_price'])
    return (a+(b-a)*(day(date)-day(p['ihs_peak1_date']))/(day(p['ihs_peak2_date'])-day(p['ihs_peak1_date'])))*scale
def economic_atr(h,date):
    known=[b for b in h if b.date<date][-15:];assert len(known)==15
    return sum(max(b.high*b.factor-b.low*b.factor,abs(b.high*b.factor-a.close*a.factor),abs(b.low*b.factor-a.close*a.factor)) for a,b in zip(known,known[1:]))/14

def main():
    assert load(OUT/'status.json')['cases']==8
    sources={key(p['setup_id']):p for p in load(OUT/'plans.json')}
    names=[f'{case}_cost{cost}' for case in CASES for cost in (1,2)]
    data={n:{k:rows(OUT/n/(k+'.csv')) for k in ('entry_audit','trades','decisions')} for n in names}
    hist=history({p['symbol'] for p in sources.values()});records=[];verification={};summaries={}
    for name,d in data.items():
        cfg=load(OUT/name/'config.json');costs=cfg['execution'];summary=load(OUT/name/'summary.json');events=d['decisions']
        fills={key(a['setup_id']):a for a in d['entry_audit'] if a['execution_reason']=='filled'}
        ts={key(t['setup_id']):t for t in d['trades']};intents={key(e['setup_id']):e for e in events if e['event']=='entry_intent'}
        retries=[e for e in events if e['event']=='entry_intent' and e.get('retest_confirmed_at')]
        failures=[e for e in events if e['event']=='ihs_breakout_failure_confirmed']
        activations=[e for e in events if e['event']=='profit_protection_activated']
        raises=[e for e in events if e['event']=='main_protection_raised' and e.get('source')=='profit_activated_daily_higher_low']
        for e in retries:
            pid=key(e['setup_id']);p=sources[pid];h=hist[e['symbol']];by={b.date:b for b in h};scale=by[p['date']].factor
            after=[b for b in h if p['date']<b.date<=e['date']];assert 2<=len(after)<=10
            assert e['original_signal_date']==p['date'] and e['retest_touch_date']<e['retest_confirmed_at']==e['date']
            atr=float(p['ihs_entry_atr'])*scale;right=float(p['ihs_right_low'])*scale;target=float(p['target'])*scale
            assert min(b.low*b.factor for b in after)>right and max(b.high*b.factor for b in after)<target
            touch=by[e['retest_touch_date']];assert touch.low*touch.factor<=economic_neck(p,h,touch.date)+.25*atr
            assert all(b.low*b.factor>economic_neck(p,h,b.date)+.25*atr for b in after if b.date<touch.date)
            b=after[-1];assert b.close*b.factor>max(economic_neck(p,h,b.date)+.1*atr,b.open*b.factor,after[-2].close*after[-2].factor)
            near(float(e['stop'])*b.factor,float(p['stop'])*scale);near(float(e['target'])*b.factor,target)
        if name.startswith('retest'):
            assert len(retries)==len({e['setup_id'] for e in retries})
            registered=[e for e in events if e['event']=='retest_registered'];assert len(registered)==1713
            for e in [e for e in events if e['event']=='retest_cancelled']:
                p=sources[key(e['setup_id'])];h=hist[e['symbol']];factor=next(b.factor for b in h if b.date==p['date']);after=[b for b in h if p['date']<b.date<=e['date']]
                expected='expired_10_stock_bars' if len(after)>10 else 'right_shoulder_broken' if min(b.low*b.factor for b in after)<=float(p['ihs_right_low'])*factor else 'original_target_touched' if max(b.high*b.factor for b in after)>=float(p['target'])*factor else None
                assert expected==e['reason']
        for e in failures:
            pid=key(e['setup_id']);a=fills[pid];p=sources[pid];h=hist[e['symbol']];held=[b for b in h if a['date']<=b.date<=e['date']]
            assert len(held)>=2 and held[-2].date==e['first_failure_date'] and held[-1].date==e['second_failure_date']
            for b,field in zip(held[-2:],('first_level','second_level')):
                level=economic_neck(p,h,b.date)-.5*economic_atr(h,b.date);near(level,float(e[field]));assert b.close*b.factor<level
        for e in activations:
            pid=key(e['setup_id']);a=fills[pid];h=hist[e['symbol']];entry=next(b for b in h if b.date==a['date']);b=next(b for b in h if b.date==e['date'])
            q=float(a['filled_quantity']);fill=float(a['fill']);fee=float(a['entry_fee']);risk=float(a['expected_loss'])
            marked=(b.close*b.factor/entry.factor-fill)*q-fee;near(marked,float(e['marked_profit']));near(risk,float(e['initial_risk']));assert marked>=risk-1e-7
            assert all((x.close*x.factor/entry.factor-fill)*q-fee<risk+1e-7 for x in h if a['date']<=x.date<e['date'])
        for e in raises:
            pid=key(e['setup_id']);a=fills[pid];h=hist[e['symbol']];local={b.date:i for i,b in enumerate(h)};i,j=local[e['formed']],local[e['confirmed']]
            assert j==i+2 and e['date']==e['confirmed'] and h[i-2].date>a['date']
            activation=next(v for v in activations if key(v['setup_id'])==pid);assert e['activation_date']==activation['date']<=e['formed']
            low=h[i].low*h[i].factor;assert all(b.low*b.factor>low for b in h[i-2:i]+h[i+1:i+3])
            previous=[k for k in range(local[a['date']]+3,i) if h[k].low*h[k].factor<min(b.low*b.factor for b in h[k-2:k]+h[k+1:k+3])]
            prev=h[previous[-1]].low*h[previous[-1]].factor if previous else h[local[a['date']]].low*h[local[a['date']]].factor
            near(prev,float(e['previous_daily_low']));assert low>prev
            atr=economic_atr(h,e['date']);near(atr,float(e['atr_economic']));near(low-.5*atr,float(e['new']))
            assert float(e['new'])>float(a['stop'])*h[local[a['date']]].factor and float(e['new'])<h[j].close*h[j].factor
            if e.get('old'):assert float(e['new'])>float(e['old'])
            assert e['effective']=='next_session'
        own=[]
        for pid,a in fills.items():
            p=sources[pid];h=hist[a['symbol']];by={b.date:b for b in h};entry=by[a['date']];t=ts.get(pid);end=t['exit_date'] if t else '20260930'
            q=float(a['filled_quantity']);fill=float(a['fill']);fee=float(a['entry_fee']);risk=float(a['expected_loss'])
            near(fill,entry.open*(1+costs['slippage']));previous=[b for b in h if b.date<a['date']][-1]
            assert entry.open<=previous.close*previous.factor/entry.factor+1e-8
            assert float(a['net_rr'])>3 and float(a['expected_upside'])>.05 and a['signal_date']<a['date']
            near(float(a['stop'])*entry.factor,float(p['stop'])*by[p['date']].factor)
            if t:
                qty=q*by[end].factor/entry.factor;value=qty*float(t['exit'])
                pnl=value-fill*q-fee-max(costs['minimum_commission'],value*costs['commission_rate'])-value*costs['sell_tax_after_20230828'];near(pnl,float(t['pnl']));near(qty,float(t['quantity']))
                if t['reason'] in ('dynamic_support_daily_break','ihs_confirmed_breakout_failure'):
                    ev=[e for e in events if key(e['setup_id'])==pid and e['event']==('dynamic_support_daily_break' if t['reason']=='dynamic_support_daily_break' else 'ihs_breakout_failure_confirmed')][-1]
                    assert ev['date']<end
                    near(float(t['exit']),max(by[end].down_limit,by[end].open*(1-costs['slippage'])))
                    if t['reason']=='dynamic_support_daily_break':
                        known=[e for e in events if key(e['setup_id'])==pid and e['event']=='main_protection_raised' and e['date']<ev['date']]
                        assert known;near(float(known[-1]['new']),float(ev['economic_protection']));assert by[ev['date']].close*by[ev['date']].factor<float(ev['economic_protection'])
            else:pnl=(by[end].close*by[end].factor/entry.factor-fill)*q-fee
            held=[b for b in h if a['date']<=b.date<=end and (not t or b.date<end)]
            peak=max(b.close*b.factor/entry.factor for b in held);value=peak*(1-costs['slippage'])*q
            peaknet=value-fill*q-fee-max(costs['minimum_commission'],value*costs['commission_rate'])-value*costs['sell_tax_after_20230828']
            r=dict(case=name,canonical_id=pid,setup_id=a['setup_id'],symbol=a['symbol'],original_signal=p['date'],signal=a['signal_date'],entry=a['date'],exit=t['exit_date'] if t else '',closed=bool(t),pnl=pnl,quantity=q,fill=fill,stop=float(a['stop']),target=float(a['target']),reason=t['reason'] if t else 'open',peak_close_gain=peak/fill-1,peak_net_R=peaknet/risk,final_R=pnl/risk)
            records.append(r);own.append(r)
        assert len(own)==summary['filled_buys'];near(sum(r['pnl'] for r in own),summary['final_equity']-1e6)
        losses=[r for r in own if r['closed'] and r['pnl']<0]
        summaries[name]=dict(buys=len(own),losses=len(losses),loss_pnl=sum(r['pnl'] for r in losses),gain5_then_loss=sum(r['peak_close_gain']>=.05 for r in losses),peak1R_then_loss=sum(r['peak_net_R']>=1 for r in losses),peak2R_then_loss=sum(r['peak_net_R']>=2 for r in losses),retest_cancellations=dict(Counter(e['reason'] for e in events if e['event']=='retest_cancelled')),retest_audit_reasons=dict(Counter(a['risk_reason'] or a['execution_reason'] for a in d['entry_audit'])) if name.startswith('retest') else {})
        verification[name]=dict(filled_buys=len(own),retest_signals=len(retries),failure_signals=len(failures),profit_activations=len(activations),profit_raises=len(raises),passed=True)
    pairs=[];attribution=[]
    for case in ('retest','failure','profit'):
        for cost in (1,2):
            name=f'{case}_cost{cost}';old={r['canonical_id']:r for r in records if r['case']==f'baseline_cost{cost}'};new={r['canonical_id']:r for r in records if r['case']==name}
            for pid in old.keys()|new.keys():
                a,b=old.get(pid),new.get(pid);ref=a or b
                rejected=[x for x in data[name]['entry_audit'] if key(x['setup_id'])==pid and x['execution_reason']!='filled']
                cancelled=[e['reason'] for e in data[name]['decisions'] if key(e['setup_id'])==pid and e['event']=='retest_cancelled']
                reasons={x['risk_reason'] or x['execution_reason'] for x in rejected}|set(cancelled)
                if not b and not reasons:
                    signals=[e['date'] for e in data[name]['decisions'] if key(e['setup_id'])==pid and e['event']=='entry_intent']
                    occupants=[r for r in records if r['case']==name and r['symbol']==ref['symbol'] and any(r['entry']<=date<(r['exit'] or '99999999') for date in signals)]
                    if occupants:reasons.add('already_holding_symbol_at_signal')
                    elif name.startswith('retest') and not signals:reasons.add('pending_retest_at_period_end')
                why=';'.join(sorted(reasons)) if not b else ''
                pairs.append(dict(case=name,canonical_id=pid,symbol=ref['symbol'],category='shared' if a and b else 'removed' if a else 'added',old_entry=a['entry'] if a else '',new_entry=b['entry'] if b else '',old_exit=a['exit'] if a else '',new_exit=b['exit'] if b else '',old_pnl=a['pnl'] if a else 0,new_pnl=b['pnl'] if b else 0,delta=(b['pnl'] if b else 0)-(a['pnl'] if a else 0),same_dates=bool(a and b and a['entry']==b['entry'] and a['exit']==b['exit']),old_reason=a['reason'] if a else '',new_reason=b['reason'] if b else '',missing_reasons=why))
            p=[x for x in pairs if x['case']==name];top=sorted(old.values(),key=lambda r:r['pnl'],reverse=True)[:5]
            attribution.append(dict(case=name,removed=sum(x['category']=='removed' for x in p),added=sum(x['category']=='added' for x in p),shared_delta=sum(x['delta'] for x in p if x['category']=='shared'),removed_delta=sum(x['delta'] for x in p if x['category']=='removed'),added_delta=sum(x['delta'] for x in p if x['category']=='added'),top5_retained=sum(r['canonical_id'] in new for r in top),top5_original_pnl=sum(r['pnl'] for r in top),top5_candidate_pnl=sum(new[r['canonical_id']]['pnl'] for r in top if r['canonical_id'] in new)))
            near(sum(x['delta'] for x in p),load(OUT/name/'summary.json')['final_equity']-load(OUT/f'baseline_cost{cost}'/'summary.json')['final_equity'])
    save(OUT/'trade-paths.csv',records);save(OUT/'paired-trades.csv',pairs);save(OUT/'attribution.csv',attribution);dump(OUT/'audit-summary.json',summaries);dump(OUT/'verification.json',verification)
    print('AUDIT COMPLETE',sum(v['filled_buys'] for v in verification.values()),'buys',verification)

if __name__=='__main__':main()
