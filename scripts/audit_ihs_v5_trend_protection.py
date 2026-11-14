"""Read-only diagnosis of v5 weekly protection confirmation and execution."""
import csv,html,json,sys
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v5-breakout-trend'
OUT=ROOT/'audits/20261025-ihs-v5-trend-protection'
sys.path.insert(0,str(RUN/'source/src'))
from trading_system.domain import Bar
from trading_system.main_trend import completed_weeks,confirmed_sequences
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 fills=[a for a in rows(RUN/'entry_audit.csv') if a['execution_reason']=='filled']
 events=rows(RUN/'decisions.csv');paths={p['setup_id']:p for p in rows(ROOT/'audits/20261025-ihs-v5-profit-paths/trade-paths.csv')}
 cal=load(RUN/'calendar.json');cost=load(RUN/'config.json')['execution'];hist=defaultdict(list)
 symbols={a['symbol'] for a in fills}
 with (RUN/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in symbols:hist[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 results=[];daily=[];lows=[]
 for a in fills:
  pid=a['setup_id'];p=paths[pid];bs=sorted(hist[a['symbol']],key=lambda b:b.date);end=p['exit_date'] or '20260930'
  bs=[b for b in bs if b.date<=end];bydate={b.date:b for b in bs};entrybar=bydate[a['date']]
  factor=entrybar.factor;entry=float(a['fill']);quantity=float(a['filled_quantity']);fee=float(a['entry_fee']);risk=float(a['expected_loss'])
  def net_r(price):
   proceeds=price*quantity*(1-cost['slippage'])
   return (proceeds-entry*quantity-fee-max(5,proceeds*cost['commission_rate'])-proceeds*cost['sell_tax_after_20230828'])/risk
  raises=[e for e in events if e['setup_id']==pid and e['event']=='main_protection_raised']
  exits=[e for e in events if e['setup_id']==pid and e['event']=='weekly_close_break']
  if p['exit_reason']=='weekly_main_trend_break':
   assert len(exits)==1 and cal['open_dates'][cal['open_dates'].index(exits[0]['date'])+1]==p['exit_date'],pid
  active=None;di=[]
  for b in bs:
   if b.date<a['date']:continue
   is_exit=bool(p['exit_date'] and b.date==p['exit_date'])
   r=dict(symbol=a['symbol'],setup_id=pid,date=b.date,entry=entry,initial_stop=float(a['stop']),
     active_weekly_protection=active/factor if active is not None else None,
     active_protection_net_R=net_r(active/factor) if active is not None else None,
     close_net_R=net_r(b.close*b.factor/factor) if not is_exit else None,
     low_below_protection=bool(not is_exit and active is not None and b.low*b.factor<active),
     close_below_protection=bool(not is_exit and active is not None and b.close*b.factor<active),
     exchange_week_end=b.date in cal['week_ends'],exit_day=is_exit)
   for e in raises:
    if e['date']==b.date:active=float(e['new'])
   r['next_session_weekly_protection']=active/factor if active is not None else None
   di.append(r);daily.append(r)
  # Explain every weekly low candidate at its original confirmation time.
  # Includes suppressed same-kind lows and higher lows rejected by the HH gate.
  ws=completed_weeks(bs,cal['open_dates']);pivots=[];candidates=[]
  for t in range(2,len(ws)-2):
   w=ws[t-2:t+3]
   if w[-1]['index']-w[0]['index']!=4:continue
   low=all(ws[t]['low']<v['low'] for v in w if v is not ws[t]);high=all(ws[t]['high']>v['high'] for v in w if v is not ws[t])
   if not low and not high:continue
   d=dict(ws[t],kind='L' if low else 'H',price=ws[t]['low' if low else 'high'],confirmed=ws[t+2]['date'])
   previous_low=next((v for v in reversed(pivots) if v['kind']=='L'),None)
   reason=None
   if low and high:reason='ambiguous_week_high_and_low'
   elif pivots and pivots[-1]['kind']==d['kind'] and ((low and d['price']>=pivots[-1]['price']) or (high and d['price']<=pivots[-1]['price'])):reason='same_kind_pivot_suppressed'
   else:
    if pivots and pivots[-1]['kind']==d['kind']:pivots[-1]=d
    else:pivots.append(d)
    if low:
     if len(pivots)<4 or ''.join(v['kind'] for v in pivots[-4:])!='HLHL':reason='no_complete_HLHL_sequence'
     elif pivots[-2]['price']<=pivots[-4]['price']:reason='latest_high_not_higher'
     elif pivots[-1]['price']<=pivots[-3]['price']:reason='latest_low_not_higher'
     elif d['start']<=a['date']:reason='trough_week_started_before_or_at_entry'
     else:reason='eligible_structure'
   if low and a['date']<=d['confirmed']<=end and not (p['exit_date'] and d['confirmed']==end):
    did_raise=any(e['formed']==d['date'] and e['confirmed']==d['confirmed'] for e in raises)
    if reason=='eligible_structure' and not did_raise:reason='not_above_active_or_initial_protection'
    candidate=dict(symbol=a['symbol'],setup_id=pid,formed=d['date'],confirmed=d['confirmed'],
      price_entry_units=d['price']/factor,net_R_at_level=net_r(d['price']/factor),
      higher_than_previous_low=previous_low is not None and d['price']>previous_low['price'],
      actually_raised=did_raise,reason=reason)
    candidates.append(candidate);lows.append(candidate)
  high=float(p['peak_high_net_R']);peak=p['peak_high_date']
  before_peak=[e for e in raises if e['date']<peak]
  daily_breaks=[r for r in di if r['close_below_protection']]
  results.append(dict(symbol=a['symbol'],setup_id=pid,entry_date=a['date'],entry=entry,initial_stop=float(a['stop']),
    peak_net_R=high,peak_date=peak,final_net_R=float(p['final_net_R']),exit_date=p['exit_date'],exit_reason=p['exit_reason'],
    protection_raises=len(raises),last_raise_date=raises[-1]['date'] if raises else None,
    last_protection_entry_units=float(raises[-1]['new'])/factor if raises else None,
    last_protection_net_R=net_r(float(raises[-1]['new'])/factor) if raises else None,
    protection_before_peak_net_R=net_r(float(before_peak[-1]['new'])/factor) if before_peak else None,
    first_daily_close_below_active=daily_breaks[0]['date'] if daily_breaks else None,
    first_daily_break_net_R=daily_breaks[0]['close_net_R'] if daily_breaks else None,
    first_weekly_exit_signal=exits[0]['date'] if exits else None,
    eligible_weekly_structures=sum(c['reason']=='eligible_structure' for c in candidates),
    rejected_weekly_lows=dict(Counter(c['reason'] for c in candidates if c['reason']!='eligible_structure')),
    raises=[dict(date=e['date'],formed=e['formed'],price_entry_units=float(e['new'])/factor,net_R_at_level=net_r(float(e['new'])/factor)) for e in raises]))
  assert sum(c['actually_raised'] for c in candidates)==len(raises),pid
  assert all(float(y['new'])>float(z['new']) for z,y in zip(raises,raises[1:])),pid
 dump(OUT/'summary.json',results);save(OUT/'daily-protection.csv',daily);save(OUT/'weekly-low-candidates.csv',lows)
 def table(headers,data):return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(str(h))+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in data)+'</table></div>'
 fmt=lambda v:'未建立' if v is None else f'{v:.3f}'
 body='<h1>v5：为什么浮盈回吐后仍未退出</h1><p>只审计现有规则与执行记录，不修改交易规则。价格统一换算为入场复权单位；保护位净R为假设按该价格减滑点成交后的估计值，周收盘条件不保证按保护价成交。</p>'
 body+='<p>代码中未接入动态压力位退出。初始日内止损保持在右肩下方；另有周线趋势保护，要求左右各2周确认、H1-L1-H2-L2同时高点和低点抬高，且新波谷形成周须在入场之后。只有周收盘跌破此前保护位，才产生下一可执行时点退出指令。保护位提高不意味着已提高至成本之上，也不会同步替换日内止损。</p>'
 body+=table(['股票','买价','初始止损','峰值净R','最终/期末R','上移次数','最后上移日','最后保护价','保护价净R','首次日收盘失守','周线退出信号','实际退出'],[(r['symbol'],fmt(r['entry']),fmt(r['initial_stop']),fmt(r['peak_net_R']),fmt(r['final_net_R']),r['protection_raises'],r['last_raise_date'],fmt(r['last_protection_entry_units']),fmt(r['last_protection_net_R']),r['first_daily_close_below_active'],r['first_weekly_exit_signal'],r['exit_date'] or '未平仓') for r in results])
 body+='<h2>逐笔保护位变化</h2>'
 for r in results:
  body+='<h3>'+r['symbol']+'</h3>'+table(['形成周末','确认/上移日','保护价（入场单位）','保护价净R'],[(e['formed'],e['date'],fmt(e['price_entry_units']),fmt(e['net_R_at_level'])) for e in r['raises']])
 body+='<p><a href="daily-protection.csv">逐日有效与下一日保护位</a> · <a href="weekly-low-candidates.csv">周线低点及未采用原因</a> · <a href="summary.json">审计明细</a></p>'
 (OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>v5趋势保护诊断</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:30px auto;padding:0 20px}.scroll{overflow:auto}table{border-collapse:collapse}th,td{padding:8px;border:1px solid #ddd;white-space:nowrap}th{background:#eef3f8}</style>'+body,encoding='utf-8')
 (OUT/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
 for r in results:print(json.dumps(r,ensure_ascii=True))
if __name__=='__main__':main()
