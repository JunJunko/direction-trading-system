"""As-of structural evidence, outcome-blind review, and account comparison."""
import sys,json,csv,pickle,hashlib,html,copy
from pathlib import Path
from collections import Counter,defaultdict

def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def audit_plan(p,raw,adjusted,SwingCache):
    e=p['evidence'];known=adjusted([b for b in raw if b.date<=p['date']])
    ix={b.date:i for i,b in enumerate(known)};bad=[];uncertain=[];stale=[]
    dates={k:e.get(k) for k in ('core_a','core_b','core_c','core_c_confirmed','small_a','small_b','small_c','small_confirmed')}
    if not all(d in ix for d in dates.values()):
        return dict(category='结构或日期不一致',errors=['结构日期不在当时已知序列'],uncertainties=[],freshness=[],facts=dates)
    a,b,c=[ix[e[k]] for k in ('core_a','core_b','core_c')]
    sa,sb,sc=[ix[e[k]] for k in ('small_a','small_b','small_c')]
    cc,confirmed=ix[e['core_c_confirmed']],ix[e['small_confirmed']]
    if not (a<b<c<=cc<len(known) and sa<sb<sc<=confirmed<len(known)):bad.append('A/B/C 或确认日期顺序不成立')
    if bad:return dict(category='结构或日期不一致',errors=bad,uncertainties=[],freshness=[],facts=dates)
    if not (known[a].low<known[c].low<known[b].high):bad.append('核心价格关系不成立')
    if not (known[sa].low<known[sc].low<known[sb].high):bad.append('小结构价格关系不成立')
    corefloor=min(known[b+1:c+1],key=lambda x:x.low)
    smallfloor=min(known[sb+1:sc+1],key=lambda x:x.low)
    if corefloor.low<known[c].low-1e-8:bad.append('核心C不是所标B至C调整的实际最低点，合并了较早下跌与较晚高谷')
    if smallfloor.low<known[sc].low-1e-8:bad.append('小结构C不是所标B至C调整的实际最低点')
    if min(x.low for x in known[c:])<known[c].low-1e-8:bad.append('信号前核心C已破坏')
    if min(x.low for x in known[sc:])<known[sc].low-1e-8:bad.append('信号前小结构C已破坏')
    for left,right,start,end,label in ((2,2,a,c,'核心'),(1,1,sa,sc,'小结构')):
        cache=SwingCache(left,right);cache.get(known)
        regions=[known[r['index']].date for r in cache.ambiguous if start<=r['index']<=end]
        if regions:uncertain.append(label+'内日K同时为高低极值，先后未知：'+','.join(regions))
    origin=e.get('direction_second')
    if origin:
        from trading_system.analysis import week_key
        group=[x for x in known if week_key(x.date)==week_key(origin)]
        if group and e['core_a']<min(group,key=lambda x:(x.low,-int(x.date))).date:
            uncertain.append('日线核心起点早于周线右底：须核对上级归属，不能只凭日期判无效')
    touches=[x for x in known[confirmed:] if x.high>=p['trigger']]
    later=[x for x in touches if x.date>e['small_confirmed']]
    closes=[x for x in known[confirmed:] if x.close>=p['trigger']]
    if touches:
        stale.append('计划前已触发'+('（仅确认当根，日内先后未知）' if not later else '（存在确认之后的触价日）'))
    projection=known[c].low+known[b].high-known[a].low
    reached=[x.date for x in known[c:] if x.high>=projection]
    if reached:stale.append('核心投射曾实现；旧空间是否可复用须另作验证')
    effective=[x for x in e.get('pressure_audit',[]) if x['reason']=='effective' and x['price']<p['target']-1e-8]
    if effective:uncertain.append('目标超过当时算法判定的有效压力；压力是否有效仍缺独立标注')
    if e.get('rhythm_floor_date') and e['small_c']<e['rhythm_floor_date']:
        uncertain.append('小结构早于记录的最新子谷：节奏归属需核对')
    category=('结构或日期不一致' if bad else '日内顺序／归属／目标待核对' if uncertain else
              '新鲜性约定待核对' if stale else '固定结构检查通过，待独立确认')
    facts=dict(**dates,first_plan=p['date'],core_actual_floor_date=corefloor.date,
        core_actual_floor_price=corefloor.low,core_c_price=known[c].low,
        small_actual_floor_date=smallfloor.date,small_actual_floor_price=smallfloor.low,
        small_c_price=known[sc].low,first_high_touch=touches[0].date if touches else None,
        first_later_high_touch=later[0].date if later else None,
        first_close_touch=closes[0].date if closes else None,
        bars_since_first_touch=(len(known)-1-ix[touches[0].date]) if touches else None,
        touch_only_confirmation=bool(touches and not later),core_projection_first_reached=reached[0] if reached else None,
        trigger=p['trigger'],stop=p['stop'],target=p['target'],gross_rr=(p['target']-p['trigger'])/(p['trigger']-p['stop']))
    return dict(category=category,errors=bad,uncertainties=uncertain,freshness=stale,facts=facts)

