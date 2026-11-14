"""Overlay v5.11 recorded states on the frozen audit's as-of charts."""
import base64,gzip,json,re,sys,shutil
from pathlib import Path


def main(previous,validation):
    previous=Path(previous);out=Path(validation)
    page=(previous/'review.html').read_text(encoding='utf-8')
    data=json.loads(re.search(r'<script>const DATA=([\s\S]*?);</script>',page)[1])
    replay={c['id']:c for c in json.loads((out/'cases.json').read_text(encoding='utf-8'))}
    for case in data['cases']:
        states={f['date']:f for f in replay[case['id']]['frames']}
        old=json.loads(gzip.decompress(base64.b64decode(case['frames_gzip'])))
        frames=[]
        for f in old:
            if f['as_of'] not in states:continue
            state=states[f['as_of']];core=state['core'];geometry=None
            if core:
                record=state['ledger'][core['owner_id']]
                prices={b['date']:b for b in f['candles']['daily']}
                geometry={k:record[k] for k in ('a','b','c')}
                geometry.update(target=core['target'],floor=core['correction_low'],
                                confirmed=core['accepted_at'])
                for key,field in (('a','low'),('b','high'),('c','low')):
                    geometry[key+'_price']=prices[record[key]][field] if record[key] in prices else None
            f['nested']=dict(core=geometry,reason=state['reason'],ledger=state['ledger'],
                              rhythm_owner=core.get('rhythm_owner') if core else None)
            frames.append(f)
        case['frames_gzip']=base64.b64encode(gzip.compress(json.dumps(frames,ensure_ascii=False,separators=(',',':')).encode(),compresslevel=1,mtime=0)).decode()
    data['summary']=json.loads((out/'summary.json').read_text(encoding='utf-8'))
    header=page.split('<script>const DATA=',1)[0]
    header=header.replace('波段模型验证：只展示所选日期当时已知的结构','v5.11归属迭代：三个版本的当时判断')
    header=header.replace('紫色＝v5.10 最新核心。','紫色＝v5.10 最新核心；深蓝色＝v5.11认可的核心。')
    header=header.replace('时间包含不等于真实父子波段。','表中的时间包含关系未验证；v5.11另有规则定义的归属与结束记录，仍需独立数据验证。')
    script=Path('scripts/wave-validation-app.js').read_text(encoding='utf-8')
    embedded=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    (out/'review.html').write_text(header+'<script>const DATA='+embedded+';</script><script>'+script+'</script>',encoding='utf-8')
    (out/'source').mkdir(exist_ok=True)
    for name in ('build_nested_wave_review.py','validate_nested_waves.py','wave-validation-app.js'):
        shutil.copy2(Path('scripts')/name,out/'source'/name)
    print('Created',out/'review.html')


if __name__=='__main__':main(*sys.argv[1:])
