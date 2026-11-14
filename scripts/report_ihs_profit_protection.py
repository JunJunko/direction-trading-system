"""Publish the frozen profit-protection comparison and reviewed candle evidence."""
import html,shutil
from datetime import datetime
from backtest_ihs_profit_protection import ROOT,OUT,PREV,CASES,load,rows,dump,sha,save_csv
from audit_candidate_policy import plt

NOTES={
1:'002928：半数浮盈保护10月27日退出，随后震荡再走高，标准利润8,927→3,237元。较大结构没有误收紧，保留原11月17日退出。',
2:'600063：各版均保留原退出。大部分早期整理发生在1R激活前，本轮盈利保护不处理这些波动。',
3:'001218：半数浮盈版10月31日提前止盈，标准利润1,854→3,742元；其余版本仍11月24日退出。这是回撤保护改善卖点的正例。',
4:'600388的10月20日形态：只在双倍成本账户出现，各版保持原退出；不可与10月28日另一形态混为同一笔。',
5:'600057：半数浮盈版新增交易，12月启动保护后退出盈利，需纳入完整账户。',
6:'600388的10月28日形态：标准成本半数浮盈版新增，最终盈利；与双倍成本原更早锚点分别匹配。',
7:'603661：半数浮盈版因名额释放新增，先有小涨再走弱，按原支撑退出小亏。',
8:'603917：新增后持续下跌，未达到盈利激活要求，仍触发硬止损，标准成本亏损约3,576元。',
9:'000708的11月形态：双倍成本半数浮盈版新增，短暂上涨后按原支撑卖出亏损。',
10:'002258：基准、小结构、较大结构保持同一盈利单；半数浮盈版因账户持仓名额约束没有成交，不是新规则直接否定形态。',
11:'603600：各版买卖日期一致，半数浮盈版亏损增大主要来自股数变化，并非保护退出更差。',
12:'605086：四版均保留标准成本原大赢家，买卖日期、股数和损益一致；原压力保护已足够高。',
13:'000708的12月形态：双倍成本账户原单，各版退出相同，半数浮盈版金额变化来自仓位。',
14:'603901的12月形态：各版原退出相同，仍实现盈利；退出后的上涨不计入持有峰值。',
15:'002271：各版仍按原保护提前退出，后续才大涨；本轮没有解决原压力保护本身过紧的问题。',
16:'002430：卖点一致，半数浮盈版的金额差主要来自股数。',
17:'600258：双倍成本基准的小盈利单，较大结构保留；半数浮盈版未成交属于账户路径变化。',
18:'001311：快速上涨后原支撑退出，各版均保留；激活不意味着一定新增更高保护线。',
19:'603901的1月形态：入场后转弱，盈利保护没有激活，保留原止损；金额差来自仓位，不能计为保护线改善。',
20:'000629：各版退出相同，半数浮盈版盈利减少主要因为股数较少。',
21:'002092：半数浮盈版因预算/现金限制错过原盈利单；较大结构仍保留原交易。',
22:'002135：较大结构完整保留原大赢家；半数浮盈版卖点一致，利润略少主要因股数。',
23:'002541：浮盈未达到1R，三个新增保护机制都没有启动，仍在原硬止损退出。',
24:'001326：较大结构用3月4日低点、3月11日确认，保护较宽，但3月20日破线后仍能比原硬止损提前一日退出，少亏约3,999元。半数浮盈版3月4日退出并盈利1,311元，也放弃后来一段反弹。',
25:'002367：标准成本半数浮盈版新增，双倍成本原有，各版对应交易的卖点一致，属于小亏。',
26:'603187：半数浮盈版释放资金后新增，买后下跌，未启动盈利保护，最后亏损。',
27:'000586：买入后持续下跌，盈利保护没有机会启动；半数浮盈版股数增加，标准亏损3,936→5,029元。',
28:'600389：标准成本半数浮盈版新增，双倍成本原有，各组对应卖点一致。新增及仓位变化带来更多亏损。',
29:'603659：较大结构保留原先跌后涨的盈利路径；各版卖点相同，金额差主要由股数造成。',
30:'605366：较大结构保持原卖点，利润小幅增加来自股数，不是保护线收紧。',
31:'603989：6月2日是2+2小低点，但左5根内5月26日更低，因此不是5+5低点。较大结构没有新增收紧，保留7月14日原退出；小结构与半数浮盈均6月15日卖出，错过第二波。较大结构仍承受6月末之后的大幅回吐。',
32:'001300：入场后持续走弱，所有盈利保护均未激活，止损与原基准相同。',
33:'002800：较大结构原买卖及净利润完全保留；小结构、半数浮盈版金额增加来自股数，不能当作卖点改善。',
34:'600493：各版退出日期相同，新增收益主要由前序交易改变仓位所致。',
35:'001231：各版原支撑退出一致，较大结构仅有小幅仓位变化；卖后继续上涨不计入原持有利润。',
36:'001336：所有版本同日退出小亏，损益差主要来自仓位。',
37:'002591：双倍成本期末仍持仓，金额为浮盈，没有已实现卖出。',
38:'600692：未触发盈利保护，所有版本在同一天按原硬止损退出；较大结构仅小幅股数差，半数浮盈版仓位更大而亏损更多。',
39:'601169：期末仍持仓浮亏，未达到盈利激活门槛；不计入已平仓亏损笔数。'}