def panels(p,raw,adjusted,weekly,ends):
    e=p['evidence'];known=adjusted([b for b in raw if b.date<=p['date']]);weeks=weekly(known,ends)
    # Focus the upper evidence on its original causal direction confirmation.
    # The current core/rhythm panels still end at this case's observation date.
    if e.get('direction_confirmed'):weeks=[w for w in weeks if w.date<=e['direction_confirmed']]
    def window(bars,start,keys,cycle):
        ix={b.date:i for i,b in enumerate(bars)};i=max(0,ix.get(start,0)-8)
        shown=bars[i:];index={b.date:n for n,b in enumerate(shown)}
        line=[]
        for label,date,kind in keys:
            if date in index:
                n=index[date];line.append(dict(label=label,date=date,i=n,y=getattr(shown[n],kind)))
        return dict(cycle=cycle,bars=[dict(date=b.date,o=b.open,h=b.high,l=b.low,c=b.close) for b in shown],line=line,levels=[])
    wk=[];first=e.get('direction_first');second=e.get('direction_second');wi={b.date:i for i,b in enumerate(weeks)}
    neckline=None
    if first in wi and second in wi and wi[first]+1<wi[second]:
        n=max(range(wi[first]+1,wi[second]),key=lambda i:weeks[i].high);neckline=weeks[n].high
        wk=[('左底',first,'low'),('颈线峰',weeks[n].date,'high'),('右底',second,'low')]
    upper=window(weeks,first,wk,'周线：方向确认时的双底与颈线')
    upper['marks']=[dict(date=e.get(k),label=label) for k,label in
        [('direction_breakout','突破'),('direction_retest_started','反抽开始'),('direction_confirmed','方向确认')]]
    if neckline:upper['levels']=[dict(label='颈线',y=neckline)]
    core=window(known,e['core_a'],[(k[-1].upper(),e[k],kind) for k,kind in
        [('core_a','low'),('core_b','high'),('core_c','low')]],'日线：核心 A/B/C')
    small=window(known,e['small_a'],[(k[-1].upper(),e[k],kind) for k,kind in
        [('small_a','low'),('small_b','high'),('small_c','low')]],'日线：小结构代理 A/B/C')
    small['marks']=[dict(date=e['small_confirmed'],label='小C确认'),dict(date=p['date'],label='首次计划')]
    small['levels']=[dict(label=label,y=p[key]) for key,label in [('trigger','触发'),('stop','初始止损'),('target','计划目标')]]
    return [upper,core,small]

