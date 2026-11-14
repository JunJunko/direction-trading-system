"""Held-price paths for v5 breakout and weekly trend; no exit-rule optimization."""
import csv
import html
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/20261025-mainboard-inverse-head-shoulders-v5-breakout-trend'
OUT = ROOT / 'audits/20261025-ihs-v5-profit-paths'


def rows(p):
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save(p, rs):
    with p.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rs[0]))
        w.writeheader()
        w.writerows(rs)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fills = [r for r in rows(RUN / 'entry_audit.csv') if r.get('execution_reason') == 'filled']
    trades = {r['setup_id']: r for r in rows(RUN / 'trades.csv')}
    config, result = load(RUN / 'config.json'), load(RUN / 'summary.json')
    x = config['execution']
    needed = {a['symbol'] for a in fills}
    raw = defaultdict(list)
    with (RUN / 'bars.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in needed and r['date'] <= '20260930':
                raw[r['symbol']].append(r)
    records, daily, charts = [], [], []
    for a in fills:
        symbol, pid = a['symbol'], a['setup_id']
        trade = trades.get(pid)
        bs = sorted(raw[symbol], key=lambda b: b['date'])
        entrybar = next(b for b in bs if b['date'] == a['date'])
        factor = float(entrybar['factor'])
        fill, qty, fee, risk = (float(a[k]) for k in ('fill', 'filled_quantity', 'entry_fee', 'expected_loss'))
        held = [b for b in bs if b['date'] >= a['date'] and (not trade or b['date'] < trade['exit_date'])]
        assert held

        def price(b, key):
            return float(b[key]) * float(b['factor']) / factor

        def net(v):
            proceeds = v * qty * (1 - x['slippage'])
            return proceeds - fill * qty - fee - max(5, proceeds * x['commission_rate']) - proceeds * x['sell_tax_after_20230828']

        highbar = max(held, key=lambda b: price(b, 'high'))
        closebar = max(held, key=lambda b: price(b, 'close'))
        peak_high_net, peak_close_net = net(price(highbar, 'high')), net(price(closebar, 'close'))
        terminal = float(trade['pnl']) if trade else (price(held[-1], 'close') - fill) * qty - fee
        if trade:
            proceeds = float(trade['exit']) * float(trade['quantity'])
            rebuilt = proceeds - fill * qty - fee - max(5, proceeds * x['commission_rate']) - proceeds * x['sell_tax_after_20230828']
            assert math.isclose(rebuilt, terminal, abs_tol=1e-6)
        classification = ('未平仓' if not trade else '盈利平仓' if terminal > 0 else
                          '收盘曾达1R后亏损' if peak_close_net >= risk else
                          '仅盘中曾达1R后亏损' if peak_high_net >= risk else
                          '曾有净浮盈但不足1R' if peak_high_net > 0 else
                          '未观察到净浮盈')
        r = dict(symbol=symbol, setup_id=pid, entry_date=a['date'], exit_date=trade['exit_date'] if trade else '',
                 exit_reason=trade['reason'] if trade else 'OPEN_MARKED', closed=bool(trade),
                 entry=fill, quantity=qty, initial_R=risk, held_complete_bars=len(held),
                 first_close_gross_return=price(held[0], 'close') / fill - 1,
                 first_close_net_R=net(price(held[0], 'close')) / risk,
                 peak_high_date=highbar['date'], peak_high_gross_return=price(highbar, 'high') / fill - 1,
                 peak_high_net_R=peak_high_net / risk,
                 peak_close_date=closebar['date'], peak_close_gross_return=price(closebar, 'close') / fill - 1,
                 peak_close_net_R=peak_close_net / risk,
                 ever_close_net_positive=peak_close_net > 0,
                 first_close_at_1R=next((b['date'] for b in held if net(price(b, 'close')) >= risk), ''),
                 held_high_touched_target=price(highbar, 'high') >= float(a['target']),
                 held_close_reached_target=price(closebar, 'close') >= float(a['target']),
                 final_net_pnl=terminal, final_net_R=terminal / risk,
                 high_to_final_net_giveback_R=(peak_high_net - terminal) / risk,
                 classification=classification)
        records.append(r)
        plotrows = []
        for b in held:
            day = dict(symbol=symbol, setup_id=pid, date=b['date'],
                       close_net_R=net(price(b, 'close')) / risk,
                       high_estimated_net_R=net(price(b, 'high')) / risk,
                       low_estimated_net_R=net(price(b, 'low')) / risk)
            daily.append(day)
            plotrows.append(day)
        if trade:
            plotrows.append(dict(date=trade['exit_date'], close_net_R=terminal / risk,
                                 high_estimated_net_R=terminal / risk, low_estimated_net_R=terminal / risk))
        low = min(0, min(d['low_estimated_net_R'] for d in plotrows)) - .15
        high = max(1, max(d['high_estimated_net_R'] for d in plotrows)) + .15
        xp = lambda i: 60 + 820 * i / max(1, len(plotrows) - 1)
        yp = lambda v: 250 - 200 * (v - low) / (high - low)
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 310"><rect width="960" height="310" fill="#f6f9fc"/>'
        for level in (0, 1):
            svg += f'<path d="M60 {yp(level):.2f} H880" stroke="#96a9bd" stroke-dasharray="5 4"/><text x="20" y="{yp(level):.2f}">{level}R</text>'
        for i, d in enumerate(plotrows):
            svg += f'<path d="M{xp(i):.2f} {yp(d["low_estimated_net_R"]):.2f} V{yp(d["high_estimated_net_R"]):.2f}" stroke="#b3c5d7"/>'
        points = ' '.join(f'{xp(i):.2f},{yp(d["close_net_R"]):.2f}' for i, d in enumerate(plotrows))
        svg += f'<polyline points="{points}" fill="none" stroke="#167aa0" stroke-width="2"/><text x="60" y="25">{symbol} · {classification} · 最高盘中估计净R {peak_high_net/risk:.2f}</text><text x="60" y="290">{a["date"]} → {plotrows[-1]["date"]}；蓝线为收盘净R，退出日仅绘制实际成交净R</text></svg>'
        filename = symbol + '-' + a['date'] + '.svg'
        (OUT / filename).write_text(svg, encoding='utf-8')
        charts.append(f'<details><summary>{symbol} · {classification}</summary><img src="{filename}" style="width:100%"/></details>')
    closed = [r for r in records if r['closed']]
    opened = [r for r in records if not r['closed']]
    assert len(records) == result['filled_buys']
    assert len(closed) == result['closed_trades']
    losers = [r for r in closed if r['final_net_pnl'] < 0]
    assert math.isclose(sum(r['final_net_pnl'] for r in records), result['final_equity'] - result['initial_cash'], abs_tol=1e-6)
    stats = dict(total=len(records), closed=len(closed), open=len(opened), losing=len(losers), winning=len(closed)-len(losers),
                 classification_counts=dict(Counter(r['classification'] for r in closed)),
                 first_day_close_net_negative=sum(r['first_close_net_R'] < 0 for r in closed),
                 never_intraday_net_positive=sum(r['peak_high_net_R'] <= 0 for r in closed),
                 ever_close_net_positive=sum(r['ever_close_net_positive'] for r in closed),
                 intraday_net_at_least_1R=sum(r['peak_high_net_R'] >= 1 for r in closed),
                 close_net_at_least_1R=sum(r['peak_close_net_R'] >= 1 for r in closed),
                 intraday_net_at_least_2R=sum(r['peak_high_net_R'] >= 2 for r in closed),
                 intraday_net_at_least_3R=sum(r['peak_high_net_R'] >= 3 for r in closed),
                 closed_pnl=sum(r['final_net_pnl'] for r in closed),
                 open_marked_pnl=sum(r['final_net_pnl'] for r in opened),
                 held_close_target_reached=sum(r['held_close_reached_target'] for r in closed), losing_classification_counts=dict(Counter(r['classification'] for r in losers)), losers_high_1R=sum(r['peak_high_net_R']>=1 for r in losers), losers_close_1R=sum(r['peak_close_net_R']>=1 for r in losers), losers_high_2R=sum(r['peak_high_net_R']>=2 for r in losers), losers_high_3R=sum(r['peak_high_net_R']>=3 for r in losers), losses_after_1R=sum(r['final_net_pnl'] for r in losers if r['peak_high_net_R']>=1), losses_below_1R=sum(r['final_net_pnl'] for r in losers if r['peak_high_net_R']<1))
    save(OUT / 'trade-paths.csv', records)
    save(OUT / 'daily-paths.csv', daily)
    (OUT / 'summary.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    body = f'<h1>v5突破入场：买后走弱还是浮盈回吐？</h1><p>{len(records)}笔成交，{len(closed)}笔已平（{len(losers)}笔亏损），{len(opened)}笔未平。只审计真实持仓阶段，不测试新的退出规则。</p>'
    body += f'<p>已平仓交易中，{stats["first_day_close_net_negative"]}笔买入当日收盘净亏。{len(losers)}笔最终亏损中，{stats["losers_high_1R"]}笔曾达至少1R盘中估计净浮盈，{stats["losers_close_1R"]}笔最高收盘净浮盈达到1R；其中{stats["losers_high_3R"]}笔盘中曾达3R。“首日亏损”与“后来曾经盈利”并不互斥。</p>'
    body += '<ul>' + ''.join('<li>' + html.escape(k) + '：' + str(v) + '笔</li>' for k, v in stats['classification_counts'].items()) + '</ul>'
    body += '<div class="scroll"><table><tr><th>股票</th><th>买入→卖出</th><th>持有完整日线</th><th>首日收盘净R</th><th>最高盘中涨幅</th><th>最高盘中净R</th><th>最高收盘净R</th><th>峰值日</th><th>最终净损益</th><th>退出原因</th><th>路径分类</th></tr>'
    for r in sorted(records, key=lambda r: r['peak_high_net_R'], reverse=True):
        values = [r['symbol'], r['entry_date'] + ' → ' + (r['exit_date'] or '持仓'), r['held_complete_bars'],
                  f"{r['first_close_net_R']:.2f}", f"{r['peak_high_gross_return']:.2%}", f"{r['peak_high_net_R']:.2f}",
                  f"{r['peak_close_net_R']:.2f}", r['peak_high_date'], f"{r['final_net_pnl']:,.2f}", r['exit_reason'], r['classification']]
        body += '<tr>' + ''.join('<td>' + html.escape(str(v)) + '</td>' for v in values) + '</tr>'
    body += '</table></div><p>R为原始含成本止损风险金额；净浮盈估计扣除买入佣金、假设卖出的滑点、佣金和税，正浮盈并不代表可按峰值成交。复权使用入场时经济价格和数量单位。退出日整根日线高低点不纳入统计，因为缺少盘中先后顺序；因此MFE是保守观察值，“未观察到”不等于证明从未出现。入场日到收盘的数据已在买入之后，但T+1可能限制兑现。</p><p>最高价、最高收盘价与最终损益的差值不是可保证实现的漏赚金额。未平仓按市值计价，未扣尚未发生的卖出成本。首次1R时点与逐日路径见下载数据。</p><h2>逐笔路径</h2>' + ''.join(charts)
    body += '<p><a href="trade-paths.csv">逐笔路径数据</a> · <a href="daily-paths.csv">逐日净R</a> · <a href="summary.json">统计</a> · <a href="../../runs/' + RUN.name + '/report.html">原始回测</a></p>'
    css = 'body{font:16px/1.7 system-ui;max-width:1450px;margin:35px auto;padding:0 20px;color:#17334c}.scroll{overflow:auto}table{border-collapse:collapse;font-size:13px}td,th{padding:9px;border:1px solid #dae3ef;white-space:nowrap}th{background:#e7eff8}details{margin:15px 0;padding:12px;border:1px solid #dbe3ef}summary{cursor:pointer}'
    (OUT / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>v5利润路径审计</title><style>' + css + '</style>' + body, encoding='utf-8')
    shutil.copy2(__file__, OUT / Path(__file__).name)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    for r in sorted(records, key=lambda r: r['peak_high_net_R'], reverse=True):
        print(r['symbol'], r['entry_date'], 'highR', round(r['peak_high_net_R'], 3), 'closeR', round(r['peak_close_net_R'], 3), 'pnl', round(r['final_net_pnl'], 2), r['classification'])


if __name__ == '__main__':
    main()
