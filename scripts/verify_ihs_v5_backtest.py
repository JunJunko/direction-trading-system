"""Reconcile frozen v5 signals, actual entry risks, trade cashflows and report."""
import csv,gzip,hashlib,html,json,math,shutil,sys
from statistics import median
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(sys.argv[1])
BASE=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v4-no-distance-cap'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def near(a,b):assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-8),(a,b)
def ordinal(d):return datetime.strptime(d,'%Y%m%d').toordinal()
def neck(p,d):
 return p['ihs_peak1_price']+(p['ihs_peak2_price']-p['ihs_peak1_price'])*(ordinal(d)-ordinal(p['ihs_peak1_date']))/(ordinal(p['ihs_peak2_date'])-ordinal(p['ihs_peak1_date']))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def main():
 manifest=load(OUT/'manifest.json');cfg=load(OUT/'config.json');summary=load(OUT/'summary.json')
 old=load(BASE/'summary.json');oldcfg=load(BASE/'config.json');plans=load(OUT/'plans.json')
 assert {k:v for k,v in cfg.items() if k!='strategies'}=={k:v for k,v in oldcfg.items() if k!='strategies'}
 assert manifest['bars_sha256']==load(BASE/'manifest.json')['bars_sha256']==sha(OUT/'bars.csv')
 assert sha(OUT/'config.json')==manifest['config_sha256']
 h=hashlib.sha256()
 for p in sorted((OUT/'source/src').rglob('*.py')):h.update(str(p.relative_to(OUT/'source/src')).encode());h.update(p.read_bytes())
 assert h.hexdigest()==manifest['code_sha256']
 events=Counter();files=list((OUT/'signal-events').glob('*.gz'));assert len(files)==3214
 for path in files:
  with gzip.open(path,'rt',encoding='utf-8') as f:
   for line in f:
    e=json.loads(line)
    if manifest['evaluation_start']<=e['date']<=manifest['evaluation_end']:events[e['event']]+=1
 assert dict(events)==summary['signal_counts']
 hist=defaultdict(list);symbols={p['symbol'] for p in plans}
 with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for b in csv.DictReader(f):
   if b['symbol'] in symbols:hist[b['symbol']].append(b)
 indexes={}
 for s,bs in hist.items():bs.sort(key=lambda b:b['date']);indexes[s]={b['date']:j for j,b in enumerate(bs)}
 rules=cfg['strategies'][0]['params'];pm={p['setup_id']:p for p in plans}
 assert len(pm)==len(plans)
 for p in plans:
  bs=hist[p['symbol']];ix=indexes[p['symbol']];i=ix[p['date']];factor=float(bs[i]['factor'])
  def price(j,k):return float(bs[j][k])*float(bs[j]['factor'])/factor
  def atr(t):return sum(max(price(j,'high')-price(j,'low'),abs(price(j,'high')-price(j-1,'close')),abs(price(j,'low')-price(j-1,'close'))) for j in range(t-14,t))/14
  a=atr(i);near(a,p['ihs_entry_atr'])
  near(p['stop'],price(ix[p['ihs_right_date']],'low')-rules['stop_buffer_atr']*a)
  near(p['target'],neck(p,p['date'])+neck(p,p['ihs_head_date'])-p['ihs_floor'])
  near(p['ihs_neckline'],neck(p,p['date']));near(p['trigger'],price(i,'close'))
  assert p['ihs_left_date']<p['ihs_peak1_date']<p['ihs_head_date']<p['ihs_peak2_date']<p['ihs_right_date']<p['date']
  assert p['ihs_known_at']<=p['date'] and p['ihs_breakout_date']==p['date']
  assert p['entry_mode']=='ihs_breakout' and 'ihs_retest_date' not in p
  assert p['trigger']>neck(p,p['date'])+rules['breakout_atr']*a
  assert price(i-1,'close')<=neck(p,bs[i-1]['date'])+rules['breakout_atr']*atr(i-1)
 audits=rows(OUT/'entry_audit.csv');filled=[a for a in audits if a['execution_reason']=='filled']
 for a in filled:
  p=pm[a['setup_id']];b=hist[a['symbol']][indexes[a['symbol']][a['date']]];scale=p['factor']/float(b['factor'])
  fill=float(a['fill']);stop=float(a['stop']);n=neck(p,a['date'])*scale;atr=p['ihs_entry_atr']*scale
  assert a['date']>p['date'];near(fill,float(b['open'])*(1+cfg['execution']['slippage']))
  near(stop,p['stop']*scale);near(float(a['target']),p['target']*scale)
  q=float(a['filled_quantity']);cost=cfg['execution'];commission=cost['commission_rate'];slip=cost['slippage']
  tax=cost['sell_tax_after_20230828'] if a['date']>='20230828' else cost['sell_tax_before_20230828']
  entry_fee=max(cost['minimum_commission'],q*fill*commission)
  stop_fill=stop*(1-slip);target_fill=float(a['target'])*(1-slip)
  loss=q*(fill-stop_fill)+entry_fee+max(cost['minimum_commission'],q*stop_fill*commission)+q*stop_fill*tax
  gain=q*(target_fill-fill)-entry_fee-max(cost['minimum_commission'],q*target_fill*commission)-q*target_fill*tax
  near(float(a['net_rr']),gain/loss);near(float(a['expected_loss']),loss)
  assert int(q)%100==0 and float(b['low'])<=fill<=float(b['high'])
  assert not float(b['up_limit']) or fill<float(b['up_limit'])-1e-5
  assert float(b['open'])>n and fill<=n+rules['max_entry_atr']*atr+1e-9
  assert fill-stop>=rules['min_stop_atr']*atr-1e-9
  assert float(a['net_rr'])>cfg['risk']['min_rr'] and float(a['expected_loss'])<=float(a['risk_budget'])+1e-8
  assert a['decision']=='BUY_ALLOWED'
 assert all(a['decision']=='NO_TRADE' for a in audits if a['execution_reason']!='filled')
 trades=rows(OUT/'trades.csv');orders=rows(OUT/'orders.csv');decisions=rows(OUT/'decisions.csv')
 for t in trades:
  assert t['exit_date']>t['entry_date']
  assert t['reason'] in ('ihs_trade_protection_break','deferred_ihs_trade_protection_break','weekly_main_trend_break')
  if t['reason']=='weekly_main_trend_break':
   assert any(e['setup_id']==t['setup_id'] and e['event']=='weekly_close_break' and e['date']<t['exit_date'] for e in decisions)
 cash=cfg['initial_cash']
 for o in orders:
  if o['status']=='filled':cash+=(-1 if o['side']=='buy' else 1)*float(o['price'])*float(o['quantity'])-float(o['fee'])
 curve=rows(OUT/'equity.csv');assert len(curve)==241;peak=cfg['initial_cash']
 for r in curve:peak=max(peak,float(r['equity']));near(float(r['drawdown']),float(r['equity'])/peak-1)
 near(float(curve[-1]['equity']),summary['final_equity']);near(float(curve[-1]['cash']),cash)
 open_cost=sum(p['entry']*p['quantity']+p['entry_fee'] for p in summary['positions'])
 near(sum(float(t['pnl']) for t in trades),cash-cfg['initial_cash']+open_cost)
 weeks=defaultdict(list)
 for d in load(OUT/'calendar.json')['open_dates']:weeks[datetime.strptime(d,'%Y%m%d').isocalendar()[:2]].append(d)
 week_index={d:j for j,ds in enumerate(weeks.values()) for d in ds};protections={}
 for e in decisions:
  if e['event']!='main_protection_raised':continue
  assert e['date']==e['confirmed'] and week_index[e['confirmed']]-week_index[e['formed']]==2
  assert float(e['new'])>protections.get(e['setup_id'],float('-inf'))
  protections[e['setup_id']]=float(e['new'])
 assert len(trades)==summary['closed_trades'] and len(filled)==summary['filled_buys']
 assert len(filled)==len(trades)+summary['open_positions']
 total_pnl=sum(float(t['pnl']) for t in trades);avg_r=sum(float(t['realized_r']) for t in trades)/len(trades) if trades else None
 detail=dict(all_3214_scanned=True,data_and_source_hash_verified=True,costs_and_account_equal_to_v4=True,
  signal_geometry_and_prior_ATR_checked=len(plans),actual_entry_risk_checked=len(filled),T1_and_exit_reason_checked=len(trades),
  cashflow_and_equity_checked=True,parameters_changed=False,holdout_used=False,realized_pnl=total_pnl,mean_closed_net_R=avg_r,
  execution_reasons=dict(Counter(a['execution_reason'] for a in audits)),exit_reasons=dict(Counter(t['reason'] for t in trades)),
  weekly_protection_raises=sum(e['event']=='main_protection_raised' for e in decisions))
 distances=[(float(a['fill'])-float(a['stop']))/float(a['fill']) for a in filled]
 detail['filled_stop_distance']=dict(min=min(distances),median=median(distances),max=max(distances)) if distances else None
 large=[t for t in trades if float(t['realized_r'])>=3]
 losses=-sum(float(t['pnl']) for t in trades if float(t['pnl'])<0)
 detail.update(closed_winners_at_least_3R=len(large),large_winner_loss_coverage=sum(float(t['pnl']) for t in large)/losses if losses else None,
               open_marked_pnl=summary['final_equity']-cfg['initial_cash']-total_pnl)
 dump(OUT/'verification-v5.json',detail);shutil.copy2(__file__,OUT/'source/verify_ihs_v5_backtest.py')
 def table(headers,data):
  return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in data)+'</table></div>'
 pct=lambda v:f'{v:.2%}'
 body='<h1>头肩底 v5：突破入场与周线趋势持仓</h1><p>2025-10-09 至 2026-09-30 · 241 个交易日 · 3,214 只股票 · 2,856,672 根日线</p>'
 body+='<p>不等待回踩；右肩下方 0.5 ATR 初始止损；距当日颈线最多 1 ATR；净收益风险比严格大于 3；无 2% 止损距离限制。形态目标只用于入场评估，持仓按已确认的周线主要波谷管理。</p>'
 body+='<p><b>与 v4 的比较同时包含入场、形态约束及退出机制变化，不能据此单独归因于取消回踩。历史数据已被多轮研究，本轮不是样本外验证，参数未按回测结果调整。</b></p>'
 body+='<p>计算方式：逐日因果扫描全部股票并冻结信号，再由扫描前冻结的原引擎回放；实际成交审核、账户风控与周线持仓管理均逐日计算。<a href="cached-replay-equivalence.json">抽样对照核验</a>确认普通形态重算与冻结信号回放的订单、交易、每日权益和审核记录一致。</p>'
 body+=table(['指标','v4 回踩买入','v5 突破买入'],[
  ['候选信号',old['signal_counts']['entry_intent'],len(plans)],['信号股票',old['signal_stocks'],len(symbols)],
  ['买入 / 已平仓 / 未平仓',f"{old['filled_buys']} / {old['closed_trades']} / {old['open_positions']}",f"{summary['filled_buys']} / {summary['closed_trades']} / {summary['open_positions']}"],
  ['期末权益',f"{old['final_equity']:,.2f}",f"{summary['final_equity']:,.2f}"],['总收益',pct(old['total_return']),pct(summary['total_return'])],
  ['最大回撤',pct(abs(old['max_drawdown'])),pct(abs(summary['max_drawdown']))],['已平仓胜率',pct(old['win_rate']) if old['win_rate'] is not None else '无成交',pct(summary['win_rate']) if summary['win_rate'] is not None else '无成交'],
  ['已实现损益','',f'{total_pnl:,.2f}'],['未平仓净浮盈（未扣未来卖出成本）','',f"{detail['open_marked_pnl']:,.2f}"],
  ['已平仓平均净 R','',f'{avg_r:.3f}' if avg_r is not None else '无成交'],['已平仓 ≥3R 盈利交易','',len(large)],
  ['≥3R 盈利覆盖已实现亏损倍数','',f"{detail['large_winner_loss_coverage']:.2f}" if losses else '无亏损'],
  ['周线保护上移次数','',detail['weekly_protection_raises']]])
 if distances:body+='<p>实际成交初始止损距离：最小 '+pct(min(distances))+'，中位数 '+pct(median(distances))+'，最大 '+pct(max(distances))+'。这是价格距离；账户单笔计划风险仍受 0.5% 预算约束，跳空可能使实际损失超出计划。</p>'
 body+='<h2>拒绝与执行原因</h2>'+table(['原因','数量'],detail['execution_reasons'].items())
 body+='<h2>逐笔已平仓交易</h2>'+table(['股票','买入日','卖出日','买价','卖价','数量','净损益','净 R','退出原因'],[(t['symbol'],t['entry_date'],t['exit_date'],f"{float(t['entry']):.4f}",f"{float(t['exit']):.4f}",t['quantity'],f"{float(t['pnl']):,.2f}",f"{float(t['realized_r']):.3f}",t['reason']) for t in trades])
 body+='<h2>期末持仓</h2>'+table(['股票','买入日','买价','数量','初始止损'],[(p['symbol'],p['entry_date'],f"{p['entry']:.4f}",p['quantity'],f"{p['stop']:.4f}") for p in summary['positions']])
 body+='<p>收益包含期末持仓市值；胜率和平均净 R 仅统计已平仓。A 股 T+1、停牌、涨跌停、跳空、费用和滑点按日线引擎模拟。日线无法还原全部盘中路径。</p><p><a href="trades.csv">交易记录</a> · <a href="entry_audit.csv">入场审核</a> · <a href="verification-v5.json">核验结果</a> · <a href="config.json">固定配置</a></p>'
 (OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>头肩底 v5 回测</title><style>body{max-width:1150px;margin:32px auto;padding:0 18px;font-family:system-ui;line-height:1.6}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:7px;text-align:left}.scroll{overflow:auto}th{background:#eef3fa}</style>'+body,encoding='utf-8')
 print(json.dumps(detail,ensure_ascii=False))
if __name__=='__main__':main()
