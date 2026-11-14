"""Independent failure-source and observation-clock checks across all accounts."""
import csv,json
from pathlib import Path
from collections import defaultdict,Counter
from backtest_candidate_policy import load,dump,rows
from trading_system.ihs_geometry import neckline_at
R=Path(__file__).resolve().parents[1]/'runs/20261109-qualified-candidates-verified'
assert load(R/'status.json')['status']=='complete'
cases={};needed=set()
for folder in sorted(R.glob('*_cost*')):
 if not folder.is_dir():continue
 audits=rows(folder/'entry_audit.csv');events=rows(folder/'decisions.csv');label=load(folder/'summary.json')['policy']
 plans={p['setup_id']:p for p in load(R/(label+'-plans.json'))}
 failures=[e for e in events if e['event']=='bottom_failure_recorded']
 cases[folder.name]=(folder,audits,events,plans,failures)
 for e in failures:
  p=plans[e['failure_setup_id']];needed.update([(p['symbol'],p['date']),(p['symbol'],e['failure_date'])])
bars={}
with (R/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
 for b in csv.DictReader(f):
  key=b['symbol'],b['date']
  if key in needed:bars[key]={k:float(b[k]) for k in ('open','low','factor')}
checks={};lineage=[]
for name,(folder,audits,events,plans,failures) in cases.items():
 byid=defaultdict(list)
 for i,a in enumerate(audits):byid[a['setup_id']].append((i,a))
 for e in failures:
  p=plans[e['failure_setup_id']];group=p['symbol']+':'+p['ihs_head_date']
  assert e['bottom_group']==group
  if e['failure_reason']=='initial_protection_breached':
   filled=[a for i,a in byid[p['setup_id']] if int(a.get('filled_quantity') or 0)>0]
   assert filled and filled[0]['date']<=e['failure_date'] and e['failure_phase']=='close'
   b=bars[p['symbol'],e['failure_date']];sf=bars[p['symbol'],p['date']]['factor']
   assert b['low']*b['factor']<=p['stop']*sf+1e-8
  else:
   origin=[(i,a) for i,a in byid[p['setup_id']] if a['date']==e['failure_date'] and e['failure_reason'] in (a.get('risk_reason'),a.get('execution_reason'))]
   assert origin,(name,e)
   i,a=origin[0]
   assert not any(x['symbol']==p['symbol'] and x['date']==a['date'] and int(x.get('filled_quantity') or 0)>0 for x in audits[:i])
   if e['failure_reason'] in ('ihs_breakout_lost_at_entry','support_invalidated_at_open'):
    b=bars[p['symbol'],e['failure_date']];sf=bars[p['symbol'],p['date']]['factor'];scale=sf/b['factor']
    if e['failure_reason']=='ihs_breakout_lost_at_entry':assert b['open']<=neckline_at(p,e['failure_date'])*scale+1e-8
    else:assert b['open']<=p['stop']*scale+1e-8
  assert e['failure_reason'] not in ('max_positions','insufficient_budget_or_cash','symbol_already_owned','expired_suspended')
 blocked=[a for a in audits if a.get('risk_reason') in ('ihs_bottom_invalidated','ihs_bottom_cohort_veto')]
 for a in blocked:
  p=plans[a['setup_id']];origin=plans[a['failure_setup_id']]
  assert p['symbol']==origin['symbol'] and p['ihs_head_date']==origin['ihs_head_date']
  assert any(e['failure_setup_id']==a['failure_setup_id'] and e['failure_date']==a['failure_date'] and e['failure_reason']==a['failure_reason'] for e in failures)
  assert a['date']>=a['failure_date']
  if a['date']==a['failure_date'] and a['date']!=a['signal_date']:assert a['failure_phase']=='execution'
  if a['risk_reason']=='ihs_bottom_cohort_veto':assert p['date']==origin['date']
  lineage.append(dict(case=name,symbol=p['symbol'],signal=p['date'],blocked_setup_id=p['setup_id'],
   source_setup_id=origin['setup_id'],source_signal=origin['date'],source_date=a['failure_date'],
   source_reason=a['failure_reason'],scope=a['failure_scope']))
 # Verify that no filled intent follows an applicable earlier failure event.
 for a in audits:
  if not int(a.get('filled_quantity') or 0) or a['setup_id'] not in plans:continue
  p=plans[a['setup_id']];group=p['symbol']+':'+p['ihs_head_date']
  fill_index=next(i for i,e in enumerate(events) if e['event']=='filled' and e.get('setup_id')==p['setup_id'] and e['date']==a['date'])
  for e in events[:fill_index]:
   if e['event']!='bottom_failure_recorded' or e['bottom_group']!=group:continue
   if e['failure_scope']=='head':
    assert not (e['failure_date']<a['date'] or (e['failure_date']==a['date'] and e['failure_phase']=='execution'))
   else:assert plans[e['failure_setup_id']]['date']!=p['date']
 checks[name]=dict(failure_sources=len(failures),propagated_rejections=len(blocked),
  source_reasons=dict(Counter(e['failure_reason'] for e in failures)),all_checks_passed=True)
dump(R/'failure-lineage.json',lineage);dump(R/'failure-verification.json',checks)
print('VERIFIED',len(checks),'accounts',sum(v['failure_sources'] for v in checks.values()),'sources',len(lineage),'propagated rejections')
