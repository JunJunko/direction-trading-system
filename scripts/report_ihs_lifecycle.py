"""Archive the frozen experiment and publish account / trade / candle evidence."""
import html,shutil
from datetime import datetime
from backtest_ihs_lifecycle import ROOT,OUT,IHS,BASE,CASES,load,rows,dump,sha
from audit_candidate_policy import plt

NOTES={
1:'002928：盈利后新增日线保护确实抬高了支撑，但未触发更早退出；破位退出也保留原赢家。回踩版等到重新走强才确认，已超过入场距离限制。',
2:'600063：短期跌破颈线后重新走强。失败退出在11月5日卖出，把原盈利约5,285元变成亏损约2,002元；盈利后保护保持原退出。',
3:'600995：回踩版新增盈利，买后仍有颈线下震荡，最终上涨后退出；回踩确认并不表示买后立即走强。',
4:'001218：买后快速上涨再整理，各组实际退出日期相同；盈利达到1R不代表立即上移保护线。',
5:'600388：仅双倍成本账户的原单，失败退出在12月初的整理中卖出，错过后续上涨；不能将小额损益与图形涨幅直接等同。',
6:'000586的2025年10月形态：回踩后买入，短暂上涨后大阴线、次日低开，仍从浮盈变亏损。保护线不是保证成交价。',
7:'600057：回踩买入后长期震荡，曾有明显浮盈，2月跌破支撑后低开退出亏损；等待回踩没有解决后续回吐。',
8:'603901的10月形态：回踩版新增盈利，早期经历颈线下调整后上涨；与12月、1月形态分别统计。',
9:'002258：回踩版入场更晚、价格稍低，最终盈利增加；失败退出提前在11月卖出，原盈利变亏损。',
10:'603600：先涨后回落，各组退出日期一致；失败版金额变化来自账户仓位，不是更早止损。',
11:'603665：回踩确认后仍持续走弱，最终触及原硬止损；“已确认”没有过滤这类失败走势。',
12:'605086：保留直接入场的三组都抓到快速拉升；回踩版在上涨大阳线收盘确认时已太贵，被原入场上限拒绝。',
13:'000708：失败退出在第一次颈线下回撤卖出，双倍成本下比原持有至2月的亏损略小；标准成本为新增交易。',
14:'603901的12月形态：各组成交及卖出日期基本一致，获利退出后继续上涨不属于实际持有利润。',
15:'002271：原保护退出后才发生后续大涨，本轮三项变化没有改善这一退出时点；不同成本的小盈利/小亏来自费用与数量。',
16:'002430：各组仍在原支撑破位后退出，失败版盈利增加主要来自更多股数。',
17:'002829：失败版因账户路径改变新增买入，先冲高再按原保护线退出亏损；新增交易也计入策略成本。',
18:'002446：新增交易经历快速冲高与大幅回吐，最后按原动态支撑退出小亏；这笔并不是新增颈线失败规则直接卖出。',
19:'600258：回踩版买入更晚且更贵，退出仍在1月26日；双倍成本基准小盈利变成回踩版小亏。',
20:'600309：回踩后买入取得盈利，但持有阶段仍有波动，按原支撑退出。',
21:'601126：双倍成本回踩版新增，买后上涨并盈利退出；收益较小受实际仓位影响。',
22:'001311：迅速上涨后跌破原保护，各组退出一致；1R激活没有产生额外日线支撑。',
23:'603901的1月形态：买后很快持续转弱，失败规则提前一日退出，标准成本亏损约5,146→3,129元。',
24:'000629：买后快速上冲，各组日期相同；失败版收益增加主要是仓位更大。',
25:'002541的1月19日右肩形态：失败版1月23日提前占有该股，后来原2月2日形态没有再买。它仍亏约3,082元，不能说原约4,914元亏损被完全消除。',
26:'600966：失败版与回踩版分别新增；均有明显浮盈后转亏。失败版卖得更早，但金额差还包含入场时间与仓位差异。',
27:'002092：保留原上涨与退出路径，利润差主要来自股数；盈利激活没有改变卖点。',
28:'002135：原大赢家仍被失败版、盈利版保留；回踩确认推迟并抬高评估价格后净RR不达标，未成交。',
29:'002541的1月27日右肩形态：盈利版没有达到1R激活条件，仍走到原硬止损；不能把另一个锚点的成交当成同一笔改善。',
30:'001326：盈利激活后，2月13日低点到2月25日才完成右侧两根确认，保护线上移。3月20日收盘破线、3月23日低开退出，少亏约3,999元，但仍没锁住盈利。',
31:'002367：双倍成本原单先震荡后走弱，原保护退出小亏；盈利保护没有启动。',
32:'603507：回踩版新增的大赢家，两种成本买卖日期一致但仓位差很大；双倍成本利润更大不能理解为费用提高带来优势。',
33:'603281：双倍成本回踩版新增，确认入场后走弱触发硬止损。',
34:'000586的2026年3月形态：失败退出在下跌早期卖出，标准成本亏损约3,936→668元；盈利版未启动保护。',
35:'600389：双倍成本原单长期震荡下行，盈利版没有新增保护，保留原亏损退出。',
36:'603659：失败版在颈线下调整中卖出，原盈利约1,719元变亏损约2,169元；回踩版等待重返颈线后买入仍获利，但不比原单更好。',
37:'605366：买后上涨再回落，各组退出相同，盈利版金额小变动来自股数。',
38:'603989：盈利版6月4日抬高日线保护，6月12日破线，6月15日卖出。随后第二波大涨完全错过，利润28,116→16,499元；失败退出保留原7月14日卖点。',
39:'001300：买后持续转弱，失败退出5月15日卖出，标准成本亏损约5,095→2,031元；盈利版无激活。',
40:'002458：回踩确认后迅速下跌，两种成本都到原止损附近亏损退出，新增确认未过滤失败。',
41:'603688：回踩版新增买入后大幅下跌。标准成本7月1日退出，双倍成本7月7日退出，仓位/费用会改变原保护资格与账户路径。',
42:'603713：回踩确认后即转弱，原硬止损亏损退出；确认后仍有约一笔风险单位的亏损。',
43:'002800：直接入场后经历右肩附近下探再走高，前五赢家之一。回踩版把8月19日触及原右肩视为失效而取消；盈利版金额提高是仓位增加。',
44:'600493：原支撑退出保留，各组日期相同；盈利版盈利更多来自股数，不是卖点提升。',
45:'001231：各组原退出一致，盈利版仓位增加带来更高利润；不能归功于新增日线保护。',
46:'001336：回踩版入场更晚更贵，仍同日退出，亏损增加；盈利版亏损变化来自股数。',
47:'002591：双倍成本失败版提前卖出亏损，基准和盈利版期末仍持仓小幅浮盈。未平仓浮盈不能算已实现赢家。',
48:'000001：回踩版期末持仓，小幅浮盈，未画卖出线；不计入已平仓胜率与亏损笔数。',
49:'600692：失败版与硬止损版都在9月15日卖出，但失败版在开盘执行，原硬止损在盘中更低位置执行。盈利版金额更差主要是仓位增加。',
50:'601169：失败版9月18日提前卖出亏损；原基准和盈利版期末仍浮亏。不能把浮亏与已平仓亏损笔数混计。',
51:'002811：回踩版在原突破后的回撤末段确认买入，取得新增盈利；个别成功样本不足以弥补整体错失赢家与新增亏损。'}

