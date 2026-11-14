"""Render verified shared-account results separately from the fixed-entry cohort."""
import csv,html,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUNS=ROOT/'runs';OUT=RUNS/'20261025-mainboard-inverse-head-shoulders-v7-pressure-support'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def table(headers,data):return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in data)+'</table></div>'
def main():
 dirs=[RUNS/'20261025-mainboard-inverse-head-shoulders-v5-breakout-trend',RUNS/'20261025-mainboard-inverse-head-shoulders-v6-confirmed-support',OUT]
 summaries=[load(p/'summary.json') for p in dirs];extra=load(OUT/'path-summary.json');verify=load(OUT/'verification.json')
 assert verify['cashflow_equity_reconciled'] and verify['daily_close_signal_and_next_open_verified']
 body='<h1>头肩底 v7：动态压力转支撑回测</h1><p>2025-10-09 至 2026-09-30 · 241 个交易日 · 原全主板扫描 3,214 只股票、2,856,672 根日线 · 共用 1,713 个候选信号、1,209 只信号股票</p>'
 body+='<p>周线确认压力与波谷；日收盘有效突破压力后继续持有，将最高已突破压力上移为下一交易日起生效的支撑；收盘失守旧支撑后下一可执行开盘退出。没有固定止盈，也没有 2% 止损距离限制。</p>'
 body+='<h2>完整账户重跑</h2><p>以下三组均重新执行账户买入审批、数量计算和卖出。提前退出会释放资金并影响后续买入，因此买入笔数与仓位可以不同。v6 此处是完整账户结果，与此前冻结14笔的实验不同。</p>'
 metrics=[('买入 / 已平仓 / 未平仓',lambda s:f"{s['filled_buys']} / {s['closed_trades']} / {s['open_positions']}"),
  ('期末权益',lambda s:f"{s['final_equity']:,.2f}"),('总收益率（含期末持仓）',lambda s:f"{s['total_return']:.2%}"),
  ('最大回撤',lambda s:f"{abs(s['max_drawdown']):.2%}"),('已平仓胜率',lambda s:f"{s['win_rate']:.2%}"),
  ('已平仓利润因子',lambda s:f"{s['profit_factor']:.3f}")]
 body+=table(['指标','v5 原周线退出','v6 独立支撑＋日收盘','v7 压力转支撑'],[[name]+[fn(s) for s in summaries] for name,fn in metrics])
 body+=table(['v7补充指标','结果'],[
  ['已实现净损益',f"{extra['realized_pnl']:,.2f}"],['未平仓浮盈（未扣未来卖出费用）',f"{extra['open_marked_pnl']:,.2f}"],
  ['已平仓平均净R',f"{extra['mean_closed_R']:.3f}"],['盈利 / 亏损笔数',f"{extra['winners']} / {summaries[-1]['closed_trades']-extra['winners']}"],
  ['实现≥3R盈利笔数',extra['large_winners']],['≥3R盈利覆盖全部已实现亏损',f"{extra['large_winner_loss_coverage']:.1%}"],
  ['收盘曾达1R后亏损笔数',extra['close_1R_to_loss']],['压力突破后继续持有事件',extra['pressure_breakouts']],
  ['支撑上移事件',extra['support_raises']],['已确认压力事件',extra['pressure_confirmations']]])
 fixed=RUNS/'20261025-ihs-v7-fixed-entry-exits';fs=load(fixed/'summary.json')
 body+='<h2>独立退出配对：冻结原 v5 全部14笔买入</h2><p>仅改变退出机制，买入日期、价格、数量、初始止损和原始R不变，不使用释放资金追加交易。用于区分退出规则与后续资金利用的影响。</p>'
 body+=table(['组别','总净损益，含期末持仓','已平 / 未平','已平仓胜率','已平仓平均净R','最大回撤','收盘1R后转亏'],[(dict(E0='v5',E3='v6',E4='v7')[r['arm']],f"{r['net_pnl']:,.2f}",f"{r['closed']}/{r['open']}",f"{r['win_rate']:.2%}",f"{r['mean_closed_R']:.3f}",f"{r['max_drawdown']:.2%}",r['close_1R_to_loss']) for r in fs if r['cost']==1])
 body+='<h3>固定14笔的成本敏感性</h3><p>倍率作用于佣金率和卖出滑点，最低佣金、税率及冻结买价保持不变。此表不是完整账户提高成本后的重新选股结果。</p>'
 body+=table(['佣金与卖出滑点倍率','v7总净损益','已平仓胜率'],[(r['cost'],f"{r['net_pnl']:,.2f}",f"{r['win_rate']:.2%}") for r in fs if r['arm']=='E4'])
 ts=rows(OUT/'trades.csv');paths={p['setup_id']:p for p in load(OUT/'profit-paths.json')}
 body+='<h2>v7 实际已平仓交易</h2>'+table(['股票','买入日','卖出日','买价（卖出复权口径）','卖价','数量（含复权调整）','净损益','净R','持仓盘中MFE净R','退出原因'],[(t['symbol'],t['entry_date'],t['exit_date'],f"{float(t['entry']):.4f}",f"{float(t['exit']):.4f}",f"{float(t['quantity']):.2f}",f"{float(t['pnl']):,.2f}",f"{float(t['realized_r']):.3f}",f"{paths[t['setup_id']]['MFE_net_R']:.3f}",t['reason']) for t in ts])
 body+='<h2>期末未平仓</h2>'+table(['股票','买入日','买价','数量','账面净损益','账面R'],[(p['symbol'],p['entry_date'],f"{p['entry']:.4f}",p['quantity'],f"{paths[p['setup_id']]['final_net_pnl']:,.2f}",f"{paths[p['setup_id']]['final_net_R']:.3f}") for p in summaries[-1]['positions']])
 events=rows(OUT/'decisions.csv');allp=sorted(paths.values(),key=lambda p:(p['entry_date'],p['symbol']))
 body+='<h2>逐笔压力与支撑迁移记录</h2>'
 selected={'dynamic_pressure_confirmed','dynamic_pressure_breakout','main_protection_raised','dynamic_support_daily_break','no_confirmed_overhead_pressure'}
 for p in allp:
  es=[e for e in events if e.get('setup_id')==p['setup_id'] and e['event'] in selected]
  body+='<details><summary>'+html.escape(p['symbol']+' · '+p['entry_date'])+'</summary>'+table(['日期','事件','压力或支撑价（当日口径）','形成日','确认日','来源'],[(e['date'],e['event'],e.get('raw_protection') or e.get('pressure') or e.get('protection') or e.get('broken_pressures'),e.get('formed') or e.get('pressure_formed'),e.get('confirmed') or e.get('pressure_confirmed'),e.get('source') or e.get('origin') or e.get('action')) for e in es])+'</details>'
 body+='<h2>核验与适用范围</h2><p>数据和源码哈希已核验；1,713个候选及入场参数一致；逐笔实际风险和净收益风险比已检查；压力必须在突破前确认；支撑单向上移且从次日起生效；没有利用同日高点上移后按同日低点有利成交。T+1、阻塞、跳空和成本沿用原引擎，241天资金曲线与订单现金流已核对。</p>'
 body+='<p><b>这是已经多轮研究过的历史开发区间，不是样本外验证。本轮参数在结果出现前已固定，未按结果重调。完整账户只有37笔已平仓，不能据此确认稳定收益。</b>两个≥3R盈利的合计尚不足独立覆盖全部亏损，其余盈利也参与贡献。MFE扣除估计卖出成本，不包含退出日整根日线，峰值不是保证能实现的成交。复权采用合成总回报份额调整。</p>'
 body+='<p><a href="trades.csv">v7交易明细</a> · <a href="entry_audit.csv">入场审核</a> · <a href="decisions.csv">支撑压力事件</a> · <a href="profit-paths.json">利润路径</a> · <a href="verification.json">核验结果</a> · <a href="config.json">固定配置</a> · <a href="../20261025-ihs-v7-fixed-entry-exits/report.html">固定入场独立对照</a></p>'
 (OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>头肩底 v7 动态压力支撑回测</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:32px auto;padding:0 20px;color:#18324a}.scroll{overflow:auto}table{border-collapse:collapse;width:100%}td,th{padding:8px;border:1px solid #dce4ec;white-space:nowrap}th{background:#eef3f8}details{margin:12px 0;border:1px solid #ddd;padding:10px}summary{cursor:pointer}</style>'+body,encoding='utf-8')
 shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
 print(json.dumps(dict(report=str(OUT/'report.html'),verified=True)),flush=True)
if __name__=='__main__':main()
