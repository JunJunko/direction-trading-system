"""Full frozen population scan, then ordinary shared-account signal-stock replay."""
import argparse
import copy
import gzip
import hashlib
import html
import json
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from trading_system.data import save_csv, validate
from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse
from backtest_daily_direction import dump, rows, sha


def initialize(config, first, last, output):
    global SETTINGS
    SETTINGS = config, first, last, Path(output)


def scan(item):
    symbol, bars = item
    config, first, last, output = SETTINGS
    strategy = build_strategies(config['strategies'])[0]
    history, plans = [], []
    counts, warm = Counter(), Counter()
    with gzip.open(output / 'signal-events' / (symbol + '.jsonl.gz'), 'wt', encoding='utf-8') as f:
        for bar in bars:
            if bar.date > last:
                break
            history.append(bar)
            intents, events = strategy.on_close(history, set())
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False) + '\n')
                (warm if bar.date < first else counts)[event['event']] += 1
            if bar.date >= first:
                plans.extend(dict(date=i.date, symbol=i.symbol, setup_id=i.setup_id,
                                  trigger=i.trigger, stop=i.stop, target=i.target, **i.evidence) for i in intents)
    return dict(symbol=symbol, bars=len(bars), counts=dict(counts), warmup=dict(warm), plans=plans)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', default=str(ROOT / 'runs/20261022-mainboard-support-zone'))
    parser.add_argument('--config', default=str(ROOT / 'configs/experiments/inverse_head_shoulders_v3_retest.json'))
    parser.add_argument('--test-log', default=str(ROOT / 'runs/ihs-v3-tests.log'))
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    snapshot, out = Path(args.snapshot), Path(args.output)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    assert len(config['strategies']) == 1 and config['strategies'][0]['type'] in (
        'inverse_head_shoulders', 'enclosing_inverse_head_shoulders', 'retest_inverse_head_shoulders',
        'risk_defined_ihs', 'breakout_trend_ihs', 'confirmed_support_ihs', 'pressure_support_ihs')
    out.mkdir()
    (out / 'signal-events').mkdir()
    shutil.copytree(ROOT / 'src', out / 'source/src', ignore=shutil.ignore_patterns('__pycache__'))
    for source in (Path(__file__), ROOT / 'scripts/backtest_daily_direction.py'):
        shutil.copy2(source, out / 'source' / source.name)
    shutil.copy2(ROOT / 'run.py', out / 'source/run.py')
    shutil.copy2(Path(args.test_log), out / 'tests.log')
    for name in ('calendar.json', 'universe.json', 'stocks.csv', 'coverage.csv'):
        shutil.copy2(snapshot / name, out / name)
    os.link(snapshot / 'bars.csv', out / 'bars.csv')
    dump(out / 'config.json', config)
    first, last = '20251009', '20260930'
    data_hash = sha(out / 'bars.csv')
    assert data_hash == json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))['bars_sha256']
    plan = dict(created_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        source_snapshot=str(snapshot.resolve()), evaluation_start=first, evaluation_end=last,
        bars_sha256=data_hash, config_sha256=sha(out / 'config.json'), universe_sha256=sha(out / 'universe.json'),
        rule_version=config['strategies'][0]['id'], parameter_tuning=False, workers=args.workers,
        method='scan every input stock; recompute every signal in the ordinary shared-account engine',
        limitations=['previously studied snapshot; no independent holdout', 'daily OHLC conservative fills',
                     'synthetic total-return factor share adjustment', 'structure-only research'],
        initial_position_policy='flat; earlier data warm detector only')
    dump(out / 'evaluation-plan.json', plan)
    print(json.dumps(dict(status='loading', output=str(out))), flush=True)
    grouped = defaultdict(list)
    for r in rows(out / 'bars.csv'):
        grouped[r['symbol']].append(Bar(r['symbol'], r['date'], **{k: float(r[k]) for k in
            ('open', 'high', 'low', 'close', 'volume', 'factor', 'up_limit', 'down_limit')}))
    for bars in grouped.values():
        bars.sort(key=lambda b: b.date)
        validate(bars)
    assert len(grouped) == 3214 and sum(map(len, grouped.values())) == 2856672
    totals, warm, plans, results = Counter(), Counter(), [], {}
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
            initargs=(config, first, last, str(out))) as pool:
        futures = [pool.submit(scan, item) for item in sorted(grouped.items())]
        for index, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results[result['symbol']] = result
            totals.update(result['counts']); warm.update(result['warmup']); plans.extend(result['plans'])
            if index % 50 == 0 or index == len(grouped):
                state = dict(status='scanning', stocks_done=index, stocks=len(grouped), plans=len(plans),
                             elapsed_seconds=round(time.monotonic() - started))
                dump(out / 'status.json', state)
                print(json.dumps(state), flush=True)
    plans.sort(key=lambda p: (p['date'], p['symbol'], p['setup_id']))
    assert len({p['setup_id'] for p in plans}) == len(plans)
    dump(out / 'plans.json', plans)
    dump(out / 'signal-counts.json', dict(evaluation=dict(totals), warmup=dict(warm)))
    cal = json.loads((out / 'calendar.json').read_text(encoding='utf-8'))
    ud = json.loads((out / 'universe.json').read_text(encoding='utf-8'))
    dates = [d for d in cal['open_dates'] if first <= d <= last]
    assert all(d in ud['st_by_date'] for d in dates)
    relevant = {p['symbol'] for p in plans}
    state = dict(status='account_replay', signal_stocks=len(relevant), plans=len(plans))
    dump(out / 'status.json', state)
    print(json.dumps(state), flush=True)
    replay_started = time.monotonic()
    def progress(state):
        if state['session'] % 100 == 0:
            state = dict(state, status='account_replay', calendar_sessions=len(cal['open_dates']),
                         elapsed_seconds=round(time.monotonic()-replay_started))
            dump(out / 'status.json', state)
            print(json.dumps(state), flush=True)
    replay_bars = sorted((b for symbol in sorted(relevant) for b in grouped[symbol]),key=lambda b:(b.date,b.symbol))
    engine = Backtest(copy.deepcopy(config), build_strategies(config['strategies'])).run(
        replay_bars, cal['open_dates'], set(cal['week_ends']), evaluation_start=first, evaluation_end=last,
        universe=MainboardUniverse(ud['stocks'], ud['st_by_date']), progress=progress)
    actual = {e['setup_id']: (e['date'], e['trigger'], e['stop'], e['target'])
              for e in engine.events if e['event'] == 'entry_intent'}
    assert actual == {p['setup_id']: (p['date'], p['trigger'], p['stop'], p['target']) for p in plans}
    for name, records in (('decisions', engine.events), ('warmup_decisions', engine.warmup_events),
            ('orders', engine.orders), ('trades', engine.trades), ('entry_audit', engine.entry_audits), ('equity', engine.curve)):
        save_csv(out / (name + '.csv'), records)
    summary = engine.summary()
    summary.update(signal_counts=dict(totals), signal_stocks=len(relevant),
        rejection_counts=dict(Counter(e.get('reason') for e in engine.events if e['event'] in ('plan_rejected', 'entry_rejected'))),
        risk_reasons=dict(Counter(a.get('risk_reason', a.get('execution_reason')) for a in engine.entry_audits)))
    dump(out / 'summary.json', summary)
    dump(out / 'account-verification.json', dict(all_population_scanned=len(results)==3214,
        signal_id_date_price_match=True, unique_plans=len(plans), signal_stocks=len(relevant)))
    digest = hashlib.sha256()
    for p in sorted((out / 'source/src').rglob('*.py')):
        digest.update(str(p.relative_to(out / 'source/src')).encode()); digest.update(p.read_bytes())
    manifest = dict(plan, stocks=len(grouped), bar_count=sum(map(len, grouped.values())),
        sessions=len(engine.curve), first_session=dates[0], last_session=dates[-1], code_sha256=digest.hexdigest())
    dump(out / 'manifest.json', manifest)
    rendered = html.escape(json.dumps(dict(manifest=manifest, summary=summary), ensure_ascii=False, indent=2))
    (out / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>头肩底回测</title>'
        '<style>body{max-width:1000px;margin:40px auto;font-family:system-ui}pre{white-space:pre-wrap}</style>'
        '<h1>头肩底全主板回测</h1><pre>' + rendered + '</pre>', encoding='utf-8')
    dump(out / 'status.json', dict(status='complete', stocks=len(results), plans=len(plans)))
    print(json.dumps(dict(status='complete', output=str(out), summary=summary)), flush=True)


if __name__ == '__main__':
    main()
