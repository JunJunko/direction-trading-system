import csv,json,html,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];O=ROOT/'runs/20261025-main-trend-mt1'
def rows(n):return list(csv.DictReader((O/n).open(encoding='utf-8-sig',newline='')))
def table(h,rs):return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in h)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in r)+'</tr>' for r in rs)+'</table></div>'
def f(x,n=2):return '—' if x is None else f'{float(x):.{n}f}'
def pct(x):return '—' if x is None else f'{x*100:.2f}%'
s=json.loads((O/'summary.json').read_text());tr=rows('paired-trades.csv');daily=rows('daily-audit.csv');ev=rows('events.csv') if (O/'events.csv').exists() else []
labels={'IHS':'头肩底 v3','W':'双底 v5.19'}
body=['<h1>MT1：固定周线主趋势跟踪实验</h1><p>小级别既有入场＋原始风险控制＋周线结构持有。只检验一个固定版本，不搜索最优参数，不改正式策略。</p><h2>先回答过拟合风险</h2><p>反复查看同一历史样本并改规则会形成适应性过拟合。此次预先保存单一协议，原始组与MT1独立配对。头肩底14笔与双底14笔均为已使用过的开发样本，不能因加入双底就称为样本外验证。失败结果同样保留，不据此调整周数或追加过滤条件。</p><h2>模块职责</h2><ol><li>入场、原始盈亏比门槛、成交数量、初始止损和初始风险金额全部冻结；原目标仍可用于原始入场资格判断，但不再作为MT1出场目标。</li><li>只用完整周线；主要高低点须左右各两周严格确认。交替出现 H1、L1、H2、L2，且 H2&gt;H1、L2&gt;L1，才确认上涨结构延续。同周兼具高低极值且顺序未知的枢轴忽略。</li><li>L2所在周必须开始于入场之后；只有高于初始止损且高于既有保护位时，才抬升趋势保护。保护使用复权不变的经济价格，不设ATR缓冲、机械保本或固定止盈。</li><li>原始止损继续日线盘中执行；趋势保护在周收盘失守后安排下一可执行开盘卖出。确认日不回填保护位，不利用当日高低先后顺序有利成交。跳空或跌停可能使亏损超出初始预算。</li></ol><p>初始止损和趋势保护是两种职责：前者限制入场判断错误，后者观察较大级别结构。没有确认上涨结构时继续保留初始风险，而不是放宽止损。周线确认带来至少两周滞后，这是允许回调的代价。</p><h2>配对结果</h2>']
body.append(table(['策略','成本倍数','组别','已平/未平','总损益元¹','已平损益元','已平平均R','胜率','利润因子','≥3R盈利笔数','大盈利覆盖亏损²','最大回撤','启用保护笔数'],[[labels[r['cohort']],r['cost'],r['arm'],f"{r['closed']}/{r['open']}",f(r['net_pnl']),f(r['closed_pnl']),f(r['mean_closed_R'],3),pct(r['win_rate']),f(r['profit_factor']),r['large_winners'],f(r['large_winner_loss_coverage']),pct(r['max_drawdown']),r['positions_with_protection']] for r in s]))
body.append('<p><b>结论：MT1未在两个策略上共同证明优于原始退出。</b>头肩底没有已平3R大盈利，虽然减少损失，仍亏损。双底出现2笔≥3R盈利，覆盖全部已平亏损约3.40倍，说明这种损益结构在本样本出现过；但原始双底有6笔≥3R盈利，总损益更高且回撤更低。MT1双底总损益约5.34万元，其中约1.94万元仍为未平浮盈；最大回撤约20.14%，不能把允许利润回吐直接解释为回吐程度合理。</p>')
body.append('<p>¹ 总损益包括未平仓按期末收盘市值估值，未扣尚未发生的卖出成本；不能将浮盈当作已实现大盈利。² ≥3R已平盈利金额合计/全部已平亏损金额绝对值；大于1才表示这些大盈利足以覆盖已平亏损。3R只用于评价分组，不触发卖出。利润因子=全部已平盈利/全部已平亏损。</p><h2>收益是否依赖少数大盈利</h2>')
body.append(table(['策略','组别','前三笔占正盈利','移除前三笔后的总损益','未平仓R'],[[labels[r['cohort']],r['arm'],pct(r['top3_positive_profit_share']),f(r['net_without_top3']),', '.join(f(x,3) for x in r['open_R']) or '无'] for r in s if r['cost']==1]))
for cohort in labels:
 rr=[r for r in tr if r['cohort']==cohort and float(r['cost'])==1];original={r['setup_id']:r for r in rr if r['arm']=='original'};candidate=[r for r in rr if r['arm']=='MT1'];out=[]
 for r in candidate:
  a=original[r['setup_id']];ds=[d for d in daily if d['cohort']==cohort and d['arm']=='MT1' and float(d['cost'])==1 and d['setup_id']==r['setup_id']]
  out.append([r['symbol'],r['entry_date'],r['quantity'],f(r['initial_stop'],4),a['exit_date'],f(a['net_pnl']),r['exit_date'] or '未平',r['exit_reason'],f(r['net_pnl']),f(r['net_R'],3),f(float(r['net_pnl'])-float(a['net_pnl'])),r['protection_raises'],len(ds),f(r['giveback_R'],3)])
 body.append(f'<h2>{labels[cohort]}：逐笔配对</h2>'+table(['股票','冻结买入日','数量','初始止损','原卖出日','原损益','MT1卖出日','原因','MT1损益','MT1净R','差额','保护抬升次数','观察交易日','MFE回吐R³'],out))
 # Two independent equity curves, no account entry re-gating.
 curves={a:rows(f'{cohort}-1-{a}-equity.csv') for a in ['original','MT1']};values=[float(r['equity']) for rs in curves.values() for r in rs];lo=min(values);hi=max(values);span=max(hi-lo,1)
 svg='<svg viewBox="0 0 1000 260" role="img" aria-label="固定入场净值对照"><rect width="1000" height="260" fill="white"/>'
 for a,color in [('original','#6e8195'),('MT1','#008d88')]:
  rs=curves[a];pts=' '.join(f"{35+i*930/max(1,len(rs)-1):.1f},{230-(float(r['equity'])-lo)/span*195:.1f}" for i,r in enumerate(rs));svg+=f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/>'
 svg+=f'<text x="35" y="20">原始：灰色　MT1：绿色　净值范围 {lo:,.0f} — {hi:,.0f} 元</text></svg>';body.append(svg)
