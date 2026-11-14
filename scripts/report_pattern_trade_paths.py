"""Build the trade-path audit report after reviewing the selected K-line pairs."""
from html import escape

from audit_pattern_trade_paths import OUT, load


NOTES = {
    '001206.SZ': '有下跌背景、两个低点和中间反弹，两底仅隔10根日K。信号在颈线附近，买价比信号收盘低约1.38%，但初始保护只差0.38%（0.14 ATR）。买入当天就跌穿，次日退出亏3,822元，此后继续走低。入场时净RR达14.77，主要由很短的止损距离放大。',
    '600397.SH': '同样是10根日K间隔的W，右底略高。12月15日开盘买入后收盘跌到入场价以下2.73%，次日退出亏2,408元。灰区里才重新上行，入场起20个交易日内最高收盘较原买价高37.24%。可复查新的站稳信号和新风险点；灰区涨幅属于退出后行情。',
    '002180.SZ': '此前下跌明显，9根日K间隔的两底接近，中间颈线清楚。回踩后在颈线附近成交，买后出现多日连续上移，随后按动态支撑失守退出，净赚10,582元。初始保护仍只有0.40 ATR，说明窄保护会增加触及风险，也会留下部分趋势赢家。',
    '603270.SH': '两底隔218根日K，中间跨越数轮上升与回落，颈线连接的是一段大箱体。右侧反弹后回到颈线附近，买入当天又大幅下穿，次日退出亏3,021元。长跨度和入场当天失守在这笔同时出现，无法单凭本例拆开影响。',
    '002800.SZ': '34根日K跨度，四段分别3、13、15、3根，肩部与主体相对可辨。靠近颈线买入后初期回落但守住初始保护，随后上行并按动态支撑失守退出，净赚6,176元。此金额对应本轮v7单策略账户。',
    '002541.SZ': '516根日K的主底部，两端外肩只有4根和3根。入场后的最高收盘较买价涨11.12%，但初始止损距离12.63%，收盘峰值净R未到2。之后回落至初始保护退出，净亏4,914元。单用2R开启保护会漏过这一类有可见涨幅的交易。',
    '603989.SH': '556根日K的大底部，四段2、156、393、5根，左肩只有两根K线。它更像长周期恢复，两侧小肩与中间走势尺度差异很大，但之后有强趋势，动态支撑退出净赚28,116元。盈利本身不能验证这个形态标签。',
}

LABELS = {'span':'形态跨度（该股日K间隔）','wait':'结构已知到发出信号（该股日K间隔）',
          'entry_gap':'成交价相对信号日收盘（含滑点）','held_sessions':'买入到退出的交易日间隔',
          'stop_atr':'入场到初始保护距离（前14根日K的ATR倍数）','net_rr':'成交时净报酬风险比',
          'prior_decline':'左底前下跌幅度','middle_rebound':'两底中间反弹幅度','outer_min':'较短一侧外肩（日K间隔）',
          'shoulder_core_ratio':'较小一侧外肩/相邻主段比例','neck_atr':'成交价高于颈线（ATR倍数）'}


def table(groups):
    header = '<thead><tr><th>分组</th><th>买入 / 平仓</th><th>平仓胜率</th><th>已实现净盈亏（元）</th><th>平均净R</th><th>买入日触初始保护</th></tr></thead>'
    lines = []
    for key, row in groups.items():
        closed = row['closed']
        win_rate = f"{row['wins']/closed:.1%}" if closed else '—'
        avg_r = f"{row['mean_R']:+.2f}" if closed else '—'
        cells = [key,f"{row['buys']} / {closed}",win_rate,f"{row['pnl']:+,.0f}",avg_r,row['t0_stop']]
        lines.append('<tr>'+''.join(f'<td>{escape(str(value))}</td>' for value in cells)+'</tr>')
    return '<div class="scroll"><table>'+header+'<tbody>'+''.join(lines)+'</tbody></table></div>'


