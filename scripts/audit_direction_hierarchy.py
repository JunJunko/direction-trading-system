"""Verify and compare a frozen v5.2 structural replay, without refitting rules."""
import csv
import json
import sys
from pathlib import Path
from collections import Counter


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def main(current, previous):
    current,previous=Path(current),Path(previous)
    summary=json.loads((current/'summary.json').read_text(encoding='utf-8'))
    old=json.loads((previous/'summary.json').read_text(encoding='utf-8'))
    config=json.loads((current/'config.json').read_text(encoding='utf-8'))
    old_config=json.loads((previous/'config.json').read_text(encoding='utf-8'))
    events=read(current/'decisions.csv')
    audits=read(current/'entry_audit.csv')
    intents=[r for r in events if r['event']=='entry_intent']
    checks={
        'signal_direction_causal':all(r['direction_confirmed']<=r['date'] for r in intents),
        'small_c_causal':all(r['small_c'][:8]<=r['date'] for r in intents),
        'valid_brackets':all(float(r['stop'])<float(r['trigger'])<float(r['target']) for r in intents),
        'unique_initial_plans':len(intents)==len({r['setup_id'] for r in intents}),
        'evaluation_sessions':len(read(current/'equity.csv'))==241,
        'filled_net_rr_above_three':all(float(r['net_rr'])>3 for r in audits if float(r.get('filled_quantity') or 0)>0),
        'same_risk_limits':config['risk']==old_config['risk'],
        'same_execution_costs':config['execution']==old_config['execution'],
    }
    # The replay links the exact same immutable price file; metadata copied too.
    import os
    checks['same_price_file']=os.path.samefile(current/'bars.csv',previous/'bars.csv')
    checks['same_calendar']=(current/'calendar.json').read_bytes()==(previous/'calendar.json').read_bytes()
    checks['same_universe']=(current/'universe.json').read_bytes()==(previous/'universe.json').read_bytes()
    result=dict(checks=checks,plan_rejections=dict(Counter(r.get('reason') for r in events if r['event']=='plan_rejected')),
        retest_kinds=dict(Counter(r.get('retest_kind') for r in events if r['event']=='upper_direction_confirmed')),
        pressure_capped_plans=sum(bool(r.get('pressure_target')) and float(r['pressure_target'])<float(r['symmetry_target']) for r in intents))
    (current/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    version=config['strategies'][0]['id'];old_version=old_config['strategies'][0]['id']
    lines=[f'# {version} 同一快照结构实验','',
           '不含历史人工阶段策略；daily_nested 不等于真实小时周期。事件次数不是独立形态数量。','',
           f'| 指标 | {old_version} | {version} |','|---|---:|---:|']
    for key,label in [('filled_buys','买入成交'),('closed_trades','平仓笔数'),('open_positions','期末持仓')]:
        lines.append(f'| {label} | {old[key]} | {summary[key]} |')
    for key,label in [('total_return','账户收益'),('max_drawdown','最大回撤')]:
        lines.append(f'| {label} | {old[key]:.2%} | {summary[key]:.2%} |')
    for key,label in [('weekly_reversal_candidate','双底突破候选事件'),('upper_direction_confirmed','方向确认事件'),('entry_intent','初始入场计划')]:
        lines.append(f'| {label} | {old["event_counts"].get(key,0)} | {summary["event_counts"].get(key,0)} |')
    lines+=['','```json',json.dumps(result,ensure_ascii=False,indent=2),'```','',
            '这是多个相关逻辑修复的联合实验，不能将收益差归因于某个单独规则。规则已使用该样本检查，仍需独立样本验证。']
    (current/'comparison.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(summary=summary,verification=result),ensure_ascii=False))
    if not all(checks.values()):
        raise SystemExit('Verification failed')


if __name__=='__main__':main(sys.argv[1],sys.argv[2])