def table(head,data):
    esc=lambda x:html.escape(str(x))
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in r)+'</tr>' for r in data)+'</tbody></table></div>'

def main():
    comp=rows(OUT/'comparison.csv');paths=rows(OUT/'trade-paths.csv');pairs=rows(OUT/'paired-trades.csv');attr=rows(OUT/'attribution.csv');audit=load(OUT/'audit-summary.json');verify=load(OUT/'verification.json');charts=load(OUT/'charts/index.json');excluded=load(OUT/'charts/exclusions.json')
    assert len(comp)==8 and len(paths)==199 and len(charts)==len(NOTES)==51 and len(excluded)==5 and all(v['passed'] for v in verify.values())
    labels={'baseline':'不追高开基准','retest':'回踩确认买入','failure':'突破失败退出','profit':'盈利后启动保护'}
    fig,axes=plt.subplots(1,2,figsize=(13,4),layout='constrained')
    for cost,ax in enumerate(axes,1):
        for rule in CASES:
            curve=rows(OUT/f'{rule}_cost{cost}'/'equity.csv');ax.plot([datetime.strptime(r['date'],'%Y%m%d') for r in curve],[(float(r['equity'])/1e6-1)*100 for r in curve],label=rule)
        ax.set_title(f'Cost {cost} | account return (%)');ax.grid(alpha=.2);ax.legend(fontsize=8);ax.tick_params(axis='x',rotation=20)
    fig.savefig(OUT/'charts/equity.png',dpi=120);plt.close(fig)
    b=['<h1>头肩底：入场、失败退出与盈利保护</h1><p>2026-11-10｜三个方向分别单变量｜8组完整账户回放｜199次买入，51个形态逐图核验</p>',
       '<p class="lead">本轮没有方案同时实现少亏、少回吐并保住大赢家收益。回踩确认明显拖累收益；突破失败退出有减少单笔损失的实例，也误卖后来走强的交易；盈利后保护将回撤明显压低，但提前截断最大赢家。维持“不追高开”研究基准，不将新规则设为默认。</p>',
       '<h2>全量对照</h2><p>使用同一3214只股票快照中的全部1713个原头肩底信号，逐日重放所有信号股票，重新计算资金、仓位和交易资格，不是只重算旧成交。评估2025-10-09至2026-09-30，预热从2023-01-03开始，初始资金100万元。形态检测不变，故复用冻结全量信号。</p>']
    b.append(table(['方案','成本','收益','最大回撤','买入/平仓','亏损笔数','亏损单合计','涨≥5%后亏损'],[[labels[r['case'].split('_')[0]],r['case'][-1],f"{float(r['total_return']):.3%}",f"{abs(float(r['max_drawdown'])):.3%}",r['filled_buys']+'/'+r['closed_trades'],audit[r['case']]['losses'],f"{audit[r['case']]['loss_pnl']:,.2f}",audit[r['case']]['gain5_then_loss']] for r in comp]))
    b.append('<p>金额为元，收益包含期末持仓市值；亏损笔数、亏损合计仅计已平仓。成本2将佣金率和双边滑点翻倍，最低佣金、印花税不变。成本会改变净RR、仓位及原保护规则资格，并非同一批交易只多扣费用。</p><img src="charts/equity.png" alt="8组账户收益曲线">')
    b.append('<h2>冻结规则与信息时点</h2>'+table(['方向','本轮唯一机制变化'],[
       ['回踩确认','原突破后最多10根股票日线等待。先出现最低价≤原斜颈线+0.25原信号ATR；必须再过至少一根K线，收阳且收盘高于前收盘和颈线+0.1原ATR，才提出次日开盘买入。期间最低价≤原右肩、最高价≥原目标或超期即取消。'],
       ['突破失败','保留原退出优先级；持仓后连续两根日线各自收盘<当日原斜颈线−0.5此前ATR14，下一可执行开盘退出。初始硬止损继续有效。'],
       ['盈利保护','收盘浮盈扣入场费、未扣假设退出费达到初始货币风险1R后激活。只采用激活日及之后形成的更高日线低点：左2右2严格分型，5根K线均在入场日之后。确认后以低点−0.5此前ATR14上移保护，下个股票交易日生效；收盘破位后下一开盘退出。']]))
    b.append('<p>回踩版保留原锚点、原右肩−0.5原信号ATR止损、原理论目标和原ATR，不重新锚定。每个信号只提交一次，遭拒也消费。所有组都保留“不追高开”、净RR严格大于3、目标空间大于5%、执行开盘仍在颈线上、入场不超过颈线+1原ATR等原约束。目标仍只是风险收益评估参考，不是触及即止盈。</p><p>盈利激活不是立刻保本，也不是达到1R就卖；须等待新低点右侧两根完成确认，且只能上移原保护。原压力转支撑与周线保护继续工作。三组未组合、未做阈值网格搜索，结果出来后未按赢家位置修改阈值。</p>')
    b.append('<h2>回踩确认：等待没有带来整体交易质量改善</h2><p>1713个原信号中，1014个完成再确认；104个触及原目标取消、257个跌破/触及原右肩取消、302个超时，剩余36个到期末仍等待。标准成本最终18次成交，10笔亏损；基准27次成交、8笔亏损。亏损单合计从29,078元增至32,100元。曾浮盈≥1R后转亏从1笔增至3笔，未解决回吐。</p><p>标准成本移除23笔原成交、新增14笔，共同4笔；并非只是把原27笔换一个买点。原前五大赢家全部未成交。新增赢家603507、002811等不足以弥补漏掉的盈利和新增亏损。</p>')
    translations={'quality_no_gap_up':'再确认后的执行日高开，被不追高开拒绝','ihs_breakout_entry_too_far':'确认时价格已超过颈线+1原ATR','right_shoulder_broken':'等待期间触及/跌破原右肩，先取消','net_rr_not_above_threshold':'延后确认价格提高，净RR不再严格大于3'}
    b.append(table(['错过的大赢家','原净利润','实际拒绝原因'],[[e['symbol'],f"{next(float(r['pnl']) for r in paths if r['case']=='baseline_cost1' and r['canonical_id']==e['canonical_id']):,.2f}",translations[e['reason']]] for e in excluded]))
    for e in excluded:b.append(f'<details><summary>{e["symbol"]} 回踩信号局部K线</summary><img loading="lazy" src="{e["chart"]}"></details>')
    b.append('<p>这些记录说明当前“回踩后再收强”与原入场距离、RR限制存在冲突，且“一次提交即消费”会在再确认后高开时永久错过原机会。002800则说明触及右肩就取消比原右肩下0.5ATR硬止损更严格。这里测试的是完整的本轮回踩机制；尚未单独测量等待、确认强度、失效边界各自的贡献。</p>')
    b.append('<h2>突破失败退出：减轻部分损失，也增加误卖</h2><p>标准成本净少3,246元，最大回撤略增；亏损笔数8→16，亏损合计仅减少约1,227元。双倍成本收益3.383%→2.926%，亏损合计反而增加约5,523元。标准成本原前五赢家均保留，合计利润64,318→64,253元；但其他盈利单被误卖。</p>')
    selected=('000586.SZ','001300.SZ','600063.SH','603659.SH','002258.SZ')
    b.append(table(['标准成本例子','原退出','新退出','原净损益','新净损益'],[[r['symbol'],r['old_exit'],r['new_exit'],f"{float(r['old_pnl']):,.2f}",f"{float(r['new_pnl']):,.2f}"] for r in pairs if r['case']=='failure_cost1' and r['category']=='shared' and r['symbol'] in selected]))
    b.append('<p>600063和603659都是颈线下调整后重新上涨；规则执行正确，并不表示它判对了趋势失败。标准成本另新增5笔交易，合计亏损5,998元。原002541的2月形态被移除，是因为已经持有1月另一右肩锚点的形态；后者亏损3,082元。它不是把原亏损完全过滤掉，也不是该单提前止损的纯效果。</p>')
    b.append('<h2>盈利后保护：回撤改善属实，但大赢家收益受损</h2><p>标准成本最大回撤4.019%→2.250%，减少约44%；双倍成本3.989%→2.057%，减少约48%。标准收益6.250%→5.694%，双倍成本3.383%→2.587%。两种成本亏损笔数分别保持8笔和9笔，亏损合计减少约2,517元和1,850元。它改善的是亏损幅度和账户回撤，未减少亏损笔数。</p><p>标准成本12次激活，但只有3次新增日线保护真正抬高原线：002928、001326、603989。002928退出不变；实际改写退出日期的只有后两笔。001326从−5,140→−1,142元，603989从+28,116→+16,499元，两笔直接差额合计−7,618元，账户总差额−5,567元还包含随后仓位变化。</p><p>001326的新保护约在入场复权基准58.07附近，高于买价56.01，但收盘破位后次日低开，实际卖价54.44，所以仍亏损。603989的新保护切掉了6月中旬的整理，也错过后面第二波大涨。不能把“退出后不再经历大回撤”直接当成“更好保留趋势利润”。</p><p>标准成本前五赢家仍5/5成交，合计利润从64,318降到54,709元（约保留85%）；双倍成本原前五合计49,650→38,629元。2,800等后续交易利润增加主要来自仓位变化，不能说是卖点改善。002541峰值浮盈不足1R，保护始终没有激活，原约4,914元亏损仍在。</p>')
    b.append('<h2>完整损益归因</h2>'+table(['方案/成本','移除/新增','共同交易差','移除贡献','新增贡献','原前五保留','原前五利润→新利润'],[[r['case'],r['removed']+'/'+r['added'],f"{float(r['shared_delta']):+,.2f}",f"{float(r['removed_delta']):+,.2f}",f"{float(r['added_delta']):+,.2f}",r['top5_retained']+'/5',f"{float(r['top5_original_pnl']):,.2f} → {float(r['top5_candidate_pnl']):,.2f}"] for r in attr]))
    b.append('<p>按原形态身份配对，包含期末浮动损益；同股不同锚点不合并。共同交易差包含入场、退出及股数变化，不能全部归因于单个卖点。浮盈峰值使用入场日至卖出前一日的收盘价格，排除卖出后行情；峰值净R含假设退出成本，与保护激活使用的未扣退出费浮盈R不是同一口径。</p>')
    b.append('<h2>逐笔K线核验</h2><p>已查看26张联系表覆盖全部51个成交形态，并查看5张错失赢家局部图。图中灰色为基准、蓝色回踩、橙色失败退出、紫色盈利保护；横线为次日才生效的动态支撑，红虚线为初始硬止损，黄线为原斜颈线。不同成本同日标记可能重叠，精确日期、股数、费用以逐笔表为准。卖出后的K线只用于复盘，不用于决策或原持有峰值。长跨度形态图用于核对锚点，入场局部规则另由逐根审计验证。</p>')
    for c in charts:
        b.append(f'<details><summary>{c["number"]:02d} {c["symbol"]}｜原信号 {c["original_signal"]}</summary><p>{html.escape(NOTES[c["number"]])}</p><img loading="lazy" src="{c["chart"]}"></details>')
    b.append('<h2>判断与下一步依据</h2><p>本轮不替换研究基准。盈利后保护可保留为降低回撤的候选，但尚未达到保住大赢家收益的目标。后续若研究保护线，应先固定“已有利润允许回撤多少”与“日线结构需要多大尺度”的区别，避免小级别低点把大趋势切断。回踩机制应先拆开定位确认延迟、一次消费和右肩失效边界的作用，不应直接放宽到恰好保留这五只赢家；突破失败应区分买入初期未走强与已有趋势中的整理。这些是待验证假设，本轮没有继续测试或组合。</p><p>本区间已反复参与策略研究，没有独立留出样本；收益集中、样本少，不能由本轮推断未来稳定收益。维持相同日线OHLC撮合、T+1、复权/股数会计假设，未模拟盘中完整成交路径。</p>')
    b.append('<h2>核验与可复现资料</h2><p>469项测试通过。独立审计核对199次买入与损益、全部1014个回踩确认（每种成本各核一次）、全部失败触发、盈利激活与日线保护时点，均通过。两种成本基准的订单、交易、入场审计、权益与上一轮冻结基准完全一致。归档源码独立重放profit_cost1，订单、交易、入场审计、权益、决策五份文件逐行相同。审计通过是本轮规则一致性的证据，并不代表形态判断具有预测优势。</p>')
    for file,label in [('protocol.json','冻结实验规则'),('comparison.csv','8组账户结果'),('trade-paths.csv','199次买入与持有路径'),('paired-trades.csv','同形态逐笔差异与拒绝原因'),('attribution.csv','收益差归因'),('audit-summary.json','亏损/回吐统计'),('verification.json','逐项核验结果'),('visual-review.json','51张图的复核备注'),('manifest.json','数据与源码指纹')]:b.append(f'<p><a href="{file}">{label}</a></p>')
    b.append('<p>归档重放命令：<code>python source/replay.py --case profit_cost1</code>，可选baseline/retest/failure/profit搭配_cost1或_cost2。该入口依赖归档数据和source/src，不依赖原工作区路径。审计及绘图脚本同时归档用于追溯，其原路径入口仍指向工作区。</p>')
    b.append('<details><summary>全部199次交易及期末持仓</summary>'+table(['组别','股票','原信号','实际信号','买入','卖出','股数','净损益','峰值净R','最终R','退出原因'],[[r['case'],r['symbol'],r['original_signal'],r['signal'],r['entry'],r['exit'] or '期末持仓',r['quantity'],f"{float(r['pnl']):,.2f}",f"{float(r['peak_net_R']):.2f}",f"{float(r['final_R']):.2f}",r['reason']] for r in paths])+'</details>')
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>头肩底三项单变量全量对照</title><style>body{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;max-width:1280px;margin:36px auto;padding:0 24px;color:#223047;background:#fafbfd}h1{font-size:30px}h2{margin-top:38px}.lead{padding:20px;background:#eaf0f8;border-left:4px solid #39709d}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d3dce5;padding:8px;text-align:left}th{background:#eef2f6;white-space:nowrap}.scroll{overflow:auto}img{max-width:100%;height:auto;background:white}details{background:white;border:1px solid #dce2e8;margin:9px 0;padding:10px}summary{cursor:pointer}a{color:#1b6097}code{background:#edf0f3;padding:4px}</style>'+''.join(b)+'</html>',encoding='utf-8')
    dump(OUT/'visual-review.json',dict(reviewed_contacts=26,reviewed_shapes=51,reviewed_exclusions=5,notes=NOTES))
    source=OUT/'source'
    for name in ('audit_ihs_lifecycle.py','chart_ihs_lifecycle.py','chart_ihs_lifecycle_exclusions.py','report_ihs_lifecycle.py','replay_ihs_lifecycle_snapshot.py','audit_pattern_trade_paths.py','audit_candidate_policy.py'):shutil.copy2(ROOT/'scripts'/name,source/name)
    shutil.copy2(ROOT/'tests/test_ihs_price_line_research.py',source/'test_ihs_price_line_research.py')
    for name in ('tests','audit','replay','run','charts','exclusions'):shutil.copy2(ROOT/f'runs/ihs-lifecycle-{name}.log',source/f'{name}.log')
    data_hash=sha(OUT/'bars.csv');assert data_hash==load(OUT/'protocol.json')['bars_sha256']==sha(IHS/'bars.csv')
    for case in (1,2):
        for name in ('orders','trades','entry_audit','equity'):assert rows(OUT/f'baseline_cost{case}'/(name+'.csv'))==rows(BASE/f'IHS_no_gap_up_cost{case}'/(name+'.csv'))
    source_files={str(p.relative_to(source)).replace('\\','/'):sha(p) for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    source_match=all(sha(p)==sha(ROOT/'src'/p.relative_to(source/'src')) for p in (source/'src').rglob('*.py'));assert source_match
    dump(OUT/'manifest.json',dict(data_sha256=data_hash,data_files={n:sha(OUT/n) for n in ('bars.csv','plans.json','calendar.json','universe.json')},source_files=source_files,source_matches_workspace=source_match,baseline_exact_match_both_costs=True,independent_replay_exact='profit_cost1: orders/trades/entry_audit/equity/decisions',tests_passed=469,visual_review_shapes=51,visual_review_exclusions=5,cases={name:{n:sha(OUT/name/n) for n in ('config.json','orders.csv','trades.csv','equity.csv','entry_audit.csv','decisions.csv','summary.json')} for name in verify},artifacts={n:sha(OUT/n) for n in ('protocol.json','comparison.csv','trade-paths.csv','paired-trades.csv','attribution.csv','audit-summary.json','verification.json','visual-review.json','report.html')}))
    print('REPORT COMPLETE; 8 cases; 199 buys; 51 reviewed shapes + 5 exclusions; baseline/source/data verified')

if __name__=='__main__':main()
