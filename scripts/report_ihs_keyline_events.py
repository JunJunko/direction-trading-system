import json,csv,html,statistics,hashlib,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];O=ROOT/'audits/20261025-ihs-keyline-events'
def rows(n):return list(csv.DictReader((O/n).open(encoding='utf-8-sig',newline='')))
def table(h,rs):return '<div class="scroll"><table><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in h)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in r)+'</tr>' for r in rs)+'</table></div>'
def pct(x):return '—' if x is None else f'{x*100:.2f}%'
roles=dict(neckline='颈线',retest_low='回踩低点',right_shoulder='右肩',head='头部',higher_low='确认更高波谷');kinds=dict(wick_only='盘中跌穿收回',close_break='首次收盘失守',reclaim='失守后收复')
s=json.loads((O/'summary.json').read_text());v=json.loads((O/'verification.json').read_text());es=rows('events.csv');pairs=rows('matched-pairs.csv')
# Verify causal metadata and non-overlapping event identities independently.
assert len({(e['symbol'],e['role'],e['kind'],e['date']) for e in es})==len(es)
assert all(e['confirmed']<e['active']<=e['date'] for e in es)
for e in pairs:
 assert e['control_symbol']!=e['symbol'] and e['control_date']<=e['date']
 assert abs(float(e['event_market'])-float(e['control_market']))<=.030000001
balance=[]
for role in roles:
 for kind in kinds:
  ps=[p for p in pairs if p['role']==role and p['kind']==kind]
  if not ps:continue
  balance.append([roles[role],kinds[kind],len(ps)]+[round(statistics.mean(abs(float(p['event_'+k])-float(p['control_'+k])) for p in ps),4) for k in ['trend','vol','age','distance','market']])
body=[f'<h1>关键价格线的职责与预测价值</h1><p>探索性事件研究 · 冻结 v3 的 {v["plans"]} 个回踩信号、{v["symbols"]} 只股票 · 截止2026-09-30 · 正式交易规则未修改</p>', '<h2>研究问题</h2><p>先检验价格线失守后是否提供额外信息，再讨论它是否适合承担观察、停止加仓、减少风险或退出职责。本报告没有优化止损位置，也没有把未来收益作为选事件或匹配对照的依据。</p>',table(['价格线','职责假设','待验证的信息'],[['颈线','突破与支撑转换','突破是否失败，或只是暂时回踩'],['回踩低点','此次入场确认','本次买入依据是否失效'],['确认更高波谷','当前上涨段','上涨节奏是否中断'],['右肩','右侧底部抬高结构','是否需要重新探底'],['头部','大形态有效性','整体反转形态是否失效']]),'<h2>口径与因果时序</h2><p>每个信号后观察最多60个交易日。固定线在信号次日起生效；更高波谷采用严格左右各2根日K确认，确认次日起生效，且高于前一个确认波谷（首个参考为右肩）。不加ATR止损缓冲。同一价格线分别只记录第一次盘中跌穿收回、第一次收盘失守、首次失守后的第一次收复。后者从收复日开始评价，不回填到失守日。</p><p>未来1、3、5、10、20交易日：从事件收盘计算收益、最高/最低价相对变动、收盘收复关键线概率、收盘超越信号以来已知最高价概率。日线最高/最低是价格路径，不代表可实现收益；收复概率针对收盘失守最有解释力，其他事件中表示后续再收在该线上方。观察窗口有缺失或停牌跨度则排除，不把缺失当零收益。</p>',f'<p>共生成 {v["lines"]} 条线（含不同信号对应的线），去重前 {v["events_before_dedup"]} 个事件，按股票/角色/类型/日期去重后 {v["events"]} 个事件，{v["controls"]} 个候选守线对照，匹配 {v["matched_pairs"]} 对。不同角色重合于0.1ATR以内时保留标记，不合并为独立的总体样本。</p>','<h2>收盘失守后：20日路径</h2>']
headers=['角色','完整事件/股票','匹配对数','平均收益','最低价变动均值','最高价变动均值','收复概率','收复日数中位¹','恢复新高概率','相对守线收益差','95%区间²']
def resultrow(r):return [roles[r['role']],f"{r['complete']}/{r['symbols']}",r['matched'],pct(r['mean_return']),pct(r['mean_down']),pct(r['mean_up']),pct(r['reclaim_rate']),r['median_reclaim_days'],pct(r['newhigh_rate']),pct(r['delta_return']),f"[{pct(r['ci_low'])}, {pct(r['ci_high'])}]"]
body.append(table(headers,[resultrow(r) for r in s if r['kind']=='close_break' and r['horizon']==20]))
body.append('<p><b>本轮20日结果不支持把任一类关键线的一次收盘失守直接解释为持续下跌信号。</b>五类线的收复比例约75%—84%，匹配收益差区间均包含零。颈线与回踩低点失守后平均20日收益接近零；右肩、头部失守后平均收益为正，但恢复前高比例分别仅约13.4%、7.2%。这提示“局部反弹收复”和“原趋势恢复”需要分开评价，也可能反映深度回撤后的均值回归和样本环境，不能推出跌破后应买入。</p>')
body.append('<p>¹ 仅在窗口内成功收复的事件中计算，不能理解成所有失守都会在该日数内恢复。² 按事件股票聚类重抽样500次的点位区间；不足5只匹配股票不提供区间。未同时按对照股票与日期聚类，未校正多重检验，区间可能偏窄，不用于宣称已经验证的统计显著性。</p><h2>不同事件与时间窗口</h2>')
for kind in kinds:
 for h in [1,3,5,10,20]:body.append(f'<details><summary>{kinds[kind]} · 未来{h}日</summary>'+table(headers,[resultrow(r) for r in s if r['kind']==kind and r['horizon']==h])+'</details>')
