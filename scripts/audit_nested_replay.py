"""Audit recorded wave lifecycle and export per-trade causal chronology."""
import csv,json,sys,html
from collections import Counter
from pathlib import Path


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def main(run):
    run=Path(run);events=rows(run/'decisions.csv');orders=rows(run/'orders.csv')
    lifecycle_events=rows(run/'warmup_decisions.csv')+events
    records={};retired=set();accepted=ended=classified=0
    for e in lifecycle_events:
        kind=e['event']
        if not kind.startswith('wave_'):continue
        assert e['structure_known_at']<=e['date'],e
        prefix=(e['symbol'],e['upper_owner_id'])
        if kind=='wave_core_accepted':
            key=prefix+(e['owner_id'],)
            assert key not in retired and key not in records,e
            if e['parent_owner']:assert prefix+(e['parent_owner'],) in records,e
            assert not any(k[:2]==prefix and state=='active' for k,state in records.items()),e
            assert e['core_a']<e['core_b']<e['core_c']<=e['structure_known_at'],e
            records[key]='active';accepted+=1
        elif kind=='wave_core_ended':
            key=prefix+(e['owner_id'],)
            assert records.get(key)=='active',e
            records[key]='ended';retired.add(key);ended+=1
        elif kind=='wave_correction_classified':
            assert prefix+(e['owner_id'],) in records,e
            duration,drop,rd,rp=(float(e[k]) for k in ('duration','drop','reference_duration','reference_drop'))
            expected=('internal' if duration<rd and drop<rp else 'core' if duration>=rd and drop>=rp else 'unresolved')
            assert e['level']==expected,e
            classified+=1
    intents={e['setup_id']:e for e in events if e['event']=='entry_intent'}
    approved={e['setup_id'] for e in events if e['event']=='plan_approved'}
    # Existing filled order rows omit setup_id; the matching decision event
    # carries it. Reconcile both streams before counting independent plans.
    filled_events=[e for e in events if e['event']=='filled']
    filled={e['setup_id'] for e in filled_events}
    filled_orders=[o for o in orders if o['side']=='buy' and o['status']=='filled']
    assert Counter((e['date'],e['symbol']) for e in filled_events)==Counter((o['date'],o['symbol']) for o in filled_orders)
    assert filled<=approved<=intents.keys()
    reject={}
    for e in events:
        if e['event'] in ('plan_rejected','entry_rejected') and e['setup_id'] not in approved:
            reject.setdefault(e['setup_id'],e['reason'])
    trades=rows(run/'trades.csv')
    unclassified=set(intents)-approved-set(reject)
    held={identity for identity in unclassified if any(t['symbol']==intents[identity]['symbol']
        and t['entry_date']<=intents[identity]['date']<t['exit_date'] for t in trades)}
    unclassified-=held
    rejected_orders=Counter(o['reason'] for o in orders if o['side']=='buy' and o['status']=='rejected')
    timeline=[]
    fields=('direction_first','direction_second','direction_breakout','direction_retest_started',
            'direction_confirmed','core_a','core_b','core_c','core_c_confirmed','core_accepted_at',
            'small_a','small_b','small_c','small_confirmed','first_planned_at','upper_owner_id',
            'entry_core_owner','rhythm_owner','trigger','stop','target')
    for trade in trades:
        e=intents[trade['setup_id']]
        assert e['first_planned_at']<trade['entry_date']<=trade['exit_date'],trade
        assert e['direction_breakout']<=e['direction_retest_started']<=e['direction_confirmed']<=e['date'],e
        assert e['small_c'][:8]<=e['small_confirmed'][:8]<=e['date']<trade['entry_date'],e
        timeline.append(dict(trade,**{k:e.get(k,'') for k in fields}))
    for e in events:
        if e['event']=='core_protection_promoted':
            assert float(e['new_stop'])>float(e['old_stop']),e
            assert e['trough_date']<=e['confirmed_at']==e['date'],e
    audit=dict(lifecycle_assertions_passed=True,accepted_cores=accepted,ended_cores=ended,
        classified_corrections=classified,independent_plans=len(intents),approved_plans=len(approved),
        filled_plans=len(filled),first_rejections=dict(Counter(reject.values())),
        suppressed_by_existing_position=sorted(held),
        plans_without_approval_or_rejection=sorted(unclassified),
        approved_unfilled_plans=sorted(approved-filled),buy_rejection_events=dict(rejected_orders),
        closed_trade_chronology_assertions_passed=True,
        promoted_stop_events=sum(e['event']=='core_protection_promoted' for e in events),
        scope='Lifecycle counts include warmup; plan/trade funnel is evaluation-only. Bootstrap structural dates can precede observation dates. Recorded consistency is not pattern accuracy or a holdout result.')
    (run/'nested-audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    (run/'trade-timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2),encoding='utf-8')
    if timeline:
        with (run/'trade-timeline.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(timeline[0]));writer.writeheader();writer.writerows(timeline)
    columns=('symbol','direction_breakout','direction_retest_started','direction_confirmed',
             'core_a','core_b','core_c','small_c','first_planned_at','entry_date','exit_date','pnl','realized_r','reason')
    page=['<!doctype html><meta charset="utf-8"><title>v5.11 交易时序与结构审计</title>',
          '<style>body{font:15px system-ui;margin:25px}table{border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd;white-space:nowrap}pre{white-space:pre-wrap}</style>',
          '<h1>v5.11 交易时序与结构审计</h1><p>方向来自周线双底及真实反抽；核心来自日线N；小结构采用日线代理。初始计划价为信号日已知复权尺度，成交价为成交日尺度，不能直接跨复权日作价差。</p>',
          '<pre>'+html.escape(json.dumps(audit,ensure_ascii=False,indent=2))+'</pre>',
          '<table><tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in columns)+'</tr>']
    for t in timeline:page.append('<tr>'+''.join('<td>'+html.escape(str(t.get(k,'')))+'</td>' for k in columns)+'</tr>')
    page.append('</table>');(run/'trade-timeline.html').write_text('\n'.join(page),encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1])
