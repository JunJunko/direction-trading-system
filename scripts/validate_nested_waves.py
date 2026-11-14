"""Historical structural replay, separate from portfolio profitability."""
import csv,json,sys,html
from collections import Counter
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import AdjustedCache
from trading_system.wave_hierarchy import WaveHierarchy
from trading_system.structure import n_structure


def main(pack,previous,output):
    pack=Path(pack);previous=Path(previous);out=Path(output)
    if out.exists():raise ValueError('Output must be new')
    out.mkdir(parents=True)
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    manifest=read(pack/'manifest.json');cases=read(previous/'case-findings.json')
    histories={c['symbol']:[] for c in cases}
    with (Path(manifest['snapshot'])/'bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in histories:
                histories[r['symbol']].append(Bar(r['symbol'],r['date'],
                    *[float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')]))
    records=[];checks=0;counts=Counter()
    for case in cases:
        raw=histories[case['symbol']];at=max(i for i,b in enumerate(raw) if b.date<=case['as_of'])
        model=WaveHierarchy();cache=AdjustedCache();frames=[];all_events=[]
        for end in range(1,min(len(raw),at+21)+1):
            bars=cache.get(raw[:end]);core,reason,events=model.get(bars);all_events.extend(events)
            if end-1 in (max(0,at-20),at,min(len(raw)-1,at+20)):
                batch=WaveHierarchy();other,other_reason,_=batch.get(bars)
                assert core==other and reason==other_reason and model.ledger==batch.ledger
                checks+=1
            if end-1>=max(0,at-20):
                legacy=n_structure(bars)[0];latest=n_structure(bars,ownership=True)[0]
                frames.append(dict(date=bars[-1].date,core=core,reason=reason,
                    active_owner=model.core['owner_id'] if model.core else None,
                    retired=list(sorted(model.retired)),ledger=json.loads(json.dumps(model.ledger)),
                    legacy_owner=':'.join(bars[legacy[k]].date for k in ('a','b','c')) if legacy else None,
                    latest_owner=':'.join(bars[latest[k]].date for k in ('a','b','c')) if latest else None))
                if core:
                    assert core['owner_id'] not in model.retired
                    assert bars[core['confirmed']].date<=bars[-1].date
                for record in model.ledger.values():
                    if record.get('parent_owner'):assert record['parent_owner'] in model.ledger
        focus=next(f for f in frames if f['date']==case['as_of'])
        for event in all_events:counts[event['event']]+=1
        records.append(dict(id=case['id'],symbol=case['symbol'],as_of=case['as_of'],focus=focus,
                            frames=frames,events=all_events))
        print(case['id'],focus['reason'],focus['active_owner'],flush=True)
    summary=dict(cases=len(records),prefix_checks=checks,causal_consistency_passed=True,
        parent_integrity_passed=True,retired_core_not_reused=True,
        events=dict(counts),scope='Core layer replay without weekly trading gate; repeated stocks/times, not profitability or independent accuracy',
        semantic_accuracy_established=False)
    (out/'cases.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    parts=['<!doctype html><meta charset="utf-8"><title>v5.11 波段迭代验证</title><style>body{font:16px system-ui;max-width:1400px;margin:30px auto}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap}</style><h1>v5.11 波段归属迭代验证</h1><p>本表单独验证日线核心状态机，未应用周线方向准入，不能当交易信号表。规则一致性不等于图形准确率。</p>',
        '<table><tr><th>案例</th><th>股票／时点</th><th>旧算法核心</th><th>v5.10最新核心</th><th>v5.11当前核心</th><th>状态</th></tr>']
    for case in records:
        f=case['focus'];parts.append('<tr>'+''.join('<td>'+html.escape(str(x or '无'))+'</td>' for x in
            (case['id'],case['symbol']+' / '+case['as_of'],f['legacy_owner'],f['latest_owner'],f['active_owner'],f['reason']))+'</tr>')
    parts.append('</table><h2>一致性检查</h2><pre>'+html.escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre>')
    for case in records:
        if not case['id'].startswith('F'):continue
        parts.append('<h2>'+case['id']+' '+case['symbol']+'</h2><pre>'+html.escape(json.dumps(case['focus']['ledger'],ensure_ascii=False,indent=2))+'</pre>')
    (out/'report.html').write_text('\n'.join(parts),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True))


if __name__=='__main__':main(*sys.argv[1:])