body.append('<h2>可比基准与残余偏差</h2><p>对照是前收盘位于线上、此前未收盘失守、当日最低价处于线至线上0.5ATR内的守线事件。同一角色，选不同股票、过去120自然日内的事件，匹配信号年龄（差≤20日）、前20日趋势（差≤10个百分点）、波动率（比率≤2）、前收盘距线距离（差≤1ATR）以及市场代理趋势（差≤3个百分点）；按预先固定距离选最近对照，每个角色/事件类型内不重复使用。不同类型仍可能共享对照。</p><p>市场代理是583只信号样本股票截至前一日的20日收益中位数，不是全市场指数，存在选样偏差。匹配没有消除行业、日历冲击、结构跨度等全部差异；收益差是条件相关性，不能证明失守导致下跌。候选对照在未来20日内也可能失守，当前比较的是首次事件的信息差。</p>')
body.append(table(['角色','类型','配对数','趋势绝对差','波动率绝对差','年龄差(日)','距离差(ATR)','市场趋势差'],balance))
body.append('<h2>如何解释职责</h2><p>若某线失守后经常收复，且与守线对照差异不稳定，应优先视为观察信号；若持续下行与低收复率在不同窗口、不同股票和独立样本中一致，才有依据研究风险退出职责。右肩与头部天然更远、结构跨度更长，不能把命中率差异直接归结为“级别越高越重要”。更高波谷也可能仅代表短周期整理。本轮保留所有方向，包括不支持假设的结果。</p><p>当前全部历史数据都是已经使用过的开发样本，扩大至708个信号并不等于获得样本外证据。报告只给候选职责，尚不授予任何价格线正式卖出权限。2026-11-02至2027-10-29留作未访问的未来验证；先冻结算法与口径，再按时间纳入事件，按股票和时间块复验，并扩大头部等稀疏事件。未安排自动运行，未修改正式策略。</p><h2>数据与复核</h2>')
for f,label in [('events.csv','逐事件价格路径'),('controls.csv','守线候选基准'),('matched-pairs.csv','匹配及逐对结果'),('summary.csv','全部75组统计'),('protocol.json','冻结研究协议'),('verification.json','验证记录')]:body.append(f'<p><a href="{f}">{label}</a></p>')
(O/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>关键价格线事件研究</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:36px auto;padding:0 24px;color:#19304c;background:#f5f7fb}table{border-collapse:collapse;background:white;font-size:13px}td,th{padding:9px;border:1px solid #dce3ed;white-space:nowrap}th{background:#e4edf8}.scroll{overflow:auto;margin:20px 0}summary{cursor:pointer;padding:8px}h1,h2{color:#194679}p{max-width:1200px}</style>'+''.join(body),encoding='utf-8')
v.update(event_identity_unique=True,line_timing_independently_verified=True,matched_market_caliper_verified=True,forward_window_unit_tests=4)
(O/'verification.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
shutil.copy2(__file__,O/Path(__file__).name);shutil.copy2(ROOT/'scripts/test_ihs_keyline_events.py',O/'test_ihs_keyline_events.py')
print('REPORT COMPLETE')
for r in s:
 if r['kind']=='close_break' and r['horizon']==20:print(json.dumps(r,ensure_ascii=False))
