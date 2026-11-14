"""Predeclared, outcome-independent event construction and matched diagnostics.

These endpoints are price-path measurements, never executable trade returns.
"""
import hashlib
import math
import random
import statistics
from collections import defaultdict, Counter


FLAGS = ('weekly', 'zone', 'trigger')
FEATURES = ('return20', 'atr_pct', 'log_turnover')


def rank(identity, seed):
    return hashlib.sha256(f'{seed}:{identity}'.encode()).hexdigest()


def event_from_prefix(bars, points, ambiguities, protocol):
    from trading_system.structure import n_structure
    if len(bars) < protocol['minimum_history'] or len(points) < 3:
        return None
    triple = points[-3:]
    if tuple(p.kind for p in triple) != ('low', 'high', 'low'):
        return None
    a, b, c = triple
    if c.confirmed != len(bars)-1:
        return None
    if any(a.index <= x['index'] <= c.index for x in ambiguities):
        return None
    if min(x.low for x in bars[b.index+1:c.index+1]) < c.price:
        return None
    core, _ = n_structure(bars, points=triple)
    if not core:
        return None
    n = protocol['atr_period']
    trs = [max(bars[i].high-bars[i].low, abs(bars[i].high-bars[i-1].close),
               abs(bars[i].low-bars[i-1].close)) for i in range(len(bars)-n, len(bars))]
    atr = sum(trs)/n
    if atr <= 0:
        return None
    close = bars[-1].close
    key = max(x.high for x in bars[-protocol['key_high_lookback']-1:-1])
    turnover = statistics.mean(x.volume*x.close for x in bars[-20:])
    if turnover <= 0:
        return None
    symbol, date = bars[-1].symbol, bars[-1].date
    return dict(event_id=f'{symbol}:{date}', symbol=symbol, date=date,
                exchange=symbol.split('.')[-1], atr=atr, close=close, factor=bars[-1].factor,
                key_high=key, zone=abs(close-key)/atr <= protocol['key_zone_atr'],
                trigger=close > bars[-2].high and bars[-1].low >= bars[-2].low,
                return20=close/bars[-21].close-1, atr_pct=atr/close,
                log_turnover=math.log(turnover),
                a=bars[a.index].date, b=bars[b.index].date, c=bars[c.index].date,
                c_confirmed=date, core_target=core['target'])


def match_events(events, flag, protocol):
    """Only contemporaneous features enter matching; outcomes are not accepted."""
    other = tuple(x for x in FLAGS if x != flag)
    def key(e):
        return (e['date'], e['exchange'], *(e[x] for x in other))
    controls = defaultdict(list)
    treated = []
    for e in events:
        (treated if e[flag] else controls[key(e)]).append(e)
    used = set()
    pairs = []
    for t in sorted(treated, key=lambda e: rank(e['event_id'], protocol['seed'])):
        candidates = []
        for c in controls.get(key(t), ()):
            if c['event_id'] in used or c['symbol'] == t['symbol']:
                continue
            ds = [abs(t[f]-c[f])/protocol['match_calipers'][f] for f in FEATURES]
            if max(ds) <= 1:
                candidates.append((sum(d*d for d in ds), rank(c['event_id'], protocol['seed']), c))
        if candidates:
            distance, _, c = min(candidates, key=lambda x: x[:2])
            used.add(c['event_id'])
            pairs.append(dict(treated=t['event_id'], control=c['event_id'], date=t['date'],
                              treated_symbol=t['symbol'], control_symbol=c['symbol'], distance=distance))
    return pairs


def path_outcome(event, raw_by_date, calendar, horizons):
    """Future factors normalize outcomes only, into the event's fixed price scale."""
    ix = {d:i for i,d in enumerate(calendar)}
    t = ix[event['date']]
    result = {}
    for h in horizons:
        if t+h >= len(calendar):
            result[str(h)] = dict(status='immature', endpoint=None, change_atr=None)
            continue
        day = calendar[t+h]
        end = raw_by_date.get(day)
        if end is None or end.volume <= 0:
            result[str(h)] = dict(status='missing_endpoint', endpoint=day, change_atr=None)
            continue
        future = [raw_by_date[d] for d in calendar[t+1:t+h+1] if d in raw_by_date and raw_by_date[d].volume>0]
        scale = lambda b, field: getattr(b, field)*b.factor/event['factor']
        result[str(h)] = dict(status='observed', endpoint=day,
            change_atr=(scale(end, 'close')-event['close'])/event['atr'],
            mfe_atr=max(0.0, max((scale(b, 'high')-event['close'])/event['atr'] for b in future)),
            mae_atr=min(0.0, min((scale(b, 'low')-event['close'])/event['atr'] for b in future)),
            observed_sessions=len(future), expected_sessions=h)
    return result


def cluster_interval(differences, clusters, seed, repetitions):
    grouped = defaultdict(list)
    for v, c in zip(differences, clusters):
        grouped[c].append(v)
    if len(grouped) < 2:
        return None
    totals = [(sum(v),len(v)) for v in grouped.values()]
    rng = random.Random(seed)
    means=[]
    for _ in range(repetitions):
        sampled=[totals[rng.randrange(len(totals))] for _ in totals]
        means.append(sum(v[0] for v in sampled)/sum(v[1] for v in sampled))
    means.sort()
    return [means[int(.025*(len(means)-1))],means[int(.975*(len(means)-1))]]


