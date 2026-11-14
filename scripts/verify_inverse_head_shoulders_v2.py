"""Fixed regression cases from the prior diagram audit, not a market backtest."""
import csv
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.strategies import build_strategies


def main():
    snapshot = ROOT/'runs/20261024-mainboard-inverse-head-shoulders-v1-cached'
    audit = ROOT/'audits/20261025-inverse-head-shoulders-diagram'
    out = ROOT/'audits/20261025-inverse-head-shoulders-v2-verification'
    out.mkdir(exist_ok=True)
    load = lambda path: json.loads(path.read_text(encoding='utf-8'))
    examples = load(audit/'real-examples.json')
    plans = {p['setup_id']:p for p in load(snapshot/'plans.json')}
    symbols = {e['symbol'] for e in examples}
    histories = defaultdict(list)
    with (snapshot/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:
                histories[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                    ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    configs = [load(ROOT/'configs/experiments'/name) for name in
               ('inverse_head_shoulders_v1_structure.json','inverse_head_shoulders_v2_enclosing_structure.json')]
    results = []
    dates = ('ihs_left_date','ihs_head_date','ihs_right_date')
    for example in examples:
        plan = plans[example['setup_id']]
        bars = sorted([b for b in histories[plan['symbol']] if b.date<=plan['date']],key=lambda b:b.date)
        keys = []
        emitted = []
        for config in configs:
            s = build_strategies(config['strategies'])[0]
            final = []
            for end in range(1,len(bars)+1):
                final, _ = s.on_close(bars[:end],set())
            keys.append({tuple(i.evidence[k] for k in dates) for i in final})
            emitted.append([i.evidence for i in final])
        original = tuple(plan[k] for k in dates)
        assert original in keys[0], example
        assert original not in keys[1], example
        results.append(dict(symbol=plan['symbol'],signal_date=plan['date'],category=example['category'],
                            original_layout=original,v1_reproduced=True,v2_rejects_original_layout=True,
                            v2_signals_on_same_date=emitted[1]))
    code=ROOT/'src/trading_system/strategies/enclosing_inverse_head_shoulders.py'
    result=dict(scope='three predetermined geometric regression cases; not full-market performance',
                status='passed',results=results,strategy_sha256=hashlib.sha256(code.read_bytes()).hexdigest(),
                defaults=configs[1]['strategies'][0]['params'])
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(__file__,out/Path(__file__).name)
    shutil.copy2(code,out/code.name)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
