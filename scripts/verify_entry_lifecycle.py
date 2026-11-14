import json,csv,sys,hashlib
from pathlib import Path

def read(path):
 with path.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))

def digest(root):
 h=hashlib.sha256()
 for p in sorted(root.rglob('*.py')):
  h.update(str(p.relative_to(root)).encode());h.update(p.read_bytes())
 return h.hexdigest()

p=Path(sys.argv[1]);lineage=json.loads((p/'trade-lineage-audit.json').read_text());verification=json.loads((p/'verification.json').read_text());events=read(p/'decisions.csv');plans=[e for e in events if e['event']=='entry_intent'];trades=read(p/'trades.csv')
invalid={e['setup_id'] for e in events if e.get('reason')=='warmup_plan_not_executable'}
checks=verification['checks'];checks.update(
 no_warmup_plan_fills=lineage['warmup_plan_count']==0,
 no_prior_trigger_fills=lineage['earlier_trigger_count']==0,
 cancelled_warmup_id_never_filled=not invalid & {t['setup_id'] for t in trades},
 core_confirmation_causal=all(e['core_c_confirmed']<=e['date'] for e in plans),
 complete_direction_lineage=all(all(e.get(k) for k in ('direction_first','direction_second','direction_breakout','direction_retest_started')) for e in plans),
 direction_lineage_ordered=all(e['direction_first']<e['direction_second']<e['direction_breakout']<=e['direction_retest_started']<=e['direction_confirmed']<=e['date'] for e in plans),
 same_automatic_account_policy=json.loads((p/'config.json').read_text())['automatic_account_policy']==json.loads((Path(sys.argv[2])/'config.json').read_text())['automatic_account_policy'],
 source_matches_replay=digest(p/'source/src')==digest(Path(__file__).resolve().parents[1]/'src'),
 unique_filled_setup=len(trades)==len({t['setup_id'] for t in trades}))
verification.update(warmup_plans_cancelled=len(invalid),initial_plans=len(plans));(p/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(verification,ensure_ascii=False))
if not all(checks.values()):raise SystemExit('Verification failed')
