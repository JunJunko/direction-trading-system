"""Independent ledger, causal support/pressure and actual entry-risk checks."""
import ast,csv,hashlib,html,json,math,shutil,sys
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
ROOT=Path(__file__).resolve().parents[1]
OUT=Path(sys.argv[1]).resolve()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def near(a,b):assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-7),(a,b)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def ordinal(d):return datetime.strptime(d,'%Y%m%d').toordinal()
def neck(p,d):return p['ihs_peak1_price']+(p['ihs_peak2_price']-p['ihs_peak1_price'])*(ordinal(d)-ordinal(p['ihs_peak1_date']))/(ordinal(p['ihs_peak2_date'])-ordinal(p['ihs_peak1_date']))
def main():
 m=load(OUT/'manifest.json');cfg=load(OUT/'config.json');s=load(OUT/'summary.json');base=Path(m['source_scan'])
 assert sha(OUT/'bars.csv')==m['bars_sha256']==load(base/'manifest.json')['bars_sha256']
 assert sha(OUT/'config.json')==m['config_sha256']
 h=hashlib.sha256()
 for p in sorted((OUT/'source/src').rglob('*.py')):h.update(str(p.relative_to(OUT/'source/src')).encode());h.update(p.read_bytes())
 assert h.hexdigest()==m['code_sha256']
 assert all(m[k] for k in ('entry_params_equal_to_v5','entry_detector_methods_equal_to_v5','engine_and_risk_equal_to_v5'))
 aliases=load(OUT/'signal-aliases.json');plans=load(OUT/'plans.json');oldplans={p['setup_id']:p for p in load(base/'plans.json')}
 for p in plans:assert dict(p,setup_id=aliases[p['setup_id']])==oldplans[aliases[p['setup_id']]]
 assert len(plans)==1713
 audits=rows(OUT/'entry_audit.csv');filled=[a for a in audits if a['execution_reason']=='filled']
 trades=rows(OUT/'trades.csv');orders=rows(OUT/'orders.csv');events=rows(OUT/'decisions.csv');curve=rows(OUT/'equity.csv')
 hist=defaultdict(list);symbols={a['symbol'] for a in filled}
 with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for b in csv.DictReader(f):
   if b['symbol'] in symbols:hist[b['symbol']].append(b)
 ix={}
 for symbol,bs in hist.items():bs.sort(key=lambda b:b['date']);ix[symbol]={b['date']:j for j,b in enumerate(bs)}
 byid={a['setup_id']:a for a in filled};pm={p['setup_id']:p for p in plans};cost=cfg['execution'];rules=cfg['strategies'][0]['params']
 def price(b,k):return float(b[k])*float(b['factor'])
 def atr(bs,i):return sum(max(price(bs[j],'high')-price(bs[j],'low'),abs(price(bs[j],'high')-price(bs[j-1],'close')),abs(price(bs[j],'low')-price(bs[j-1],'close'))) for j in range(i-14,i))/14
 for a in filled:
  p=pm[a['setup_id']];b=hist[a['symbol']][ix[a['symbol']][a['date']]];scale=p['factor']/float(b['factor'])
  fill,stop,target,q=(float(a[k]) for k in ('fill','stop','target','filled_quantity'))
  assert p['date']<a['date'];near(fill,float(b['open'])*(1+cost['slippage']));near(stop,p['stop']*scale);near(target,p['target']*scale)
  n=neck(p,a['date'])*scale;at=p['ihs_entry_atr']*scale
  assert float(b['open'])>n and fill<=n+rules['max_entry_atr']*at+1e-9 and fill-stop>=rules['min_stop_atr']*at-1e-9
  ef=max(5,q*fill*cost['commission_rate']);sf=stop*(1-cost['slippage']);tf=target*(1-cost['slippage'])
  tax=cost['sell_tax_after_20230828'];loss=q*(fill-sf)+ef+max(5,q*sf*cost['commission_rate'])+q*sf*tax
  gain=q*(tf-fill)-ef-max(5,q*tf*cost['commission_rate'])-q*tf*tax
  near(gain/loss,float(a['net_rr']));near(loss,float(a['expected_loss']))
  assert gain/loss>cfg['risk']['min_rr'] and loss<=float(a['risk_budget'])+1e-8
  assert q%100==0 and float(b['low'])<=fill<=float(b['high'])
  assert not float(b['up_limit']) or fill<float(b['up_limit'])-1e-5
  assert a['decision']=='BUY_ALLOWED'
 assert all(a['decision']=='NO_TRADE' for a in audits if a['execution_reason']!='filled')
 # Independent complete-week construction for pivot date/price validation.
 cal=load(OUT/'calendar.json');groups={}
 for d in cal['open_dates']:groups.setdefault(datetime.strptime(d,'%Y%m%d').isocalendar()[:2],[]).append(d)
 weeks=list(groups.values());week_index={d:j for j,ds in enumerate(weeks) for d in ds}
 def pivot(symbol,formed,confirmed,kind):
  wi=week_index[formed];assert weeks[wi][-1]==formed and weeks[wi+2][-1]==confirmed
  bs=hist[symbol];bydate={b['date']:b for b in bs};values=[]
  for ds in weeks[wi-2:wi+3]:
   assert all(d in bydate for d in ds)
   values.append((max(price(bydate[d],'high') for d in ds),min(price(bydate[d],'low') for d in ds)))
  high=all(values[2][0]>v[0] for i,v in enumerate(values) if i!=2)
  low=all(values[2][1]<v[1] for i,v in enumerate(values) if i!=2)
  assert high!=low and (high if kind=='H' else low)
  return values[2][0 if kind=='H' else 1]
 pressure_checks=support_checks=0;last={};raises=defaultdict(list)
 for e in events:
  pid=e.get('setup_id');symbol=e['symbol'];kind=e['event']
  if pid not in byid:continue
  if kind=='dynamic_pressure_confirmed':
   near(pivot(symbol,e['formed'],e['confirmed'],'H'),float(e['economic_pressure']))
   assert e['confirmed']<=e['date'];pressure_checks+=1
  if kind=='main_protection_raised':
   a=byid[pid];b0=hist[symbol][ix[symbol][a['date']]];initial=float(a['stop'])*float(b0['factor']);level=float(e['new'])
   assert level>max(initial,last.get(pid,initial));last[pid]=level
   b=hist[symbol][ix[symbol][e['date']]];near(float(e['raw_protection'])*float(b['factor']),level)
   if e.get('source')=='broken_confirmed_pressure':
    br=next(v for v in events if v.get('setup_id')==pid and v['event']=='dynamic_pressure_breakout' and v['date']==e['date'])
    assert br['pressure_confirmed']<br['date'];near(pivot(symbol,br['pressure_formed'],br['pressure_confirmed'],'H'),level)
    at=atr(hist[symbol],ix[symbol][e['date']]);near(at/float(b['factor']),float(br['atr']))
    assert price(b,'close')>level+rules['pressure_breakout_atr']*at
    levels=ast.literal_eval(br['broken_pressures']);near(max(levels)*float(b['factor']),level)
    assert all(price(b,'close')>v*float(b['factor'])+rules['pressure_breakout_atr']*at for v in levels)
   else:
    near(pivot(symbol,e['formed'],e['confirmed'],'L'),level)
    assert weeks[week_index[e['formed']]][0]>a['date']
   raises[pid].append(e);support_checks+=1
 dynamic_reasons=('dynamic_support_daily_break','confirmed_support_daily_break')
 for e in events:
  if e['event'] not in dynamic_reasons:continue
  prev=[v for v in raises[e['setup_id']] if v['date']<e['date']];assert prev
  level=float(prev[-1]['new']);b=hist[e['symbol']][ix[e['symbol']][e['date']]]
  near(level,float(e['protection'])*float(b['factor']));assert price(b,'close')<level
 for t in trades:
  assert t['exit_date']>t['entry_date']
  assert t['reason'] in (*dynamic_reasons,'ihs_trade_protection_break','deferred_ihs_trade_protection_break')
  if t['reason'] in dynamic_reasons:
   trigger=next(v for v in events if v.get('setup_id')==t['setup_id'] and v['event']==t['reason'])
   assert trigger['date']<t['exit_date']
   b=hist[t['symbol']][ix[t['symbol']][t['exit_date']]]
   near(float(t['exit']),max(float(b['low']),float(b['open'])*(1-cost['slippage'])))
   for d in cal['open_dates']:
    if trigger['date']<d<t['exit_date'] and d in ix[t['symbol']]:
     prevbar=hist[t['symbol']][ix[t['symbol']][d]]
     assert float(prevbar['volume'])<=0 or (float(prevbar['down_limit']) and float(prevbar['high'])<=float(prevbar['down_limit'])+1e-5)
 cash=cfg['initial_cash']
 for o in orders:
  if o['status']=='filled':cash+=(-1 if o['side']=='buy' else 1)*float(o['price'])*float(o['quantity'])-float(o['fee'])
 assert len(curve)==241;peak=cfg['initial_cash']
 for v in curve:peak=max(peak,float(v['equity']));near(float(v['drawdown']),float(v['equity'])/peak-1)
 near(cash,float(curve[-1]['cash']));near(float(curve[-1]['equity']),s['final_equity'])
 realized=sum(float(t['pnl']) for t in trades);open_cost=sum(p['entry']*p['quantity']+p['entry_fee'] for p in s['positions'])
 near(realized,cash-cfg['initial_cash']+open_cost)
 assert len(filled)==s['filled_buys']==len(trades)+s['open_positions']
 paths=[];tm={t['setup_id']:t for t in trades}
 for a in filled:
  t=tm.get(a['setup_id']);bs=hist[a['symbol']];f=float(bs[ix[a['symbol']][a['date']]]['factor'])
  held=[b for b in bs if b['date']>=a['date'] and b['date']<=m['evaluation_end'] and (not t or b['date']<t['exit_date'])]
  fill,q,fee,risk=(float(a[k]) for k in ('fill','filled_quantity','entry_fee','expected_loss'))
  def net(p):
   val=p*q*(1-cost['slippage']);return val-fill*q-fee-max(5,val*cost['commission_rate'])-val*cost['sell_tax_after_20230828']
  hi=max(held,key=lambda b:price(b,'high'));cl=max(held,key=lambda b:price(b,'close'))
  pnl=float(t['pnl']) if t else (price(held[-1],'close')/f-fill)*q-fee
  paths.append(dict(symbol=a['symbol'],setup_id=a['setup_id'],entry_date=a['date'],exit_date=t['exit_date'] if t else '',
   MFE_net_R=net(price(hi,'high')/f)/risk,peak_close_net_R=net(price(cl,'close')/f)/risk,
   peak_date=hi['date'],final_net_R=pnl/risk,final_net_pnl=pnl,closed=bool(t)))
 near(sum(p['final_net_pnl'] for p in paths),s['final_equity']-cfg['initial_cash'])
 closed=[p for p in paths if p['closed']];loss=-sum(float(t['pnl']) for t in trades if float(t['pnl'])<0)
 extra=dict(realized_pnl=realized,open_marked_pnl=s['final_equity']-cfg['initial_cash']-realized,
  mean_closed_R=sum(float(t['realized_r']) for t in trades)/len(trades) if trades else None,
  winners=sum(float(t['pnl'])>0 for t in trades),large_winners=sum(float(t['realized_r'])>=3 for t in trades),
  close_1R_to_loss=sum(p['peak_close_net_R']>=1 and p['final_net_R']<0 for p in closed),
  large_winner_loss_coverage=sum(float(t['pnl']) for t in trades if float(t['realized_r'])>=3)/loss if loss else None,
  pressure_breakouts=sum(e['event']=='dynamic_pressure_breakout' for e in events),
  support_raises=support_checks,pressure_confirmations=pressure_checks,
  exit_reasons=dict(Counter(t['reason'] for t in trades)),stop_distance_median=median((float(a['fill'])-float(a['stop']))/float(a['fill']) for a in filled))
 dump(OUT/'path-summary.json',extra);dump(OUT/'profit-paths.json',paths)
 dump(OUT/'verification.json',dict(data_and_source_hashes_verified=True,unchanged_1713_entry_candidates=True,
  actual_entries_risk_checked=len(filled),causal_support_raises_checked=support_checks,causal_pressure_pivots_checked=pressure_checks,
  daily_close_signal_and_next_open_verified=True,closed_trades_checked=len(trades),cashflow_equity_reconciled=True,
  parameters_changed=False,holdout_accessed=False))
 shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
 print(json.dumps(dict(verified=True,summary=extra)),flush=True)
if __name__=='__main__':main()
