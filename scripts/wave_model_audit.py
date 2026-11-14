"""Audit existing pivots and interval containment; not a new trading model."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.analysis import adjusted,weekly,week_key
from trading_system.structure import swings,n_structure,rhythm


def node_rows(bars,points,scale,daily=None):
    result=[]
    for p in points:
        occurred=bars[p.index].date
        if daily is not None:
            # Weekly OHLC timestamp is the session end, not the extreme's date.
            group=[b for b in daily if week_key(b.date)==week_key(occurred)]
            matches=[b for b in group if abs(getattr(b,'low' if p.kind=='low' else 'high')-p.price)<1e-7]
            if matches:occurred=matches[-1].date
        result.append(dict(id=f'{scale}:{p.kind}:{occurred}',scale=scale,kind=p.kind,
                           date=occurred,bar_date=bars[p.index].date,
                           confirmed=bars[p.confirmed].date,price=p.price))
    return result


def legs(nodes):
    return [dict(id=a['id']+'>'+b['id'],scale=a['scale'],start=a['date'],end=b['date'],
                 confirmed=max(a['confirmed'],b['confirmed']),from_price=a['price'],to_price=b['price'])
            for a,b in zip(nodes,nodes[1:])]


def containment(children,parents):
    result=[]
    for child in children:
        matches=[p['id'] for p in parents if p['start']<=child['start']<child['end']<=p['end']]
        result.append(dict(child=child['id'],parent=matches[0] if len(matches)==1 else None,
                           relation='interval_only' if len(matches)==1 else 'unassigned',
                           semantic_parent_proven=False))
    return result


def candidate_rows(bars,points):
    result=[]
    for a,b,c in zip(points,points[1:],points[2:]):
        if (a.kind,b.kind,c.kind)!=('low','high','low'):continue
        impulse=b.price-a.price;duration=c.index-b.index
        drop=b.price-c.price;span=max(x.high for x in bars[b.index:c.index+1])-min(x.low for x in bars[b.index:c.index+1])
        reason='qualified'
        if c.price<=a.price or b.price<=c.price:reason='geometry'
        elif duration<3:reason='duration_below_three'
        elif duration>b.index-a.index:reason='correction_longer_than_impulse'
        elif drop/duration>=impulse/(b.index-a.index):reason='correction_too_fast'
        elif span>=impulse:reason='correction_span_too_large'
        elif min(x.low for x in bars[c.index:])<c.price:reason='floor_broken'
        elif max(x.high for x in bars[c.index:])>=c.price+impulse:reason='projection_consumed'
        result.append(dict(id=':'.join(bars[p.index].date for p in (a,b,c)),
            a=bars[a.index].date,b=bars[b.index].date,c=bars[c.index].date,
            a_price=a.price,b_price=b.price,c_price=c.price,confirmed=bars[c.confirmed].date,
            duration=duration,range=drop,impulse=impulse,reason=reason,
            target=c.price+impulse,floor=c.price))
    return result


def snapshot(raw,ends):
    bars=adjusted(raw);weeks=weekly(bars,ends)
    dp=swings(bars,2,2);sp=swings(bars,1,1);wp=swings(weeks,2,2)
    nodes={'weekly':node_rows(weeks,wp,'weekly',bars),
           'daily':node_rows(bars,dp,'daily'),
           'daily_nested_proxy':node_rows(bars,sp,'daily_nested_proxy')}
    wave_legs={k:legs(v) for k,v in nodes.items()}
    relations=containment(wave_legs['daily'],wave_legs['weekly'])
    relations+=containment(wave_legs['daily_nested_proxy'],wave_legs['daily'])
    candidates=candidate_rows(bars,dp)
    legacy,legacy_reason=n_structure(bars,points=dp)
    latest,latest_reason=n_structure(bars,points=dp,ownership=True)
    def describe(core,reason):
        if not core:return dict(core=None,reason=reason,small=None)
        small,small_reason=rhythm(bars,core,points=sp,planned=True,ownership=True)
        return dict(core={k:bars[core[k]].date for k in ('a','b','c')}|
                    dict(target=core['target'],floor=core['correction_low'],confirmed=bars[core['confirmed']].date),
                    reason=reason,small=small,small_reason=small_reason)
    nested=[]
    if legacy and not latest:
        base_range=bars[legacy['b']].high-bars[legacy['c']].low
        for candidate in candidates:
            if candidate['c']<=bars[legacy['c']].date:continue
            nested.append(dict(candidate_id=candidate['id'],reason=candidate['reason'],
                duration_ratio=candidate['duration']/legacy['correction_duration'],
                range_ratio=candidate['range']/base_range,
                smaller_in_both=candidate['duration']<legacy['correction_duration'] and 0<candidate['range']<base_range))
    return dict(as_of=raw[-1].date,factor=raw[-1].factor,nodes=nodes,legs=wave_legs,
        relations=relations,candidates=candidates,legacy=describe(legacy,legacy_reason),
        latest=describe(latest,latest_reason),later_corrections=nested,
        candles={k:[dict(date=b.date,open=b.open,high=b.high,low=b.low,close=b.close)
                    for b in series[-260:]] for k,series in (('daily',bars),('weekly',weeks))})