def main():
    groups = load(OUT/'summary.json')
    charts = load(OUT/'charts/index.json')
    assert len(charts) == len(NOTES) and {row['symbol'] for row in charts} == NOTES.keys()
    doc = ['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>日线双底和头肩底的入场与退出复盘</title><style>
body{font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif;background:#f8fafc;color:#233244;max-width:1080px;padding:0 24px;margin:32px auto}
h1{font-size:30px}h2{font-size:22px;margin-top:34px}h3{font-size:17px}a{color:#196494}.scroll{overflow:auto}
table{border-collapse:collapse;width:100%;font-size:14px;background:white}th,td{border-bottom:1px solid #dde5ed;padding:7px 10px;text-align:right}th{background:#e9eff5}th:first-child,td:first-child{text-align:left}
summary{cursor:pointer;padding:8px 0}img{width:100%;height:auto}figure{margin:14px 0 26px}.muted{color:#53667a}code{background:#edf1f7;padding:1px 4px}
</style><h1>日线双底和头肩底的入场与退出复盘</h1>
<p class="muted">2026-11-10｜3,214股历史快照｜2025-10-09至2026-09-30｜两个独立v7单策略账户</p>
<p><b>双底先解决入场后立即失守。头肩底优先比较颈线附近入场和涨后保护。</b> 两类交易都存在形态尺度问题，但过往盈亏无法支持一条统一的形态跨度上限。</p>
<p>从冻结账户取230笔日线W买入和38笔头肩底买入，逐笔核对信号身份、次日开盘成交、复权后的止损与目标、退出和净损益。每笔只出现于所属单策略账户。下方盈亏表只计已平仓，另有4笔期末持仓。7个案例用于说明机制及反例，选图时已知结果。</p>''']
    doc.append(table({'日线双底':groups['W']['total'],'头肩底':groups['IHS']['total']}))
    doc.append('''<h2>日线双底的主要损失发生得很早</h2>
<p>230笔中118笔买入日触及初始保护，按T+1延至之后执行，这批交易合计净亏约7.50万元。177笔亏损中，126笔下一交易日退出，165笔退出日前的最高收盘涨幅不足3%。初始止损距离中位数约0.45 ATR。001206净RR看起来高达14.77，但止损仅距买价0.14 ATR，买入当天便失守。</p>
<p>亏损并非全部来自图形错误。173笔具有完整20日观察期的亏损交易中，58笔在退出之前没有收盘涨5%，却在退出当日收盘或更晚达到。600397是典型样例。001206则在退出后继续下跌。两者支持分开研究「持仓保护」和「失守后重新确认」，直接放宽所有止损会同时保留两种路径。</p>
<p>历史已有的对照也支持谨慎处理退出。相同全量日线W信号池中，固定目标版本收益−2.59%、动态支撑版本−7.32%，两组都亏损；另一次同口径全量实验将目标突破延续的C2规则应用到日线W，收益从−6.21%降到−8.59%。这些是共享账户重跑，退出差异会改变后续可买交易。</p>
<p>可检验的入场方案是先有可辨的下跌与中间反弹，回踩后收盘收复颈线，执行时确认仍守住结构，并以真实可用的保护点重算距离、波动和净RR。对已触保护的形态，单独比较重新站稳且形成新风险点后是否可以再入场。已有0.25、0.5、1 ATR过滤结果对照；1 ATR显著减少成交，但单独双底全量只赚0.087%，适合作为敏感性对照。</p>
<h2>头肩底有一部分利润在确认保护前回吐</h2>
<p>38笔买入中没有买入日触初始保护；37笔已平仓中，14笔亏损，其中5笔退出日前的最高收盘曾较买价上涨至少5%。这5笔收盘峰值净R都低于2。002541一度上涨11.12%，最后按初始保护退出净亏4,914元。</p>
<p>成交价低于信号收盘的19笔已平仓，合计净赚69,678元；在其上成交的18笔合计净亏16,858元。用颈线距离也能看到相近方向，低于0.5 ATR的31笔净赚57,446元，另一组仅6笔、净亏4,626元。这是已成交样本的分组，无法独立估计把所有订单改成低价限价会漏掉多少趋势。旧v2→v3曾改用统一回踩确认，收益从+1.65%降到−3.58%，所以也应保留直接突破入场作为对照。</p>
<p>退出优先对照原动态支撑与更早的日线结构保护。可以从已完成K线确认的更高低点、有效突破的压力位计算，下一交易日生效。保留右肩附近的初始风险，等走势形成新的结构再上移。只按2R开启保护会漏过这5笔，同时过早保护也可能割掉趋势赢家，需用同一信号池重放并比较大赢家保留率。</p>
<h2>分别看三类有效区间</h2>
<h3>形态跨度</h3><p>双底的两底相隔超过120根日K有8笔，1笔盈利，平均约−1.10R；较短三组的平均净R也为负。此前62股回测中，600482的v5.18双底两底相隔171根，仍盈利约2.47万元。头肩底超过250根日K有29笔，平均约+0.10R，低于120根以内6笔的+0.62R。长组净盈利25,588元，其中603989一笔就赚28,116元。更适合先把「多年底部配几根短肩」单独标为大周期恢复类，再比较它和尺度相称的头肩底；单看总长短会把两种结构放在一起。</p>
<h3>确认后等待</h3><p>双底登记颈线突破后3根日K内发出回踩信号的194笔已平仓，平均−0.43R。等待4根以上的33笔合计约+1,275元，前半段约+1.04万元、后半段约−0.92万元。样本不支持硬设「至少等4天」。头肩底从右肩确认到信号的样本集中在10日内，11–30日仅3笔，30日以上无成交。有效期宜先根据颈线失守、保护失守、价格离开可入场区等条件定义，再单独比较天数上限。</p>
<h3>持仓停滞与评估区间</h3><p>头肩底持有超过20个交易日的12笔已平仓中，8笔盈利。该分组只描述实际存续的仓位，无法推导持有更久本身有利。时间规则更适合限定「到第N天仍无已确认的新高或更高支撑」这样的状态，和单纯固定天数退出分别重放。两类样本都来自同一历史窗口，报告里的前后段是描述分组，独立验证需要另留时间区间。</p>
<h2>逐笔图形</h2><p>上图只显示信号日及以前K线。下图为成交与初始保护，灰区从卖出交易日开始。动态支撑类型来自原交易记录；下图不画未经复核的逐日动态水平。</p>''')
    for row in charts:
        doc.append(f'<details><summary>{escape(row["symbol"])} · {escape(row["entry"])}</summary><p>{escape(NOTES[row["symbol"]])}</p><figure><img loading="lazy" src="{row["chart"]}" alt="{row["symbol"]}形态与持仓K线"></figure></details>')
    doc.append('<h2>完整分组</h2>')
    for family, data in groups.items():
        doc.append(f'<h3>{"日线双底" if family=="W" else "头肩底"}</h3>')
        for key, bins in data['splits'].items():
            doc.append(f'<details><summary>{LABELS[key]}</summary>{table(bins)}</details>')
        doc.append('<details><summary>按入场日期分前后段</summary>'+table(data['time_halves'])+'</details>')
    doc.append('''<h2>口径与来源</h2><p>净R以入场时含费用的风险金额为单位。退出日全天排除在持仓峰值外，避免把卖出后的价格当作持仓收益。四笔模拟卖价因滑点低于当日最低报价，差幅均在原模拟滑点范围内。日K的高低价无法确定盘中先后顺序。本轮是成交后分组和案例审查，所列待检验规则尚未重跑。</p>
<ul><li><a href="trade-features.csv">268笔交易特征与路径</a> · <a href="summary.json">分组汇总</a> · <a href="method.json">核验口径</a></li>
<li><a href="../20261109-algorithm-combination-comparison/ranking.csv">全量账户对照</a> · <a href="../20261026-c2-full-comparable/report.html">C2全量复验</a> · <a href="../20261026-volatility-entry-filter/report.html">ATR门槛对照</a></li>
<li><a href="../20261024-w-retest-cohort/report.html">旧日线双底回踩复验</a> · <a href="../../docs/double-bottom-complete-diagram-audit.md">600482图形核查</a> · <a href="../20261025-mainboard-inverse-head-shoulders-v3-retest/report.html">旧头肩底回踩复验</a></li></ul></html>''')
    (OUT/'report.html').write_text('\n'.join(doc), encoding='utf-8')
    print('Report written:',OUT/'report.html')


if __name__=='__main__':
    main()
