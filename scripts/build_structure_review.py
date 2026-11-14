"""Frozen, outcome-blind review pack; selection strata are NOT reference labels."""
import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted, weekly
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom
from trading_system.universe import MainboardUniverse


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    with path.open(encoding='utf-8-sig') as stream:
        yield from csv.DictReader(stream)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(snapshot, output, seed=20261009):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    if output.exists():
        raise ValueError('Review pack must be new; do not overwrite a locked sample')
    cal = read(snapshot/'calendar.json')
    universe_data = read(snapshot/'universe.json')
    universe = MainboardUniverse(universe_data['stocks'], universe_data['st_by_date'])
    traded = {r['symbol'] for r in rows(snapshot/'trades.csv')}
    # Also exclude the two winners removed by v5.6, not just surviving trades.
    old = snapshot.parent/'20261008-091700-mainboard-double_bottom_v5_5-structure'
    if old.exists():
        traded.update(r['symbol'] for r in rows(old/'trades.csv'))
    rng = random.Random(seed)
    pool = []
    ends = sorted(cal['week_ends'])
    week_ends = set(ends)
    week_index = {day: i for i, day in enumerate(ends)}
    for r in rows(snapshot/'decisions.csv'):
        if r['event'] not in ('upper_direction_confirmed', 'weekly_reversal_candidate') or r['symbol'] in traded:
            continue
        if r['event'] == 'upper_direction_confirmed':
            pool.append(dict(symbol=r['symbol'], as_of=r['date'], stratum='legacy_confirmed'))
        else:
            index = week_index[r.get('direction_bar') or r['date']]+4
            if index < len(ends):
                pool.append(dict(symbol=r['symbol'], as_of=ends[index], stratum='candidate_plus_four_weeks'))
    eligible_stocks = sorted(r['ts_code'] for r in universe_data['stocks']
                             if r['ts_code'] not in traded and r['list_date'] < '20230103')
    rng.shuffle(eligible_stocks)
    review_weeks = [d for d in ends if '20251009' <= d <= '20260930']
    for symbol in eligible_stocks:
        day = rng.choice(review_weeks)
        if universe.eligible(symbol, day):
            pool.append(dict(symbol=symbol, as_of=day, stratum='random_stock_week'))
    rng.shuffle(pool)
    selected, used = [], set()
    for stratum in ('legacy_confirmed', 'candidate_plus_four_weeks', 'random_stock_week'):
        for case in pool:
            if case['stratum'] != stratum or case['symbol'] in used or not universe.eligible(case['symbol'], case['as_of']):
                continue
            selected.append(case)
            used.add(case['symbol'])
            if sum(c['stratum'] == stratum for c in selected) == 8:
                break
    if len(selected) != 24:
        raise ValueError('Insufficient eligible stock-week cases')
    histories = {c['symbol']: [] for c in selected}
    for r in rows(snapshot/'bars.csv'):
        if r['symbol'] in histories:
            histories[r['symbol']].append(Bar(r['symbol'], r['date'], *[
                float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume', 'factor', 'up_limit', 'down_limit')]))
    for case in selected:
        bars = [b for b in histories[case['symbol']] if b.date <= case['as_of']]
        if not bars:
            raise ValueError('No observed history for selected case')
        case['predictions'] = {}
        for mode in ('legacy', 'structured'):
            strategy = DirectionDoubleBottom('review_'+mode, dict(
                lower_cycle='daily_nested', structure_mode='hierarchy',
                exit_mode='active_correction', entry_lifecycle='fresh', retest_mode=mode))
            strategy.set_calendar(cal['open_dates'])
            found = []
            for i in range(len(bars)):
                _, events = strategy.on_close(bars[:i+1], week_ends)
                found.extend(e for e in events if e['event'] == 'upper_direction_confirmed')
            state = strategy.states.get(case['symbol'], {})
            active = state.get('direction') == 'long'
            case['predictions'][mode] = dict(
                double_bottom=bool(active or state.get('pending')),
                retest=active, confirmed_date=state.get('confirmed_date') if active else None,
                source=state.get('direction_source'),
                status='confirmed_direction' if active else 'pending_candidate' if state.get('pending') else 'inactive_or_absent',
                historical_confirmations=found,
                confirmation=found[-1] if active and found else None)
        case['bars'] = bars
    # Repeats test within-reviewer consistency; they are not additional unique observations.
    all_cases = [dict(c, internal_id=i) for i, c in enumerate(selected)]
    all_cases += [dict(selected[i], internal_id=i, is_repeat=True) for i in rng.sample(range(24), 4)]
    rng.shuffle(all_cases)
    output.mkdir(parents=True)
    (output/'charts').mkdir()
    primary_ids = {c['internal_id']: f'R{i+1:02d}' for i, c in enumerate(all_cases) if not c.get('is_repeat')}
    private, predictions, public = [], {}, []; hover = {}
    for i, case in enumerate(all_cases):
        identity = f'R{i+1:02d}'
        bars = adjusted(case['bars'])
        weeks = weekly(bars, week_ends)
        fig, axes = plt.subplots(2, 1, figsize=(15, 9), gridspec_kw={'height_ratios': [2, 1]})
        for ax, view, title in ((axes[0], weeks, 'Weekly, all available history'),
                                (axes[1], bars[-80:], 'Daily, latest 80 observed sessions')):
            for index, b in enumerate(view):
                color = '#b94141' if b.close >= b.open else '#21846b'
                ax.vlines(index, b.low, b.high, color=color, linewidth=.7)
                ax.add_patch(Rectangle((index-.3, min(b.open, b.close)), .6,
                                      max(abs(b.close-b.open), .003), facecolor=color))
            ticks = list(range(0, len(view), max(1, len(view)//10)))
            ax.set_xticks(ticks, [view[j].date for j in ticks], rotation=35, fontsize=8)
            ax.set_title(title, fontsize=11)
            ax.grid(alpha=.15)
        fig.suptitle(identity+' | observed through '+case['as_of']+' | no future candles', fontsize=14)
        fig.tight_layout()
        fig.canvas.draw()
        hover[identity] = []
        for ax, view, kind in ((axes[0], weeks, 'weekly'), (axes[1], bars[-80:], 'daily')):
            box = ax.get_position()
            hover[identity].append(dict(kind=kind, bounds=dict(left=box.x0*1000, right=box.x1*1000, top=(1-box.y1)*1000, bottom=(1-box.y0)*1000), xlim=list(ax.get_xlim()), ylim=list(ax.get_ylim()), bars=[dict(date=b.date, open=b.open, high=b.high, low=b.low, close=b.close) for b in view]))
        filename = 'charts/'+identity+'.png'
        fig.savefig(output/filename, dpi=110)
        plt.close(fig)
        public.append(dict(id=identity, as_of=case['as_of'], image=filename))
        item = dict(id=identity, symbol=case['symbol'], as_of=case['as_of'], stratum=case['stratum'],
                    first_observed=case['bars'][0].date,
                    last_observed=case['bars'][-1].date,
                    weeks=len(weeks), repeat_of=primary_ids[case['internal_id']] if case.get('is_repeat') else None)
        private.append(item)
        predictions[identity] = case['predictions']
    identity_hash = hashlib.sha256(json.dumps(private, sort_keys=True).encode()).hexdigest()[:12]
    pack_id = 'structure-review-'+str(seed)+'-'+identity_hash
    write = lambda name, value: (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    write('cases-private.json', private)
    write('predictions-private.json', predictions)
    write('labels-template.json', dict(pack_id=pack_id, reviewer='', labels=[dict(
        id=c['id'], double_bottom='', retest='', confirmed_date='', notes='') for c in public]))
    shutil.copy2(snapshot/'calendar.json', output/'calendar.json')
    page = REVIEW_HTML.replace('__PACK_ID__', pack_id).replace('__CASES__', json.dumps(public)).replace('__CHART_META__', json.dumps(hover))
    (output/'review.html').write_text(page, encoding='utf-8')
    (output/'assets').mkdir()
    for name in ('review-state.js', 'review-app.js'):
        shutil.copy2(Path(__file__).parent/name, output/'assets'/name)
    source_root = Path(__file__).resolve().parents[1]
    shutil.copytree(source_root/'src', output/'source/src', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(source_root/'tests', output/'source/tests', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(source_root/'configs', output/'source/configs')
    for name in ('build_structure_review.py', 'score_structure_review.py', 'structure_review_metrics.py'):
        shutil.copy2(source_root/'scripts'/name, output/'source'/name)
    locked = ['cases-private.json', 'predictions-private.json', 'calendar.json', 'review.html', 'assets/review-state.js', 'assets/review-app.js']
    locked += [c['image'] for c in public]
    write('manifest.json', dict(pack_id=pack_id, seed=seed, primary_cases=24, repeats=4,
        strata=dict(Counter(c['stratum'] for c in selected)), snapshot=str(snapshot.resolve()),
        status='awaiting_independent_reference_labels', untouched_holdout=False,
        excluded_previously_traded_symbols=sorted(traded),
        price_snapshot_sha256=read(snapshot/'manifest.json')['bars_sha256'],
        file_hashes={name: sha(output/name) for name in locked},
        protocol=['No labels invented by the algorithm or derived from profitability.',
                  'Two independent reviewers; disagreement and unclear cases excluded from consensus scoring.',
                  'Repeated cases are scored for consistency, never counted twice in confusion matrices.',
                  'Known research snapshot: only an identification audit, not independent profitability evidence.',
                  'No thresholds adjusted after labels; no automatic production promotion.',
                  'Untouched future data must be acquired and frozen before a later holdout evaluation.']))
    print(json.dumps(dict(output=str(output), primary_cases=24, repeats=4,
                          status='awaiting_independent_reference_labels'), ensure_ascii=False), flush=True)


REVIEW_HTML = '''<!doctype html><meta charset="utf-8"><title>结构盲审</title>
<style>body{font-family:system-ui;max-width:1250px;margin:24px auto;line-height:1.7;background:#f5f7fa}header,article{background:white;padding:20px;margin:18px 0;border-radius:8px}header{position:sticky;top:0;z-index:2;border:1px solid #ddd}img{width:100%;cursor:zoom-in}label{display:inline-block;margin:8px}select,input,button,textarea{font:inherit;padding:7px}textarea{width:90%}.row{display:flex;flex-wrap:wrap}button{cursor:pointer}</style>
<header><b>结构识别盲审</b>　审核者：<input id="reviewer" placeholder="独立审核者名称"> <button id="export">导出标注JSON</button> <span id="progress"></span></header>
<article><p>只看截至图示日期已经发生的走势。图中不展示股票名称、算法标线、买卖或盈亏；现有数据已用于研究，不能当作独立保留样本。请先标注，不打开同目录的private文件。</p>
<p>① 当时是否存在仍有效的周线双底方向候选或已确认的双底方向？② 该双底突破后的回踩，是否已形成有效调整并恢复、足以确认方向？尚未恢复或尚未突破选“否”，无法稳定识别选“不确定”。横向整理不要求触及颈线；不要为了凑W形连接不属于同一结构级别的低点。</p>
<p>确认日期可选填你认为当时首次具备确认条件的交易日。周K标签是该周最后交易日。审核后再比较算法，审核者之间应独立作答。标注只用于验证识别，不是交易系统中的人工阶段指令。</p>
<p>页面只在当前浏览器本地保存；请导出JSON留存。不同审核者应使用不同浏览器配置或修改审核者名称。点击图形可打开原尺寸。</p></article><main id="cases"></main>
<script>const pack="__PACK_ID__";const cases=__CASES__;const REVIEW_MODE="blind";const chartMeta=__CHART_META__;</script>
<script src="assets/review-state.js"></script>
<script src="assets/review-app.js"></script>
<style>
.chart-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}.chart-tools button.active{background:#dce9fc;border-color:#3465ae}.chart-scroll{overflow:auto;border:1px solid #b6c1cc;background:white;max-height:1000px}.chart-stage{position:relative;width:100%;line-height:0}.chart-stage img{display:block;width:100%;cursor:crosshair}.chart-overlay{position:absolute;inset:0;width:100%;height:100%;touch-action:none;cursor:crosshair}.guide{stroke:#1763b0;stroke-width:1.4;vector-effect:non-scaling-stroke}.cross{stroke:#495866;stroke-width:1;stroke-dasharray:5 4;vector-effect:non-scaling-stroke}.drawing-hint{font-size:13px;color:#4c5966;line-height:1.6}
</style>
<script>
(function(){
const ns='http://www.w3.org/2000/svg';
function line(svg,a,b,cls){const e=document.createElementNS(ns,'line');e.setAttribute('x1',a.x);e.setAttribute('y1',a.y);e.setAttribute('x2',b.x);e.setAttribute('y2',b.y);e.setAttribute('class',cls);svg.append(e);return e}
for(const image of document.querySelectorAll('#cases img')){
 const article=image.closest('article'),id=article.querySelector('h2').textContent.split(' · ')[0];
 const original=image.parentElement,scroll=document.createElement('div'),stage=document.createElement('div'),svg=document.createElementNS(ns,'svg');
 scroll.className='chart-scroll';stage.className='chart-stage';svg.classList.add('chart-overlay');svg.setAttribute('viewBox','0 0 1000 1000');svg.setAttribute('preserveAspectRatio','none');
 original.replaceWith(scroll);scroll.append(stage);stage.append(image,svg);
 const tools=document.createElement('div');tools.className='chart-tools';tools.innerHTML='<button data-mode="cross">十字线</button><button data-mode="horizontal">画水平线</button><button data-mode="segment">两点画斜线</button><button data-action="undo">撤销</button><button data-action="clear">清空辅助线</button><label>放大 <select><option value="100">100%</option><option value="150">150%</option><option value="200">200%</option></select></label><button data-action="original">打开原图</button>';
 scroll.before(tools);const hint=document.createElement('p');hint.className='drawing-hint';hint.textContent='水平线：点击位置。斜线：依次点击两个端点。放大后可横向滚动；这些线由你手动绘制，不代表算法判断。';tools.after(hint);
 let mode='cross',first=null,marks=[];const key=pack+':guides:'+id;
 try{marks=JSON.parse(localStorage.getItem(key)||'[]')}catch(e){}
 const h=line(svg,{x:0,y:0},{x:1000,y:0},'cross'),v=line(svg,{x:0,y:0},{x:0,y:1000},'cross');h.style.display=v.style.display='none';
 function save(){try{localStorage.setItem(key,JSON.stringify(marks))}catch(e){}}
 function render(){svg.querySelectorAll('.guide').forEach(e=>e.remove());for(const mark of marks)line(svg,mark.a,mark.b,'guide');tools.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode))}
 function point(e){const r=svg.getBoundingClientRect();return{x:Math.max(0,Math.min(1000,(e.clientX-r.left)/r.width*1000)),y:Math.max(0,Math.min(1000,(e.clientY-r.top)/r.height*1000))}}
 const readout=document.createElement('div');readout.className='candle-readout';readout.setAttribute('role','status');readout.textContent='把十字线移到K线区域，显示日期和价格。';tools.after(readout);const tip=document.createElement('div');tip.className='candle-tip';tip.hidden=true;stage.append(tip);
 svg.addEventListener('pointermove',e=>{const p=point(e),result=candleAt(p,chartMeta[id]);if(!result){h.style.display=v.style.display='none';tip.hidden=true;return}const b=result.bounds,c=result.candle;h.style.display=v.style.display='';h.setAttribute('x1',b.left);h.setAttribute('x2',b.right);h.setAttribute('y1',p.y);h.setAttribute('y2',p.y);v.setAttribute('y1',b.top);v.setAttribute('y2',b.bottom);v.setAttribute('x1',result.x);v.setAttribute('x2',result.x);const date=c.date.slice(0,4)+'-'+c.date.slice(4,6)+'-'+c.date.slice(6,8);const info=(result.panel==='weekly'?'周线 ':'日线 ')+date+' · 开 '+c.open.toFixed(3)+' 高 '+c.high.toFixed(3)+' 低 '+c.low.toFixed(3)+' 收 '+c.close.toFixed(3)+' · 光标价 '+result.cursorPrice.toFixed(3);readout.textContent=info;tip.textContent=info;tip.hidden=false;tip.style.left=p.x/10+'%';tip.style.top=p.y/10+'%';tip.style.transform=p.x>650?'translate(calc(-100% - 12px),calc(-100% - 8px))':'translate(12px,calc(-100% - 8px))'});
 svg.addEventListener('pointerleave',()=>{h.style.display=v.style.display='none';tip.hidden=true});
 svg.addEventListener('click',e=>{const p=point(e);if(mode==='horizontal')marks.push({a:{x:0,y:p.y},b:{x:1000,y:p.y}});else if(mode==='segment'){if(!first){first=p;hint.textContent='已选第一个端点，请点击第二个端点。';return}marks.push({a:first,b:p});first=null;hint.textContent='斜线已添加，可以继续选择两个端点。'}else return;save();render()});
 tools.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.mode){mode=b.dataset.mode;first=null;render()}else if(b.dataset.action==='undo'){marks.pop();save();render()}else if(b.dataset.action==='clear'){marks=[];first=null;save();render()}else if(b.dataset.action==='original')window.open(image.getAttribute('src'),'_blank')});
 tools.querySelector('select').addEventListener('change',e=>{stage.style.width=e.target.value+'%'});render();
}
})();
</script>
'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int, default=20261009)
    args = parser.parse_args()
    main(args.snapshot, args.output, args.seed)