PAGE=r'''<!doctype html><meta charset="utf-8"><title>规则对照：结构盲审</title>
<style>body{font:16px system-ui;margin:24px;background:#f3f5f8;color:#1b2735}canvas{width:100%;height:290px;background:white;display:block;border:1px solid #bcc5d2;margin:12px 0}button,select,input{padding:8px;margin:4px}textarea{width:95%;height:65px}#info{white-space:pre-wrap}#nav{position:sticky;top:0;background:#f3f5f8;padding:6px;z-index:2}.chart{position:relative}.tip{min-height:24px;font:14px monospace}p{max-width:1200px}</style>
<h1>结构盲审</h1><p>只显示首次计划当日及以前的已知行情；隐藏规则分组、后续行情和盈亏。周线图集中显示该次方向确认前的双底；日线核心和局部图截止案例日期，用于检查波段归属及节奏。小结构为日线代理。画线是算法提出的结构，不代表正确答案。移动鼠标可看日期和OHLC。</p>
<div id="nav"><button id="prev">上一条</button><span id="counter"></span><button id="next">下一条</button><button id="export">导出审核 JSON</button><span id="saved"></span></div><h2 id="title"></h2><div id="charts"></div>
<div id="labels"></div><textarea id="note" placeholder="具体原因或应当采用的A/B/C日期"></textarea><pre id="info"></pre>
<script>const cases=__DATA__;let current=0;const key='rule-ablation-__RUN__';let labels={};try{labels=JSON.parse(localStorage.getItem(key)||'{}')}catch(e){};
const fields=[['core','日线核心成立吗'],['rhythm','小结构及归属成立吗'],['timing','此时入场计划仍合理吗']];
function save(){const id=cases[current].case_id;labels[id]=Object.fromEntries(fields.map(([k])=>[k,document.getElementById(k).value]));labels[id].note=document.getElementById('note').value;labels[id].as_of=cases[current].as_of;try{localStorage.setItem(key,JSON.stringify(labels));document.getElementById('saved').textContent='已保存草稿 '+Object.keys(labels).length+' 条'}catch(e){document.getElementById('saved').textContent='草稿保存失败，请立即导出'} }
function draw(canvas,panel,cursor){const ctx=canvas.getContext('2d'),dpr=devicePixelRatio||1;canvas.width=canvas.clientWidth*dpr;canvas.height=290*dpr;ctx.scale(dpr,dpr);const W=canvas.clientWidth,H=290,L=65,R=135,T=28,B=40,bs=panel.bars;if(!bs.length)return;let lo=Math.min(...bs.map(b=>b.l)),hi=Math.max(...bs.map(b=>b.h));for(const l of panel.levels){if(l.label!=="计划目标"){lo=Math.min(lo,l.y);hi=Math.max(hi,l.y)}}const pad=Math.max(.01,(hi-lo)*.08);lo-=pad;hi+=pad;const x=i=>L+(i+.5)*(W-L-R)/bs.length,y=v=>T+(hi-v)*(H-T-B)/(hi-lo);ctx.font='12px system-ui';ctx.fillStyle='#1b2735';ctx.fillText(panel.cycle,L,17);for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;ctx.strokeStyle='#e1e6ed';ctx.beginPath();ctx.moveTo(L,y(v));ctx.lineTo(W-R,y(v));ctx.stroke();ctx.fillStyle='#536274';ctx.fillText(v.toFixed(2),4,y(v)+4)}bs.forEach((b,i)=>{ctx.strokeStyle=ctx.fillStyle=b.c>=b.o?'#c75454':'#45927c';ctx.beginPath();ctx.moveTo(x(i),y(b.h));ctx.lineTo(x(i),y(b.l));ctx.stroke();const w=Math.max(1,Math.min(9,(W-L-R)/bs.length*.65));ctx.fillRect(x(i)-w/2,y(Math.max(b.o,b.c)),w,Math.max(1,Math.abs(y(b.o)-y(b.c))))});ctx.strokeStyle='#2a58b7';ctx.lineWidth=2;ctx.beginPath();panel.line.forEach((p,i)=>{i?ctx.lineTo(x(p.i),y(p.y)):ctx.moveTo(x(p.i),y(p.y))});ctx.stroke();ctx.lineWidth=1;ctx.fillStyle='#2a58b7';panel.line.forEach(p=>ctx.fillText(p.label+' '+p.date,x(p.i)+3,y(p.y)-9));for(const l of panel.levels){if(y(l.y)<T||y(l.y)>H-B){ctx.fillStyle="#70561f";ctx.fillText(l.label+" "+l.y.toFixed(3)+"（图外）",W-R+5,T+12);continue}ctx.setLineDash([5,4]);ctx.strokeStyle='#a47927';ctx.beginPath();ctx.moveTo(L,y(l.y));ctx.lineTo(W-R,y(l.y));ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#70561f';ctx.fillText(l.label+' '+l.y.toFixed(3),W-R+5,y(l.y)+4)}for(const m of panel.marks||[]){let i=bs.findIndex(b=>b.date===m.date);if(i<0)continue;ctx.strokeStyle='#83739e';ctx.setLineDash([2,4]);ctx.beginPath();ctx.moveTo(x(i),T);ctx.lineTo(x(i),H-B);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#65537e';ctx.fillText(m.label,x(i)+3,H-B-5)}const step=Math.max(1,Math.ceil(bs.length/8));for(let i=0;i<bs.length;i+=step){ctx.fillStyle='#536274';ctx.fillText(bs[i].date,x(i)-26,H-12)}if(cursor!=null){const i=Math.max(0,Math.min(bs.length-1,Math.floor((cursor-L)*bs.length/(W-L-R))));ctx.strokeStyle='#18293e';ctx.beginPath();ctx.moveTo(x(i),T);ctx.lineTo(x(i),H-B);ctx.stroke();ctx.fillStyle='#18293e';ctx.fillRect(Math.max(L,Math.min(x(i)-42,W-R-84)),H-B,84,20);ctx.fillStyle='white';ctx.fillText(bs[i].date,Math.max(L,Math.min(x(i)-42,W-R-84))+10,H-B+14);return bs[i]}}
function render(){const c=cases[current];document.getElementById('counter').textContent=(current+1)+' / '+cases.length;document.getElementById('title').textContent=c.case_id+' · '+c.symbol+' · 截至 '+c.as_of;const charts=document.getElementById('charts');charts.replaceChildren();c.panels.forEach(p=>{const box=document.createElement('div'),canvas=document.createElement('canvas'),tip=document.createElement('div');tip.className='tip';box.append(canvas,tip);charts.append(box);draw(canvas,p);canvas.addEventListener('mousemove',ev=>{const b=draw(canvas,p,ev.clientX-canvas.getBoundingClientRect().left);if(b)tip.textContent=b.date+' 开 '+b.o.toFixed(3)+' 高 '+b.h.toFixed(3)+' 低 '+b.l.toFixed(3)+' 收 '+b.c.toFixed(3)});canvas.addEventListener('mouseleave',()=>draw(canvas,p))});const form=document.getElementById('labels');form.replaceChildren();fields.forEach(([k,text])=>{const label=document.createElement('label');label.textContent=(c.kind==='holding'?({core:'该调整属于日线保护结构吗',rhythm:'波谷确认与恢复成立吗',timing:'此时上移保护位合理吗'})[k]:text)+' ';const select=document.createElement('select');select.id=k;[['','未审核'],['yes','成立'],['no','不成立'],['unclear','看不准']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;select.append(o)});select.value=(labels[c.case_id]||{})[k]||'';select.addEventListener('change',save);label.append(select);form.append(label)});document.getElementById('note').value=(labels[c.case_id]||{}).note||'';document.getElementById('info').textContent='核心C确认 '+c.core_confirmed+'；小C确认 '+c.small_confirmed+'；首次计划 '+c.as_of;}
document.getElementById('prev').onclick=()=>{current=(current+cases.length-1)%cases.length;render()};document.getElementById('next').onclick=()=>{current=(current+1)%cases.length;render()};document.getElementById('note').addEventListener('input',save);document.getElementById('export').onclick=()=>{save();const payload={schema:'rule-ablation-review-v1',run:'__RUN__',exported_at:new Date().toISOString(),labels};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json;charset=utf-8'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='__RUN__-'+Object.keys(labels).length+'-labels.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);document.getElementById('saved').textContent='已请求下载 '+Object.keys(labels).length+' 条，请确认下载目录'};window.addEventListener('resize',render);render();</script>'''

