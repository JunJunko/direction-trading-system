"""Inspect annotated feedback without treating it as independent ground truth."""
import argparse
import hashlib
import html
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from trading_system.domain import Bar
from trading_system.structure import structured_retest


def main(pack, labels_path, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    read = lambda path: json.loads(path.read_text(encoding='utf-8-sig'))
    labels_file = read(labels_path)
    manifest = read(pack / 'manifest.json')
    if labels_file['pack_id'] != manifest['pack_id']:
        raise ValueError('Feedback belongs to a different pack')
    cases = read(pack / 'cases-private.json')
    predictions = read(pack / 'predictions-private.json')
    hover = read(pack / 'chart-hover-data.json')
    labels = {x['id']: x for x in labels_file['labels']}
    if len(labels) != len(labels_file['labels']):
        raise ValueError('Duplicate review IDs')
    if set(labels) - {x['id'] for x in cases}:
        raise ValueError('Unknown review IDs')
    output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(labels_path, output / 'feedback-original.json')
    records = []
    page = ['<meta charset="utf-8"><title>回踩逐案核对</title>',
            '<style>body{font:16px sans-serif;max-width:1400px;margin:24px auto}img{width:100%}article{border-top:1px solid #aaa;padding:20px 0}pre{white-space:pre-wrap}</style>',
            '<h1>回踩逐案核对</h1><p>保留原始审核；不将算法标线审核当作独立正确答案。蓝线为颈线；橙色为确认前调整区间；绿色为历史方向确认日。图形仅使用截至审核日的已完成周线。</p>']
    for case in cases:
        identity = case['id']
        model = predictions[identity]['structured']
        source, confirmation = model['source'], model['confirmation']
        bars = [Bar(case['symbol'], b['date'], b['open'], b['high'], b['low'], b['close'], 0)
                for b in hover[identity][0]['bars']]
        dates = {b.date: i for i, b in enumerate(bars)}
        record = dict(case=case, feedback=labels.get(identity), frozen_prediction=model,
                      status='confirmed_direction' if model['retest'] else
                             'pending_candidate' if model['double_bottom'] else 'inactive_or_absent')
        fig, ax = plt.subplots(figsize=(14, 5))
        begin = max(0, dates[source['second_date']] - 6) if source else max(0, len(bars)-35)
        for i in range(begin, len(bars)):
            b = bars[i]
            color = '#b94141' if b.close >= b.open else '#21846b'
            ax.vlines(i, b.low, b.high, color=color)
            ax.add_patch(Rectangle((i-.3, min(b.open,b.close)), .6,
                                  max(abs(b.close-b.open), .002), color=color))
        if source:
            neck_index = max(range(dates[source['first_date']]+1, dates[source['second_date']]),
                             key=lambda i: bars[i].high)
            neck = bars[neck_index].high
            ax.axhline(neck, color='blue', label='Neckline')
            ax.axvline(dates[source['breakout_date']], color='blue', linestyle=':', label='First breakout')
            pending = dict(source, neckline=neck, bottom=min(bars[dates[source['first_date']]].low,
                                                            bars[dates[source['second_date']]].low))
            boundary_events=[]
            for end in range(pending['breakout_index']+1,len(bars)):
                if bars[end].low<pending['bottom'] or bars[end].close<neck*.975:
                    boundary_events.append(dict(date=bars[end].date,event='invalidated_structure'))
                    break
                result, observation=structured_retest(bars[:end+1],pending,recovery_mode='boundary')
                if result:
                    boundary_events.append(dict(date=bars[end].date,event='confirmed',**result))
                    break
                if observation.get('reason')=='retest_expired':
                    boundary_events.append(dict(date=bars[end].date,event='expired'))
                    break
            record['boundary_candidate_replay']=boundary_events
            if confirmation:
                end = dates[confirmation['direction_bar']]
                recovered, observation = structured_retest(bars[:end+1], pending)
                record['confirmation_recheck'] = dict(result=recovered, observation=observation)
                ax.axvline(end, color='green', label='Historical confirmation '+bars[end].date)
                start = observation.get('retest_start_index')
                if start is not None and start < end:
                    high = max(b.high for b in bars[start:end])
                    ceiling = max(b.close for b in bars[start:end])
                    low = min(b.low for b in bars[start:end])
                    ax.add_patch(Rectangle((start-.5, low), end-start, high-low,
                                          color='orange', alpha=.15))
                    ax.hlines([ceiling, high], start-.5, end+.5, colors=['orange','gray'],
                              linestyles=['--',':'])
                    record['confirmation_boundaries'] = dict(adjustment_high=high,
                        adjustment_closing_high=ceiling, confirmation_close=bars[end].close,
                        exceeds_closing_high=bars[end].close>ceiling,
                        exceeds_wick_high=bars[end].close>high)
            else:
                _, observation = structured_retest(bars, pending)
                record['as_of_diagnostic'] = observation
        if case['repeat_of']:
            other = labels.get(case['repeat_of'])
            own = labels.get(identity)
            record['repeat_disagreements'] = [key for key in ('double_bottom','retest')
                if own and other and own[key] != other[key]]
        ticks = list(range(begin, len(bars), max(1,(len(bars)-begin)//12)))
        ax.set_xticks(ticks, [bars[i].date for i in ticks], rotation=35)
        ax.set_title(identity+' | '+case['symbol']+' | as of '+case['as_of']+' | '+record['status'])
        ax.grid(alpha=.2)
        if source: ax.legend(fontsize=9)
        fig.tight_layout(); fig.savefig(output / (identity+'.png'), dpi=110); plt.close(fig)
        records.append(record)
        details = {k:v for k,v in record.items() if k not in ('frozen_prediction',)}
        page.append('<article><h2>'+identity+'</h2><img src="'+identity+'.png"><pre>'+
                    html.escape(json.dumps(details, ensure_ascii=False, indent=2))+'</pre></article>')
    result = dict(pack_id=manifest['pack_id'], reference_status='annotated_inspection_only',
                  feedback_sha256=hashlib.sha256(labels_path.read_bytes()).hexdigest(),
                  missing=[c['id'] for c in cases if c['id'] not in labels], records=records)
    (output/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'review.html').write_text('\n'.join(page),encoding='utf-8')
    print(json.dumps(dict(cases=len(records),missing=result['missing'],
                         output=str(output)),ensure_ascii=True))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('pack',type=Path);parser.add_argument('labels',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args();main(args.pack,args.labels,args.output)