def balance(events, pairs):
    by_id={e['event_id']:e for e in events}
    ans={}
    for feature in FEATURES:
        all_values=[e[feature] for e in events]
        sd=statistics.pstdev(all_values) if len(all_values)>1 else 0
        a=[by_id[p['treated']][feature] for p in pairs]
        b=[by_id[p['control']][feature] for p in pairs]
        ans[feature]=dict(treated_mean=statistics.mean(a) if a else None,
            control_mean=statistics.mean(b) if b else None,
            standardized_difference=(statistics.mean(a)-statistics.mean(b))/sd if a and sd else None,
            maximum_absolute_pair_difference=max((abs(x-y) for x,y in zip(a,b)),default=None))
    return ans


def summarize_contrast(events, pairs, outcomes, flag, protocol):
    by_id={e['event_id']:e for e in events}
    h=str(protocol['primary_horizon'])
    complete=[]
    missing=Counter()
    for p in pairs:
        a,b=outcomes[p['treated']][h],outcomes[p['control']][h]
        if a['status']!='observed' or b['status']!='observed':
            missing[a['status']+' / '+b['status']]+=1
        else:
            complete.append((p,a['change_atr']-b['change_atr']))
    ds=[v for _,v in complete]
    months=[p['date'][:6] for p,_ in complete]
    symbols={p[k] for p,_ in complete for k in ('treated_symbol','control_symbol')}
    thresholds=dict(pairs=len(ds)>=protocol['minimum_pairs'],
        symbols=len(symbols)>=protocol['minimum_symbols'],
        months=len(set(months))>=protocol['minimum_month_blocks'])
    pre={}
    for f in FEATURES:
        a=[e[f] for e in events if e[flag]];b=[e[f] for e in events if not e[flag]]
        sd=statistics.pstdev([e[f] for e in events]) if len(events)>1 else 0
        pre[f]=(statistics.mean(a)-statistics.mean(b))/sd if a and b and sd else None
    secondary={}
    for horizon in protocol['horizons']:
        vals=[outcomes[p['treated']][str(horizon)]['change_atr']-outcomes[p['control']][str(horizon)]['change_atr']
              for p in pairs if all(outcomes[p[k]][str(horizon)]['status']=='observed' for k in ('treated','control'))]
        secondary[str(horizon)]=dict(complete_pairs=len(vals),mean_difference=statistics.mean(vals) if vals else None)
    # Missing outcomes have no defensible finite economic bound. Show only an
    # explicitly labelled clipped sensitivity estimand, never an imputed return.
    clipped=sum(max(-10,min(10,outcomes[p['treated']][h]['change_atr']))-
                max(-10,min(10,outcomes[p['control']][h]['change_atr'])) for p,_ in complete)
    m=len(pairs)-len(complete)
    sensitivity=[(clipped-20*m)/len(pairs),(clipped+20*m)/len(pairs)] if pairs else None
    return dict(flag=flag,events=len(events),treated=sum(e[flag] for e in events),
        controls=sum(not e[flag] for e in events),pairs=len(pairs),complete_pairs=len(ds),
        unmatched_treated=sum(e[flag] for e in events)-len(pairs),
        matched_symbols=len(symbols),month_blocks=len(set(months)),coverage_gates=thresholds,
        mean_difference_atr=statistics.mean(ds) if ds else None,
        month_cluster_interval=cluster_interval(ds,months,protocol['seed'],protocol['bootstrap_repetitions']),
        treated_symbol_cluster_interval=cluster_interval(ds,[p['treated_symbol'] for p,_ in complete],
            protocol['seed'],protocol['bootstrap_repetitions']),
        control_symbol_cluster_interval=cluster_interval(ds,[p['control_symbol'] for p,_ in complete],
            protocol['seed'],protocol['bootstrap_repetitions']),
        missing_pairs=dict(missing),clipped_10atr_missing_sensitivity=sensitivity,
        balance_before=pre,balance_after=balance(events,pairs),secondary=secondary,
        conclusion='exploratory_only' if all(thresholds.values()) else 'insufficient_coverage',
        estimand='20-session forward close change / fixed signal ATR; NOT trade PnL',
        causal_claim=False,production_promoted=False)


def simple_protection(base_method):
    """A jointly simplified diagnostic control, not a tuned profit-taking rule."""
    def manage(self, history, position):
        from trading_system.analysis import adjusted
        from trading_system.structure import SwingCache
        exits,events=base_method(self,history,position)
        if exits:
            return exits,events
        bars=adjusted(history)
        cache=SwingCache(self.p['left'],self.p['right'])
        points=cache.get(bars)
        for low in points:
            if low.kind!='low' or bars[low.index].date<=position.entry_date:
                continue
            if low.confirmed>=len(bars) or min(x.low for x in bars[low.index:])<low.price:
                continue
            if any(low.index<=a['index']<=len(bars)-1 for a in cache.ambiguous):
                continue
            if bars[-1].close<=bars[low.index].high:
                continue
            proposed=low.price*(1-self.p['stop_buffer'])
            if proposed>position.stop:
                old=position.stop
                position.stop=proposed
                events.append(self.event(bars[-1],'diagnostic_protection_promoted',
                    setup_id=position.setup_id,old_stop=old,new_stop=proposed,
                    trough_date=bars[low.index].date,confirmed_at=bars[low.confirmed].date))
        return exits,events
    return manage
