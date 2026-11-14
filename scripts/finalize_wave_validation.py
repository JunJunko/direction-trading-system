"""Compact offline UI and static QA figures; retain full audit in gzip archive."""
import base64,gzip,json,shutil,sys
from pathlib import Path


def main(folder):
    p=Path(folder).resolve();raw=p/'audit.json'
    with (raw.open(encoding='utf-8') if raw.exists() else gzip.open(p/'audit.json.gz','rt',encoding='utf-8')) as stream:
        data=json.load(stream)
    count=0;findings=[];compact=[]
    for case in data['cases']:
        focus=next(f for f in case['frames'] if f['as_of']==case['focus_date'])
        for f in case['frames']:
            for item in f['later_corrections']:
                if item['range_ratio']<=0:item['smaller_in_both']=False
            if f['candidates'] and any(a['candidate_id']==f['candidates'][-1]['id'] and a['smaller_in_both'] for a in f['later_corrections']):count+=1
        latest=focus['candidates'][-1] if focus['candidates'] else None
        findings.append(dict(id=case['id'],symbol=case['symbol'],as_of=case['focus_date'],
            legacy=focus['legacy'],latest=focus['latest'],latest_candidate=latest,
            later_corrections=focus['later_corrections'],reference=case.get('reference')))
        frames=[]
        for f in case['frames']:
            light={k:v for k,v in f.items() if k!='legs'}
            starts={k:v[0]['date'] if v else '' for k,v in f['candles'].items()}
            light['nodes']={k:[n for n in ns if n['bar_date']>=starts['weekly' if k=='weekly' else 'daily']]
                            for k,ns in f['nodes'].items()}
            light['relations']=[* [r for r in f['relations'] if r['child'].startswith('daily:')][-20:],
                                * [r for r in f['relations'] if r['child'].startswith('daily_nested_proxy:')][-20:]]
            chosen={':'.join(f[k]['core'][v] for v in ('a','b','c')) for k in ('legacy','latest') if f[k]['core']}
            light['candidates']=[c for c in f['candidates'] if c in f['candidates'][-16:] or c['id'] in chosen]
            frames.append(light)
        meta={k:v for k,v in case.items() if k!='frames'}
        encoded=json.dumps(frames,ensure_ascii=False,separators=(',',':')).encode()
        packed=gzip.compress(encoded,compresslevel=1,mtime=0)
        assert gzip.decompress(packed)==encoded
        meta['frames_gzip']=base64.b64encode(packed).decode();compact.append(meta)
    data['summary']['counters']['latest_correction_smaller_in_both_frames']=count
    (p/'summary.json').write_text(json.dumps(data['summary'],ensure_ascii=False,indent=2),encoding='utf-8')
    (p/'case-findings.json').write_text(json.dumps(findings,ensure_ascii=False,indent=2),encoding='utf-8')
    page=(p/'review.html').read_text(encoding='utf-8').split('<script>const DATA=',1)[0]
    script=Path('scripts/wave-validation-app.js').read_text(encoding='utf-8')
    embedded=json.dumps(dict(summary=data['summary'],cases=compact),ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (p/'review.html').write_text(page+'<script>const DATA='+embedded+';</script><script>'+script+'</script>',encoding='utf-8')
    with gzip.open(p/'audit.json.gz','wt',encoding='utf-8',compresslevel=1) as stream:
        json.dump(data,stream,ensure_ascii=False,separators=(',',':'))
    # Only remove this task's generated uncompressed duplicate, never inputs.
    assert raw.parent==p and p.name=='20261010-wave-model-validation'
    if raw.exists():raw.unlink()
    for name in ('wave_model_audit.py','build_wave_validation.py','finalize_wave_validation.py','wave-validation-app.js'):
        shutil.copy2(Path('scripts')/name,p/'source'/name)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans']
    for identifier in ('F01','F02','F03','F04','F05','R17'):
        case=next(c for c in data['cases'] if c['id']==identifier)
        f=next(x for x in case['frames'] if x['as_of']==case['focus_date'])
        fig,axes=plt.subplots(2,1,figsize=(16,9));fig.suptitle(identifier+' '+case['symbol']+' 当时已知 '+f['as_of'])
        for scale,ax in zip(('weekly','daily'),axes):
            bars=f['candles'][scale];dates={b['date']:i for i,b in enumerate(bars)}
            for i,b in enumerate(bars):
                color='#c75454' if b['close']>=b['open'] else '#45927c'
                ax.vlines(i,b['low'],b['high'],color=color,linewidth=.8)
                ax.add_patch(Rectangle((i-.3,min(b['open'],b['close'])),.6,max(.005,abs(b['close']-b['open'])),color=color))
            layers=[(scale,'#c12638' if scale=='weekly' else '#d98816','-')]
            if scale=='daily':layers.append(('daily_nested_proxy','#367fba','--'))
            for key,color,style in layers:
                nodes=[n for n in f['nodes'][key] if ('bar_date' if scale=='weekly' else 'date') in n and n['bar_date' if scale=='weekly' else 'date'] in dates]
                ax.plot([dates[n['bar_date' if scale=='weekly' else 'date']] for n in nodes],[n['price'] for n in nodes],style,color=color,lw=1,label=key)
            if scale=='daily':
                for key,color in (('legacy','#1e8b50'),('latest','#8a41a1')):
                    core=f[key]['core']
                    if not core:continue
                    c=next(x for x in f['candidates'] if x['a']==core['a'] and x['b']==core['b'] and x['c']==core['c'])
                    if all(c[k] in dates for k in ('a','b','c')):
                        ax.plot([dates[c[k]] for k in ('a','b','c')],[c[k+'_price'] for k in ('a','b','c')],color=color,lw=2,label=key+' core')
                        for k in ('a','b','c'):ax.annotate(k.upper(),(dates[c[k]],c[k+'_price']))
                    ax.axhline(core['floor'],color=color,ls=':',label=key+' floor')
            ticks=list(range(0,len(bars),max(1,len(bars)//8)))
            ax.set_xticks(ticks,[bars[i]['date'] for i in ticks]);ax.grid(alpha=.2);ax.legend(loc='upper left',fontsize=8)
        fig.tight_layout();fig.savefig(p/(identifier+'.png'),dpi=120);plt.close(fig)
    print(json.dumps(dict(page_bytes=(p/'review.html').stat().st_size,latest_smaller_frames=count,figures=6),ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1])
