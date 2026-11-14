"""Replay a frozen universe without redownloading or copying its large price file."""
import sys,json,os,shutil,hashlib,html
from pathlib import Path
from datetime import datetime
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.data import load_csv,save_csv
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse

def main(snapshot,config_path):
    root=Path(__file__).resolve().parents[1];snapshot=Path(snapshot)
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    cal=json.loads((snapshot/'calendar.json').read_text(encoding='utf-8'))
    ud=json.loads((snapshot/'universe.json').read_text(encoding='utf-8'))
    version=config['strategies'][0]['id']
    out=root/'runs'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-mainboard-'+version+'-structure')
    out.mkdir()
    print(json.dumps(dict(output=str(out),scope=config.get('research_scope'))),flush=True)
    shutil.copytree(root/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(root/'run.py',out/'source/run.py')
    shutil.copy2(__file__,out/'source/replay_mainboard.py')
    for name in ('calendar.json','universe.json','stocks.csv','coverage.csv'):
        shutil.copy2(snapshot/name,out/name)
    (out/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    os.link(snapshot/'bars.csv',out/'bars.csv')
    print('Loading immutable snapshot',flush=True)
    bars=load_csv(snapshot/'bars.csv')
    engine=Backtest(config,build_strategies(config['strategies']))
    print('Replay started',flush=True)
    engine.run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251008',evaluation_end='20261007',
        universe=MainboardUniverse(ud['stocks'],ud['st_by_date']),
        progress=lambda p:print(json.dumps(p),flush=True))
    for name,rows in [('decisions',engine.events),('warmup_decisions',engine.warmup_events),('orders',engine.orders),
                      ('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits)]:
        save_csv(out/(name+'.csv'),rows)
    summary=engine.summary();summary['event_counts']=dict(Counter(e['event'] for e in engine.events))
    summary['rejection_counts']=dict(Counter(o.get('reason') for o in engine.orders if o['status']=='rejected'))
    manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    # Results inherited from an earlier snapshot are not this run's assessment.
    manifest.pop('assessment',None)
    digest=hashlib.sha256()
    for p in sorted((out/'source/src').rglob('*.py')):
        digest.update(str(p.relative_to(out/'source/src')).encode());digest.update(p.read_bytes())
    manifest.update(source_snapshot=str(snapshot.resolve()),rule_version=version,research_scope=config.get('research_scope'),
        code_sha256=digest.hexdigest(),config_sha256=hashlib.sha256((out/'config.json').read_bytes()).hexdigest())
    manifest['limitations']=['structure-only experiment; no historical human phase policy',
        'daily_nested uses daily substructure, not reconstructed hourly bars',
        'same previously studied snapshot, not independent validation',
        ('enclosing W level remains unresolved; nested daily wave scale rules need independent validation'
         if config['strategies'][0].get('params',{}).get('core_mode')=='nested'
         else 'enclosing W level remains unresolved; latest confirmed daily correction ownership is a research convention'
         if config['strategies'][0].get('params',{}).get('core_mode')=='owned'
         else 'enclosing W level and active N replacement remain unresolved'),
        'daily OHLC conservative fills','synthetic total-return factor share adjustment']
    for name,value in [('summary',summary),('manifest',manifest),('status',dict(status='complete'))]:
        (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'report.html').write_text('<!doctype html><meta charset="utf-8"><h1>v5 结构修复实验：不含人工阶段策略</h1><pre>'+html.escape(json.dumps(dict(manifest=manifest,summary=summary),ensure_ascii=False,indent=2))+'</pre>',encoding='utf-8')
    print(json.dumps(dict(output=str(out),summary=summary)),flush=True)

if __name__=='__main__':main(sys.argv[1],sys.argv[2])
