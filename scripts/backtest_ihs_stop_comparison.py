"""Paired stop experiment using the verified, causal v2 signal tape and frozen engine."""
import copy
import csv
import hashlib
import html
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'runs/20261025-mainboard-inverse-head-shoulders-v2'
sys.path.insert(0, str(BASE / 'source/src'))
from trading_system.domain import Bar, Intent
from trading_system.engine import Backtest
from trading_system.data import save_csv
from trading_system.strategies.inverse_head_shoulders import InverseHeadShoulders
from trading_system.universe import MainboardUniverse
from trading_system.risk import RiskManager

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

class FrozenSignals(InverseHeadShoulders):
    """Only entry generation is taped; all position management is inherited unchanged."""
    def __init__(self, name, plans, stop_rule):
        super().__init__(name, {})
        self.plans = {(p['symbol'], p['date']): p for p in plans}
        assert len(self.plans) == len(plans)
        self.stop_rule = stop_rule

    def on_close(self, history, week_ends):
        b = history[-1]
        p = self.plans.get((b.symbol, b.date))
        if p is None:
            return [], []
        assert b.close == p['trigger'] and b.factor == p['factor']
        evidence = {k: v for k, v in p.items() if k not in
                    ('date', 'symbol', 'setup_id', 'trigger', 'stop', 'target', 'right_stop')}
        stop = p['stop'] if self.stop_rule == 'head' else p['right_stop']
        evidence['ihs_stop_rule'] = self.stop_rule
        intent = Intent(self.name, b.symbol, b.date, p['trigger'], stop, p['target'],
                        p['setup_id'], 'inverse_head_shoulders', evidence)
        event = dict(date=b.date, symbol=b.symbol, strategy=self.name, setup_id=p['setup_id'],
                     event='entry_intent', trigger=intent.trigger, stop=stop, target=intent.target, **evidence)
        return [intent], [event]

