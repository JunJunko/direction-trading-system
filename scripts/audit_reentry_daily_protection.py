"""Independently verify new signals and support observation times, then attribute trades."""
import math
from collections import Counter
from backtest_reentry_daily_protection import OUT, load, rows, dump
from audit_pattern_trade_paths import history, save


def main():
    assert load(OUT/'status.json')['status']=='complete'
    cases={p.name:p for p in OUT.glob('*_cost*') if p.is_dir()}
    symbols={a['symbol'] for folder in cases.values() for a in rows(folder/'entry_audit.csv') if a['execution_reason']=='filled'}
    hist=history(symbols)
    verification={};records=[];summaries={}
    for name,folder in cases.items():
        events=rows(folder/'decisions.csv');audits=rows(folder/'entry_audit.csv')
        trades=rows(folder/'trades.csv');cfg=load(folder/'config.json');summary=load(folder/'summary.json')
        plans={e['setup_id']:e for e in events if e['event']=='entry_intent'}
        fills={(a['setup_id'],a['date']):a for a in audits if a['execution_reason']=='filled'}
        closed={(t['setup_id'],t['entry_date']):t for t in trades}
        retry=[e for e in events if e['event']=='entry_intent' and e.get('retry_origin')]
        daily=[e for e in events if e['event']=='main_protection_raised' and e.get('source')=='confirmed_daily_higher_low']
        breaks=[e for e in events if e['event']=='dynamic_support_daily_break']
        for e in breaks:
            h=hist[e['symbol']];bar=next(b for b in h if b.date==e['date'])
            assert bar.close*bar.factor<float(e['economic_protection'])
            known=[v for v in events if v['setup_id']==e['setup_id'] and v['event']=='main_protection_raised' and v['date']<e['date']]
            assert known and math.isclose(float(known[-1]['new']),float(e['economic_protection']),abs_tol=1e-8)
        for e in retry:
            origin=[t for t in trades if t['setup_id']==e['retry_origin'] and t['exit_date']==e['retry_exit_date']]
            assert len(origin)==1 and origin[0]['reason'] in ('support_break','deferred_support_break')
            h=hist[e['symbol']];after=[b for b in h if e['retry_exit_date']<b.date<=e['date']]
            assert 5<=len(after)<=14
            index=next(i for i,b in enumerate(after) if b.date==e['retry_low_date'])
            assert index>=2 and index+2<len(after) and after[index+2].date==e['retry_confirmed_at']
            factor=after[-1].factor;low=after[index].low*after[index].factor/factor
            assert math.isclose(low,float(e['stop']),abs_tol=1e-8)
            assert all(b.low*b.factor/factor>low for b in after[index-2:index]+after[index+1:index+3])
            assert min(b.low*b.factor/factor for b in after[index+1:])>=low-1e-8
            assert max(b.high*b.factor/factor for b in after)<float(e['target'])
            assert after[-1].close>max(float(e['w_neckline']),after[-1].open,after[-2].close*after[-2].factor/factor)
        for e in daily:
            h=hist[e['symbol']];by={b.date:i for i,b in enumerate(h)}
            i,j=by[e['formed']],by[e['confirmed']]
            assert j==i+2 and e['date']==e['confirmed'] and e['effective']=='next_session'
            low=h[i].low*h[i].factor
            known=h[max(0,j-15):j]
            atr=sum(max(b.high*b.factor-b.low*b.factor,abs(b.high*b.factor-prev.close*prev.factor),abs(b.low*b.factor-prev.close*prev.factor)) for prev,b in zip(known,known[1:]))/14
            assert len(known)==15 and math.isclose(atr,float(e['atr_economic']),abs_tol=1e-8)
            assert all(b.low*b.factor>low for b in h[i-2:i]+h[i+1:i+3])
            assert low>float(e['previous_daily_low'])
            assert math.isclose(float(e['new']),low-.5*float(e['atr_economic']),abs_tol=1e-8)
            if e.get('old'):assert float(e['new'])>float(e['old'])
            assert h[j].close*h[j].factor>float(e['new'])
            fill=next(a for (pid,date),a in fills.items() if pid==e['setup_id'])
            assert h[i-2].date>fill['date']
        own=[]
        for key,a in fills.items():
            plan=plans[key[0]];h=hist[a['symbol']];by={b.date:b for b in h}
            trade=closed.get(key);end=trade['exit_date'] if trade else '20260930'
            first=by[a['date']];factor=first.factor
            fill=float(a['fill']);quantity=float(a['filled_quantity']);fee=float(a['entry_fee']);risk=float(a['expected_loss'])
            assert float(a['net_rr'])>3 and float(a['expected_upside'])>.05
            assert math.isclose(fill,first.open*(1+cfg['execution']['slippage']),abs_tol=1e-7)
            bars=[b for b in h if a['date']<=b.date<=end and (not trade or b.date<end)]
            peak=max(b.close*b.factor/factor for b in bars)
            value=peak*(1-cfg['execution']['slippage'])*quantity
            peaknet=value-fill*quantity-fee-max(5,value*cfg['execution']['commission_rate'])-value*.0005
            pnl=float(trade['pnl']) if trade else (by[end].close*by[end].factor/factor-fill)*quantity-fee
            if trade:
                exitqty=quantity*by[end].factor/factor
                proceeds=float(trade['exit'])*exitqty
                exitfee=max(cfg['execution']['minimum_commission'],proceeds*cfg['execution']['commission_rate'])+proceeds*cfg['execution']['sell_tax_after_20230828']
                assert math.isclose(exitqty,float(trade['quantity']),abs_tol=1e-6)
                assert math.isclose(proceeds-fill*quantity-fee-exitfee,pnl,abs_tol=1e-5)
                if trade['reason']=='dynamic_support_daily_break':
                    signal=next(e for e in breaks if e['setup_id']==key[0])
                    assert signal['date']<end
                    expected=max(by[end].down_limit,by[end].open*(1-cfg['execution']['slippage']))
                    assert math.isclose(expected,float(trade['exit']),abs_tol=1e-8)
            row=dict(case=name,symbol=a['symbol'],setup_id=key[0],signal=a['signal_date'],entry=a['date'],
                exit=end if trade else '',closed=bool(trade),pnl=pnl,peak_gain=peak/fill-1,
                peak_net_R=peaknet/risk,final_R=pnl/risk,retry=bool(plan.get('retry_origin')),
                reason=trade['reason'] if trade else 'open',quantity=quantity)
            own.append(row);records.append(row)
        assert math.isclose(sum(r['pnl'] for r in own),summary['final_equity']-summary['initial_cash'],abs_tol=1e-4)
        losses=[r for r in own if r['closed'] and r['pnl']<0]
        summaries[name]=dict(buys=len(own),loss_count=len(losses),loss_pnl=sum(r['pnl'] for r in losses),
            gain5_then_loss=sum(r['peak_gain']>=.05 for r in losses),
            peak2R_then_loss=sum(r['peak_net_R']>=2 for r in losses),retry_buys=sum(r['retry'] for r in own),
            retry_pnl=sum(r['pnl'] for r in own if r['retry']),
            retry_rejections=dict(Counter(a['risk_reason'] or a['execution_reason'] for a in audits if ':retry:' in a['setup_id'])))
        verification[name]=dict(retry_signals=len(retry),daily_raises=len(daily),daily_breaks=len(breaks),fills=len(fills),checks_passed=True)
    pairs=[]
    for family in ('W','IHS'):
        for cost in (1,2):
            before={r['setup_id']:r for r in records if r['case']==f'{family}_baseline_cost{cost}'}
            after={r['setup_id']:r for r in records if r['case']==f'{family}_candidate_cost{cost}'}
            for pid in before.keys()|after.keys():
                a=before.get(pid);b=after.get(pid)
                pairs.append(dict(family=family,cost=cost,setup_id=pid,symbol=(a or b)['symbol'],
                    old_entry=a['entry'] if a else '',new_entry=b['entry'] if b else '',
                    old_exit=a['exit'] if a else '',new_exit=b['exit'] if b else '',
                    old_pnl=a['pnl'] if a else 0,new_pnl=b['pnl'] if b else 0,
                    delta=(b['pnl'] if b else 0)-(a['pnl'] if a else 0)))
    save(OUT/'trade-paths.csv',records);save(OUT/'paired-trades.csv',pairs)
    dump(OUT/'audit-summary.json',summaries);dump(OUT/'verification.json',verification)
    print('AUDIT COMPLETE',summaries)


if __name__=='__main__':main()
