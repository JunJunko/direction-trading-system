"""Read-only diagnostics and report for frozen exit experiments."""
import csv,json,html,hashlib,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
O=ROOT/'runs/20261025-ihs-v3-exit-mechanisms'
B=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):return list(csv.DictReader(p.open(encoding='utf-8-sig',newline='')))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def table(headers,data):
 return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in data)+'</tbody></table></div>'
def num(x,n=2):return '' if x in ('',None) else f'{float(x):.{n}f}'
entries=load(O/'frozen-entries.json');plans={p['setup_id']:p for p in load(B/'plans.json')};market=load(O/'market-context.json')
tr={a:rows(O/'base'/a/'trades.csv') for a in ['E0','E1','E2','E3']}
daily={a:rows(O/'base'/a/'daily-audit.csv') for a in tr}
failed=[r for r in tr['E0'] if r['closed']=='True' and float(r['own_MFE'])/float(r['initial_R'])<1]
needed={r['symbol'] for r in failed};bars={s:[] for s in needed}
with (B/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
 for r in csv.DictReader(f):
  if r['symbol'] in needed and r['date']<='20260930':bars[r['symbol']].append(r)
failaudit=[]
for r in failed:
 a=next(e for e in entries if e['setup_id']==r['setup_id']);p=plans[r['setup_id']];bs=sorted(bars[r['symbol']],key=lambda x:x['date']);i=next(i for i,b in enumerate(bs) if b['date']==a['signal_date']);b=bs[i];factor=float(b['factor']);neck=p['ihs_neckline']
 after=[x for x in bs[:i+1] if x['date']>p['ihs_known_at']]
 lows=[float(x['low'])*float(x['factor'])/factor for x in after]
 previous=float(bs[i-1]['close'])*float(bs[i-1]['factor'])/factor
 passed=(min(lows)>=neck*.975 and min(lows)<=neck*1.005 and float(b['close'])>max(neck,float(b['open']),previous) and float(b['close'])<=neck*1.02 and len(after)<=14)
 assert passed
 held=[x for x in daily['E0'] if x['setup_id']==r['setup_id'] and x['close_observed_while_held']=='True']
 under=[x for x in held if float(x['close'])<float(x['neckline'])];broken=[x for x in held if float(x['low'])<float(x['neckline'])*.975]
 atr=[]
 for j in range(i-13,i+1):
  x=bs[j];sc=float(x['factor'])/factor;pc=float(bs[j-1]['close'])*float(bs[j-1]['factor'])/factor
  atr.append(max(float(x['high'])*sc-float(x['low'])*sc,abs(float(x['high'])*sc-pc),abs(float(x['low'])*sc-pc)))
 row=dict(symbol=r['symbol'],signal_date=a['signal_date'],entry_date=a['date'],confirmation_passed=passed,neckline=neck,retest_low=p['ihs_retest_low'],retest_depth_pct=(p['ihs_retest_low']/neck-1)*100,initial_stop_distance_pct=(1-float(r['initial_stop'])/float(r['entry']))*100,stop_distance_signal_ATR=(float(r['entry'])-float(r['initial_stop']))/(sum(atr)/14),first_close_below_neckline=under[0]['date'] if under else None,first_low_below_failure_band=broken[0]['date'] if broken else None,MFE_R=float(r['own_MFE'])/float(r['initial_R']),**market[a['signal_date']])
 failaudit.append(row)
dump(O/'entry-failure-audit.json',failaudit)
with (O/'entry-failure-audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(failaudit[0]));w.writeheader();w.writerows(failaudit)
# Independent production and daily chronology checks.
diff=[]
for p in (B/'source/src').rglob('*.py'):
 q=ROOT/'src'/p.relative_to(B/'source/src')
 if not q.exists() or p.read_bytes()!=q.read_bytes():diff.append(str(q))
assert not diff
checks=0
for scenario in ['base','cost_1_5x','cost_2x']:
 for arm in tr:
  prev={}
  for r in rows(O/scenario/arm/'daily-audit.csv'):
   old=prev.get(r['setup_id'])
   if old and old['next_session_stop']:
    expected=float(old['next_session_stop'])*float(r['entry_price_current_scale'])/float(old['entry_price_current_scale'])
    assert abs(expected-float(r['effective_stop']))<1e-7
    checks+=1
   prev[r['setup_id']]=r
v=load(O/'verification.json');v.update(production_source_matches_v3=True,daily_stop_carry_checks=checks,entry_failure_confirmation_checks=len(failaudit));dump(O/'verification.json',v)
parts=['<h1>头肩底 v3：利润路径与出场机制诊断</h1><p>固定原始 14 笔入场、成交价格与数量。研究截止 2026-09-30；不修改正式策略，不重新筛选入场，不搜索参数。</p>', '<h2>1. 审计结论</h2><p><b>主要问题是原始出场规则允许利润回吐。</b>原始 trailing_stop 保持初始右肩止损；只有收盘达到形态测算目标才安排下一开盘卖出。没有启用保本、已确认波谷迁移或相关状态切换，因此不能归因为这些模块漏触发或确认滞后。E0 精确复现原始 11 笔卖出及 241 日现金、净值、回撤。11 笔亏损全部曾有正的收盘净浮盈，其中 7 笔达到收盘净 1R；没有达到目标后漏卖的证据。</p><p>持仓有利波动按整根已持有至收盘的日线计算，退出日全日高点排除；净浮盈扣除假设立即卖出的滑点、佣金和税。故数值略低于旧版只扣部分费用的审计。600063 的原始买价和退出时价格经过复权因子换算，不应直接用两者相减。</p>']
focus=['000935.SZ','600063.SH','002258.SZ']
focusrows=[]
for s in focus:
 for arm in tr:
  r=next(r for r in tr[arm] if r['symbol']==s);ds=[x for x in daily[arm] if x['symbol']==s];one=next((x['date'] for x in ds if x['close_net_R'] and float(x['close_net_R'])>=1),'未达到')
  focusrows.append([s,arm,one,r['exit_date'],num(r['exit'],5),r['exit_source'],num(r['net_pnl']),num(r['net_R'],3)])
parts.append(table(['股票','组别','首次收盘净1R','卖出日','模拟成交价','有效保护来源','净损益元','净R'],focusrows))
parts.append('<p>结构保护也可能过早退出：600063 在 E2/E3 于 2025-11-03 亏损退出，随后才出现大幅上涨。000935 的 E1 仅保住很小利润，E2/E3 在本样本保留了部分利润；不能据此认定组合规则已具备样本外优势。</p>')
labels=['日期','当期入场价','初始止损','颈线','回踩低点','已知持仓最高价','收盘净浮盈R','当日有效止损','下一交易日止损','下一交易日','退出原因','模拟成交价','日末状态','收盘决策']
keys=['date','entry_price_current_scale','initial_stop_current_scale','neckline','retest_low','known_holding_peak','close_net_R','effective_stop','next_session_stop','next_session','exit_trigger','simulated_fill','state_at_close','decision_reasons']
for s in focus:
 for arm in tr:
  data=[[num(r[k],4) if k in keys[1:9] or k=='simulated_fill' else r[k] for k in keys] for r in daily[arm] if r['symbol']==s]
  parts.append(f'<details><summary>{s} · {arm} 逐日审计（{len(data)} 日）</summary>'+table(labels,data)+'</details>')
parts.append('<h2>2. 固定入场的独立对照</h2><p>E0：原始退出。E1：收盘净浮盈≥1R，下一交易日起启用含成本保本价。E2：入场后已确认的更高波谷（左右各 2 根日K），扣减选取时前置 ATR14 的 0.5 倍作为缓冲；该缓冲随后冻结，下一交易日起生效。E3：两者结合取更高保护。全部保留原始目标退出，止损仅上移。E2 可在尚未达到 1R 时减少风险。本次参数事先固定，没有逐笔调优。</p>')
comp=load(O/'comparison.json')
parts.append(table(['成本','组别','平/未平','总损益元¹','平均净R¹','已平平均R','已平胜率','最大回撤','自身MFE兑现²','E0参考兑现²','曾盈转亏','≥1R转亏','提前截断代理³'],[[r['scenario'],r['arm'],f"{r['closed']}/{r['open']}",num(r['net_pnl']),num(r['mean_net_R_all_including_open'],3),num(r['mean_net_R_closed'],3),num(r['win_rate_closed']*100)+'%',num(r['max_drawdown_pct'])+'%',num(r['own_MFE_capture_closed']*100)+'%',num(r['E0_reference_MFE_capture_closed']*100)+'%',r['profit_to_loss'],r['at_least_1R_to_loss'],f"{r['early_trend_cut_full20']}完整+{r['early_trend_cut_partial']}不足20日"] for r in comp]))
parts.append('<p>¹ 总损益和全样本平均R含期末持仓按收盘市值计价，未扣尚未发生的卖出费用；另列已平仓平均R。R分母固定为原始含成本预期止损金额。² 兑现比例=已平仓净损益合计/对应MFE金额合计；负数表示有过浮盈却最终净亏。自身窗口可能因早卖而缩短，故同时列同笔 E0 持有窗口作参考。各组已平集合不同，逐笔配对表用于进一步判断。³ 正收益提前退出后，未来20交易日内（不超过E0终点）某日收盘估计净值比退出收益高至少1R；不足20日单列。这只是价格路径代理，不能视为可实现的漏赚金额。</p><p>成本压力：佣金率及卖出滑点分别乘 1、1.5、2；原始买入成交价冻结，买入佣金重算，最低佣金5元及印花税不变。不是完整的买入滑点压力测试。模拟沿用冻结引擎的 T+1、停牌、跌停无法卖出、跳空按开盘处理和滑点；日线无法还原盘口排队或成交量冲击。仅收盘后调整保护，下一可执行时点生效，不能承诺跳空时仍精确保本。</p>')
paired=[]
for r in tr['E0']:
 rr=[next(x for x in tr[a] if x['setup_id']==r['setup_id']) for a in tr]
 paired.append([r['symbol'],r['entry_date'],r['quantity']]+[num(x['net_pnl'])+('（未平）' if x['closed']!='True' else '') for x in rr]+[num(float(rr[3]['net_pnl'])-float(r['net_pnl']))])
parts.append('<h3>逐笔配对净损益</h3>'+table(['股票','固定买入日','固定数量','E0','E1','E2','E3','E3−E0'],paired))
cuts=[[a,r['symbol'],r['exit_date'],r['post_exit_observations'],num(r['post_exit_best_net_R'],3)] for a in tr for r in tr[a] if r['early_trend_cut_proxy']=='True']
parts.append(table(['组别','提前截断代理股票','退出日','后续观察日数','后续最高收盘净R'],cuts))
parts.append('<h2>3. 未达到1R的入场失败</h2><p>下列三笔均满足当时 v3 的程序化回踩确认条件：突破登记之后的低点进入颈线触及带，未先跌破2.5%失败带，确认日收盘高于颈线、开盘和前收盘，且位于颈线上方2%以内。条件成立不代表趋势一定延续；回踩低点也不是原始止损，原始止损仍在右肩。</p>')
parts.append(table(['股票','信号日','回踩低点/颈线','止损距离','距离/信号日ATR14','首次收盘失守颈线','首次盘中破2.5%带','MFE/R','市场20日中位收益','20日上涨占比'],[[r['symbol'],r['signal_date'],num(r['retest_depth_pct'])+'%',num(r['initial_stop_distance_pct'])+'%',num(r['stop_distance_signal_ATR']),r['first_close_below_neckline'],r['first_low_below_failure_band'],num(r['MFE_R'],3),num(r['median_20d_return']*100)+'%',num(r['positive_20d_fraction']*100)+'%'] for r in failaudit]))
parts.append('<p>这三笔的市场20日中位收益均为正，不能笼统归因于市场普跌；市场指标来自冻结主板股票池、信号日已完成数据，并非官方指数，也不构成因果检验。000586 回踩较深且初始风险较宽；003016 的风险较窄，浮盈接近但未达1R；603172 的上行延续较弱。改进退出能减少部分亏损，但不会改变这些原始入场质量。三笔不足以据此重新选择阈值。</p><h2>4. 评价与验证边界</h2><p><b>本样本支持“需要检查利润保护”，不支持“策略已盈利”。</b>E3 的本样本结果最接近盈亏平衡，但基础及更高成本下均仍为负；E1 的较高胜率主要包括很小的保本收益。结构保护降低回吐，也会错过后续趋势。样本仅14笔且已经反复观察，不能作为独立验证集。</p><p>未访问 2026-09-30 之后数据。protocol.json 预留 2026-11-02 至 2027-10-29 的前瞻验证窗口，至少50笔已平事件、30只股票；按时间纳入全部合格事件，不足则延长，不反复调参。此处仅保存验证方案，尚未执行扩大样本或样本外验证，也未安排自动运行。正式策略保持不变。</p><h2>复核与下载</h2>')
for path,label in [('paired-trades.csv','全部成本逐笔配对'),('comparison.csv','12组指标'),('entry-failure-audit.csv','入场失败审计'),('protocol.json','冻结实验口径与后续验证方案'),('verification.json','验证记录')]:parts.append(f'<p><a href="{path}">{label}</a></p>')
for a in tr:parts.append(f'<p><a href="base/{a}/daily-audit.csv">{a} 全部逐日记录</a> · <a href="base/{a}/events.csv">状态和波谷确认事件</a> · <a href="base/{a}/orders.csv">成交订单</a></p>')
parts.append(f'<p>独立校验：{checks} 次跨日止损衔接；正式 src 与冻结 v3 的 Python 文件逐字节相同；7项研究机制测试通过。日表退出日净浮盈留空，避免使用退出后收盘信息；价格均按当日因子标度，经济保护不会因除权被误判为下移。</p>')
(O/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>v3 出场机制诊断</title><style>body{font:16px/1.7 system-ui;margin:36px auto;max-width:1500px;padding:0 24px;color:#182b42;background:#f5f7fb}table{border-collapse:collapse;background:white;font-size:13px;width:100%}td,th{padding:8px;border:1px solid #dae1eb;white-space:nowrap;text-align:right}th{background:#e6eef9}h1,h2{color:#183e70}.scroll{overflow:auto;margin:18px 0}details{margin:12px 0}summary{cursor:pointer;font-weight:bold}p{max-width:1200px}a{color:#1762a4}</style>'+''.join(parts),encoding='utf-8')
for p in [Path(__file__),ROOT/'scripts/test_ihs_exit_research.py']:shutil.copy2(p,O/'source'/p.name)
shutil.copy2(ROOT/'runs/ihs-v3-exit-mechanisms-tests.log',O/'tests.log')
print(json.dumps(failaudit,ensure_ascii=False,indent=2));print('REPORT COMPLETE',checks)
