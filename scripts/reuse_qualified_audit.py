"""Reuse deterministic charts only after all their inputs match the reviewed rerun."""
import shutil
from pathlib import Path
from backtest_candidate_policy import load,rows,sha,dump
ROOT=Path(__file__).resolve().parents[1]
A=ROOT/'runs/20261109-qualified-candidates';B=ROOT/'runs/20261109-qualified-candidates-verified'
assert load(B/'status.json')['status']=='complete'
assert load(A/'protocol.json')['bars_sha256']==load(B/'protocol.json')['bars_sha256']
for policy in load(B/'protocol.json')['configs']:
 assert load(A/(policy+'-plans.json'))==load(B/(policy+'-plans.json'))
 name=policy+'_combined_cost1'
 fills=lambda p:[a for a in rows(p/'entry_audit.csv') if int(a.get('filled_quantity') or 0)>0]
 assert fills(A/name)==fills(B/name),name
 assert rows(A/name/'trades.csv')==rows(B/name/'trades.csv'),name
 active=lambda p:[e for e in rows(p/'decisions.csv') if e['event'] in ('main_protection_raised','stop_raised','dynamic_support_daily_break')]
 assert active(A/name)==active(B/name),name
shutil.copytree(A/'chart-audit',B/'chart-audit')
dump(B/'chart-reuse-verification.json',dict(all_11_standard_combined_fills_trades_and_protection_events_exact=True,
 all_plan_evidence_exact=True,data_hash_exact=True,audit_source_sha256=sha(ROOT/'scripts/audit_candidate_policy.py'),
 rationale='Engine edge-case correction did not change these audit inputs; all 42 accounts rerun and failure-state audit performed separately.'))
print('ALL CHART INPUTS EXACT; reused',load(B/'chart-audit/verification.json'))
