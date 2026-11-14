"""Independently reconcile fixed v4 rules, account output and rejection funnel."""
import csv
import gzip
import hashlib
import html
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'runs/20261025-mainboard-inverse-head-shoulders-v4-risk-defined'
BASE = ROOT / 'runs/20261025-mainboard-inverse-head-shoulders-v3-retest'


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def rows(p):
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def dump(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha(p):
    digest = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(b)
    return digest.hexdigest()


def close(a, b):
    assert math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10), (a, b)


def main():
    manifest = load(OUT / 'manifest.json')
    config = load(OUT / 'config.json')
    baseline = load(BASE / 'config.json')
    summary = load(OUT / 'summary.json')
    before = load(BASE / 'summary.json')
    rules = config['strategies'][0]['params']
    width_cap = rules.get('max_entry_risk')
    plans = load(OUT / 'plans.json')
    assert {k: v for k, v in config.items() if k != 'strategies'} == {
        k: v for k, v in baseline.items() if k != 'strategies'}
    assert manifest['bars_sha256'] == load(BASE / 'manifest.json')['bars_sha256'] == sha(OUT / 'bars.csv')
    assert sha(OUT / 'config.json') == manifest['config_sha256']
    digest = hashlib.sha256()
    for p in sorted((OUT / 'source/src').rglob('*.py')):
        digest.update(str(p.relative_to(OUT / 'source/src')).encode())
        digest.update(p.read_bytes())
    assert digest.hexdigest() == manifest['code_sha256']

    counts, invalidations = Counter(), Counter()
    registered = {}
    files = list((OUT / 'signal-events').glob('*.gz'))
    assert len(files) == 3214
    for path in files:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            for line in f:
                event = json.loads(line)
                if event['event'] == 'ihs_retest_registered':
                    registered[event['setup_id']] = event
                if not manifest['evaluation_start'] <= event['date'] <= manifest['evaluation_end']:
                    continue
                counts[event['event']] += 1
                if event['event'] == 'ihs_retest_invalidated':
                    invalidations[event['reason']] += 1
    assert dict(counts) == summary['signal_counts']
    symbols = {p['symbol'] for p in plans}
    hist = defaultdict(list)
    with (OUT / 'bars.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:
                hist[r['symbol']].append(r)
    indexes = {}
    for symbol, bs in hist.items():
        bs.sort(key=lambda b: b['date'])
        indexes[symbol] = {b['date']: i for i, b in enumerate(bs)}
    checks = []
    for p in plans:
        bs = hist[p['symbol']]
        ix = indexes[p['symbol']]
        i = ix[p['date']]
        factor = float(bs[i]['factor'])

        def price(j, field):
            return float(bs[j][field]) * float(bs[j]['factor']) / factor

        atr = sum(max(price(j, 'high') - price(j, 'low'),
                      abs(price(j, 'high') - price(j - 1, 'close')),
                      abs(price(j, 'low') - price(j - 1, 'close')))
                  for j in range(i - 13, i + 1)) / 14
        # ATR is known at the completed signal close, before next-session execution.
        close(atr, p['ihs_entry_atr'])
        right = price(ix[p['ihs_right_date']], 'low')
        left = price(ix[p['ihs_left_date']], 'low')
        assert right >= left
        close(p['stop'], right - rules['stop_buffer_atr'] * atr)
        close(p['target'], 2 * p['ihs_neckline'] - p['ihs_floor'])
        assert registered[p['setup_id']]['date'] == p['ihs_known_at'] < p['ihs_retest_date'] <= p['date']
        assert sum(p['ihs_breakout_date'] < b['date'] <= p['date'] for b in bs) <= rules['retest_sessions']
        after = [j for j in range(i + 1) if bs[j]['date'] > p['ihs_known_at']]
        streak = 0
        for j in after:
            streak = streak + 1 if price(j, 'close') < p['ihs_neckline'] else 0
            assert streak < rules['reclaim_sessions']
        low = min(price(j, 'low') for j in after)
        close(low, p['ihs_retest_low'])
        assert low > right and low >= p['ihs_neckline'] * (1 - rules['failure_tolerance'])
        assert low <= p['ihs_neckline'] * (1 + rules['touch_tolerance'])
        assert p['ihs_neckline'] < p['trigger'] <= p['ihs_entry_ceiling']
        assert price(i, 'close') > max(price(i, 'open'), price(i - 1, 'close'))
        distance = (p['trigger'] - p['stop']) / p['trigger']
        checks.append(dict(setup_id=p['setup_id'], symbol=p['symbol'], date=p['date'],
                           reference_stop_distance=distance,
                           reference_stop_ATR=(p['trigger'] - p['stop']) / atr,
                           reference_within_width_limit=width_cap is None or distance <= width_cap + 1e-12,
                           reference_outside_noise=p['trigger'] - p['stop'] >= rules['min_stop_atr'] * atr - 1e-12))
    audits = rows(OUT / 'entry_audit.csv')
    filled = [a for a in audits if a.get('execution_reason') == 'filled']
    pm = {p['setup_id']: p for p in plans}
    for a in filled:
        p = pm[a['setup_id']]
        b = hist[a['symbol']][indexes[a['symbol']][a['date']]]
        scale = p['factor'] / float(b['factor'])
        fill, stop = float(a['fill']), float(a['stop'])
        if width_cap is not None:
            assert (fill - stop) / fill <= width_cap + 1e-12
        assert fill - stop >= p['ihs_entry_atr'] * scale * rules['min_stop_atr'] - 1e-12
        close(stop, p['stop'] * scale)
        assert float(a['net_rr']) > config['risk']['min_rr']
        assert float(a['expected_loss']) <= float(a['risk_budget'])
    curve = rows(OUT / 'equity.csv')
    assert len(curve) == 241
    peak = config['initial_cash']
    for r in curve:
        peak = max(peak, float(r['equity']))
        close(float(r['drawdown']), float(r['equity']) / peak - 1)
    close(float(curve[-1]['equity']), summary['final_equity'])
    exits = [e for e in rows(OUT / 'decisions.csv') if e.get('event') == 'exit_intent'
             and e.get('reason') == 'ihs_neckline_not_reclaimed']
    for event in exits:
        p = pm[event['setup_id']]
        entry = next(a for a in filled if a['setup_id'] == event['setup_id'])
        held = [b for b in hist[p['symbol']] if entry['date'] <= b['date'] <= event['date']]
        n = rules['reclaim_sessions']
        assert len(held) >= n
        assert all(float(b['close']) * float(b['factor']) < p['ihs_neckline'] * p['factor']
                   for b in held[-n:])
    for trade in rows(OUT / 'trades.csv'):
        if trade['reason'] == 'ihs_neckline_not_reclaimed':
            assert any(e['setup_id'] == trade['setup_id'] and e['date'] < trade['exit_date'] for e in exits)
    detail = dict(invalidations=dict(invalidations),
                  execution_reasons=dict(Counter(a.get('execution_reason', '') for a in audits)),
                  risk_reasons=dict(Counter(a.get('risk_reason', '') for a in audits)),
                  price_stop_distance_cap=width_cap,
                  signal_reference_width_pass=sum(c['reference_within_width_limit'] for c in checks),
                  signal_reference_both_pass=sum(c['reference_within_width_limit'] and c['reference_outside_noise'] for c in checks))
    capped = ROOT / 'runs/20261025-mainboard-inverse-head-shoulders-v4-risk-defined'
    same_signals = None
    if width_cap is None and (capped / 'plans.json').exists():
        oldconfig = load(capped / 'config.json')
        oldconfig['strategies'][0]['params'].pop('max_entry_risk')
        assert config == oldconfig
        signature = lambda ps: sorted((p['setup_id'], p['date'], p['trigger'], p['stop'], p['target']) for p in ps)
        assert signature(plans) == signature(load(capped / 'plans.json'))
        same_signals = True
    dump(OUT / 'entry-risk-diagnostics.json', detail)
    dump(OUT / 'signal-risk-checks.json', checks)
    dump(OUT / 'verification-v4.json', dict(all_3214_scanned=True, price_data_hash_equal=True,
         costs_and_account_config_equal=True, source_hash_verified=True, causal_signal_checks=len(checks),
         filled_entry_risk_checks=len(filled), equity_rows_verified=len(curve), parameters_changed=False,
         no_out_of_sample_data_accessed=True, price_stop_distance_cap=width_cap,
         signals_equal_to_capped_v4=same_signals, neckline_exit_intents_checked=len(exits)))
    names = {'ihs_entry_risk_too_wide': '实际买价到止损超过2%',
             'ihs_stop_inside_noise': '止损空间不足1 ATR',
             'right_shoulder_below_left': '右肩低于左肩',
             'neckline_not_reclaimed': '连续3个收盘未收复颈线',
             'right_shoulder_broken': '右肩被跌破', 'head_broken': '头部被跌破',
             'neckline_retest_failed': '回踩跌破颈线容忍带', 'expired': '等待回踩超时',
             'target_already_touched': '入场前已经触及原目标',
             'net_rr_not_above_threshold': '含成本收益风险比未严格超过3'}

    def table(headers, data):
        esc = lambda x: html.escape(str(x))
        return '<div class="scroll"><table><tr>' + ''.join('<th>' + esc(x) + '</th>' for x in headers) + '</tr>' + ''.join(
            '<tr>' + ''.join('<td>' + esc(x) + '</td>' for x in row) + '</tr>' for row in data) + '</table></div>'

    body = '<h1>头肩底 v4 风险定义版：全主板回测</h1><p>固定参数 · 2025-10-09 至 2026-09-30 · 241个交易日 · 3,214只股票 · 2,856,672根日线</p>'
    if width_cap is None:
        body += '<p><b>本轮按用户要求移除固定价格止损幅度上限。</b>保留距颈线2%的防追高限制、1 ATR最小止损空间、账户单笔0.5%风险预算及含成本净收益风险比门槛。与上一版相比仅取消止损宽度上限，367个信号的日期、入场参考价、止损及目标已逐一核对相同。</p>'
    if not filled:
        body += '<p><b>本轮没有成交。零收益、零回撤来自空仓，不能解释为策略有效。</b>未放宽风险条件或修改参数。</p>'
    body += table(['指标', 'v3', 'v4'], [
        ['回踩信号', load(BASE / 'account-verification.json')['unique_plans'], len(plans)],
        ['信号股票', before['signal_stocks'], summary['signal_stocks']],
        ['买入 / 已平 / 未平', f"{before['filled_buys']} / {before['closed_trades']} / {before['open_positions']}",
         f"{summary['filled_buys']} / {summary['closed_trades']} / {summary['open_positions']}"],
        ['期末权益', f"{before['final_equity']:,.2f}", f"{summary['final_equity']:,.2f}"],
        ['收益率', f"{before['total_return']:.2%}", f"{summary['total_return']:.2%}"],
        ['最大回撤', f"{abs(before['max_drawdown']):.2%}", f"{abs(summary['max_drawdown']):.2%}"],
        ['已平胜率', f"{before['win_rate']:.2%}", '无样本' if summary['win_rate'] is None else f"{summary['win_rate']:.2%}"]])
    body += '<h2>候选与审批</h2><p>候选信号先经过形态与回踩状态机，再接受原账户的资格、实际开盘价和风险审核。下列原因按各阶段实际记录统计，不同阶段的计数不能直接相加作互斥交易数。失效计数可能涉及预热期登记、考核期失效的候选。</p>'
    for heading, reasons in [('形态与回踩失效', detail['invalidations']), ('风险审批记录', detail['risk_reasons']),
                              ('执行审批记录', detail['execution_reasons'])]:
        body += '<h3>' + heading + '</h3>' + table(['原因', '记录数'], [(names.get(k, k), v) for k, v in reasons.items()])
    body += '<p>仅以信号收盘参考价计算，满足当前宽度规则的信号为 ' + str(detail['signal_reference_width_pass']) + ' 个；同时具备至少1ATR空间的为 ' + str(detail['signal_reference_both_pass']) + ' 个。未设置宽度上限时第一项为全部信号。这不是实际成交审批结果，开盘跳空、滑点和账户资格仍会改变判断。</p>'
    cap_text = '不设置固定百分比上限' if width_cap is None else f'不得超过{width_cap:.0%}'
    body += '<h2>固定规则与边界</h2><p>右肩不得低于左肩；突破后20个股票交易日内回踩；连续3个收盘未收复颈线则失效。止损为右肩低点减去信号收盘已知ATR14的0.25倍，实际成交价到止损' + cap_text + '，但不得小于1ATR。账户单笔预算仍为0.5%，净收益风险比须严格大于3。目标固定为颈线加头部至颈线高度，不得放远目标通过审核。</p><p>本轮包含原固定形态目标出场和新增的颈线失守退出，未叠加MT1周线模块。v4改变了形态资格、回踩状态和入场风险，因此与v3属于完整策略版本比较，不能把收益差单独归因于某个条件。当前历史样本已经研究过，不是样本外验证。</p><p>正常执行沿用A股T+1、跳空、停牌、涨跌停、手续费及滑点模型；日线不能还原盘口排队。除权沿用合成总回报数量调整。本轮未访问2026-09-30之后的数据。</p>'
    body += '<h2>逐笔实际买入及初始风险</h2>' + table(
        ['股票', '买入日', '买价', '初始止损', '价格止损幅度', '数量', '预计损失元', '预算元', '净收益风险比'],
        [[a['symbol'], a['date'], f"{float(a['fill']):.4f}", f"{float(a['stop']):.4f}",
          f"{(float(a['fill'])-float(a['stop']))/float(a['fill']):.2%}", a['filled_quantity'],
          f"{float(a['expected_loss']):.2f}", f"{float(a['risk_budget']):.2f}", f"{float(a['net_rr']):.3f}"] for a in filled])
    trades = rows(OUT / 'trades.csv')
    body += '<h2>已平仓交易</h2>' + table(['股票', '买入日', '卖出日', '成交价', '净损益元', '净R', '原因'],
        [[t['symbol'], t['entry_date'], t['exit_date'], f"{float(t['exit']):.4f}",
          f"{float(t['pnl']):.2f}", f"{float(t['realized_r']):.3f}", t['reason']] for t in trades])
    body += '<h2>期末持仓</h2><p>总收益包含期末持仓市值浮盈亏，尚未发生的卖出成本未扣除。</p>' + table(
        ['股票', '买入日', '当期标度成本', '数量', '有效止损'],
        [[p['symbol'], p['entry_date'], f"{p['entry']:.4f}", p['quantity'], f"{p['stop']:.4f}"] for p in summary['positions']])
    for name, label in [('entry_audit.csv', '入场审批明细'), ('trades.csv', '已平交易'), ('orders.csv', '订单'),
                        ('signal-risk-checks.json', '逐信号风险复核'), ('entry-risk-diagnostics.json', '拒绝与失效统计'),
                        ('verification-v4.json', '独立验证记录'), ('config.json', '冻结配置')]:
        body += '<p><a href="' + name + '">' + label + '</a></p>'
    (OUT / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>v4风险定义版回测</title><style>body{font:16px/1.7 system-ui;max-width:1200px;margin:35px auto;padding:0 22px;color:#17344f;background:#f6f8fb}table{border-collapse:collapse;background:white;margin:18px 0}td,th{padding:9px;border:1px solid #dce5ef}th{background:#e5edf8}.scroll{overflow:auto}</style>' + body, encoding='utf-8')
    shutil.copy2(__file__, OUT / 'source' / Path(__file__).name)
    print(json.dumps(dict(summary=summary, diagnostics=detail), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
