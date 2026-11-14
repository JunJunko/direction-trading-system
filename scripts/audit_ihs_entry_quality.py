"""Independent pre-entry feature checks and complete account trade attribution."""
import math
from backtest_ihs_entry_quality import OUT,RULES,load,rows,dump
from audit_pattern_trade_paths import history,save

def key(pid):return pid.split(':',1)[1]

def features(plan,h,date):
    b=next(b for b in h if b.date==date);known=[x for x in h if x.date<date];signal=[x for x in known if x.date<=plan['date']]
    assert len(signal)>=25 and signal[-1].date==plan['date']
    s=signal[-1];v=sum(x.volume for x in signal[-21:-1])/20
    values=[x.close*x.factor for x in signal]
    tr=[max(y.high*y.factor-y.low*y.factor,abs(y.high*y.factor-x.close*x.factor),abs(y.low*y.factor-x.close*x.factor)) for x,y in zip(known[-15:-1],known[-14:])]
    assert len(tr)==14
    return dict(close_location=(s.close-s.low)/(s.high-s.low) if s.high>s.low else 0,volume_ratio=s.volume/v if v else 0,
        ma20_change=sum(values[-20:])/sum(values[-25:-5])-1,
        gap_atr=(b.open*b.factor-known[-1].close*known[-1].factor)/(sum(tr)/14),
        gap_pct=b.open*b.factor/(known[-1].close*known[-1].factor)-1,signal_known_at=s.date,atr_known_at=known[-1].date)

def passes(rule,f):
    return {'baseline':True,'solid_close':f['close_location']>=.5,'volume_confirmed':f['volume_ratio']>=1,'rising_ma20':f['ma20_change']>=0,'limited_gap_down':f['gap_atr']>=-.5}[rule]