body.append('<h2>固定成交实验的账户约束边界</h2>'+table(['策略','组别','最低现金','最高合并仓位'],[[labels[r['cohort']],r['arm'],f(r['min_cash']),pct(r['max_gross'])] for r in s if r['cost']==1]))
body.append('<p><b>双底MT1最高合并仓位65.32%，超过原账户50%上限。</b>逐笔入场与初始风险冻结不等于延长持仓后的账户风险仍合规。本实验为保持逐笔可比，没有因资金占用重新删减入场；结果不能直接用于实盘或作为正式账户回测收益。</p>')
body.append('<p>³ MFE回吐按持有至收盘的日线最高价毛浮盈减最终净损益计算，排除退出日全日高点；不是可实现利润损失，也不是本实验优化目标。持仓天数包括尚未平仓观察期。</p><h2>解释边界</h2><p>所有组沿用同一成交引擎的T+1、停牌、跌停、跳空、佣金、印花税和滑点处理。成本压力把佣金与卖出滑点乘1.5和2，买入价固定，最低佣金不变；不是完整的买入滑点压力。除权使用原引擎合成总回报数量调整，不是逐笔现金分红模型。</p><p>这是冻结原成交的退出配对实验，延长持仓后不重新审核后续入场的账户仓位上限。净值曲线是独立交易批次的现金合并，不代表能够原样执行的重新跑账户策略。两个策略分别评价，不合并宣称组合收益。</p><p>周线模块与原始策略的差异同时包括取消目标和结构退出，因此结果只能归于MT1整体，不能单独证明哪一部分有效。本轮不追加拆分实验。历史表现不能确认今后能靠少数大盈利覆盖亏损。</p><h2>后续验证约束</h2><p>冻结MT1与全部参数，保留2026-11-02至2027-10-29的未访问数据。按时间纳入全部原规则合格事件，累计至少50笔已平、30只股票后进行一次评价；不足则延长、不调参。评价仍以已平净R、大盈利覆盖亏损、成本稳健性、回撤和收益集中度为主。上线前另做完整账户约束验证，不自动修改正式策略。本次没有访问未来样本或创建定时任务。</p><h2>下载与复核</h2>')
for n,label in [('protocol.json','冻结协议'),('paired-trades.csv','全部逐笔配对'),('daily-audit.csv','逐日初始止损与趋势保护'),('events.csv','周线结构确认与退出事件'),('summary.csv','成本对照'),('verification.json','基线及输入一致性验证')]:
 if (O/n).exists():body.append(f'<p><a href="{n}">{label}</a></p>')
(O/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>MT1主趋势跟踪实验</title><style>body{font:16px/1.7 system-ui;margin:36px auto;max-width:1500px;padding:0 24px;background:#f5f7fb;color:#18334c}h1,h2{color:#174777}.scroll{overflow:auto;margin:18px 0}table{border-collapse:collapse;font-size:13px;background:white}td,th{padding:9px;border:1px solid #dae3ef;white-space:nowrap}th{background:#e4edf7}p,li{max-width:1250px}svg{width:100%;max-width:1000px}</style>'+''.join(body),encoding='utf-8')
shutil.copy2(__file__,O/'source'/Path(__file__).name);shutil.copy2(ROOT/'scripts/test_main_trend.py',O/'source/test_main_trend.py')
print('REPORT COMPLETE')
