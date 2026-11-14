"""Publish all frozen variants, complete visual review and source/data provenance."""
import html,shutil
from backtest_ihs_entry_quality import ROOT,OUT,IHS,RULES,load,rows,dump,sha

NOTES={
1:'信号量比1.232、收盘靠近高位，入场后先震荡再上涨；各组保留原盈利交易。',
2:'信号有上影但收盘仍在区间上半部，长期持仓中经历回撤再走高；四个过滤均未直接排除。',
3:'信号收在最高附近，量比1.358；买后先上冲再回落，保留的成交日期一致。',
4:'双倍成本账户中的成交，量比1.893。价格走势上涨较多但交易利润较小；图形涨幅不能替代实际仓位损益。',
5:'002258收盘位置仅0.16，被收盘强度规则直接删除；基准实际盈利约860元。退出之后更大的上涨不计入原单收益。',
6:'量比5.439仍未形成持续上涨，最终小亏；强放量不等于后续趋势成功。不同组损益差异主要是数量。',
7:'605086信号量比0.979，刚低于1而被排除；随后快速上涨，基准盈利15,311.81元，是本轮关键误删。',
8:'000708量比1.411通过过滤，标准成本量能组新增该单；随后反复震荡，最终净亏约2,995元。',
9:'603901在12月的这笔信号量比1.058，保留盈利；不可与该股1月的另一笔亏损形态混为一笔。',
10:'002271入场后短暂上冲，实际卖出早于后续大涨；同一日期下成本和数量变化可令小盈利变成小亏。',
11:'002430量比1.195，本来满足条件；量能组因持仓名额排除，属于间接成交变化。收盘强度组只是数量增大。',
12:'002829为收盘强度组新增成交，量比1.724、收盘位置0.66，随后回落而小亏约220元。',
13:'600258是双倍成本基准的小盈利单，收盘强度组因名额变化未成交，不能归因于其收盘位置不合格。',
14:'001311收盘强、量比1.220，入场后上涨；各组保留原盈利，退出时点一致。',
15:'603901在1月的信号量比1.013，刚超过门槛却很快转弱。量能组亏损减少来自仓位缩小，并非卖得更早。',
16:'000629量比1.295且收盘强，买后上冲、随后退出获利；量能组未成交原因为预算或现金不足。',
17:'002092在1月30日的原盈利单量比1.331，通过特征门槛但被量能组预算限制挡住；后面另一笔入场不是原单保留。',
18:'002135原大赢家保留，量比1.319；入场和退出一致，小额利润差异来自数量。',
19:'002541量比0.897被直接剔除。原单先有上涨再跌回止损，过滤确实避免原约4,914元亏损。',
20:'001326收盘在最高位置但量比0.887；原单明显上涨后大幅回落。量能规则删掉亏损，收盘强度规则保留亏损。',
21:'002367量比1.788的新成交先震荡后下行，最终小亏；释放名额后的新单也需要计入账户。',
22:'603073量比1.705、收盘位置0.64，量能组新增后震荡走弱，标准成本净亏约4,949元。',
23:'002897量比1.999的新成交后来上涨，最终盈利；量能组的新增交易并非全部亏损。',
24:'002092于2月11日的新形态成交位置高于1月30日原单，最后仅小盈利；应按不同形态匹配，不能合并算保留赢家。',
25:'002930为双倍成本量能组新增，收盘强且量比1.399；长期横盘后退出亏损，卖出后的反弹不属于持有收益。',
26:'000586量比1.154通过过滤，入场后明显转弱。标准成本量能组仓位更大，亏损反而增加；双倍成本为新增成交。',
27:'600389量比2.059仍在买入后走弱。标准成本量能组新增亏损约4,096元，双倍成本同一单亏损增大来自数量。',
28:'603659量比2.019，买后先跌再恢复，最终盈利；各组保留相同买卖日期。',
29:'605366量比0.849被直接删除，但原单买后上涨并实现约1,102元盈利，是另一笔低量误删。',
30:'603989量比2.026，所有组保留大赢家；标准成本量能组利润约26,710元，低于基准28,116元，买卖日期相同，差异为数量。',
31:'001300量比0.964，量能过滤避免原约5,095元亏损；与0.979量比的大赢家605086十分接近，单一门槛难以稳定区分。',
32:'002800量比2.297，入场后上涨；各组保留标准成本约6,176元盈利。',
33:'600493量比1.043，买后上涨再退出；共享交易日期一致，小额损益差异为数量。',
34:'001231量比1.291、信号收盘较强，实际退出后仍有上冲；收益按实际退出记录，不按后续高点回填。',
35:'001336量比0.808被直接排除；原单小幅震荡后转弱，量能规则避免小亏。',
36:'002591为双倍成本基准期末未平仓交易，量比0.853被过滤；图中没有卖出线，期末约38元是浮动损益。',
37:'600232是双倍成本量能组新增，量比1.648；原持有期间转弱后亏损退出，卖出后回升不能改变这笔实际亏损。',
38:'600692量比1.248、收盘位置0.75，仍在买后迅速下跌；常见强度条件未过滤这笔亏损。',
39:'601169量比1.016，期末仍持仓且浮亏；各组均没有退出线，不把浮亏计入已平仓亏损笔数。'}

