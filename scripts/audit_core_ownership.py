"""Deduplicated admission funnel and causal ownership assertions for a replay."""
import ast,csv,json,sys
from collections import Counter
from pathlib import Path


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def audit(path):
    path=Path(path);events=rows(path/'decisions.csv')
    intents={e['setup_id']:e for e in events if e['event']=='entry_intent'}
    approved={e['setup_id'] for e in events if e['event']=='plan_approved'}
    rejects={}
    for e in events:
        if e['event']=='plan_rejected' and e['setup_id'] not in approved:
            rejects.setdefault(e['setup_id'],e['reason'])
    mode=json.loads((path/'config.json').read_text(encoding='utf-8'))['strategies'][0]['params'].get('core_mode')
    owned=mode in ('owned','nested')
    pressure_reasons=Counter()
    for e in intents.values():
        if not owned:continue
        owner=':'.join(e[k] for k in ('core_a','core_b','core_c'))
        assert e['entry_core_owner']==e['small_owner']==owner,e
        assert e['small_a'][:8]>=e['core_c'][:8],e
        assert e['core_c_confirmed']<=e['date'] and e['small_confirmed'][:8]<=e['date'],e
        if mode=='nested':
            assert e['rhythm_floor_date']<=e['small_c'][:8] and e['rhythm_start_date']<=e['small_a'][:8],e
            assert e['core_accepted_at']<=e['date'] and e['upper_owner_id'],e
        else:assert not e['direction_second'] or e['core_a']>=e['direction_second'],e
        for p in ast.literal_eval(e['pressure_audit'] or '[]'):
            pressure_reasons[p['reason']]+=1
    counts=Counter(e['reason'] for e in events if e['event']=='core_structure_wait')
    result=dict(version=json.loads((path/'manifest.json').read_text(encoding='utf-8'))['rule_version'],
        independent_intents=len(intents),independent_approved=len(approved),
        first_rejection_reasons=dict(Counter(rejects.values())),
        core_wait_observations=dict(counts),pressure_decisions_in_unique_plans=dict(pressure_reasons),
        ownership_assertions_passed=owned,
        owner_changes=sum(e['event']=='core_owner_changed' for e in events),
        invalidated_on_owner_change=sum(e['event']=='entry_plan_invalidated' and e['reason']=='core_owner_changed' for e in events),
        focused_stocks={symbol:[{k:e.get(k) for k in ('date','core_a','core_b','core_c','small_c','trigger','stop','target','symmetry_target','pressure_target')}
                         for e in intents.values() if e['symbol']==symbol]
                        for symbol in ('000019.SZ','603500.SH','002812.SZ')})
    (path/'core-ownership-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    for path in sys.argv[1:]:audit(path)