def main():
    out = ROOT / 'runs/20261025-ihs-head-vs-right-shoulder'
    out.mkdir()
    config, manifest, plans = (load(BASE / n) for n in ('config.json', 'manifest.json', 'plans.json'))
    assert load(BASE/'account-verification.json')['signal_id_date_price_match']
    assert sha(BASE/'bars.csv') == manifest['bars_sha256']
    assert sha(BASE/'universe.json') == manifest['universe_sha256']
    h = hashlib.sha256()
    for p in sorted((BASE/'source/src').rglob('*.py')):
        h.update(str(p.relative_to(BASE/'source/src')).encode()); h.update(p.read_bytes())
    assert h.hexdigest() == manifest['code_sha256']
    shutil.copy2(__file__, out/Path(__file__).name)
    dump(out/'config.json', config)
    needed = {p['symbol'] for p in plans}
    bars, lookup = [], {}
    print('Loading frozen bars', flush=True)
    with (BASE/'bars.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in needed:
                b = Bar(r['symbol'], r['date'], **{k: float(r[k]) for k in
                    ('open','high','low','close','volume','factor','up_limit','down_limit')})
                bars.append(b); lookup[b.symbol, b.date] = b
    for p in plans:
        right = lookup[p['symbol'], p['ihs_right_date']]
        head = lookup[p['symbol'], p['ihs_head_date']]
        p['right_stop'] = right.low * right.factor / p['factor']
        assert math.isclose(head.low * head.factor / p['factor'], p['stop'], rel_tol=1e-12)
        assert p['ihs_right_date'] < p['date']
        assert p['stop'] < p['right_stop'] < p['ihs_neckline'] < p['trigger'] < p['target']
        assert math.isclose(p['target'], 2*p['ihs_neckline']-p['stop'], rel_tol=1e-12)
    bars.sort(key=lambda b: (b.date, b.symbol))
    dump(out/'paired-plans.json', plans)
    calendar, ud = load(BASE/'calendar.json'), load(BASE/'universe.json')
    universe = MainboardUniverse(ud['stocks'], ud['st_by_date'])
    results = {}
    for rule in ('head', 'right_shoulder'):
        folder = out/rule; folder.mkdir()
        strategy = FrozenSignals(config['strategies'][0]['id'], plans, rule)
        def progress(s):
            if s['session'] % 100 == 0:
                print(json.dumps(dict(rule=rule, **s)), flush=True)
        engine = Backtest(copy.deepcopy(config), [strategy]).run(bars,
            calendar['open_dates'], set(calendar['week_ends']),
            evaluation_start=manifest['evaluation_start'], evaluation_end=manifest['evaluation_end'],
            universe=universe, progress=progress)
        entries = [e for e in engine.events if e['event']=='entry_intent']
        assert len(entries) == len(plans) == 2925
        assert {(e['setup_id'], e['date'], e['trigger'], e['target']) for e in entries} == {
            (p['setup_id'], p['date'], p['trigger'], p['target']) for p in plans}
        for name, records in (('decisions',engine.events), ('orders',engine.orders),
                ('trades',engine.trades), ('equity',engine.curve), ('entry_audit',engine.entry_audits)):
            save_csv(folder/(name+'.csv'), records)
        summary = engine.summary()
        summary['plan_approved'] = sum(e['event']=='plan_approved' for e in engine.events)
        summary['rejections'] = dict(Counter(e.get('reason') for e in engine.events
            if e['event'] in ('plan_rejected','entry_rejected')))
        summary['exit_reasons'] = dict(Counter(t['reason'] for t in engine.trades))
        summary['stop_exit_count'] = sum('break' in t['reason'] or 'stop' in t['reason'] for t in engine.trades)
        summary['stop_exit_fraction_of_closed'] = summary['stop_exit_count']/len(engine.trades) if engine.trades else None
        summary['mean_realized_r'] = sum(t['realized_r'] for t in engine.trades)/len(engine.trades) if engine.trades else None
        if rule == 'head':
            previous = load(BASE/'summary.json')
            for key in ('final_equity','total_return','max_drawdown','filled_buys','closed_trades','open_positions'):
                assert summary[key] == previous[key]
            assert summary['rejections'] == previous['rejection_counts']
        dump(folder/'summary.json', summary); results[rule] = summary
        print(json.dumps(dict(rule=rule, summary=summary), ensure_ascii=False), flush=True)
    # Independent flat-account screen isolates stop geometry from portfolio competition.
    diagnostic = []
    for p in plans:
        b = lookup[p['symbol'], p['date']]
        for rule in ('head','right_shoulder'):
            strategy = FrozenSignals(config['strategies'][0]['id'], [p], rule)
            intent = strategy.on_close([b], set())[0][0]
            e = config['execution']
            result = RiskManager(config['risk']).assess(intent, b.close*(1+e['slippage']),
                config['initial_cash'], config['initial_cash'], {}, {}, e['commission_rate'],
                e['sell_tax_after_20230828'], slippage=e['slippage'])
            diagnostic.append(dict(setup_id=p['setup_id'], date=p['date'], symbol=p['symbol'],
                rule=rule, **result))
    save_csv(out/'isolated-screen.csv', diagnostic)
    screen = {rule: dict(approved=sum(d['quantity']>0 for d in diagnostic if d['rule']==rule),
        max_net_rr=max(d.get('net_rr',-math.inf) for d in diagnostic if d['rule']==rule))
        for rule in results}
    dump(out/'comparison.json', dict(results=results, isolated_screen=screen))
    dump(out/'verification.json', dict(status='passed', baseline_head_result_reproduced=True,
        same_2925_signal_id_date_entry_target=True, right_stop_uses_signal_date_factor=True,
        original_stop_and_target_verified=True, frozen_source_sha256=h.hexdigest(),
        bars_sha256=manifest['bars_sha256'], source_plans_sha256=sha(BASE/'plans.json'),
        config_sha256=sha(BASE/'config.json'), script_sha256=sha(Path(__file__)),
        method='Frozen causal v2 tape; two ordinary shared-account replays; only stop changes',
        baseline=str(BASE), population=3214, signal_stocks=1741, sessions=241))
    labels = [('成交笔数','filled_buys'),('已平仓','closed_trades'),('期末持仓','open_positions'),
        ('收益率','total_return'),('最大回撤','max_drawdown'),('胜率','win_rate'),
        ('利润因子','profit_factor'),('止损退出笔数','stop_exit_count'),
        ('已平仓中止损退出比例','stop_exit_fraction_of_closed'),('平均已实现R','mean_realized_r')]
    def fmt(k,v):
        if v is None: return '—'
        if k in ('total_return','max_drawdown','win_rate','stop_exit_fraction_of_closed'): return f'{v:.2%}'
        return f'{v:.4f}' if isinstance(v,float) else str(v)
    table = ''.join('<tr><td>'+label+'</td>'+''.join('<td>'+fmt(key,results[r][key])+'</td>' for r in results)+'</tr>' for label,key in labels)
    report = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>头部与右肩止损对照回测</title>
    <style>body{max-width:1000px;margin:40px auto;padding:20px;font:16px/1.8 system-ui;color:#172b42}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #ccd5df}th{background:#edf3f8}pre{white-space:pre-wrap}a{color:#1262af}</style>
    <h1>头部与右肩止损对照回测</h1><p>2025-10-09 至 2026-09-30；3,214 只股票全量扫描产生的同一批 2,925 个信号，涉及 1,741 只股票。沿用冻结引擎，逐日重放两组独立账户。</p>
    <h2>截图与算法审查</h2><ul><li>包络搜索容纳内部小波动；头部低于两肩；两肩差异与两颈线峰差异按形态高度归一化。20% / 20% / 10% 是研究定义，截图不提供数值。</li>
    <li>颈线取两个峰的较高值，目标为颈线加头部高度，符合图示水平颈线与等距目标。</li>
    <li>下跌背景仅要求左肩之前存在高于颈线的高点，尚不等于完整下降趋势；未增加时间对称约束。</li>
    <li>截图红线表示头部附近的结构失效。头部组采用头部最低价；右肩组采用已确认右肩最低价，均无额外缓冲，触价执行相同退出规则。右肩止损是新增对照假设。</li>
    <li>收盘突破、次日开盘入场、收盘达到目标后次日开盘止盈都是原有执行约定；截图没有规定这些细节。目标区上方压力也未另作历史压力识别。</li></ul>
    <h2>账户结果</h2><table><tr><th>指标</th><th>头部止损</th><th>右肩止损</th></tr>'''+table+'''</table>
    <p>两组均要求净盈亏比严格大于 3，使用相同费用、滑点、风险预算、账户收缩规则、历史资格、涨跌停与 T+1 模型。持仓股数按各自止损距离重新计算。止损比例以已平仓交易为分母；期末持仓按市值计入收益，未强平。</p>
    <h2>信号层诊断（固定空账户，不含资格过滤及持仓竞争）</h2><pre>'''+html.escape(json.dumps(screen,ensure_ascii=False,indent=2))+'''</pre>
    <h2>解释边界</h2><p>头部止损与等距目标的空间近似相等，突破后按信号价筛选的毛盈亏比低于 1。右肩更接近颈线，可以改善盈亏比，但是否达到 3 取决于实际肩部高度及突破溢价。该实验不改变形态识别或调低门槛，也不能将本次已研究样本视为独立样本外验证。</p>
    <p>相同的候选信号不代表两组买入相同股票；止损影响筛选、仓位和账户占用。本报告比较完整策略结果，未测算所有被拒信号的假想持仓表现。</p>
    <h2>可复核文件</h2><ul><li><a href="head/summary.json">头部组结果</a> · <a href="head/decisions.csv">决策</a></li><li><a href="right_shoulder/summary.json">右肩组结果</a> · <a href="right_shoulder/trades.csv">交易</a> · <a href="right_shoulder/equity.csv">净值</a> · <a href="right_shoulder/entry_audit.csv">入场审计</a></li><li><a href="paired-plans.json">配对信号</a> · <a href="isolated-screen.csv">独立筛选</a> · <a href="verification.json">验证与哈希</a></li></ul></html>'''
    (out/'report.html').write_text(report, encoding='utf-8')
    print('COMPLETE '+str(out), flush=True)

if __name__ == '__main__':
    main()