def table(head,data):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in data)+'</tbody></table>'

def main():
    comp=rows(OUT/'comparison.csv');by={r['case']:r for r in comp};paths=rows(OUT/'trade-paths.csv');pairs=rows(OUT/'paired-trades.csv');attr=rows(OUT/'attribution.csv');charts=load(OUT/'charts/index.json');verify=load(OUT/'verification.json')
    assert len(comp)==10 and len(charts)==39 and all(v['passed'] for v in verify.values())
    labels={'baseline':'不追高开基准','solid_close':'信号收盘在上半区','volume_confirmed':'信号量≥前20日均量','rising_ma20':'20日均线抬升','limited_gap_down':'低开不超过0.5 ATR'}
    b=['<h1>头肩底：不追高开基础上的入场质量筛选</h1><p>2026-11-10｜4个额外条件，分别单变量｜标准及双倍成本，共10组全量回测</p>',
    '<p class="lead">本轮没有找到同时减少亏损、保住大赢家且跨成本有效的新过滤条件。维持“不追高开”研究基准；不新增默认过滤器。成交量确认删掉了部分亏损，却误删大赢家并引入新的亏损；其余规则无效或略有拖累。</p>',
    '<h2>完整结果</h2><p>3214只股票的同一冻结快照，全部1713个头肩底候选信号；评估2025-10-09至2026-09-30，预热从2023-01-03开始，初始资金100万元。每组重新计算账户现金、风险预算、名额和成交。基准即上一轮“不追高开”，没有混入提前日线保护或双底。</p>']
    data=[]
    for rule in RULES:
        a,c=by[rule+'_cost1'],by[rule+'_cost2']
        losses=lambda case:sum(r['case']==case and r['closed']=='True' and float(r['pnl'])<0 for r in paths)
        data.append([labels[rule],f"{float(a['total_return']):.3%}",f"{abs(float(a['max_drawdown'])):.3%}",a['filled_buys'],losses(rule+'_cost1'),f"{float(c['total_return']):.3%}",f"{abs(float(c['max_drawdown'])):.3%}",losses(rule+'_cost2')])
    b.append(table(['方案','标准收益','标准最大回撤','标准买入数','标准亏损笔数','双倍成本收益','双倍成本回撤','双倍成本亏损笔数'],data))
    b.append('<p>双倍成本将佣金率、双边滑点翻倍，最低佣金与印花税不变。亏损笔数只计已平仓。成本也会改变入场资格、账户持仓和仓位，因此不是同一批交易简单增加费用。</p>')
    b.append('<h2>四个条件与信息时点</h2>'+table(['规则','通过条件','研究假设/代价'],[
        ['收盘强度','信号日(收盘−最低)/(最高−最低)≥0.5','排除尾盘走弱，可能错过有上影但仍能上涨的交易'],
        ['成交量确认','信号日原始成交量≥此前20根股票日线的算术均量；均量不含信号日','排除缺少量能支持的突破，也可能误删量能稍低的趋势赢家'],
        ['均线方向','信号日复权收盘MA20≥五个股票交易日前的MA20','排除中期趋势仍下降的入场'],
        ['低开幅度','当日开盘−复权前收盘≥−0.5×此前14日ATR','保留不追高开，并排除隔夜显著转弱']]))
    b.append('<p>全部条件只在原计划的下一开盘执行时拒绝入场，不改变原信号消费、止损、目标、出场和风险预算。信号特征在前一收盘已知，低开幅度在当前开盘已知；不读取买入日最终高低收盘。缺少必要历史不通过。四个阈值在账户结果出现前冻结，未做网格寻优，也未事后将量比1调整到能刚好保留某个赢家的数值。</p>')
    b.append('<h2>逐笔归因：少亏是否真的转成更多利润</h2>')
    b.append(table(['方案/成本','原成交移除','其中亏损/盈利','新增成交','共同交易损益差','移除贡献','新增贡献','原前五赢家保留'],[[r['case'],r['removed'],r['removed_losses']+'/'+r['removed_wins'],r['added'],f"{float(r['shared_delta']):+,.2f}",f"{float(r['removed_delta']):+,.2f}",f"{float(r['added_delta']):+,.2f}",r['top5_retained']+'/5'] for r in attr]))
    b.append('<p>金额为元，包含期末未平仓市值。共享交易已核验买入与卖出日期一致，差额来自数量。移除交易包括直接被新条件拒绝，以及账户资金/名额改变后的间接移除；不能把它们全部称为“低质量交易”。</p>')
    b.append('<p><b>收盘强度：</b>标准成本唯一直接过滤的是002258，原利润859.78元；同时新增002829亏219.74元，账户净少610.55元，亏损笔数8→9。双倍成本净少3,634.73元，亏损笔数9→11。该条件保住前五赢家，却没有减少亏损。</p>')
    b.append('<p><b>成交量确认：</b>标准成本删掉9笔原成交（4亏5盈），另新增6笔。原亏损单001326、002541、001300、001336被直接排除，但605086的15,311.81元盈利和605366的1,102.13元盈利也被排除。共同交易差额−36.72元、移除贡献−6,867.04元、新增贡献−8,131.55元，总计少15,035.31元。亏损单合计从29,078.40元降至24,008.07元，但亏损笔数仍为8，净收益更低。</p>')
    b.append('<p>双倍成本下量能组收益3.383%→3.726%，却伴随最大回撤3.989%→4.366%。关键是605086原本就在信号阶段因净RR=2.990889未严格大于3而被基准拒绝，量能规则不再承担删掉该大赢家的代价。这个差异解释了两种成本下的相反结果，不能视为成本越高策略越好。</p>')
    b.append('<p><b>均线抬升与低开幅度：</b>两种成本下均未改变成交、权益或亏损。这两个条件对本批可成交信号是冗余约束，没有带来筛选增量。</p>')
    b.append('<h2>大赢家逐笔跟踪（标准成本）</h2>')
    base=sorted([r for r in paths if r['case']=='baseline_cost1'],key=lambda r:float(r['pnl']),reverse=True)[:5]
    maps={rule:{r['canonical_id']:r for r in paths if r['case']==rule+'_cost1'} for rule in RULES}
    b.append(table(['股票','基准净利润','收盘强度','成交量确认','均线/低开幅度'],[[r['symbol'],f"{float(r['pnl']):,.2f}",f"{float(maps['solid_close'][r['canonical_id']]['pnl']):,.2f}",f"{float(maps['volume_confirmed'][r['canonical_id']]['pnl']):,.2f}" if r['canonical_id'] in maps['volume_confirmed'] else '未成交', '与基准一致'] for r in base]))
    b.append('<p>603989仍持有至原退出日，没有被提前卖出；量能组利润减少约1,406元来自仓位缩小。605086才是直接错过的大赢家。不能用“保住最大一笔”替代“保住重要赢家集合”。</p>')
    b.append('<h2>分段观察</h2>');halves=[]
    for rule in RULES[:3]:
        for cost in (1,2):
            case=f'{rule}_cost{cost}';eq=rows(OUT/case/'equity.csv');mid=[r for r in eq if r['date']<'20260401'][-1]
            halves.append([case,f"{float(mid['equity'])/1e6-1:.3%}",f"{float(eq[-1]['equity'])/float(mid['equity'])-1:.3%}"])
    b.append(table(['账户','开始至2026-03-31','2026-04-01至结束'],halves))
    b.append('<p>使用连续账户权益，跨段持仓保留；这些时间段此前已被研究，不能当成独立验证或保留样本。本轮基准只有27/24笔买入，单个赢家对结果影响很大。</p>')
    b.append('<h2>全部交易K线核对</h2><p>10组共有252笔账户买入记录，按形态去重为39笔，已逐张查看39张图（20张双图联系表），没有只挑收益改善的案例。左上为入场附近日线，左下为量能，右侧为完整持有及退出日期。后续行情以复核为目的展示，不参与过滤。CLV是信号收盘位置；量柱除以前20日均量。每图用标题标明的一组作为价格/买入代表，其他组逐笔价格与数量在CSV中；未平仓没有卖出线。</p>')
    for c in charts:
        note=NOTES[c['number']]
        b.append(f'<details><summary>{c["number"]:02d} · {c["symbol"]} · {c["entry"]} — {html.escape(note)}</summary><a href="{c["chart"]}"><img loading="lazy" src="{c["chart"]}" alt="trade {c["number"]}"></a></details>')
    b.append('<h2>验证与后续判断</h2><p>462项测试通过，包含当前日高低收盘与成交量不泄漏、复权口径、历史长度和阈值边界。标准及双倍成本基准的orders/trades/entry_audit/equity均与上轮逐项一致；700条开盘评估的特征与通过条件独立重算，252笔买入的滑点、净RR、空间、数量和费用逐笔核验，与最终权益对账一致。保留全部失败规则、配置、信号、拒绝原因、数据/源码指纹。</p>')
    b.append('<p>本轮没有新增可采纳的过滤器。“低量突破”并非足够可靠的低质量标签：失败的001300量比0.964，而大赢家605086是0.979；单一硬门槛同时删除两者。若继续研究，应另外冻结突破前涨幅/波动扩张、附近历史压力等特征，用独立新样本检验，不能在这39张已知结果的图上持续调整门槛直到漂亮。该建议尚未经过回测。</p>')
    b.append('<h2>复查与复跑</h2><p>研究基准和默认配置未升级。独立配置使用v12新策略ID，逐笔匹配按原形态锚点进行。新过滤由专用IHSEntryQualityBacktest执行，普通入口不会自动启用。运行 source/replay.py --case volume_confirmed_cost1 可从本目录冻结源码、1713个plans和行情复跑，写入reproduced目录并逐表对照原结果。</p><ul>'+''.join(f'<li><a href="{f}">{f}</a></li>' for f in ['comparison.csv','attribution.csv','paired-trades.csv','trade-paths.csv','baseline-screen.csv','baseline-preentry-features.csv','protocol.json','verification.json','manifest.json','charts/visual-review.json','source/ihs-entry-quality-tests.log','source/replay.py'])+'</ul>')
    css='body{max-width:1200px;margin:40px auto;padding:0 24px;font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif;color:#253149;background:#f7f9fc}h1,h2{line-height:1.4}h2{margin-top:36px}.lead{background:#fff0e4;border-left:5px solid #bc7743;padding:18px}table{border-collapse:collapse;width:100%;background:white;font-size:13px}td,th{padding:9px;border:1px solid #dce3ed;text-align:left}th{background:#eaf0f7}details{background:white;margin:12px 0;padding:14px}summary{cursor:pointer}img{width:100%;height:auto}a{color:#245bb3}'
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>头肩底入场质量单变量回测</title><style>'+css+'</style><body>'+''.join(b)+'</body></html>',encoding='utf-8')
    dump(OUT/'charts/visual-review.json',dict(method='nonblind visual inspection of all 39 charts via 20 contact sheets',reviewed_numbers=list(range(1,40)),notes=NOTES))
    source=OUT/'source'
    for name in ('profile_ihs_entry_quality.py','audit_ihs_entry_quality.py','chart_ihs_entry_quality.py','report_ihs_entry_quality.py'):
        shutil.copy2(ROOT/'scripts'/name,source/name)
    shutil.copy2(ROOT/'scripts/replay_ihs_entry_quality_snapshot.py',source/'replay.py')
    shutil.copy2(IHS/'plans.json',OUT/'plans.json')
    shutil.copy2(ROOT/'tests/test_ihs_entry_quality_research.py',source/'test_ihs_entry_quality_research.py')
    for name in ('ihs-entry-quality-tests.log','ihs-entry-quality-audit.log'):shutil.copy2(ROOT/'runs'/name,source/name)
    for p in (source/'src').rglob('*.py'):assert p.read_bytes()==(ROOT/'src'/p.relative_to(source/'src')).read_bytes(),p
    assert sha(OUT/'bars.csv')==load(OUT/'protocol.json')['bars_sha256']
    dump(OUT/'manifest.json',dict(data_sha256=sha(OUT/'bars.csv'),plans_sha256=sha(OUT/'plans.json'),source_hashes={str(p.relative_to(source)):sha(p) for p in (source/'src').rglob('*.py')},tests=462,full_cases=10,gate_audit_rows=700,filled_buy_rows=252,unique_charts=39,nonblind=True,holdout=False,promoted=False,default_changed=False))
    print('REPORT COMPLETE',OUT/'report.html')

if __name__=='__main__':main()
