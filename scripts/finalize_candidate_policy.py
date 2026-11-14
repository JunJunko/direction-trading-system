"""Verify review coverage, freeze audit tools and fingerprint the completed experiment."""
import ast,csv,hashlib,json,shutil
from pathlib import Path
R=Path(__file__).resolve().parents[1];O=R/'runs/20261109-candidate-policy-full'
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
protocol=load(O/'protocol.json')
assert load(O/'status.json')==dict(status='complete',stocks=3214,cases=20)
assert all(sha(R/p)==v for p,v in protocol['source_hashes'].items())
visual=load(O/'chart-audit/visual-review.json')['observations']
assert set(visual)=={p.stem for p in (O/'chart-audit/structures').glob('*.png')}
assert len(visual)==45
for path,count in [('warmup-verification',6),('shared-cache-verification',6),('signal-days-verification',6),('ordinary-verification',24),('ordinary-tail-verification',12)]:
 checks=load(O/path/'verification.json');assert len(checks)==count
assert load(O/'chart-audit/verification.json')==dict(distinct_charts=45,trade_records=175,entry_checks=175,exit_checks=160,support_timing_and_level_checks=221)
for name in ['backtest_candidate_policy.py','verify_candidate_scan.py','audit_candidate_policy.py','report_candidate_policy.py','supplement_candidate_review.py','finalize_candidate_policy.py']:
 p=R/'scripts'/name;ast.parse(p.read_text(encoding='utf-8'));shutil.copy2(p,O/'source'/('final-'+name))
shutil.copy2(R/'run.py',O/'source/run.py')
verification=load(O/'verification.json');verification['all_population_processed']=verification.pop('all_population_scanned',verification.get('all_population_processed',False))
verification.update(dense_daily_scan_stocks=1795,remaining_stocks_reuse_full_causal_baseline_signal_calendar=1419,
 independent_ordinary_strategy_checks=36,entry_price_checks=175,exit_price_checks=160,protection_level_checks=221,distinct_structure_images_reviewed=45)
(O/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
artifacts=[p for p in O.glob('*.json') if p.name!='manifest.json']+list(O.glob('*.csv'))+list(O.glob('*.html'))+list(O.glob('*.png'))
artifacts+=list((O/'chart-audit').glob('*.json'))+list((O/'chart-audit').glob('*.csv'))+list((O/'chart-audit').glob('*.html'))
for folder in O.glob('*_cost*'):
 artifacts.extend(p for p in folder.iterdir() if p.suffix in ('.csv','.json'))
manifest=dict(data_sha256=protocol['bars_sha256'],strategy_source_hashes=protocol['source_hashes'],
 test_log_sha256=sha(O/'tests.log'),artifact_hashes={str(p.relative_to(O)):sha(p) for p in artifacts},
 scope='3214-stock frozen population, 20 full account comparisons; visual audit of five standard-cost combined arms',
 acceleration='execution-notes.json',review_method='Nonblind AI-assisted visual review; geometric diagnostics are not labeled error rates',
 holdout='No untouched holdout in this experiment')
(O/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('FINAL VERIFIED',len(artifacts),'artifacts, 45 structure reviews, 175 entries, 160 exits, 221 protection updates')
