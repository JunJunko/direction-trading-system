"""Independent gate and fee checks plus retained/removed/added trade attribution."""
import math
from collections import Counter
from backtest_quality_entry import OUT,SOURCE,CASES,load,rows,dump
from audit_pattern_trade_paths import history,save

def measure(rule,plan,h,date,fill):
    known=[b for b in h if b.date<date];b=next(b for b in h if b.date==date)
    if rule=='span120':return float(plan['w_separation_sessions']),float(plan['w_separation_sessions'])<=120
    if rule=='no_gap_up':
        v=b.open/(known[-1].close*known[-1].factor/b.factor)-1
        return v,v<=1e-12
    tr=[max(y.high*y.factor-y.low*y.factor,abs(y.high*y.factor-x.close*x.factor),abs(y.low*y.factor-x.close*x.factor)) for x,y in zip(known[-15:-1],known[-14:])]
    assert len(tr)==14
    from datetime import datetime
    day=lambda d:datetime.strptime(d,'%Y%m%d').toordinal()
    p1,p2=float(plan['ihs_peak1_price']),float(plan['ihs_peak2_price'])
    neckline=p1+(p2-p1)*(day(date)-day(plan['ihs_peak1_date']))/(day(plan['ihs_peak2_date'])-day(plan['ihs_peak1_date']))
    signal=next(x for x in h if x.date==plan['date'])
    neckline*=signal.factor/b.factor
    v=(fill-neckline)/(sum(tr)/14/b.factor)
    return v,v<.5

def main():
    assert load(OUT/'status.json')['status']=='complete'
    folders={p.name:p for p in OUT.glob('*_cost*') if p.is_dir()}
    data={n:{k:rows(p/(k+'.csv')) for k in ('entry_audit','trades','decisions')} for n,p in folders.items()}
    symbols={a['symbol'] for d in data.values() for a in d['entry_audit']}
    hist=history(symbols);records=[];verification={};plans={}
    for name,d in data.items():
        cfg=load(folders[name]/'config.json');summary=load(folders[name]/'summary.json');rule=cfg.get('quality_entry_filter')
        ps={e['setup_id']:e for e in d['decisions'] if e['event']=='entry_intent'};plans[name]=ps
        trades={t['setup_id']:t for t in d['trades']};checked=0;own=[]
        for a in d['entry_audit']:
            if a.get('quality_rule'):
                value,passed=measure(rule,ps[a['setup_id']],hist[a['symbol']],a['date'],float(a['fill']))
                assert math.isclose(value,float(a['quality_value']),abs_tol=1e-7),(name,a['symbol'])
                assert passed==(a['quality_pass']=='True') and a['quality_known_at']<a['date']
                checked+=1
            if a['execution_reason']!='filled':continue
            h=hist[a['symbol']];by={b.date:b for b in h};b=by[a['date']];t=trades.get(a['setup_id'])
            q=float(a['filled_quantity']);fill=float(a['fill']);fee=float(a['entry_fee'])
            assert math.isclose(fill,b.open*(1+cfg['execution']['slippage']),abs_tol=1e-8)
            assert float(a['net_rr'])>3 and float(a['expected_upside'])>.05
            if rule:assert a['quality_pass']=='True'
            if t:
                qty=q*by[t['exit_date']].factor/b.factor;proceeds=qty*float(t['exit'])
                pnl=proceeds-fill*q-fee-max(cfg['execution']['minimum_commission'],proceeds*cfg['execution']['commission_rate'])-proceeds*cfg['execution']['sell_tax_after_20230828']
                assert math.isclose(pnl,float(t['pnl']),abs_tol=1e-5)
            else:
                last=[x for x in h if x.date<='20260930'][-1]
                pnl=(last.close*last.factor/b.factor-fill)*q-fee
            r=dict(case=name,setup_id=a['setup_id'],symbol=a['symbol'],entry=a['date'],exit=t['exit_date'] if t else '',pnl=pnl,quantity=q,fill=fill,closed=bool(t))
            records.append(r);own.append(r)
        assert math.isclose(sum(r['pnl'] for r in own),summary['final_equity']-summary['initial_cash'],abs_tol=1e-4)
        verification[name]=dict(checked_gate_rows=checked,filled_buys=len(own),passed=True)
    pairs=[];screens=[];stats=[]
    for family,rule in CASES:
        for cost in (1,2):
            case=f'{family}_{rule}_cost{cost}';baseline=f'{family}_baseline_cost{cost}'
            before={r['setup_id']:r for r in records if r['case']==baseline};after={r['setup_id']:r for r in records if r['case']==case}
            for pid in before.keys()|after.keys():
                a,b=before.get(pid),after.get(pid);source=a or b
                value,passed=measure(rule,plans[baseline if a else case][pid],hist[source['symbol']],source['entry'],source['fill'])
                category='shared' if a and b else 'removed' if a else 'added'
                pairs.append(dict(case=case,category=category,setup_id=pid,symbol=source['symbol'],old_entry=a['entry'] if a else '',new_entry=b['entry'] if b else '',old_exit=a['exit'] if a else '',new_exit=b['exit'] if b else '',old_pnl=a['pnl'] if a else 0,new_pnl=b['pnl'] if b else 0,delta=(b['pnl'] if b else 0)-(a['pnl'] if a else 0),baseline_gate_value=value,baseline_would_pass=passed))
                if a:screens.append(dict(case=case,setup_id=pid,symbol=a['symbol'],entry=a['entry'],closed=a['closed'],baseline_pnl=a['pnl'],gate_value=value,kept_by_static_screen=passed,actual_retained=bool(b)))
            own=[r for r in records if r['case']==case];old=list(before.values());p=[r for r in pairs if r['case']==case]
            stats.append(dict(case=case,losses=sum(r['closed'] and r['pnl']<0 for r in own),baseline_losses=sum(r['closed'] and r['pnl']<0 for r in old),loss_pnl=sum(r['pnl'] for r in own if r['closed'] and r['pnl']<0),baseline_loss_pnl=sum(r['pnl'] for r in old if r['closed'] and r['pnl']<0),
                removed=len([r for r in p if r['category']=='removed']),added=len([r for r in p if r['category']=='added']),removed_wins=sum(r['category']=='removed' and r['old_pnl']>0 for r in p),removed_losses=sum(r['category']=='removed' and r['old_pnl']<0 for r in p),
                shared_delta=sum(r['delta'] for r in p if r['category']=='shared'),removed_delta=sum(r['delta'] for r in p if r['category']=='removed'),added_delta=sum(r['delta'] for r in p if r['category']=='added')))
    save(OUT/'trade-paths.csv',records);save(OUT/'paired-trades.csv',pairs);save(OUT/'baseline-screen.csv',screens);save(OUT/'attribution.csv',stats);dump(OUT/'verification.json',verification)
    print('AUDIT OK',sum(v['filled_buys'] for v in verification.values()),'buys',sum(v['checked_gate_rows'] for v in verification.values()),'gate rows')

if __name__=='__main__':main()
