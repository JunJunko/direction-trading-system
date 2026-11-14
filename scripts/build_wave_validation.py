"""Offline case-by-case wave audit using the frozen review and focus cases."""
import csv,hashlib,json,shutil,sys,base64,gzip
from collections import Counter
from pathlib import Path
from wave_model_audit import snapshot,node_rows
from trading_system.domain import Bar
from trading_system.analysis import AdjustedCache
from trading_system.structure import SwingCache,swings


def main(pack,output,labels_path):
    pack=Path(pack);output=Path(output)
    if output.exists():raise ValueError('Do not overwrite a validation pack')
    output.mkdir(parents=True)
    read=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    manifest=read(pack/'manifest.json');calendar=read(pack/'calendar.json')
    cases=[c for c in read(pack/'cases-private.json') if not c['repeat_of']]
    reference=read(Path(labels_path))
    assert reference['pack_id']==manifest['pack_id']
    labels={row['id']:row for row in reference['labels']}
    for identifier,symbol,day,note in (
        ('F01','000019.SZ','20260109','旧春季核心与极近压力目标'),
        ('F02','603500.SH','20251231','数月后的节奏仍归旧核心'),
        ('F03','002812.SZ','20260320','止损较宽与目标空间不足'),
        ('F04','600089.SH','20251107','盈利展开时结构'),
        ('F05','600089.SH','20251124','利润回落、退出前结构')):
        cases.append(dict(id=identifier,symbol=symbol,as_of=day,note=note))
    symbols={c['symbol'] for c in cases};histories={s:[] for s in symbols}
    source=Path(manifest['snapshot'])/'bars.csv'
    with source.open(encoding='utf-8-sig') as stream:
        for r in csv.DictReader(stream):
            if r['symbol'] in symbols:
                histories[r['symbol']].append(Bar(r['symbol'],r['date'],
                    *[float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')]))
    counters=Counter();ledger=[];checks=0
    for symbol,raw in histories.items():
        cache=AdjustedCache();pivot_cache=SwingCache(2,2);active=set()
        for end in range(1,len(raw)+1):
            bars=cache.get(raw[:end]);points=pivot_cache.get(bars)
            current={f'{p.kind}:{bars[p.index].date}' for p in points}
            for identity in sorted(current-active):
                ledger.append(dict(symbol=symbol,date=bars[-1].date,pivot=identity,event='first_active'))
            for identity in sorted(active-current):
                ledger.append(dict(symbol=symbol,date=bars[-1].date,pivot=identity,event='endpoint_superseded'))
                counters['endpoint_superseded']+=1
            active=current
            if end%20==0 or end==len(raw):
                assert points==swings(bars,2,2),(symbol,bars[-1].date)
                checks+=1
    result=[];ends=set(calendar['week_ends'])
    for case in cases:
        raw=histories[case['symbol']]
        at=max(i for i,b in enumerate(raw) if b.date<=case['as_of'])
        frames=[snapshot(raw[:i+1],ends) for i in range(max(0,at-40),min(len(raw),at+21))]
        focus=next(f for f in frames if f['as_of']==raw[at].date)
        # Calls using later bars cannot mutate an already recorded decision.
        assert focus==snapshot(raw[:at+1],ends)
        for frame in frames:
            assert all(n['confirmed']<=frame['as_of'] for ns in frame['nodes'].values() for n in ns)
            assert all(c['date']<=frame['as_of'] for cs in frame['candles'].values() for c in cs)
            counters['frames']+=1
            if frame['legacy']['core'] and not frame['latest']['core']:
                counters['legacy_valid_latest_rejected_frames']+=1
                if any(c['smaller_in_both'] for c in frame['later_corrections']):
                    counters['contains_smaller_later_correction_frames']+=1
                if frame['candidates'] and any(c['candidate_id']==frame['candidates'][-1]['id'] and c['smaller_in_both']
                                               for c in frame['later_corrections']):
                    counters['latest_correction_smaller_in_both_frames']+=1
        if focus['legacy']['core'] and not focus['latest']['core']:
            counters['legacy_valid_latest_rejected_cases']+=1
        result.append(dict(**case,reference=labels.get(case['id']),focus_date=raw[at].date,frames=frames))
        print(case['id'],case['symbol'],flush=True)
    summary=dict(cases=len(cases),review_cases=24,focus_cases=5,stocks=len(symbols),
        counters=dict(counters),stream_batch_prefix_checks=checks,causal_checks_passed=True,
        semantic_hierarchy_validated=False,
        conclusion='Existing model provides time containment, not an accepted parent-child wave hierarchy. Latest pivot replacement remains unvalidated.',
        limitations=['Previously studied sample, not independent holdout',
            'Existing labels concern W and retest, not wave boundaries',
            'Daily_nested is a daily pivot proxy, not hourly',
            'Frame counts are repeated observations, not independent opportunities',
            'Superseded endpoints are later refinements; saved earlier snapshots remain unchanged'])
    payload=dict(summary=summary,cases=result)
    (output/'audit.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'pivot-ledger.json').write_text(json.dumps(ledger,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    provenance=dict(source=str(source.resolve()),source_price_sha256=manifest['price_snapshot_sha256'],
        review_manifest_sha256=hashlib.sha256((pack/'manifest.json').read_bytes()).hexdigest(),
        labels_sha256=hashlib.sha256(Path(labels_path).read_bytes()).hexdigest(),
        status='complete',production_rules_changed=False)
    (output/'manifest.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'source').mkdir()
    for name in ('build_wave_validation.py','wave_model_audit.py','wave-validation-app.js'):
        shutil.copy2(Path(__file__).parent/name,output/'source'/name)
    script=(Path(__file__).parent/'wave-validation-app.js').read_text(encoding='utf-8')
    page='''<!doctype html><meta charset="utf-8"><title>波段模型验证</title>
<style>body{font:16px system-ui;margin:22px;color:#202b38;background:#f5f7fa}main{max-width:1500px;margin:auto}select,button,input{font:inherit;padding:8px}canvas{width:100%;height:350px;background:white;border:1px solid #ccd5df}table{border-collapse:collapse;width:100%;background:white}td,th{padding:7px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap}#hover{min-height:28px;font-family:monospace}section{margin:15px 0} .warning{background:#fff0cd;padding:12px}.legend{line-height:1.8}</style>
<main><h1>波段模型验证：只展示所选日期当时已知的结构</h1>
<p class="warning">时间包含不等于真实父子波段。周线、日线枢轴是现有算法；蓝色小枢轴仍是日线代理，不能当小时线。后续时间切换只用于观察变化，不能倒推原时点。原审核意见不是波段边界标准答案。</p>
<section><select id="case"></select> <button id="prev">上一日</button> <button id="next">下一日</button> <button id="focus">回到原审核时点</button><input id="time" type="range"><b id="date"></b></section>
<div id="reference"></div><p class="legend">红色＝已确认周线波段；橙色＝已确认日线波段；蓝色虚线＝日线小枢轴代理；绿色＝旧算法认可的核心 A/B/C；紫色＝v5.10 最新核心。末端尚无确认波峰/波谷的部分不补线。</p>
<div id="hover">移动到K线上显示实际日期和OHLC</div><h3>周线（仅完整交易周）</h3><canvas id="weekly" width="1400" height="350"></canvas><h3>日线及日线内部小枢轴</h3><canvas id="daily" width="1400" height="350"></canvas>
<section id="state"></section><section><h3>当前核心候选与失效边界</h3><div id="candidates"></div></section>
<section><h3>大小结构关系</h3><div id="relations"></div></section><section><h3>验证结果</h3><pre id="summary"></pre></section></main>'''
    compact_cases=[]
    for case in result:
        meta={k:v for k,v in case.items() if k!='frames'}
        meta['frames_gzip']=base64.b64encode(gzip.compress(json.dumps(case['frames'],ensure_ascii=False,separators=(',',':')).encode(),mtime=0)).decode()
        compact_cases.append(meta)
    embedded=json.dumps(dict(summary=summary,cases=compact_cases),ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (output/'review.html').write_text(page+'<script>const DATA='+embedded+';</script><script>'+script+'</script>',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True))


if __name__=='__main__':main(*sys.argv[1:])