def table(head,data):
    esc=lambda x:html.escape(str(x))
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in r)+'</tr>' for r in data)+'</tbody></table></div>'

def main():
    comp=rows(OUT/'comparison.csv');by={r['case']:r for r in comp};paths=rows(OUT/'trade-paths.csv');pairs=rows(OUT/'paired-trades.csv');attr=rows(OUT/'attribution.csv');audit=load(OUT/'audit-summary.json');verify=load(OUT/'verification.json');charts=load(OUT/'charts/index.json')
    assert len(comp)==8 and len(paths)==213 and len(charts)==len(NOTES)==39 and all(v['passed'] for v in verify.values())
    labels={'baseline':'不追高开原基准','small':'上一轮：2+2结构保护','larger':'本轮：5+5结构保护','half':'本轮：保留半数浮盈'}
    maps={name:{r['canonical_id']:r for r in paths if r['case']==name} for name in by}
    vs_small=[]
    for cost in (1,2):
        a=maps[f'small_cost{cost}']
        for rule in ('larger','half'):
            name=f'{rule}_cost{cost}';z=maps[name]
            for pid in sorted(a.keys()|z.keys()):
                old,new=a.get(pid),z.get(pid)
                vs_small.append(dict(case=name,canonical_id=pid,symbol=(old or new)['symbol'],old_entry=old['entry'] if old else '',new_entry=new['entry'] if new else '',old_exit=old['exit'] if old else '',new_exit=new['exit'] if new else '',old_pnl=old['pnl'] if old else 0,new_pnl=new['pnl'] if new else 0,delta=float(new['pnl'] if new else 0)-float(old['pnl'] if old else 0)))
            assert abs(sum(r['delta'] for r in vs_small if r['case']==name)-(float(by[name]['final_equity'])-float(by[f'small_cost{cost}']['final_equity'])))<1e-6
    save_csv(OUT/'paired-vs-small.csv',vs_small)
    fig,axes=plt.subplots(1,2,figsize=(13,4),layout='constrained')
    for cost,ax in enumerate(axes,1):
        for rule in CASES:
            curve=rows(OUT/f'{rule}_cost{cost}'/'equity.csv');ax.plot([datetime.strptime(r['date'],'%Y%m%d') for r in curve],[(float(r['equity'])/1e6-1)*100 for r in curve],label=rule)
        ax.set_title(f'Cost {cost} | account return (%)');ax.grid(alpha=.2);ax.legend(fontsize=8);ax.tick_params(axis='x',rotation=20)
    fig.savefig(OUT/'charts/equity.png',dpi=120);plt.close(fig)
    b=['<h1>头肩底盈利保护：扩大结构，还是允许利润回撤？</h1><p>2026-11-10｜两个新方向分别测试｜四方案×两档成本｜213次买入、39个形态逐图核验</p>',
       '<p class="lead">本轮较大结构版优于原基准和上一轮小结构版：保住603989及原前五赢家的完整收益，同时保留001326少亏的效果。改善却几乎由001326一笔贡献，最大回撤仍约4%；603989后半段的大幅利润回吐没有减少。保留半数浮盈版依然提前洗出603989和002928，账户收益更低。较大结构可列为优先验证候选，尚不能称为已解决利润保护。</p>',
       '<h2>全量账户结果</h2><p>同一3214只股票快照、全部1713个原头肩底信号，逐日重新运行账户资金、名额、风险预算与撮合。评估2025-10-09～2026-09-30，预热从2023-01-03开始，初始100万元。不是只调整旧交易的卖出价；形态检测与入场规则不变，复用冻结全量信号。</p>']
    b.append(table(['方案','成本','收益','最大回撤','买入/平仓','亏损笔数','亏损单合计','曾达1R后亏损'],[[labels[r['case'].split('_')[0]],r['case'][-1],f"{float(r['total_return']):.3%}",f"{abs(float(r['max_drawdown'])):.3%}",r['filled_buys']+'/'+r['closed_trades'],audit[r['case']]['losses'],f"{audit[r['case']]['loss_pnl']:,.2f}",audit[r['case']]['peak1R_then_loss']] for r in comp]))
    b.append('<p>金额单位元。收益含期末持仓市值，亏损统计仅计已平仓。成本2仅将佣金率及双边滑点翻倍，最低佣金与印花税不变；费用也影响入场资格、仓位及原管理规则，故不是同一批交易多扣手续费。</p><img src="charts/equity.png" alt="八组账户曲线">')
    b.append('<h2>两项预先固定的规则</h2>'+table(['方案','规则与唯一变化'],[
       ['5+5结构保护','相对上一轮2+2，仅将低点确认窗口扩大到左右各5根日线，共11根。达到1R浮盈后，低点必须形成于激活当日或之后，11根K线均在入场日之后；严格低于相邻10根最低价，并高于前一个同级别低点（首次参照入场日低点）。保护=低点−0.5此前ATR14，确认后下个股票交易日生效。'],
       ['保留半数浮盈','替换额外日线分型保护；同样1R激活。逐日记录最高收盘货币浮盈，保护线对应保留其50%，允许另50%回吐。浮盈扣入场费、未扣假设退出费；保护价=当前复权买价+(入场费+0.5×最高浮盈)/当前股数。只上移，下个交易日生效。']]))
    b.append('<p>两个候选分别测试，不组合。所有版本保持不追高开、原净RR/目标空间/入场距离门槛、原右肩硬止损，以及原压力转支撑和周线保护。原退出先处理，新保护只能抬高现有线，不能放松原线；收盘破保护后下一可执行开盘退出。没有用盘中最高价计算浮盈峰值，没有事后把分型确认回填到低点当天。阈值在结果产生前固定，未对603989单独设例外。</p><p>这里的50%是浮盈回吐比例，不是股价跌50%；触发后次日执行，费用和跳空可能使实际保留比例低于50%。1R激活也不等于大结构线一定在成本之上。</p>')
    b.append('<h2>603989：为什么较大结构保住了第二波？</h2><p>原小结构把6月2日当成可保护低点，6月4日确认后收紧。扩大窗口后，左侧5根中的5月26日最低价更低，6月2日不再是有效5+5低点。因此较大结构没有在这里新增抬线，继续沿用原支撑，熬过6月12日调整，保留6月下旬第二波上涨。</p><p>小结构和半数浮盈版都于6月12日收盘触发、6月15日卖出，标准成本净利润16,499.35元；较大结构与原基准均7月14日退出，净利润28,115.62元，买入日期、股数、卖点和净损益一致。半数浮盈线来自5月28日峰值，位置约29.80，仍被这次调整触发；“允许回吐一半利润”并没有天然避免洗出。</p><img src="charts/focus-603989.SH.png" alt="603989四方案保护线与买卖点">')
    b.append(table(['603989标准成本','卖出','持仓期间峰值净浮盈','实际净利润','峰值到退出回吐'],[[labels[r['case'].split('_')[0]],r['exit'],f"{float(r['peak_net_profit']):,.2f}",f"{float(r['pnl']):,.2f}",f"{float(r['giveback_from_peak']):,.2f}"] for r in paths if r['symbol']=='603989.SH' and r['case'].endswith('cost1')]))
    b.append('<p><b>仍未解决：</b>较大结构的峰值净浮盈约69,584元，最终28,116元，仍回吐约41,468元。它避免了提前卖掉赢家，但没有改善这笔交易的后期卖点。小结构/半数版峰值较小，是因为提前卖出而没有参与第二波，不能据此宣称回吐控制优于较大结构。上述峰值是事后持有路径诊断，不是可预知、保证可实现的最优卖点；不包含卖出当天及卖出后的收盘。</p>')
    b.append('<h2>001326：较大结构仍少亏，但不是锁住盈利</h2><p>较大结构使用3月4日低点，3月11日完成右侧5根确认，下一交易日生效，保护约55.37（入场日复权口径）。它比小结构约58.11更宽，仍在3月20日收盘破位后于3月23日开盘卖出，净亏1,141.55元；原基准3月24日硬止损亏5,140.10元。半数浮盈版更早于3月4日退出，净赚1,311.03元。</p><img src="charts/focus-001326.SZ.png" alt="001326三种盈利保护与原基准">')
    b.append('<p>较大结构在两档成本下都只有001326这一笔新增保护实际抬高原线，且仅这一笔改变原基准的退出日期。标准成本账户净增4,152.27元，其中此单少亏3,998.54元，其余约153.72元来自后续仓位；双倍成本净增3,424.18元，其中此单少亏3,422.86元。买入数、亏损笔数、曾达1R后亏损笔数都未改善。收益提升很集中，不能把它解释为大量低质量交易被识别出来。</p>')
    b.append('<h2>大赢家集合与账户代价</h2>')
    top=sorted(maps['baseline_cost1'].values(),key=lambda r:float(r['pnl']),reverse=True)[:5]
    b.append(table(['标准成本原前五','原基准','小结构','较大结构','半数浮盈'],[[r['symbol']]+[f"{float(maps[rule+'_cost1'][r['canonical_id']]['pnl']):,.2f}" for rule in CASES] for r in top]))
    b.append('<p>较大结构在两档成本下完整保留原前五赢家的买卖日期、股数和净损益。标准合计64,318.43元、双倍成本49,650.12元，均与原基准相同。半数浮盈版虽仍5/5成交，标准合计只有48,954.67元，双倍成本33,082.66元；“成交还在”不能等同于“赢家收益保住”。</p><p>半数浮盈的正例是001218（标准利润1,854→3,742元）和001326（亏5,140→赚1,311元），负例是002928（8,927→3,237元）和603989（28,116→16,499元）。提前卖出还改变后续名额和仓位：标准成本移除2笔原盈利、新增7笔合计亏3,910元。总亏损笔数8→12，亏损合计29,078→35,060元；双倍成本亏损笔数9→13。峰值达1R后转亏虽1→0，但整户收益更低。</p>')
    b.append(table(['相对原基准','移除/新增','共同交易差','移除贡献','新增贡献','原前五保留','原前五新利润'],[[r['case'],r['removed']+'/'+r['added'],f"{float(r['shared_delta']):+,.2f}",f"{float(r['removed_delta']):+,.2f}",f"{float(r['added_delta']):+,.2f}",r['top5_retained']+'/5',f"{float(r['top5_candidate_pnl']):,.2f}"] for r in attr]))
    b.append('<p>同股不同形态按原锚点身份分别配对。共同交易差包含股数和退出变化，期末持仓按市值计入。相对上一轮小结构，较大结构标准成本多9,719.17元，双倍成本多11,383.64元；主要是恢复603989第二波收益，但原来的低回撤优势同时消失。</p>')
    b.append('<h2>逐笔K线复核</h2><p>已查看20张联系表，覆盖全部39个成交形态，并查看603989、001326两张局部详图。灰色=基准，紫色=小结构，蓝色=较大结构，橙色=半数浮盈；黄线为冻结颈线，红虚线为原硬止损，短横线为确认后下个交易日才生效的动态保护。颜色重叠时以逐笔表为准，图中卖出后行情仅作复盘。</p>')
    for c in charts:b.append(f'<details><summary>{c["number"]:02d} {c["symbol"]}｜原信号 {c["original_signal"]}</summary><p>{html.escape(NOTES[c["number"]])}</p><img loading="lazy" src="{c["chart"]}"></details>')
    b.append('<h2>本轮判断</h2><p>较大结构是本轮较好的后续验证候选：它减少一个亏损交易的回吐，同时避免对原大赢家新增错误退出。但对603989而言，最终卖出仍靠原周线/压力保护，后期利润回吐原样保留。半数浮盈规则不宜替换基准；它把个别浮盈转亏变成盈利，却付出了提前退出赢家及新增亏损的代价。</p><p>下一步应先在独立时期验证较大结构是否能在更多交易上起作用，再检验“趋势已充分展开后”的保护条件，区分趋势初段整理与后段回吐；这只是待检验方向，本轮没有继续调参或叠加。当前区间已反复用于研究，603989是预先知道的案例，两档成本不是两个独立样本。仅1笔直接改善不足以证明稳定增量；本轮未修改默认策略。</p>')
    b.append('<h2>验证与归档</h2><p>474项测试通过。基准及上一轮小结构在两档成本下，订单、交易、入场审计、权益、决策五类输出与上一轮逐行一致。独立审计核对213次买入、全部激活和新增保护的历史信息时点、5+5分型、峰值利润与复权、费用及账户对账，均通过。归档源码独立重跑larger_cost1和half_cost1，五类输出逐行一致。原日线OHLC撮合、T+1与复权股数会计假设保持不变。</p><p>浮盈激活使用扣入场费、未扣假设退出费的货币利润；表中峰值净R/峰值净浮盈另扣估算退出滑点与费用，两种口径明确分开。规则一致性核验不等于预测能力证明。</p>')
    for file,label in [('protocol.json','冻结协议'),('comparison.csv','8组账户结果'),('trade-paths.csv','213次买入、持仓峰值与回吐'),('paired-trades.csv','相对原基准逐笔差异'),('paired-vs-small.csv','相对上一轮小结构逐笔差异'),('attribution.csv','账户损益归因'),('pivot-scale-diagnostic.json','小结构低点为何不符合更大窗口'),('audit-summary.json','亏损与回吐统计'),('verification.json','独立核验结果'),('visual-review.json','全部39张图复核备注'),('manifest.json','数据、源码及结果指纹')]:b.append(f'<p><a href="{file}">{label}</a></p>')
    b.append('<p>归档目录下运行：<code>python source/replay.py --case larger_cost1</code>。支持baseline/small/larger/half与_cost1/_cost2，共8个case。重放入口只依赖归档source/src和同目录数据；审计及图表脚本亦保留用于追溯，其原入口仍引用工作区路径。</p>')
    b.append('<details><summary>全部213次买入及期末持仓</summary>'+table(['组别','股票','买入','卖出','入场股数','净损益','持有峰值净R','最终R','退出原因'],[[r['case'],r['symbol'],r['entry'],r['exit'] or '期末持仓',r['quantity'],f"{float(r['pnl']):,.2f}",f"{float(r['peak_net_R']):.2f}",f"{float(r['final_R']):.2f}",r['reason']] for r in paths])+'</details>')
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>头肩底盈利保护全量对照</title><style>body{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;max-width:1280px;margin:36px auto;padding:0 24px;color:#223047;background:#fafbfd}h1{font-size:30px}h2{margin-top:38px}.lead{padding:20px;background:#eaf0f8;border-left:4px solid #39709d}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #d3dce5;padding:8px;text-align:left}th{background:#eef2f6;white-space:nowrap}.scroll{overflow:auto}img{max-width:100%;height:auto;background:white}details{background:white;border:1px solid #dce2e8;margin:9px 0;padding:10px}summary{cursor:pointer}a{color:#1b6097}code{background:#edf0f3;padding:4px}</style>'+''.join(b)+'</html>',encoding='utf-8')
    dump(OUT/'visual-review.json',dict(reviewed_contacts=20,reviewed_shapes=39,focus_charts=2,notes=NOTES))
    source=OUT/'source'
    for name in ('audit_ihs_profit_protection.py','chart_ihs_profit_protection.py','diagnose_ihs_profit_protection.py','report_ihs_profit_protection.py','replay_ihs_profit_protection_snapshot.py','audit_pattern_trade_paths.py','audit_candidate_policy.py'):shutil.copy2(ROOT/'scripts'/name,source/name)
    for name in ('test_ihs_price_line_research.py','test_ihs_profit_protection_research.py'):shutil.copy2(ROOT/'tests'/name,source/name)
    for name in ('tests','audit','replay','replay-half','run','charts','diagnostic'):shutil.copy2(ROOT/f'runs/ihs-profit-protection-{name}.log',source/f'{name}.log')
    assert 'Exact reproduction: larger_cost1' in (source/'replay.log').read_text(encoding='utf-8-sig')
    assert 'Exact reproduction: half_cost1' in (source/'replay-half.log').read_text(encoding='utf-8-sig')
    data_hash=sha(OUT/'bars.csv');assert data_hash==load(OUT/'protocol.json')['bars_sha256']==sha(PREV/'bars.csv')
    for cost in (1,2):
        for rule,old in [('baseline','baseline'),('small','profit')]:
            for n in ('orders','trades','entry_audit','equity','decisions'):assert rows(OUT/f'{rule}_cost{cost}'/(n+'.csv'))==rows(PREV/f'{old}_cost{cost}'/(n+'.csv'))
        for r in sorted(maps[f'baseline_cost{cost}'].values(),key=lambda r:float(r['pnl']),reverse=True)[:5]:
            new=maps[f'larger_cost{cost}'][r['canonical_id']]
            for k in ('entry','exit','quantity','pnl'):assert r[k]==new[k]
    assert all(sha(p)==sha(ROOT/'src'/p.relative_to(source/'src')) for p in (source/'src').rglob('*.py'))
    dump(OUT/'manifest.json',dict(data_sha256=data_hash,data_files={n:sha(OUT/n) for n in ('bars.csv','plans.json','calendar.json','universe.json')},source_files={str(p.relative_to(source)).replace('\\','/'):sha(p) for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts},source_matches_workspace=True,reference_exact_match_both_costs=True,reproduced=['larger_cost1','half_cost1'],tests_passed=474,reviewed_shapes=39,focus_charts=2,cases={name:{n:sha(OUT/name/n) for n in ('config.json','orders.csv','trades.csv','equity.csv','entry_audit.csv','decisions.csv','summary.json')} for name in verify},artifacts={n:sha(OUT/n) for n in ('protocol.json','comparison.csv','trade-paths.csv','paired-trades.csv','paired-vs-small.csv','attribution.csv','audit-summary.json','verification.json','visual-review.json','pivot-scale-diagnostic.json','report.html')}))
    print('REPORT COMPLETE: 8 accounts / 213 buys / 39 charts / 2 focus charts; all references and source hashes match')

if __name__=='__main__':main()
