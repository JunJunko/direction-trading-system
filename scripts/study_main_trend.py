"""Fixed-lot baseline vs MT1, IHS and qualified double bottom independently."""
import sys,csv,json,copy,hashlib,shutil,math
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];B=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest';O=ROOT/'runs/20261025-main-trend-mt1'
sys.path.insert(0,str(B/'source/src'))
from trading_system.domain import Bar,Position,ExitIntent
from trading_system.engine import Backtest
from trading_system.universe import MainboardUniverse
from main_trend_module import MainTrend

def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):return list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
 if not rs:return
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rs for k in r)));w.writeheader();w.writerows(rs)
def main():
 O.mkdir();protocol=dict(version='MT1',trend='completed calendar weekly bars; strict left2 right2 pivots; confirmed alternating H1 L1 H2 L2 with H2>H1 and L2>L1; ambiguous outside-bar pivot ignored',protection='L2 week starts after entry; monotonically raise protection above initial stop; economic factor-invariant levels',exit='initial original daily intraday hard stop remains; otherwise completed weekly close below previously active main protection => next executable open; no fixed target, breakeven or ATR overlay',entry='original actual fills and quantities, initial money risk and entry eligibility unchanged, including original RR gate; no re-entry or account regating',cohorts=['IHS v3 actual14','qualified W v5.19 actual14 from C0 source'],arms=['original','MT1'],costs=[1,1.5,2],cost_scope='entry fill fixed; commission and sell slippage multiplied; taxes/minimum fees unchanged',selection='one fixed specification; no parameter grid and no known14 tuning',evaluation='20251009-20260930 historical development only; future20261102-20271029 held out,>=50closed events and>=30symbols before single evaluation',metrics='closed profit factor, meanR,>=3R winners coverage of all closed losses, top3 positive profit share, net pnl without top3 winners, open marking separated, drawdown, turnover and exposure; costs',production_changed=False)
 dump(O/'protocol.json',protocol)
 (O/'source').mkdir();shutil.copytree(B/'source/src',O/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
 for n in ['main_trend_module.py','study_main_trend.py']:shutil.copy2(ROOT/'scripts'/n,O/'source'/n)
 results=[];records=[];all_daily=[];events=[];allorders=[];ver=[];hashes={}
 for cohort,base,market in [('IHS',B,B),('W',ROOT/'runs/20261024-qualified-w-cohort/candidate',ROOT/'runs/20261024-qualified-w-cohort')]:
  cfg=load(base/'config.json');cal=load(market/'calendar.json');ud=load(market/'universe.json');u=MainboardUniverse(ud['stocks'],ud['st_by_date']);dates=[d for d in cal['open_dates'] if '20251009'<=d<='20260930']
  entries=[r for r in rows(base/'entry_audit.csv') if r.get('execution_reason')=='filled'];plans={p['setup_id']:p for p in load(market/'plans.json')};old={r['setup_id']:r for r in rows(base/'trades.csv')};symbols={e['symbol'] for e in entries};by=defaultdict(list)
  dump(O/(cohort+'-frozen-entries.json'),entries)
  for f in [base/'entry_audit.csv',base/'trades.csv',base/'config.json',market/'plans.json',market/'bars.csv']:hashes[str(f.relative_to(ROOT))]=hashlib.sha256(f.read_bytes()).hexdigest()
  with (market/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
   for r in csv.DictReader(f):
    if r['symbol'] in symbols and r['date']<='20260930':by[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ['open','high','low','close','volume','factor','up_limit','down_limit']}))
  for bs in by.values():bs.sort(key=lambda b:b.date)
  for mult in [1,1.5,2]:
   c=copy.deepcopy(cfg);c['execution']['commission_rate']*=mult;c['execution']['slippage']*=mult
   for arm in ['original','MT1']:
    recs=[];curves=[]
    for a in entries:
     symbol=a['symbol'];pid=a['setup_id'];bs=by[symbol];day={b.date:b for b in bs};entryday=a['date'];b0=day[entryday];fill=float(a['fill']);qty=float(a['filled_quantity']);stop=float(a['stop']);risk=float(a['expected_loss']);fee=max(5,fill*qty*c['execution']['commission_rate']);e=Backtest(copy.deepcopy(c),[]);manager=MainTrend(a['strategy'],cal['open_dates'],cal['week_ends']);e.histories[symbol]=[b for b in bs if b.date<entryday];e.marks[symbol]=e.histories[symbol][-1].close;curve={};pending=False;mfe=0;raised=0
     for d in dates:
      if d<entryday:curve[d]=(0,0,0);continue
      if d>entryday and symbol not in e.positions:curve[d]=(e.cash-c['initial_cash'],0,0);continue
      b=day.get(d);today={symbol:b} if b else {};e.adjust_factors(today,d)
      if d==entryday:
       plan=copy.deepcopy(plans[pid]);scale=float(plan['factor'])/b.factor
       for k in ['w_neckline','w_floor','w_target','w_retest_low','ihs_neckline','ihs_floor','ihs_target','ihs_right_low','ihs_retest_low','ihs_entry_ceiling','breakout_reference']:
        if k in plan:plan[k]=float(plan[k])*scale
       plan['factor']=b.factor;e.positions[symbol]=Position(a['strategy'],symbol,d,fill,qty,stop,risk,fee,pid,b.factor,plan,fill);e.cash-=fill*qty+fee
       if b.low<=stop:e.positions[symbol].plan['t1_stop_breached_at']=d
      p=e.positions[symbol];before=len(e.trades);active=manager.protection/p.factor if manager.protection else None
      if d!=entryday:e.execute_interval(today,d,u,e.cash)
      if b:e.histories[symbol].append(b);e.marks[symbol]=b.close
      exited=len(e.trades)>before;ev=[]
      if not exited and b:
       mfe=max(mfe,(b.high-p.entry)*p.quantity)
       if arm=='MT1':
        exits,ev=manager.manage(e.histories[symbol],p);e.pending_exits.extend(exits)
       elif not pending and b.close>=p.plan['ihs_target' if cohort=='IHS' else 'w_target']:
        e.pending_exits.append(ExitIntent(a['strategy'],symbol,d,pid,('ihs' if cohort=='IHS' else 'w')+'_target_close_confirmed'));pending=True
       for event in ev:
        if event['event']=='main_protection_raised':raised+=1;assert event['confirmed']==d and event['formed']<d and (event['old'] is None or event['new']>event['old'])
        events.append(dict(cohort=cohort,cost=mult,arm=arm,symbol=symbol,setup_id=pid,**event))
      all_daily.append(dict(cohort=cohort,cost=mult,arm=arm,setup_id=pid,symbol=symbol,date=d,initial_stop=p.stop,active_main_protection=active,next_main_protection=manager.protection/p.factor if manager.protection else None,close=b.close if b else None,exit_reason=e.trades[-1]['reason'] if exited else '',fill=e.trades[-1]['exit'] if exited else None,events=';'.join(v['event'] for v in ev)))
      gross=sum(p.quantity*e.marks[s] for s,p in e.positions.items());curve[d]=(e.cash-c['initial_cash'],gross,len(e.positions))
     terminal=e.trades[0] if e.trades else None;pnl=terminal['pnl'] if terminal else e.equity()-c['initial_cash']
     if arm=='original' and mult==1:
      original=old.get(pid);assert bool(original)==bool(terminal)
      if original:
       for k in ['entry_date','exit_date','reason']:assert original[k]==terminal[k],(cohort,pid,k)
       for k in ['entry','exit','quantity','pnl','realized_r']:assert math.isclose(float(original[k]),terminal[k],abs_tol=1e-7),(cohort,pid,k)
     r=dict(cohort=cohort,cost=mult,arm=arm,symbol=symbol,setup_id=pid,entry_date=entryday,entry=fill,quantity=qty,initial_stop=stop,initial_R=risk,exit_date=terminal['exit_date'] if terminal else '',exit_reason=terminal['reason'] if terminal else 'OPEN_MARKED',exit_price=terminal['exit'] if terminal else None,closed=bool(terminal),net_pnl=pnl,net_R=pnl/risk,MFE_R=mfe/risk,giveback_R=(mfe-pnl)/risk,protection_raises=raised)
     recs.append(r);curves.append(curve);allorders.extend(dict(cohort=cohort,cost=mult,arm=arm,**x) for x in e.orders)
    equity=[];peak=c['initial_cash']
    for d in dates:
     cash=c['initial_cash']+sum(x[d][0] for x in curves);gross=sum(x[d][1] for x in curves);value=cash+gross;peak=max(peak,value);equity.append(dict(date=d,cash=cash,equity=value,drawdown=value/peak-1,gross_weight=gross/value))
    if arm=='original' and mult==1:
     for r,oldrow in zip(equity,rows(base/'equity.csv')):
      assert r['date']==oldrow['date']
      for k in ['cash','equity','drawdown']:assert math.isclose(r[k],float(oldrow[k]),abs_tol=1e-7),(cohort,k)
     ver.append(cohort+' baseline trades/equity exact')
    closed=[r for r in recs if r['closed']];profits=sorted([r['net_pnl'] for r in closed if r['net_pnl']>0],reverse=True);loss=-sum(min(0,r['net_pnl']) for r in closed);large=[r for r in closed if r['net_R']>=3];total=sum(r['net_pnl'] for r in recs)
    result=dict(cohort=cohort,cost=mult,arm=arm,entries=len(recs),closed=len(closed),open=len(recs)-len(closed),net_pnl=total,closed_pnl=sum(r['net_pnl'] for r in closed),mean_closed_R=sum(r['net_R'] for r in closed)/len(closed) if closed else None,win_rate=len(profits)/len(closed) if closed else None,profit_factor=sum(profits)/loss if loss else None,large_winners=len(large),large_winner_loss_coverage=sum(r['net_pnl'] for r in large)/loss if loss else None,top3_positive_profit_share=sum(profits[:3])/sum(profits) if profits else None,net_without_top3=total-sum(profits[:3]),max_drawdown=-min(r['drawdown'] for r in equity),min_cash=min(r['cash'] for r in equity),max_gross=max(r['gross_weight'] for r in equity),positions_with_protection=sum(r['protection_raises']>0 for r in recs),open_R=[r['net_R'] for r in recs if not r['closed']])
    records.extend(recs);results.append(result);save(O/f'{cohort}-{mult}-{arm}-equity.csv',equity);print(json.dumps(result),flush=True)
 save(O/'paired-trades.csv',records);save(O/'daily-audit.csv',all_daily);save(O/'events.csv',events);save(O/'orders.csv',allorders);dump(O/'summary.json',results);save(O/'summary.csv',results);dump(O/'input-hashes.json',hashes)
 assert len({(r['cohort'],r['setup_id'],r['entry_date'],r['entry'],r['quantity'],r['initial_stop'],r['initial_R']) for r in records})==sum(r['entries'] for r in results if r['cost']==1 and r['arm']=='original')
 changed=[str(p) for p in (B/'source/src').rglob('*.py') if p.read_bytes()!=(ROOT/'src'/p.relative_to(B/'source/src')).read_bytes()];assert not changed
 dump(O/'verification.json',dict(baseline_checks=ver,entries_risk_quantities_identical=True,production_unchanged=True,out_of_sample_accessed=False,experiment_specifications=1))
 print('COMPLETE',flush=True)
if __name__=='__main__':main()