def main(run):
    out=Path(run);sys.path.insert(0,str(out/'frozen-baseline/source/src'))
    from trading_system.domain import Bar
    from trading_system.analysis import adjusted,weekly
    from trading_system.structure import SwingCache
    from trading_system.data import save_csv
    cache=pickle.loads((out/'signal-cache.pkl').read_bytes());plans=cache['plans'];frames=cache['frames']
    comparison=json.loads((out/'comparison.json').read_text(encoding='utf-8'))
    ends=set(json.loads((out/'frozen-baseline/calendar.json').read_text(encoding='utf-8'))['week_ends'])
    symbols={p['symbol'] for ps in plans.values() for p in ps.values()};history=defaultdict(list)
    with (out/'frozen-baseline/bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:history[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for bs in history.values():bs.sort(key=lambda b:b.date)
    audits={};differences=[];base=plans['baseline'];selected={};review_members=[];holding_cases=[]
    def evidence(vid,p):
        key=(p['setup_id'],p['date'],p['trigger'],p['stop'],p['target'])
        if key not in audits:audits[key]=audit_plan(p,history[p['symbol']],adjusted,SwingCache)
        return copy.deepcopy(audits[key])
    def add_case(vid,p,role):
        identity=(p['setup_id'],p['date'],p['trigger'],p['stop'],p['target'])
        if identity not in selected:
            case_id='S'+str(len(selected)+1).zfill(3);selected[identity]=(case_id,p)
        else:case_id=selected[identity][0]
        review_members.append(dict(case_id=case_id,variant=vid,role=role,setup_id=p['setup_id']))
    ranking=lambda sid:hashlib.sha256(('20261010|'+sid).encode()).hexdigest()
    for result in comparison:
        vid=result['id'];ps=base if result['group']=='holding' else plans[vid]
        result['modified_levels']=sum(any(abs(ps[s][k]-base[s][k])>1e-8 for k in ('trigger','stop','target')) for s in set(ps)&set(base))
        result['net_pnl']=result['summary']['final_equity']-result['summary']['initial_cash']
        counts=Counter()
        roles={'restored':result['restored_ids'],'lost':result['lost_ids'],'rescheduled':result['rescheduled_ids']}
        for role,ids in roles.items():
            for sid in ids:
                p=base[sid] if role=='lost' else ps[sid];ev=evidence(vid,p)
                if role=='restored':counts[ev['category']]+=1
                differences.append(dict(variant=vid,role=role,symbol=p['symbol'],setup_id=sid,plan_date=p['date'],
                    baseline_date=base.get(sid,{}).get('date'),**ev,
                    baseline_observed_events=frames.get((p['symbol'],p['date']),[])))
            for sid in sorted(ids,key=ranking)[:4]:add_case(vid,base[sid] if role=='lost' else ps[sid],role)
        result['restored_checks']=dict(counts)
        result['restored_error_count']=sum(bool(d['errors']) for d in differences if d['variant']==vid and d['role']=='restored')
        result['restored_touch_only_confirmation']=sum(d['facts'].get('touch_only_confirmation',False) for d in differences if d['variant']==vid and d['role']=='restored')
        # Prices can change while setup identity stays fixed (e.g. pressure control).
        for sid in set(ps)&set(base):
            if any(abs(ps[sid][k]-base[sid][k])>1e-8 for k in ('trigger','stop','target')):
                differences.append(dict(variant=vid,role='modified_levels',symbol=ps[sid]['symbol'],setup_id=sid,
                    plan_date=ps[sid]['date'],baseline_levels={k:base[sid][k] for k in ('trigger','stop','target')},**evidence(vid,ps[sid])))
        promotions=[];account_events=[]
        with (out/vid/'decisions.csv').open(encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['event'] in ('entry_rejected','plan_rejected','plan_approved'):account_events.append(r)
                if r['event']=='core_protection_promoted':promotions.append({k:v for k,v in r.items() if v!=''})
        first_status={}
        for ev in account_events:
            sid=ev['setup_id']
            if sid in ps and ev['date']==ps[sid]['date']:
                first_status.setdefault(sid,ev['reason'] or ev['event'])
        for sid in ps:first_status.setdefault(sid,'already_held_or_no_assessment')
        result['first_plan_funnel']=dict(Counter(first_status.values()))
        result['restored_first_plan_funnel']=dict(Counter(first_status[sid] for sid in result['restored_ids']))
        result['protection_promotions']=len(promotions);dump(out/vid/'promotions.json',promotions)
        if result['group']=='holding':
            anchors={sid:p['evidence']['core_c'] for sid,p in base.items()}
            proposed=[]
            for pr in promotions:
                sid=pr['setup_id'];original=base[sid];p=copy.deepcopy(original);p['date']=pr['date']
                e=p['evidence'];anchor=anchors[sid];anchors[sid]=pr['trough_date']
                for prefix in ('core','small'):
                    e[prefix+'_a']=anchor;e[prefix+'_b']=pr['peak_date'];e[prefix+'_c']=pr['trough_date']
                e['core_c_confirmed']=e['small_confirmed']=pr['date']
                factor=next(b.factor for b in history[p['symbol']] if b.date==pr['date'])
                p['trigger']*=e['factor']/factor;p['target']*=e['factor']/factor
                p['stop']=float(pr['old_stop']);p['new_stop']=float(pr['new_stop'])
                proposed.append(p)
            for p in sorted(proposed,key=lambda p:ranking(p['setup_id']+':'+p['date']))[:4]:
                holding_cases.append((vid,p))
        with (out/vid/'trades.csv').open(encoding='utf-8-sig') as f:trades=list(csv.DictReader(f))
        trade_checks=[]
        for t in trades:
            rr=float(t['realized_r']);pnl=float(t['pnl']);risk=pnl/rr if rr else None
            exit_known=adjusted([b for b in history[t['symbol']] if b.date<=t['exit_date']])
            held=[b for b in exit_known if t['entry_date']<=b.date<t['exit_date']]
            peak=max(held,key=lambda b:b.close) if held else None
            peak_r=(peak.close-float(t['entry']))*float(t['quantity'])/risk if peak and risk else None
            trade_checks.append(dict(**t,peak_close_date=peak.date if peak else None,
                peak_close_gross_r=peak_r,realized_net_r=rr,
                positive_peak_then_loss=bool(peak_r is not None and peak_r>0 and rr<0),
                attribution='Retrospective, close gross peak excludes exit day; never used to label structure validity.'))
        dump(out/vid/'trade-profit-checks.json',trade_checks)
        result['peak_then_loss_trades']=sum(t['positive_peak_then_loss'] for t in trade_checks)
    for sid in sorted(base,key=ranking)[:4]:add_case('baseline',base[sid],'control')
    probe=out/'holding-gate-observations.json'
    if probe.exists():
        observed=json.loads(probe.read_text(encoding='utf-8'))['first_observations']
        for pr in sorted(observed,key=lambda p:ranking(p['setup_id']+':'+p['trough_date']))[:4]:
            original=base[pr['setup_id']];p=copy.deepcopy(original);p['date']=pr['date'];e=p['evidence']
            for prefix in ('core','small'):
                e[prefix+'_a']=pr['anchor_date'];e[prefix+'_b']=pr['peak_date'];e[prefix+'_c']=pr['trough_date']
            e['core_c_confirmed']=e['small_confirmed']=pr['date']
            factor=next(b.factor for b in history[p['symbol']] if b.date==pr['date'])
            p['trigger']*=e['factor']/factor;p['target']*=e['factor']/factor
            p['stop']*=e['factor']/factor
            known=adjusted([b for b in history[p['symbol']] if b.date<=pr['date']])
            p['new_stop']=next(b.low for b in known if b.date==pr['trough_date'])*.995
            holding_cases.append(('holding_baseline_rejected',p))
    dump(out/'comparison.json',comparison);dump(out/'structure-differences.json',differences)
    save_csv(out/'structure-differences.csv',[dict(variant=d['variant'],role=d['role'],symbol=d['symbol'],setup_id=d['setup_id'],
        plan_date=d['plan_date'],category=d['category'],errors='；'.join(d['errors']),uncertainties='；'.join(d['uncertainties']),
        freshness='；'.join(d['freshness']),**d['facts']) for d in differences])
    rebuild_exclusion_context(out,differences,plans,history,cache['upper_events'],adjusted,ends)
    cases=[]
    for identity,(cid,p) in selected.items():
        e=p['evidence'];case=dict(case_id=cid,symbol=p['symbol'],as_of=p['date'],
            core_confirmed=e['core_c_confirmed'],small_confirmed=e['small_confirmed'],panels=panels(p,history[p['symbol']],adjusted,weekly,ends))
        assert all(b['date']<=p['date'] for panel in case['panels'] for b in panel['bars'])
        cases.append(case)
    for vid,p in holding_cases:
        cid='P'+str(len(cases)+1).zfill(3);e=p['evidence'];pn=panels(p,history[p['symbol']],adjusted,weekly,ends)
        pn[1]['cycle']='日线：提出上移保护位的调整 A/B/C'
        pn[2]['cycle']='日线：保护候选局部（非入场小结构）'
        pn[2]['levels']=[dict(label='原保护位',y=p['stop']),dict(label='候选保护位（需审核）',y=p['new_stop'])]
        pn[2]['marks']=[dict(date=p['date'],label='候选首次可观察')]
        cases.append(dict(case_id=cid,symbol=p['symbol'],as_of=p['date'],kind='holding',
            core_confirmed=e['core_c_confirmed'],small_confirmed=e['small_confirmed'],panels=pn))
        review_members.append(dict(case_id=cid,variant=vid,role='holding_promotion',setup_id=p['setup_id']))
    assert all(b['date']<=c['as_of'] for c in cases for panel in c['panels'] for b in panel['bars'])
    dump(out/'review-case-map.json',review_members)
    dump(out/'frozen-baseline-structure-checks.json',[dict(setup_id=p['setup_id'],symbol=p['symbol'],date=p['date'],
        **evidence('baseline',p)) for p in base.values()])
    dump(out/'blind-cases.json',cases)
    (out/'blind-review.html').write_text(PAGE.replace('__DATA__',json.dumps(cases,ensure_ascii=False)).replace('__RUN__',out.name),encoding='utf-8')
    dump(out/'validity-notes.json',dict(outcome_blind_checks=True,review_cases=len(cases),
        independent_daily_wave_labels=False,intraday_order_data_available=False,
        category_warning='通过固定规则仅为待独立确认候选；未知先后并非已证明错误；新鲜性与压力规则是工程约定。'))
    build_report(out,comparison,differences,len(cases))
    plot_examples(out,cases,review_members)
    print(json.dumps(dict(output=str(out),differences=len(differences),blind_cases=len(cases)),ensure_ascii=False))

def build_report(out,comparison,differences,n):
    esc=html.escape
    table=[]
    for r in comparison:
        table.append('<tr>'+''.join('<td>'+esc(str(v))+'</td>' for v in [r['id'],r['name'],r['plans'],r['restored'],r['lost'],r['rescheduled'],r['modified_levels'],r['buys'],r['protection_promotions'],r['restored_error_count'],round(r['net_pnl'],2)])+'</tr>')
    reasons=[]
    for r in comparison:
        if r['group'] in ('entry','control'):
            reasons.append('<tr><td>'+r['id']+'</td><td>'+esc(json.dumps(r['restored_checks'],ensure_ascii=False))+'</td><td>'+esc(json.dumps(r['first_plan_funnel'],ensure_ascii=False))+'</td><td>'+esc(json.dumps(r['restored_first_plan_funnel'],ensure_ascii=False))+'</td></tr>')
    cases=[]
    for d in differences:
        cases.append('<tr><td>'+esc(d['variant']+' / '+d['role'])+'</td><td>'+esc(d['symbol'])+'</td><td>'+esc(d['plan_date'])+'</td><td>'+esc(d['category'])+'</td><td>'+esc('；'.join(d['errors']+d['uncertainties']+d['freshness']))+'</td><td>'+esc(json.dumps(d['facts'],ensure_ascii=False))+'</td></tr>')
    report='''<!doctype html><meta charset="utf-8"><title>冻结基线与单规则对照</title><style>body{font:16px system-ui;color:#1b2735;margin:28px}table{border-collapse:collapse;width:100%;font-size:14px;margin:20px 0}td,th{border:1px solid #cad1db;padding:8px;vertical-align:top}th{background:#eef2f7}p{max-width:1250px;line-height:1.7}.scroll{overflow:auto}a{color:#245baf}</style>
    <h1>冻结基线与单规则对照</h1><p>固定 v5.11.2、3214只历史主板股票、2856672条日K、逐日ST排除与100万元共同账户。评估2025-10-09至2026-09-30。每组只关闭指定约束；周线方向/反抽使用基线已观察到的不可变事件。数值阈值、费用、风控、RR&gt;3、T+1和执行歧义处理均未放宽。基线计划、全部订单、交易、日净值及执行审核均逐项复现通过。</p>
    <p>这是已研究样本的规则因果对照，不能作为独立收益验证。生产代码未修改，未根据盈利挑选版本。H组复用完全相同的入场计划，只改变持仓保护。C01为压力目标敏感性对照，不认定为最近新增规则。关闭规则可能改变状态路径，因此同时列恢复、丢失及改期。H03是时间/幅度的联合准入，H04/H05分别关闭一个子条件，有遮挡时单项可能无变化。</p>
    <p><a href="baseline-equivalence.json">基线复现证明</a> · <a href="evaluation-plan.json">事先冻结的实验定义</a> · <a href="frozen-inputs.json">输入校验</a> · <a href="blind-review.html">结构盲审（__N__个去重案例）</a> · <a href="structure-differences.csv">全量差异明细CSV</a> · <a href="structure-differences.json">完整结构证据</a></p>
    <h2>单规则结果</h2><div class="scroll"><table><tr><th>组</th><th>关闭规则</th><th>计划</th><th>恢复</th><th>丢失</th><th>改期</th><th>价位改变</th><th>买入</th><th>保护位提升次数</th><th>恢复中结构不一致</th><th>净盈亏</th></tr>__TABLE__</table></div>
    <h2>被排除结构与账户过滤</h2><p>核对仅用首次计划日及以前行情，后续盈亏不参与结构分类。实谷不符、日期倒置、C已破坏属于可由当时数据证明的不一致；日内先后、上级归属、目标压力另列待核对。确认当根触价可能只是确认与触发发生在同一天，不能凭日K证明能先挂单再成交；确认之后旧触发价已被反复越过，则需判断是不是旧节奏的再利用。固定检查通过仍需独立结构标签，不能直接称为有效交易机会。</p>
    <table><tr><th>组</th><th>恢复候选检查</th><th>首次计划独立口径</th><th>其中恢复计划的首次审核</th></tr>__REASONS__</table>
    <h2>书中思想与本次检验边界</h2><p>《持续盈利》第一部分讨论顶底辨识方向、突破与反抽；第二部分系统架构要求上下周期配合、匹配的N结构、节奏失败止损、盈亏比大于3以及确认波谷后的保护。本次检验的是现有量化约定是否错误排除或错误合并结构，不把工程门槛当成书中的唯一含义。周线方向已固定，所以不能由本次证明上级双底算法正确；日线小结构代理也不能替代真实小时线。原有26条审核主要检验周线W和反抽，尚无独立日线核心与小结构标签。</p>
    <h2>逐条证据（包含算法分组；盲审页隐藏这些信息）</h2><div class="scroll"><table><tr><th>组/变化</th><th>股票</th><th>首次计划</th><th>检查分类</th><th>原因</th><th>当时事实</th></tr>__CASES__</table></div>'''
    if (out/'recovery-verification.json').exists():
        report=report.replace('<h2>单规则结果</h2>','<p>研究工具最初发生冻结目录与输出目录重名，覆盖的决策日志已按事前SHA-256逐字节恢复。全部冻结输入复核通过；输入现在保存在frozen-baseline、账户输出在baseline。<a href="recovery-verification.json">恢复证明</a>与禁止目录覆盖的回归测试均保留。</p><h2>单规则结果</h2>')
    if (out/'holding-gate-observations.json').exists():
        probe=json.loads((out/'holding-gate-observations.json').read_text(encoding='utf-8'))
        content='<h2>持仓保护：没有提升的完整门槛证据</h2><p>追加的只读诊断逐日计算全部保护条件，并再次证明订单、交易、净值与基线一致。它没有新增对照分组或修改规则。仅关闭本级分类仍为零提升：其他条件还要求调整至少3根、回落速度慢于从核心C起算的整个上涨段、波谷完好及恢复确认。对002602在2026-02-02已知的01-29波谷，实际谷底、恢复、抬高止损等检查通过，但时间、幅度和速度同时不通过。这不能被解释为“只降一个参数就能保护利润”；需要检验把入场匹配条件用于持仓保护是否有依据。</p><p><a href="holding-gate-observations.csv">逐日全部门槛CSV</a> · <a href="holding-gate-observations.json">完整诊断与账户一致性证明</a></p><table><tr><th>股票</th><th>当时日期</th><th>候选波谷</th><th>未通过条件</th></tr>'
        for e in probe['first_observations']:
            content+='<tr><td>'+e['symbol']+'</td><td>'+e['date']+'</td><td>'+e['trough_date']+'</td><td>'+esc(', '.join(k for k,v in e['checks'].items() if not v))+'</td></tr>'
        content+='</table>'
        report=report.replace('<h2>书中思想',content+'<h2>书中思想')
    (out/'report.html').write_text(report.replace('__N__',str(n)).replace('__TABLE__',''.join(table)).replace('__REASONS__',''.join(reasons)).replace('__CASES__',''.join(cases)),encoding='utf-8')

def rebuild_exclusion_context(out,differences,plans,histories,events,adjusted,ends):
    from ablation_rules import FrozenUpper,entry_method,bind_entry
    from trading_system.strategies import direction_double_bottom as dm,autonomous_double_bottom as am
    from trading_system import wave_hierarchy as wm
    config=json.loads((out/'frozen-baseline/config.json').read_text(encoding='utf-8'))
    calendar=json.loads((out/'frozen-baseline/calendar.json').read_text(encoding='utf-8'))['open_dates']
    queries=defaultdict(set)
    for d in differences:queries[d['symbol']].add(d['plan_date'])
    method=entry_method(dm,wm,None);upper=FrozenUpper(events);result=[]
    for symbol,dates in sorted(queries.items()):
        s=bind_entry(am.AutonomousDoubleBottom(config['strategies'][0]['id'],config['strategies'][0]['params']),method,upper)
        s.set_calendar(calendar);s.set_context(dict(allow_same_level=False,allow_cycle_upgrade=False,lower_histories={}))
        history=[];begun=False;latest=None
        for b in histories[symbol]:
            if b.date>max(dates):break
            if b.date>='20251009' and not begun:s.begin_evaluation('20251009');begun=True
            history.append(b);new,observed=s.on_close(history,ends)
            for e in observed:
                if e['event']=='wave_correction_classified':latest=copy.deepcopy(e)
            if b.date not in dates:continue
            m=s.wave_models.get(symbol);entry=dict(symbol=symbol,date=b.date,
                baseline_intents=[i.setup_id for i in new],baseline_events=observed,
                phase=m.phase if m else None,latest_observed_classification=copy.deepcopy(latest))
            if m and m.reference and m.seed is not None:
                bs=adjusted(history);ref=m.reference
                peak=max(range(m.seed,len(bs)),key=lambda i:(bs[i].high,i))
                width=bs[peak].high-min(x.low for x in bs[peak+1:]) if peak<len(bs)-1 else 0
                duration=len(bs)-1-peak;rd=ref['correction_duration'];rp=bs[ref['b']].high-bs[ref['c']].low
                entry.update(reference_owner=ref['owner_id'],reference_duration=rd,reference_range=rp,
                    current_peak=bs[peak].date,current_duration=duration,current_range=width,
                    current_scale=wm.correction_level(duration,width,rd,rp),
                    core_ledger=copy.deepcopy(m.ledger.get(ref['owner_id'])))
            expected=[p['setup_id'] for p in plans['baseline'].values() if p['symbol']==symbol and p['date']==b.date]
            assert all(sid in entry['baseline_intents'] for sid in expected)
            result.append(entry)
    dump(out/'excluded-baseline-context.json',result)

def plot_examples(out,cases,members):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans']
    chosen=[]
    for vid in ('E01','E02','E03','E06','baseline'):
        matches=[m for m in members if m['variant']==vid and m['role'] in ('restored','control')]
        if matches and matches[0]['case_id'] not in chosen:chosen.append(matches[0]['case_id'])
    holding=[m for m in members if m['variant']=='holding_baseline_rejected']
    if holding:chosen.append(holding[0]['case_id'])
    for cid in chosen:
        c=next(c for c in cases if c['case_id']==cid);fig,axes=plt.subplots(3,1,figsize=(16,12))
        fig.suptitle(cid+' '+c['symbol']+' 截至 '+c['as_of']+'（不含后来行情）')
        for ax,p in zip(axes,c['panels']):
            bs=p['bars']
            for i,b in enumerate(bs):
                color='#c75454' if b['c']>=b['o'] else '#45927c';ax.vlines(i,b['l'],b['h'],color=color,lw=.8)
                ax.add_patch(Rectangle((i-.3,min(b['o'],b['c'])),.6,max(.005,abs(b['o']-b['c'])),color=color))
            line=p['line'];ax.plot([x['i'] for x in line],[x['y'] for x in line],color='#2a58b7',lw=2)
            for x in line:ax.annotate(x['label']+' '+x['date'],(x['i'],x['y']),xytext=(2,10),textcoords='offset points',fontsize=8)
            for level in p['levels']:ax.axhline(level['y'],color='#a47927',ls='--',label=level['label']+' '+str(round(level['y'],3)))
            for m in p.get('marks',[]):
                indices=[i for i,b in enumerate(bs) if b['date']==m['date']]
                if indices:ax.axvline(indices[0],color='#83739e',ls=':',label=m['label']+' '+m['date'])
            ticks=list(range(0,len(bs),max(1,len(bs)//8)));ax.set_xticks(ticks,[bs[i]['date'] for i in ticks]);ax.grid(alpha=.2);ax.set_title(p['cycle'])
            if p['levels'] or p.get('marks'):ax.legend(fontsize=8,loc='upper left')
        fig.tight_layout();fig.savefig(out/(cid+'-asof.png'),dpi=120);plt.close(fig)

if __name__=='__main__':main(sys.argv[1])
