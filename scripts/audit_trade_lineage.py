"""Audit actual fills against causal direction/plan lineage in a frozen replay."""
import csv,json,sys,html
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted,weekly

def read(path):
    with path.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))

def main(folder):
    root=Path(folder)
    trades=sorted(read(root/'trades.csv'),key=lambda t:(t['entry_date'],t['symbol']))
    events=read(root/'warmup_decisions.csv')+read(root/'decisions.csv')
    events.sort(key=lambda e:e['date'])
    plans={e['setup_id']:e for e in events if e['event']=='entry_intent'}
    symbols={t['symbol'] for t in trades};bars={s:[] for s in symbols}
    with (root/'bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in bars:
                bars[r['symbol']].append(Bar(r['symbol'],r['date'],*[float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')]))
    audits=read(root/'entry_audit.csv');cal=json.loads((root/'calendar.json').read_text())
    index={d:i for i,d in enumerate(cal['open_dates'])};evaluated=read(root/'equity.csv')[0]['date']
    used=set();rows=[]
    for t in trades:
        plan=plans[t['setup_id']];prior=[e for e in events if e['symbol']==t['symbol'] and e['date']<=plan['direction_confirmed']]
        cand=[e for e in prior if e['event']=='weekly_reversal_candidate'][-1]
        retest=[e for e in prior if e['event']=='weekly_retest_started' and e['date']>=cand['date']][-1]
        w=weekly(adjusted([b for b in bars[t['symbol']] if b.date<=cand['date']]),set(cal['week_ends']))
        a,c=int(cand['first']),int(cand['second']);peak=max(range(a+1,c),key=lambda i:w[i].high)
        touches=[]
        for b in bars[t['symbol']]:
            if plan['date']<b.date<t['entry_date'] and b.volume>0 and b.high>=float(plan['trigger'])*float(plan['factor'])/b.factor:
                matches=[r for r in audits if r['setup_id']==t['setup_id'] and r['date']==b.date and r.get('execution_reason')]
                touches.append(dict(date=b.date,execution_reason=matches[-1]['execution_reason'] if matches else 'no_executable_order'))
        identity=(t['symbol'],plan['core_a'],plan['core_b'],plan['core_c'])
        rows.append(dict(symbol=t['symbol'],entry=t['entry_date'],exit=t['exit_date'],pnl=float(t['pnl']),
            bottom1=w[a].date,bottom2=w[c].date,neck_peak=w[peak].date,neckline=float(cand['neckline']),
            bottom_difference=abs(w[c].low/w[a].low-1),bottom_span_weeks=c-a,
            breakout=cand['date'],retest_start=retest['date'],direction_confirmed=plan['direction_confirmed'],
            direction_age_sessions=index[t['entry_date']]-index[plan['direction_confirmed']],
            core_a=plan['core_a'],core_b=plan['core_b'],core_c=plan['core_c'],small_c=plan['small_c'],
            planned=plan['date'],plan_age_sessions=index[t['entry_date']]-index[plan['date']],
            warmup_plan=plan['date']<evaluated,earlier_trigger_touches=touches,reused_daily_core=identity in used,
            classification='direction_following_daily_rhythm',setup_id=t['setup_id']))
        used.add(identity)
    result=dict(evaluation_start=evaluated,trades=rows,
        warmup_plan_count=sum(r['warmup_plan'] for r in rows),
        earlier_trigger_count=sum(bool(r['earlier_trigger_touches']) for r in rows),
        reused_core_count=sum(r['reused_daily_core'] for r in rows))
    (root/'trade-lineage-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    keys=list(rows[0]) if rows else []
    table='<table><tr>'+''.join('<th>'+k+'</th>' for k in keys)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(r[k]))+'</td>' for k in keys)+'</tr>' for r in rows)+'</table>'
    (root/'trade-lineage-audit.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font-family:system-ui;padding:20px}table{border-collapse:collapse;font-size:13px}td,th{border:1px solid #bbb;padding:8px;white-space:nowrap}</style><h1>交易来源与计划生命周期审计</h1><p>顶部/底部用于方向，日线N及小节奏用于入场。方向时间较久和多次入场本身不构成错误。未新增按天数强制判定方向失效的规则。warmup_plan标记预热计划；earlier_trigger_touches标记成交前已达到触发价，附当时拒绝原因。reused_daily_core表示同一日线A/B/C再次用于交易，不能称为新双底。</p>'+table,encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='trades'},ensure_ascii=False))
    for r in rows:print(json.dumps(r,ensure_ascii=False))

if __name__=='__main__':main(sys.argv[1])
