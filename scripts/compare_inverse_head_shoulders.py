"""Compare two frozen runs and independently audit the flat IHS signal account."""
import csv
import json
import math
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Intent
from trading_system.risk import RiskManager
from trading_system.universe import MainboardUniverse


def main(baseline, candidate):
    baseline, out = Path(baseline), Path(candidate)
    load = lambda p: json.loads(p.read_text(encoding='utf-8'))
    old, new = load(baseline/'summary.json'), load(out/'summary.json')
    old_manifest, manifest = load(baseline/'manifest.json'), load(out/'manifest.json')
    config, before_config = load(out/'config.json'), load(baseline/'config.json')
    assert manifest['bars_sha256'] == old_manifest['bars_sha256']
    assert manifest['universe_sha256'] == old_manifest['universe_sha256']
    for key in ('evaluation_start','evaluation_end','sessions'):
        assert manifest[key] == old_manifest[key]
    assert {k:v for k,v in config.items() if k!='strategies'} == {k:v for k,v in before_config.items() if k!='strategies'}
    plans, previous = load(out/'plans.json'), load(baseline/'plans.json')
    key = lambda p: (p['symbol'], p['ihs_left_date'], p['ihs_head_date'], p['ihs_right_date'])
    old_map, new_map = {key(p):p for p in previous}, {key(p):p for p in plans}
    assert len(new_map) == len(plans)
    shared = old_map.keys() & new_map.keys()
    params = config['strategies'][0]['params']
    removed_quality = None
    regression_checks = []
    old_metrics_path = ROOT/'audits/20261025-inverse-head-shoulders-diagram/candidate-metrics.csv'
    if old_manifest['rule_version'] == 'inverse_head_shoulders_v1' and old_metrics_path.exists():
        with old_metrics_path.open(encoding='utf-8-sig',newline='') as f:
            old_metrics = {row['setup_id']:row for row in csv.DictReader(f)}
        violations, any_violation = Counter(), 0
        for layout in old_map.keys()-new_map.keys():
            row = old_metrics[old_map[layout]['setup_id']]
            failed = [name for name, condition in (
                ('head_prominence',float(row['head_prominence']) + 1e-12 < params['min_head_height']),
                ('shoulder_gap',float(row['shoulder_imbalance']) > params['max_shoulder_height'] + 1e-12),
                ('neckline_gap',float(row['neck_imbalance']) > params['max_neckline_height'] + 1e-12)) if condition]
            violations.update(failed); any_violation += bool(failed)
        removed_quality = dict(any_quality_violation=any_violation,overlapping_violation_counts=dict(violations),
            pass_quality_but_absent=len(old_map.keys()-new_map.keys())-any_violation,
            note='Diagnostic properties of absent v1 layouts, not causal rejection attribution or false-positive rates.')
        old_by_id = {p['setup_id']:p for p in previous}
        cases = load(old_metrics_path.parent/'real-examples.json')
        for example in cases:
            original_key = key(old_by_id[example['setup_id']])
            assert original_key not in new_map, example
            regression_checks.append(dict(symbol=example['symbol'],category=example['category'],
                                          absent_in_full_v2_scan=True))
    for p in plans:
        for k in ('ihs_head_prominence','ihs_shoulder_gap','ihs_neckline_gap'):
            assert math.isfinite(p[k])
        assert p['ihs_head_prominence'] + 1e-12 >= params['min_head_height']
        assert p['ihs_shoulder_gap'] <= params['max_shoulder_height'] + 1e-12
        assert p['ihs_neckline_gap'] <= params['max_neckline_height'] + 1e-12
    ud = load(out/'universe.json')
    universe = MainboardUniverse(ud['stocks'],ud['st_by_date'])
    risk, reasons, rr = RiskManager(config['risk']), Counter(), []
    for p in plans:
        if not universe.eligible(p['symbol'],p['date']):
            reasons['universe_ineligible_signal'] += 1
            continue
        intent = Intent(config['strategies'][0]['id'],p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],p['setup_id'],'inverse_head_shoulders',p)
        e = config['execution']
        assessment = risk.assess(intent,intent.trigger*(1+e['slippage']),config['initial_cash'],config['initial_cash'],{}, {},
            e['commission_rate'],e['sell_tax_after_20230828'],1,e['slippage'])
        assert assessment['quantity'] == 0, 'This flat-account verifier requires every signal to be rejected'
        reasons[assessment['risk_reason']] += 1
        if 'net_rr' in assessment:rr.append(assessment['net_rr'])
    assert dict(reasons) == new['rejection_counts']
    assert sum(reasons.values()) == len(plans)
    assert new['filled_buys'] == new['closed_trades'] == new['open_positions'] == 0
    with (out/'equity.csv').open(encoding='utf-8-sig',newline='') as f:
        equity = list(csv.DictReader(f))
    assert len(equity) == manifest['sessions'] == 241
    assert all(float(row['equity']) == config['initial_cash'] for row in equity)
    verification = load(out/'account-verification.json')
    assert verification['all_population_scanned'] and verification['signal_id_date_price_match']
    independent = dict(status='passed',method='independent signal risk assessment; every signal rejects, proving a flat account by induction',
        signals=len(plans),reasons=dict(reasons),highest_net_rr=max(rr) if rr else None,
        lowest_net_rr=min(rr) if rr else None,flat_equity_sessions=len(equity))
    (out/'independent-risk-verification.json').write_text(json.dumps(independent,ensure_ascii=False,indent=2),encoding='utf-8')
    comparison = dict(baseline_path=str(baseline.resolve()),candidate_path=str(out.resolve()),
        same_data_universe_window_and_account_rules=True,
        baseline=dict(rule_version=old_manifest['rule_version'],signals=len(previous),**old),
        candidate=dict(rule_version=manifest['rule_version'],signals=len(plans),**new),
        layout_overlap=dict(shared=len(shared),v1_only=len(old_map.keys()-new_map.keys()),
            v2_only=len(new_map.keys()-old_map.keys()),shared_signal_date_changes=sum(old_map[k]['date']!=new_map[k]['date'] for k in shared)),
        v1_only_quality_diagnostics=removed_quality,
        prior_problem_layout_checks=regression_checks,
        quality=dict(min_head_prominence=min((p['ihs_head_prominence'] for p in plans),default=None),
            max_shoulder_gap=max((p['ihs_shoulder_gap'] for p in plans),default=None),
            max_neckline_gap=max((p['ihs_neckline_gap'] for p in plans),default=None)),
        independent_risk=independent,
        interpretation='Layout differences measure changed detection, not validated false-positive or true-positive rates. No parameter selection from returns.')
    (out/'comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest.update(completed_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),independent_risk_verification=True,
                    baseline_same_snapshot_verified=True)
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    shutil.copy2(__file__,out/'source'/Path(__file__).name)
    print(json.dumps(comparison,ensure_ascii=False,indent=2))


if __name__=='__main__':main(sys.argv[1],sys.argv[2])
