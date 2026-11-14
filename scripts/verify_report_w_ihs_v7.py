"""Reconcile population, signals, entry brackets, causal support and joint-account ledgers."""
import ast,csv,hashlib,html,json,math,shutil,sys
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/20261025-w-ihs-v7-shared-account'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def near(a,b):assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-7),(a,b)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def table(headers,data):return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in data)+'</table></div>'
def main():
 m=load(OUT/'manifest.json');assert sha(OUT/'bars.csv')==m['bars_sha256']
 h=hashlib.sha256()
 for p in sorted((OUT/'source/src').rglob('*.py')):h.update(str(p.relative_to(OUT/'source/src')).encode());h.update(p.read_bytes())
 assert h.hexdigest()==m['code_sha256']
 ws=Path(m['source_W_scan']);iscan=Path(m['source_IHS_scan'])
 assert load(ws/'verification.json')['cohort_99_entry_plans_exact']
 assert load(ws/'manifest.json')['stocks']==3214 and load(iscan/'manifest.json')['stocks']==3214
 canonical={p['setup_id']:p for source in (ws,iscan) for p in load(source/'plans.json')}
 labels=('baseline_w','candidate_w','baseline_combined','candidate_combined')
 cases={label:dict(folder=OUT/label,summary=load(OUT/label/'summary.json'),config=load(OUT/label/'config.json'),
  fills=[a for a in rows(OUT/label/'entry_audit.csv') if a.get('execution_reason')=='filled'],
  trades=rows(OUT/label/'trades.csv'),events=rows(OUT/label/'decisions.csv'),orders=rows(OUT/label/'orders.csv'),curve=rows(OUT/label/'equity.csv')) for label in labels}
 needed={a['symbol'] for c in cases.values() for a in c['fills']};hist=defaultdict(list)
 with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for b in csv.DictReader(f):
   if b['symbol'] in needed:hist[b['symbol']].append(b)
 ix={}
 for symbol,bs in hist.items():bs.sort(key=lambda b:b['date']);ix[symbol]={b['date']:j for j,b in enumerate(bs)}
 cal=load(OUT/'calendar.json');groups={}
 for d in cal['open_dates']:groups.setdefault(datetime.strptime(d,'%Y%m%d').isocalendar()[:2],[]).append(d)
 weeks=list(groups.values());wi={d:j for j,ds in enumerate(weeks) for d in ds};weekly_cache={}
 def price(b,k):return float(b[k])*float(b['factor'])
 def pivot(symbol,formed,confirmed,kind):
  key=(symbol,formed,confirmed,kind)
  if key in weekly_cache:return weekly_cache[key]
  i=wi[formed];assert weeks[i][-1]==formed and weeks[i+2][-1]==confirmed
  bs=hist[symbol];known={b['date']:b for b in bs};vals=[]
  for ds in weeks[i-2:i+3]:
   assert all(d in known for d in ds)
   vals.append((max(price(known[d],'high') for d in ds),min(price(known[d],'low') for d in ds)))
  hi=all(vals[2][0]>v[0] for j,v in enumerate(vals) if j!=2);lo=all(vals[2][1]<v[1] for j,v in enumerate(vals) if j!=2)
  assert hi!=lo and (hi if kind=='H' else lo)
  weekly_cache[key]=vals[2][0 if kind=='H' else 1];return weekly_cache[key]
 diagnostics={}
 for label,c in cases.items():
  folder=c['folder'];cfg=c['config'];summary=c['summary'];cost=cfg['execution'];filled=c['fills'];events=c['events'];trades=c['trades']
  aliases=load(folder/'signal-aliases.json');plans=load(folder/'plans.json');pm={p['setup_id']:p for p in plans};fam=load(folder/'strategy-families.json')
  specs={s['id']:s for s in cfg['strategies']};byid={a['setup_id']:a for a in filled}
  for p in plans:
   orig=canonical[aliases[p['setup_id']]];adjust=dict(p,setup_id=orig['setup_id'])
   if 'w_owner' in adjust:adjust['w_owner']=orig['w_owner']
   adjust['target_exit_rule']=orig['target_exit_rule']
   assert adjust==orig
  entry_day_stop_touches=0
  for a in filled:
   p=pm[a['setup_id']];b=hist[a['symbol']][ix[a['symbol']][a['date']]];scale=p['factor']/float(b['factor'])
   fill,stop,target,q=(float(a[k]) for k in ('fill','stop','target','filled_quantity'))
   assert a['date']>p['date'];near(fill,float(b['open'])*(1+cost['slippage']));near(stop,p['stop']*scale);near(target,p['target']*scale)
   assert float(b['low'])<=fill<=float(b['high']) and q%100==0
   assert not float(b['up_limit']) or fill<float(b['up_limit'])-1e-5
   entry_day_stop_touches+=float(b['low'])<=stop
   if fam[a['strategy']]=='W':
    near(stop,p['w_retest_low']*scale)
    assert (fill-stop)/fill<=p['w_max_entry_risk']+1e-12
    assert p['w_retest_low_date']<=p['w_retest_confirmed']==p['date']
   else:
    ord=lambda d:datetime.strptime(d,'%Y%m%d').toordinal()
    n=p['ihs_peak1_price']+(p['ihs_peak2_price']-p['ihs_peak1_price'])*(ord(a['date'])-ord(p['ihs_peak1_date']))/(ord(p['ihs_peak2_date'])-ord(p['ihs_peak1_date']))
    at=p['ihs_entry_atr']*scale
    assert float(b['open'])>n*scale and fill<=n*scale+p['ihs_max_entry_atr']*at+1e-9
    assert fill-stop>=p['ihs_min_stop_atr']*at-1e-9
   ef=max(5,q*fill*cost['commission_rate']);sf=stop*(1-cost['slippage']);tf=target*(1-cost['slippage']);tax=cost['sell_tax_after_20230828']
   loss=q*(fill-sf)+ef+max(5,q*sf*cost['commission_rate'])+q*sf*tax
   gain=q*(tf-fill)-ef-max(5,q*tf*cost['commission_rate'])-q*tf*tax
   near(loss,float(a['expected_loss']));near(gain/loss,float(a['net_rr']))
   assert loss<=float(a['risk_budget'])+1e-8 and gain/loss>cfg['risk']['min_rr']
  cash=cfg['initial_cash']
  for o in c['orders']:
   if o['status']=='filled':cash+=(-1 if o['side']=='buy' else 1)*float(o['price'])*float(o['quantity'])-float(o['fee'])
  curve=c['curve'];assert len(curve)==241;peak=cfg['initial_cash']
  for v in curve:
   peak=max(peak,float(v['equity']));near(float(v['drawdown']),float(v['equity'])/peak-1)
   assert int(v['positions'])<=cfg['risk']['max_positions']
  near(cash,float(curve[-1]['cash']));near(float(curve[-1]['equity']),summary['final_equity'])
  realized=sum(float(t['pnl']) for t in trades);open_cost=sum(p['entry']*p['quantity']+p['entry_fee'] for p in summary['positions'])
  near(realized,cash-cfg['initial_cash']+open_cost)
  assert len(filled)==len(trades)+summary['open_positions']==summary['filled_buys']
  assert len({p['symbol'] for p in summary['positions']})==summary['open_positions']
  last={};raises=defaultdict(list);pressure_count=flip_count=support_count=0
  for e in events:
   pid=e.get('setup_id')
   if pid not in byid:continue
   symbol=e['symbol'];kind=e['event']
   if kind=='dynamic_pressure_confirmed':
    near(float(e['economic_pressure']),pivot(symbol,e['formed'],e['confirmed'],'H'));assert e['confirmed']<=e['date'];pressure_count+=1
   if kind=='main_protection_raised':
    a=byid[pid];entrybar=hist[symbol][ix[symbol][a['date']]];floor=float(a['stop'])*float(entrybar['factor']);new=float(e['new'])
    assert new>max(floor,last.get(pid,floor));last[pid]=new
    b=hist[symbol][ix[symbol][e['date']]];near(float(e['raw_protection'])*float(b['factor']),new)
    if e.get('source')=='broken_confirmed_pressure':
     br=next(v for v in events if v.get('setup_id')==pid and v['event']=='dynamic_pressure_breakout' and v['date']==e['date'])
     assert br['pressure_confirmed']<br['date'];near(new,pivot(symbol,br['pressure_formed'],br['pressure_confirmed'],'H'))
     bs=hist[symbol];i=ix[symbol][e['date']]
     at=sum(max(price(bs[j],'high')-price(bs[j],'low'),abs(price(bs[j],'high')-price(bs[j-1],'close')),abs(price(bs[j],'low')-price(bs[j-1],'close'))) for j in range(i-14,i))/14
     near(at/float(b['factor']),float(br['atr']));near(max(ast.literal_eval(br['broken_pressures']))*float(b['factor']),new)
     assert price(b,'close')>new+specs[a['strategy']]['params']['pressure_breakout_atr']*at
     flip_count+=1
    else:
     near(new,pivot(symbol,e['formed'],e['confirmed'],'L'));assert weeks[wi[e['formed']]][0]>a['date']
    raises[pid].append(e);support_count+=1
  for e in events:
   if e['event'] not in ('dynamic_support_daily_break','weekly_close_break'):continue
   pid=e['setup_id'];previous=[v for v in raises[pid] if v['date']<e['date']];assert previous
   b=hist[e['symbol']][ix[e['symbol']][e['date']]];level=float(previous[-1]['new'])
   near(level,float(e['protection'])*float(b['factor']));assert price(b,'close')<level
  for t in trades:
   assert t['entry_date']<t['exit_date']
   if t['reason']=='dynamic_support_daily_break':
    event=next(e for e in events if e.get('setup_id')==t['setup_id'] and e['event']==t['reason']);assert event['date']<t['exit_date']
    b=hist[t['symbol']][ix[t['symbol']][t['exit_date']]];near(float(t['exit']),max(float(b['low']),float(b['open'])*(1-cost['slippage'])))
    for d in cal['open_dates']:
     if event['date']<d<t['exit_date'] and d in ix[t['symbol']]:
      prev=hist[t['symbol']][ix[t['symbol']][d]]
      assert float(prev['volume'])<=0 or (float(prev['down_limit']) and float(prev['high'])<=float(prev['down_limit'])+1e-5)
  attribution=[]
  for sid,family in fam.items():
   ts=[t for t in trades if t['strategy']==sid];opens=[p for p in summary['positions'] if p['strategy']==sid];op=0
   for p in opens:
    b=max((b for b in hist[p['symbol']] if b['date']<='20260930'),key=lambda b:b['date'])
    op+=(float(b['close'])-p['entry'])*p['quantity']-p['entry_fee']
   pnl=sum(float(t['pnl']) for t in ts)
   attribution.append(dict(strategy=sid,family=family,buys=sum(a['strategy']==sid for a in filled),closed=len(ts),open=len(opens),
    realized_pnl=pnl,open_marked_pnl=op,total_pnl=pnl+op,win_rate=sum(float(t['pnl'])>0 for t in ts)/len(ts) if ts else None,
    mean_closed_R=sum(float(t['realized_r']) for t in ts)/len(ts) if ts else None))
  near(sum(a['total_pnl'] for a in attribution),summary['final_equity']-summary['initial_cash'])
  loss=-sum(min(float(t['pnl']),0) for t in trades)
  diagnostic=dict(filled_buys=len(filled),closed=len(trades),realized_pnl=realized,open_marked_pnl=summary['final_equity']-summary['initial_cash']-realized,
   mean_closed_R=sum(float(t['realized_r']) for t in trades)/len(trades) if trades else None,
   large_winners=sum(float(t['realized_r'])>=3 for t in trades),
   large_winner_loss_coverage=sum(float(t['pnl']) for t in trades if float(t['realized_r'])>=3)/loss if loss else None,
   causal_pressure_confirmations_checked=pressure_count,causal_pressure_to_support_checked=flip_count,support_raises_checked=support_count,
   attribution=attribution,entry_day_stop_touches=entry_day_stop_touches,duplicate_entry_rejections=sum(a.get('risk_reason')=='symbol_already_owned' for a in rows(folder/'entry_audit.csv')),
   execution_reasons=dict(Counter(a.get('execution_reason') for a in rows(folder/'entry_audit.csv'))))
  dump(folder/'verification.json',dict(candidates_match_full_scans=True,actual_entry_brackets_and_cost_RR_checked=len(filled),
   causal_pressure_confirmations_checked=pressure_count,causal_pressure_promotions_checked=flip_count,monotonic_support_checked=support_count,
   T1_checked=True,daily_signal_next_executable_open_checked=True,cashflow_241_equity_rows_checked=True,account_attribution_reconciled=True))
  dump(folder/'diagnostics.json',diagnostic);diagnostics[label]=diagnostic
  print(json.dumps(dict(case=label,verified=True,diagnostics=diagnostic)),flush=True)
 dump(OUT/'diagnostics.json',diagnostics)
 title={'baseline_w':'双底原卖出','candidate_w':'双底＋v7卖出','baseline_combined':'双底＋头肩底原卖出','candidate_combined':'双底＋头肩底＋v7卖出'}
 ihs=load(ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v7-pressure-support/summary.json')
 body='<h1>双底＋头肩底：统一动态压力/支撑卖出回测</h1><p>2025-10-09 至 2026-09-30 · 241交易日 · 两种形态均覆盖3,214只股票 · 同一份2,856,672根日线</p>'
 body+=f'<p>双底全市场候选 {m["W_signals"]} 个，头肩底候选 {m["IHS_signals"]} 个。双底采用原v5.19合格W回踩入场，头肩底采用v5突破入场；仅替换卖出管理。双底原有2%局部入场风险距离约束保留，头肩底没有2%距离上限。两者共享相同账户风险预算。</p>'
 combined_order=['candidate_w','candidate_ihs','candidate_combined']
 body+='<h2>v7卖出：单独运行与组合账户</h2>'+table(['策略','买入/已平/未平','收益率（含持仓）','最大回撤','已平仓胜率','利润因子','期末权益'],[(title[k] if k!='candidate_ihs' else '头肩底＋v7卖出',f"{s['filled_buys']}/{s['closed_trades']}/{s['open_positions']}",f"{s['total_return']:.2%}",f"{abs(s['max_drawdown']):.2%}",f"{s['win_rate']:.2%}" if s['win_rate'] is not None else '无成交',f"{s['profit_factor']:.3f}" if s['profit_factor'] is not None else '无亏损',f"{s['final_equity']:,.2f}") for k in combined_order for s in [ihs if k=='candidate_ihs' else cases[k]['summary']]])
 body+='<h2>相同入场候选、完整账户重跑：原卖出对照</h2>'+table(['组别','收益率','最大回撤','买入笔数','已平仓胜率','平均已平仓净R','实现≥3R盈利笔数'],[(title[k],f"{c['summary']['total_return']:.2%}",f"{abs(c['summary']['max_drawdown']):.2%}",c['summary']['filled_buys'],f"{c['summary']['win_rate']:.2%}" if c['summary']['win_rate'] is not None else '无成交',f"{diagnostics[k]['mean_closed_R']:.3f}" if diagnostics[k]['mean_closed_R'] is not None else '无成交',diagnostics[k]['large_winners']) for k,c in cases.items()])
 body+='<p>各独立账户均从100万元开始；组合也是总共100万元，最多5只持仓、总仓位50%、单笔风险0.5%、总风险2%，不将两种策略的独立收益相加。信号固定按双底优先、头肩底其次，再按股票代码排序。一个股票只持有一个仓位。退出提前释放资金后会重新审核后续买入，因此成交数及数量可以不同。</p>'
 cd=diagnostics['candidate_combined'];cs=cases['candidate_combined']['summary']
 body+='<h2>组合账户实际贡献</h2>'+table(['策略','买入/已平/未平','已实现净损益','未平仓账面损益','合计贡献','已平仓胜率'],[(a['family'],f"{a['buys']}/{a['closed']}/{a['open']}",f"{a['realized_pnl']:,.2f}",f"{a['open_marked_pnl']:,.2f}",f"{a['total_pnl']:,.2f}",f"{a['win_rate']:.2%}" if a['win_rate'] is not None else '无成交') for a in cd['attribution']])
 body+=f'<p>组合压力突破转支撑核验 {cd["causal_pressure_to_support_checked"]} 次，支撑上移核验 {cd["support_raises_checked"]} 次；已实现净损益 {cd["realized_pnl"]:,.2f} 元，未平仓账面损益 {cd["open_marked_pnl"]:,.2f} 元。利润归属按实际成交策略划分，不把同一股票重复计算。</p>'
 for label in ('candidate_w','candidate_combined'):
  folder=OUT/label;body+='<h2>'+title[label]+'：逐笔已平仓</h2>'+table(['策略','股票','买入日','卖出日','净损益','净R','退出原因'],[(load(folder/'strategy-families.json')[t['strategy']],t['symbol'],t['entry_date'],t['exit_date'],f"{float(t['pnl']):,.2f}",f"{float(t['realized_r']):.3f}",t['reason']) for t in cases[label]['trades']])
  body+='<p><a href="'+label+'/trades.csv">交易明细</a> · <a href="'+label+'/entry_audit.csv">入场审核</a> · <a href="'+label+'/decisions.csv">压力与支撑事件</a> · <a href="'+label+'/verification.json">核验结果</a> · <a href="'+label+'/config.json">固定配置</a></p>'
 body+='<h2>初始风险与T+1观察</h2>'+table(['账户','买入笔数','买入当日触及初始止损','初始/延迟止损平仓','动态支撑退出'],[(title[k],cases[k]['summary']['filled_buys'],diagnostics[k]['entry_day_stop_touches'],sum(v for reason,v in cases[k]['summary']['exit_reasons'].items() if reason in ('support_break','deferred_support_break','ihs_trade_protection_break','deferred_ihs_trade_protection_break')),cases[k]['summary']['exit_reasons'].get('dynamic_support_daily_break',0)) for k in ('candidate_w','candidate_combined')])
 body+='<h2>验证与边界</h2><p>本轮补齐双底全市场扫描，不将之前62只历史信号股票的结果冒充全市场。旧62只股票的99个入场信号、14笔成交及241天现金/权益/回撤均逐项复现。双底复权计算增加缓存，数值与原计算一致；两种策略没有改变入场或初始止损条件。</p><p>压力必须在突破前确认，新支撑次日起生效，只能上移；日收盘失守后下一可执行开盘卖出。未使用当日盘中高点提高支撑再按当日低点有利成交。T+1、涨跌停、停牌、跳空、成本、原引擎保守初始止损优先级与合成复权份额约定继续适用。</p><p><b>同一历史区间已被多轮研究，本轮不是样本外验证。参数、组合排序均在结果出现前固定，未按收益调整。</b>未平仓按市值计价，不扣未来卖出费用；单独策略与组合账户属于不同资金利用路径。</p>'
 body+='<p><a href="evaluation-plan.json">固定回测方案</a> · <a href="diagnostics.json">分组核验统计</a> · <a href="cohort_control/verification.json">旧双底复现核验</a> · <a href="../20261025-mainboard-inverse-head-shoulders-v7-pressure-support/report.html">头肩底v7完整报告</a></p>'
 (OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>双底＋头肩底 v7组合回测</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:32px auto;padding:0 20px;color:#18324a}.scroll{overflow:auto}table{border-collapse:collapse;width:100%}th,td{padding:8px;border:1px solid #dce4ec;white-space:nowrap}th{background:#eef3f8}</style>'+body,encoding='utf-8')
 shutil.copy2(__file__,OUT/'source'/Path(__file__).name);print('VERIFIED_AND_REPORTED',flush=True)
if __name__=='__main__':main()
