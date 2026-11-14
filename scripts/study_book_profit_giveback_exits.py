"""Frozen v7 combined entries: book-inspired exit experiments."""
import copy,csv,hashlib,html,json,math,shutil,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'runs/20261025-w-ihs-v7-shared-account'
BASE=DATA/'candidate_combined'
OUT=ROOT/'runs/20261026-book-profit-giveback-exits'
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar,Position
from trading_system.engine import Backtest
from trading_system.core_cycle_exit import ProfitGivebackExit
from trading_system.pressure_support_trend import PressureSupportTrend
from trading_system.universe import MainboardUniverse
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
 if not rs:return
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rs for k in r)));w.writeheader();w.writerows(rs)
def near(a,b):assert math.isclose(a,b,abs_tol=1e-7,rel_tol=1e-10),(a,b)
def main():
 OUT.mkdir();(OUT/'source').mkdir()
 cfg=load(BASE/'config.json');cal=load(DATA/'calendar.json');ud=load(DATA/'universe.json')
 dates=[d for d in cal['open_dates'] if '20251009'<=d<='20260930'];u=MainboardUniverse(ud['stocks'],ud['st_by_date'])
 entries=[a for a in rows(BASE/'entry_audit.csv') if a.get('execution_reason')=='filled']
 plans={p['setup_id']:p for p in load(BASE/'plans.json')};old={t['setup_id']:t for t in rows(BASE/'trades.csv')}
 protocol=dict(entry='freeze all 146 actual v7 combined fills, quantities, initial stops and cost-inclusive R',
  arms={'E0':'v7 baseline','E5':'v7 plus 50% peak close price-gain protection, activated at 2 initial cost-inclusive risk units'},
  source='attachment printed pp.295,305; 2R activation and close peak are explicit engineering hypotheses, not book constants',
  research_sequence='separate follow-up after E3/E4 failed; same known sample, not independent validation',
  execution='old support close break -> next executable open; original intraday stop unchanged',
  costs=[1,1.5,2],no_parameter_search=True,holdout_accessed=False,
  limitations=['known development sample','frozen entry counterfactual; no reinvestment; not a feasible reallocated portfolio','original W 2% cap retained','daily OHLC and synthetic factor convention'],
  rollout='research only')
 dump(OUT/'protocol.json',protocol);dump(OUT/'frozen-entries.json',entries);dump(OUT/'config.json',cfg)
 shutil.copytree(ROOT/'src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
 dump(OUT/'input-hashes.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (BASE/'entry_audit.csv',BASE/'trades.csv',BASE/'plans.json',BASE/'config.json')})
 dump(OUT/'data-reference.json',dict(bars_sha256=load(DATA/'manifest.json')['bars_sha256'],source_run=str(BASE),first='20251009',last='20260930'))
 hist=defaultdict(list);symbols={a['symbol'] for a in entries}
 with (DATA/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in symbols and r['date']<='20260930':hist[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 for bs in hist.values():bs.sort(key=lambda b:b.date)
 results=[];records=[];daily=[];events=[];curves_out=[]
 for cost in (1,1.5,2):
  c=copy.deepcopy(cfg);c['execution']['commission_rate']*=cost;c['execution']['slippage']*=cost
  for arm in ('E0','E5'):
   recs=[];curves=[]
   for a in entries:
    pid=a['setup_id'];symbol=a['symbol'];entryday=a['date'];bs=hist[symbol];day={b.date:b for b in bs};b0=day[entryday]
    entry=float(a['fill']);qty=float(a['filled_quantity']);stop=float(a['stop']);risk=float(a['expected_loss']);fee=max(5,entry*qty*c['execution']['commission_rate'])
    e=Backtest(copy.deepcopy(c),[]);e.histories[symbol]=[b for b in bs if b.date<entryday];e.marks[symbol]=e.histories[symbol][-1].close
    manager=(PressureSupportTrend(a['strategy'],cal['open_dates'],cal['week_ends']) if arm=='E0' else
       ProfitGivebackExit(a['strategy'],cal['open_dates'],cal['week_ends']))
    curve={};mfe=None;close_peak=None;first1='';raised=0
    for d in dates:
     if d<entryday:curve[d]=(0,0,0);continue
     if d>entryday and symbol not in e.positions:curve[d]=(e.cash-c['initial_cash'],0,0);continue
     b=day.get(d);today={symbol:b} if b else {};e.adjust_factors(today,d)
     if d==entryday:
      plan=copy.deepcopy(plans[pid]);scale=plan['factor']/b.factor
      for k in ('ihs_peak1_price','ihs_peak2_price','ihs_head_neckline','ihs_neckline','ihs_floor','ihs_target','ihs_right_low','ihs_entry_atr','breakout_reference'):
       if k in plan:plan[k]*=scale
      plan['factor']=b.factor
      e.positions[symbol]=Position(a['strategy'],symbol,d,entry,qty,stop,risk,fee,pid,b.factor,plan,entry)
      e.cash-=entry*qty+fee
      if b.low<=stop:e.positions[symbol].plan['t1_stop_breached_at']=d
     p=e.positions[symbol];active=manager.protection/p.factor if manager.protection is not None else None
     if d!=entryday:e.execute_interval(today,d,u,e.cash)
     if b:e.histories[symbol].append(b);e.marks[symbol]=b.close
     exited=symbol not in e.positions;ev=[]
     if not exited and b:
      def net(v):
       proceeds=v*p.quantity*(1-c['execution']['slippage'])
       return proceeds-p.entry*p.quantity-p.entry_fee-e.fee(proceeds,True,d)
      h,cl=net(b.high)/risk,net(b.close)/risk
      mfe=max(mfe,h) if mfe is not None else h;close_peak=max(close_peak,cl) if close_peak is not None else cl
      if not first1 and cl>=1:first1=d
      ex,ev=manager.manage(e.histories[symbol],p);e.pending_exits.extend(ex)
      for event in ev:
       if event['event']=='main_protection_raised':
        raised+=1;assert event['confirmed']==d and event['formed']<=d
        assert event['old'] is None or event['new']>event['old']
       events.append(dict(arm=arm,cost=cost,symbol=symbol,setup_id=pid,**event))
     daily.append(dict(arm=arm,cost=cost,symbol=symbol,setup_id=pid,date=d,initial_stop=p.stop,active_protection=active,
       next_protection=manager.protection/p.factor if manager.protection is not None else None,
       close=b.close if b and not exited else None,exit_reason=e.trades[-1]['reason'] if exited else '',fill=e.trades[-1]['exit'] if exited else None))
     gross=sum(p.quantity*e.marks[s] for s,p in e.positions.items());curve[d]=(e.cash-c['initial_cash'],gross,len(e.positions))
    terminal=e.trades[0] if e.trades else None;pnl=terminal['pnl'] if terminal else e.equity()-c['initial_cash']
    if arm=='E0' and cost==1:
     t=old.get(pid);assert bool(t)==bool(terminal)
     if t:
      for k in ('entry_date','exit_date','reason'):assert t[k]==terminal[k],(pid,k)
      for k in ('entry','exit','quantity','pnl','realized_r'):near(float(t[k]),terminal[k])
    r=dict(arm=arm,cost=cost,symbol=symbol,setup_id=pid,entry_date=entryday,entry=entry,quantity=qty,initial_stop=stop,initial_R=risk,
      exit_date=terminal['exit_date'] if terminal else '',exit_reason=terminal['reason'] if terminal else 'OPEN_MARKED',
      exit_price=terminal['exit'] if terminal else None,closed=bool(terminal),net_pnl=pnl,net_R=pnl/risk,
      MFE_net_R=mfe,peak_close_net_R=close_peak,first_close_1R=first1,protection_raises=raised,
      MFE_capture=pnl/(mfe*risk) if mfe and mfe>0 else None)
    recs.append(r);curves.append(curve)
   equity=[];peak=c['initial_cash']
   for d in dates:
    cash=c['initial_cash']+sum(x[d][0] for x in curves);gross=sum(x[d][1] for x in curves);value=cash+gross;peak=max(peak,value)
    equity.append(dict(date=d,cash=cash,equity=value,drawdown=value/peak-1,gross_weight=gross/value,positions=sum(x[d][2] for x in curves)))
   if arm=='E0' and cost==1:
    oldcurve=rows(BASE/'equity.csv');assert len(oldcurve)==len(equity)
    for x,y in zip(equity,oldcurve):
     assert x['date']==y['date']
     for k in ('cash','equity','drawdown'):near(x[k],float(y[k]))
   closed=[r for r in recs if r['closed']];wins=[r for r in closed if r['net_pnl']>0];loss=-sum(min(r['net_pnl'],0) for r in closed)
   mfesum=sum(max(0,r['MFE_net_R'])*r['initial_R'] for r in closed)
   total=sum(r['net_pnl'] for r in recs);near(total,equity[-1]['equity']-c['initial_cash'])
   result=dict(arm=arm,cost=cost,entries=len(recs),closed=len(closed),open=len(recs)-len(closed),net_pnl=total,
     total_return=total/c['initial_cash'],closed_pnl=sum(r['net_pnl'] for r in closed),
     mean_closed_R=sum(r['net_R'] for r in closed)/len(closed) if closed else None,
     mean_marked_R=sum(r['net_R'] for r in recs)/len(recs),win_rate=len(wins)/len(closed) if closed else None,
     profit_factor=sum(r['net_pnl'] for r in wins)/loss if loss else None,max_drawdown=-min(r['drawdown'] for r in equity),
     max_positions=max(r['positions'] for r in equity),min_cash=min(r['cash'] for r in equity),max_gross=max(r['gross_weight'] for r in equity),
     large_winners=sum(r['net_R']>=3 for r in closed),
     positive_to_loss=sum(r['peak_close_net_R']>0 and r['net_R']<0 for r in closed),
     close_1R_to_loss=sum(r['peak_close_net_R']>=1 and r['net_R']<0 for r in closed),
     MFE_capture_closed=sum(r['net_pnl'] for r in closed)/mfesum if mfesum else None)
   records.extend(recs);results.append(result);curves_out.extend(dict(arm=arm,cost=cost,**v) for v in equity)
   print(json.dumps(result),flush=True)
 paired=[]
 for cost in (1,1.5,2):
  baseline={r['setup_id']:r for r in records if r['arm']=='E0' and r['cost']==cost}
  for result in [r for r in results if r['cost']==cost]:
   rs=[r for r in records if r['cost']==cost and r['arm']==result['arm']]
   result['baseline_closed_winners_reduced']=sum(baseline[r['setup_id']]['closed'] and baseline[r['setup_id']]['net_pnl']>0 and r['net_pnl']<baseline[r['setup_id']]['net_pnl']-1e-7 for r in rs)
   result['baseline_profitable_marked_trades_reduced']=sum(baseline[r['setup_id']]['net_pnl']>0 and r['net_pnl']<baseline[r['setup_id']]['net_pnl']-1e-7 for r in rs)
   for r in rs:
    base=baseline[r['setup_id']]
    assert all(r[k]==base[k] for k in ('entry_date','entry','quantity','initial_stop','initial_R'))
    paired.append(dict(**r,baseline_net_pnl=base['net_pnl'],paired_delta=r['net_pnl']-base['net_pnl']))
 save(OUT/'paired-trades.csv',paired);save(OUT/'daily-audit.csv',daily);save(OUT/'events.csv',events);save(OUT/'equity.csv',curves_out);dump(OUT/'summary.json',results)
 dump(OUT/'verification.json',dict(original_trades_and_equity_exact=True,
  frozen_entries=len(entries),all_arms_same_entries_stops_quantities_and_R=True,
  causal_monotonic_support_checked=True,account_engine_modified=False,parameter_search=False,holdout_accessed=False))
 def table(headers,data):return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in data)+'</table></div>'
 body='<h1>书中核心周期退出：冻结 v7 组合146笔买入</h1><p>E0 原v7；E5 收盘价格收益达到初始风险2倍后，以最高收盘涨幅的50%建立保护。此阈值为工程假设，非原书原话。原始入场、止损、数量及R固定。已知开发样本，不证明样本外优势。</p>'
 for cost in (1,1.5,2):
  body+=f'<h2>成本倍率 {cost}</h2>'+table(['组别','已平/未平','总净损益（含持仓）','已平净损益','已平平均R','胜率','最大回撤','收盘1R后转亏','≥3R盈利笔数','已平MFE兑现比例','原已平盈利变少笔数'],[(r['arm'],f"{r['closed']}/{r['open']}",f"{r['net_pnl']:,.2f}",f"{r['closed_pnl']:,.2f}",f"{r['mean_closed_R']:.3f}",f"{r['win_rate']:.1%}",f"{r['max_drawdown']:.2%}",r['close_1R_to_loss'],r['large_winners'],f"{r['MFE_capture_closed']:.1%}",r['baseline_closed_winners_reduced']) for r in results if r['cost']==cost])
 body+='<h2>标准成本逐笔配对</h2>'+table(['股票','买入日','组别','退出日','净R','净损益','较E0变化','退出原因'],[(r['symbol'],r['entry_date'],r['arm'],r['exit_date'] or '持仓',f"{r['net_R']:.3f}",f"{r['net_pnl']:,.2f}",f"{r['paired_delta']:,.2f}",r['exit_reason']) for r in sorted(paired,key=lambda r:(r['entry_date'],r['symbol'],r['arm'])) if r['cost']==1])
 body+='<p>成本敏感性只提高佣金率与卖出滑点；买入价格为冻结实际成交，最低佣金和税率固定。R始终使用原始风险金额。MFE不使用退出日整根K线；峰值不是可成交保证。未平仓按市值计价、未扣未来卖出费。已知小样本只能验证机制差异，不能证明样本外优势；不据此修改正式默认策略。</p><p><a href="paired-trades.csv">逐笔配对</a> · <a href="daily-audit.csv">逐日保护与成交</a> · <a href="events.csv">支撑与压力事件</a> · <a href="protocol.json">固定实验规则</a> · <a href="verification.json">核验结果</a></p>'
 (OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>核心周期固定入场退出对照</title><style>body{font:16px/1.65 system-ui;max-width:1450px;margin:30px auto;padding:0 20px}.scroll{overflow:auto}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ddd;white-space:nowrap}th{background:#eef3f8}</style>'+body,encoding='utf-8')
 print('COMPLETE',flush=True)
if __name__=='__main__':main()