def main():
    assert load(OUT/'status.json')['cases']==10
    names=[f'{r}_cost{c}' for r in RULES for c in (1,2)]
    data={n:{k:rows(OUT/n/(k+'.csv')) for k in ('entry_audit','trades','decisions')} for n in names}
    hist=history({a['symbol'] for d in data.values() for a in d['entry_audit']});records=[];verification={};plans={}
    for name,d in data.items():
        cfg=load(OUT/name/'config.json');summary=load(OUT/name/'summary.json');rule=cfg.get('ihs_entry_quality_filter','baseline')
        ps={key(p['setup_id']):p for p in d['decisions'] if p['event']=='entry_intent'};plans[name]=ps
        ts={key(t['setup_id']):t for t in d['trades']};checked=0;own=[]
        for a in d['entry_audit']:
            if not a.get('quality_rule'):continue
            pid=key(a['setup_id']);h=hist[a['symbol']];f=features(ps[pid],h,a['date']);by={b.date:b for b in h};b=by[a['date']]
            assert math.isclose(f['gap_pct'],float(a['quality_value']),abs_tol=1e-8)
            assert (f['gap_pct']<=1e-12)==(a['quality_pass']=='True')
            if rule!='baseline':
                for k in ('close_location','volume_ratio','ma20_change','gap_atr'):
                    assert math.isclose(f[k],float(a['ihs_quality_'+k]),abs_tol=1e-8),(name,pid,k)
                for k in ('signal_known_at','atr_known_at'):assert a['ihs_quality_'+k]==f[k]<a['date']
                assert passes(rule,f)==(a['ihs_quality_pass']=='True')
            checked+=1
            if a['execution_reason']!='filled':continue
            assert passes(rule,f) and f['gap_pct']<=1e-12
            assert float(a['net_rr'])>3 and float(a['expected_upside'])>.05
            fill=float(a['fill']);qty=float(a['filled_quantity']);fee=float(a['entry_fee']);ex=cfg['execution'];t=ts.get(pid)
            assert math.isclose(fill,b.open*(1+ex['slippage']),abs_tol=1e-8)
            if t:
                q=qty*by[t['exit_date']].factor/b.factor;value=q*float(t['exit'])
                pnl=value-fill*qty-fee-max(ex['minimum_commission'],value*ex['commission_rate'])-value*ex['sell_tax_after_20230828']
                assert math.isclose(pnl,float(t['pnl']),abs_tol=1e-5)
                assert math.isclose(q,float(t['quantity']),abs_tol=1e-6)
            else:
                last=[x for x in h if x.date<='20260930'][-1];pnl=(last.close*last.factor/b.factor-fill)*qty-fee
            r=dict(case=name,canonical_id=pid,setup_id=a['setup_id'],symbol=a['symbol'],signal=ps[pid]['date'],entry=a['date'],exit=t['exit_date'] if t else '',closed=bool(t),pnl=pnl,quantity=qty,fill=fill,initial_stop=float(a['stop']),reason=t['reason'] if t else 'open',**f)
            own.append(r);records.append(r)
        assert len(own)==summary['filled_buys']
        assert math.isclose(sum(r['pnl'] for r in own),summary['final_equity']-1e6,abs_tol=1e-5)
        verification[name]=dict(gate_rows=checked,buys=len(own),passed=True)
    pairs=[];screens=[];stats=[]
    for rule in RULES[1:]:
        for cost in (1,2):
            case=f'{rule}_cost{cost}';base=f'baseline_cost{cost}'
            old={r['canonical_id']:r for r in records if r['case']==base};new={r['canonical_id']:r for r in records if r['case']==case}
            for pid in old.keys()|new.keys():
                a,b=old.get(pid),new.get(pid);src=a or b;passed=passes(rule,src)
                rejected=[x for x in data[case]['entry_audit'] if key(x['setup_id'])==pid and x['execution_reason']!='filled']
                reasons=';'.join(sorted({x['risk_reason'] or x['execution_reason'] for x in rejected})) if not b else ''
                pairs.append(dict(case=case,canonical_id=pid,symbol=src['symbol'],category='shared' if a and b else 'removed' if a else 'added',
                    old_entry=a['entry'] if a else '',new_entry=b['entry'] if b else '',old_exit=a['exit'] if a else '',new_exit=b['exit'] if b else '',
                    old_pnl=a['pnl'] if a else 0,new_pnl=b['pnl'] if b else 0,delta=(b['pnl'] if b else 0)-(a['pnl'] if a else 0),baseline_pass=passed,rejection_reasons=reasons))
                if a:screens.append(dict(case=case,canonical_id=pid,symbol=a['symbol'],baseline_pnl=a['pnl'],baseline_pass=passed,actual_retained=bool(b)))
                if a and b:
                    assert a['entry']==b['entry'] and a['exit']==b['exit'],(case,pid,'unexpected exit change')
            p=[r for r in pairs if r['case']==case];own=list(new.values());loss=[r for r in own if r['closed'] and r['pnl']<0]
            top=sorted(old.values(),key=lambda r:r['pnl'],reverse=True)[:5]
            stats.append(dict(case=case,losses=len(loss),loss_pnl=sum(r['pnl'] for r in loss),
                removed=sum(r['category']=='removed' for r in p),added=sum(r['category']=='added' for r in p),removed_wins=sum(r['category']=='removed' and r['old_pnl']>0 for r in p),removed_losses=sum(r['category']=='removed' and r['old_pnl']<0 for r in p),
                direct_removed=sum(r['category']=='removed' and not r['baseline_pass'] for r in p),shared_delta=sum(r['delta'] for r in p if r['category']=='shared'),removed_delta=sum(r['delta'] for r in p if r['category']=='removed'),added_delta=sum(r['delta'] for r in p if r['category']=='added'),
                top5_retained=sum(r['canonical_id'] in new for r in top),top5_baseline_pnl=sum(r['pnl'] for r in top),top5_new_pnl=sum(new[r['canonical_id']]['pnl'] for r in top if r['canonical_id'] in new)))
            summary=load(OUT/case/'summary.json');baseline=load(OUT/base/'summary.json')
            assert math.isclose(sum(r['delta'] for r in p),summary['final_equity']-baseline['final_equity'],abs_tol=1e-5)
    save(OUT/'trade-paths.csv',records);save(OUT/'paired-trades.csv',pairs);save(OUT/'baseline-screen.csv',screens);save(OUT/'attribution.csv',stats);dump(OUT/'verification.json',verification)
    print('AUDIT COMPLETE',sum(x['buys'] for x in verification.values()),'buys;',sum(x['gate_rows'] for x in verification.values()),'gate rows')

if __name__=='__main__':main()
