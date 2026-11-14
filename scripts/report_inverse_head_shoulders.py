"""Readable audit report for the frozen head-and-shoulders experiment."""
import csv
import html
import json
import shutil
import sys
from collections import Counter
from pathlib import Path


def main(folder):
    out = Path(folder)
    load = lambda name: json.loads((out / name).read_text(encoding='utf-8'))
    manifest, summary, plans = load('manifest.json'), load('summary.json'), load('plans.json')
    verification = load('account-verification.json')
    with (out / 'entry_audit.csv').open(encoding='utf-8-sig', newline='') as f:
        audits = list(csv.DictReader(f))
    gross = [(p['target'] - p['trigger']) / (p['trigger'] - p['stop']) for p in plans]
    net = [float(a['net_rr']) for a in audits if a.get('net_rr')]
    diagnostic = dict(signals=len(plans), signal_symbols=summary['signal_stocks'],
        signal_gross_rr_min=min(gross) if gross else None, signal_gross_rr_max=max(gross) if gross else None,
        audited_net_rr_min=min(net) if net else None, audited_net_rr_max=max(net) if net else None,
        monthly_signals=dict(sorted(Counter(p['date'][:6] for p in plans).items())),
        risk_reasons=summary['risk_reasons'], rejected_signals=summary['rejection_counts'])
    (out / 'diagnostics.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
    with (out / 'signals.csv').open('w', encoding='utf-8-sig', newline='') as f:
        keys = ['date', 'symbol', 'setup_id', 'trigger', 'stop', 'target', 'ihs_left_date',
                'ihs_head_date', 'ihs_right_date', 'ihs_neckline', 'gross_rr']
        writer = csv.DictWriter(f, keys)
        writer.writeheader()
        for p, rr in zip(plans, gross):
            writer.writerow(dict({k: p[k] for k in keys if k != 'gross_rr'}, gross_rr=rr))
    esc = lambda value: html.escape(str(value))
    reason_names = {'net_rr_not_above_threshold': '净盈亏比未超过 3',
                    'universe_ineligible_signal': '信号日不满足上市 / 非 ST 资格',
                    'invalid_bracket': '含滑点后的入场价格已超出止损目标区间',
                    'insufficient_budget_or_cash': '风险预算或资金不足以买入一手'}
    def table(headers, rows):
        return '<table><thead><tr>' + ''.join('<th>'+esc(x)+'</th>' for x in headers) + '</tr></thead><tbody>' + ''.join(
            '<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows) + '</tbody></table>'
    def fmt(value):
        return '无样本' if value is None else f'{value:.4f}'
    result = table(['指标', '结果'], [
        ('股票数', manifest['stocks']), ('日线数', f"{manifest['bar_count']:,}"),
        ('考核区间', f"{manifest['first_session']}—{manifest['last_session']}（{manifest['sessions']} 个交易日）"),
        ('入场信号', len(plans)), ('信号股票', summary['signal_stocks']),
        ('成交买入', summary['filled_buys']), ('已平仓', summary['closed_trades']), ('期末持仓', summary['open_positions']),
        ('期初资金', f"{summary['initial_cash']:,.2f}"), ('期末权益', f"{summary['final_equity']:,.2f}"),
        ('收益率', f"{summary['total_return']:.2%}"), ('最大回撤', f"{abs(summary['max_drawdown']):.2%}"),
        ('胜率', '无成交，无法估计' if not summary['closed_trades'] else f"{summary['win_rate']:.2%}")])
    reasons = table(['拒绝原因', '数量'], [(reason_names.get(r, r), n) for r, n in summary['rejection_counts'].items()])
    month = table(['月份', '信号数'], [(m[:4]+'-'+m[4:], n) for m, n in diagnostic['monthly_signals'].items()])
    retest = manifest['rule_version'].endswith('_retest')
    candidate_rows = table(['日期', '股票', '回踩确认收盘' if retest else '突破收盘', '右肩止损' if retest else '头部止损', '量度目标', '毛盈亏比'],
        [(p['date'], p['symbol'], fmt(p['trigger']), fmt(p['stop']), fmt(p['target']), fmt(rr)) for p, rr in list(zip(plans, gross))[:30]])
    body = '<h1>头肩底：全主板回测</h1><p>策略版本：'+esc(manifest['rule_version'])+'</p><p class="sub">固定参数 · 历史上市与 ST 资格 · 共享账户 · 日线结构研究</p>'
    if summary['filled_buys'] == 0:
        body += '<div class="callout"><b>'+('存在入场候选，但没有通过风控成交。' if plans else '本区间未生成入场候选。')+'</b><br>零收益和零回撤来自空仓，无法据此评价盈利能力。</div>'
    if (out/'comparison.json').exists():
        comparison = load('comparison.json')
        before, after = comparison['baseline'], comparison['candidate']
        body += '<h2>相同快照：v1 与 v2 对照</h2>' + table(['指标','v1','v2'],[
            ('入场候选',before['signals'],after['signals']),
            ('候选股票',before['signal_stocks'],after['signal_stocks']),
            ('成交买入',before['filled_buys'],after['filled_buys']),
            ('收益率',f"{before['total_return']:.2%}",f"{after['total_return']:.2%}")])
        body += '<p>两个版本使用相同行情、历史股票资格、考核窗口和账户规则。候选增减表示识别规则变化，不能直接视为准确率改善。'
        body += '<a href="comparison.json">完整对照及候选布局交集</a>。</p>'
        overlap = comparison['layout_overlap']
        body += table(['布局匹配（按股票及三底日期）','数量'],[
            ('两个版本共有',overlap['shared']),('仅 v1 出现',overlap['v1_only']),
            ('仅 v2 出现',overlap['v2_only'])])
        quality = comparison['quality']
        if quality['min_head_prominence'] is not None:
            body += '<p>v2 全部已发信号的几何范围：最小头部突出度 '+f"{quality['min_head_prominence']:.2%}"
            body += '，最大肩差 '+f"{quality['max_shoulder_gap']:.2%}"+'，最大颈线高点差 '+f"{quality['max_neckline_gap']:.2%}"+'（均相对于形态高度）。</p>'
        else:
            body += '<p>v2 无入场信号。</p>'
    body += '<h2>回测结果</h2>'+result+'<h2>信号为何未成交</h2>'+reasons
    if retest:
        body += '<p>首次突破只登记，随后等待回踩颈线并收盘回升确认；次日开盘若低于颈线或含滑点入场价高于颈线 2%，取消交易。止损取右肩最低价，目标仍为颈线加头部高度，净盈亏比严格大于 3。收盘达到目标后下一可执行开盘退出。</p>'
        body += '<p>等待最多 14 根股票日线；颈线上方 0.5% 以内视为触及，跌破颈线超过 2.5%、右肩/头部失守或已触及目标则取消。这些是固定研究参数，尚非最优参数。</p>'
    else:
        body += '<p>颈线为 N，头部低点为 H，目标为 2N−H；收盘突破后的入场参考价 E&gt;N。'
        body += '因此毛盈亏比 (2N−H−E)/(E−H)&lt;1；费用和滑点会进一步降低净盈亏比。配置要求净盈亏比严格大于 3。</p>'
    body += '<p>本次信号毛盈亏比范围：'+fmt(diagnostic['signal_gross_rr_min'])+'—'+fmt(diagnostic['signal_gross_rr_max'])
    body += '；已计算的净盈亏比范围：'+fmt(diagnostic['audited_net_rr_min'])+'—'+fmt(diagnostic['audited_net_rr_max'])+'。</p>'
    body += '<h2>每月信号</h2>'+month+'<h2>前 30 个候选</h2>'+candidate_rows
    body += '<p>完整候选见 <a href="signals.csv">signals.csv</a>；逐笔风控见 <a href="entry_audit.csv">entry_audit.csv</a>。</p>'
    body += '<h2>口径与核验</h2><p>扫描全部 3,214 只股票，不限定在之前双底筛出的股票。考核前数据仅预热识别器，考核开始为空仓；'
    body += '全部信号股票在普通共享账户引擎中重新计算，候选 ID、日期、触发价、止损和目标与全量扫描逐项相同。'
    body += '原始数据、配置及代码均保留哈希和快照。参数未根据结果调整。</p>'
    body += '<p>数据为之前研究过的固定快照，不是独立保留样本；采用日线成交近似与合成复权股数调整。'
    body += '此次仅考察头肩底独立策略，尚未检验与双底组合后的收益。</p>'
    body += '<p><a href="manifest.json">运行记录</a> · <a href="account-verification.json">信号核验</a> · '
    for name, label in (('cache-verification.json','缓存等价核验'),('independent-risk-verification.json','独立风控核验')):
        if (out/name).exists():body += '<a href="'+name+'">'+label+'</a> · '
    body += '<a href="config.json">冻结配置</a> · <a href="summary.json">完整统计</a></p>'
    css = 'body{max-width:1000px;margin:40px auto;padding:0 24px;font:16px/1.7 system-ui;color:#172433;background:#f7f9fc}h1{font-size:30px}h2{margin-top:36px;font-size:22px}.sub{color:#52647a}.callout{padding:20px;background:#fff1d7;border-left:4px solid #cc8a12}table{border-collapse:collapse;width:100%;background:white;margin:16px 0;font-size:14px}td,th{padding:8px 12px;border-bottom:1px solid #e2e8ef;text-align:left}th{background:#edf2f8}a{color:#155b9c}'
    (out / 'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>头肩底回测报告</title><style>'+css+'</style>'+body+'</html>', encoding='utf-8')
    shutil.copy2(__file__, out / 'source' / Path(__file__).name)
    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main(sys.argv[1])
