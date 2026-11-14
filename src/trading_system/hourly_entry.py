"""Causal hourly execution rhythm inside a separately completed daily core."""
from dataclasses import replace
from .analysis import adjusted
from .domain import Intent
from .structure import rhythm, SwingCache, effective_pressures


def on_hour_close(strategy,history,hour,week_ends):
    s=strategy;b=hour;symbol=b.symbol
    if s.last_hour.get(symbol)==b.date:return [],[]
    if s.last_hour.get(symbol,'')>b.date:raise ValueError('Hourly histories must advance chronologically')
    s.last_hour[symbol]=b.date
    events=[]
    def event(kind,**details):events.append(s.event(b,kind,**details))
    parent=s.hourly_parents.get(symbol)
    state=s.states.get(symbol,{})
    old=s.hourly_opportunities.get(symbol)
    def discard(reason):
        if old:
            s.hourly_opportunities.pop(symbol,None)
            event('entry_plan_invalidated',setup_id=old.setup_id,reason=reason)
    if not history or not parent or state.get('direction')!='long':
        discard('completed_parent_unavailable')
        return [],events
    if parent['known_at']>b.date or history[-1].date+'150000'>b.date:
        raise ValueError('Uncompleted daily parent supplied to hourly entry')
    # Factor changes are known at session open; they do not add a daily candle.
    scale=history[-1].factor/b.factor
    bars=[replace(x,**{k:getattr(x,k)*scale for k in ('open','high','low','close')},factor=b.factor)
          for x in adjusted(history)]
    core=dict(parent['core'])
    for k in ('impulse','correction_area','correction_low','target'):
        if k in core:core[k]*=scale
    owner=core['owner_id']
    known=s.context.get('lower_histories',{}).get(symbol,[])
    lower=[replace(x,**{k:getattr(x,k)*x.factor/b.factor for k in ('open','high','low','close')},factor=b.factor)
           for x in known if x.date<=b.date]
    if not lower or lower[-1].date!=b.date:
        raise ValueError('Hourly callback must include its completed candle')
    # Missing real sessions are never replaced with a daily path.
    sessions={}
    for x in lower:sessions.setdefault(x.date[:8],set()).add(x.date[8:])
    needed={x.date for x in bars[core['c']:]}
    if any(sessions.get(day)!=set(('103000','113000','140000','150000')) for day in needed):
        discard('incomplete_lower_cycle_history')
        event('rhythm_wait',reason='incomplete_lower_cycle_history')
        return [],events
    after_parent=[x for x in lower if x.date>parent['known_at']]
    floor_date=core.get('rhythm_floor_date',bars[core['c']].date)
    daily_floor=next(x.low for x in bars if x.date==floor_date)
    if any(x.low<max(daily_floor,bars[core['c']].low) or x.high>=core['target'] for x in after_parent):
        discard('daily_core_invalidated_intraday')
        event('rhythm_wait',reason='daily_core_invalidated_intraday')
        return [],events
    daily_points=SwingCache(s.p['left'],s.p['right'])
    points=daily_points.get(bars)
    if old:
        if (old.evidence['entry_core_owner']!=owner or
                (old.evidence.get('rhythm_owner')!=core.get('rhythm_owner')
                 and old.evidence['small_c'][:8]<floor_date)):
            discard('core_or_rhythm_owner_changed');old=None
        else:
            old_scale=old.evidence['factor']/b.factor
            evidence=dict(old.evidence,factor=b.factor,rhythm_owner=core.get('rhythm_owner'),
                rhythm_floor_date=floor_date,rhythm_start_date=core.get('rhythm_start_date'))
            for k in ('symmetry_target','pressure_target','correction_area','correction_range','initial_rhythm_floor'):
                if evidence.get(k) is not None:evidence[k]*=old_scale
            trigger=old.trigger*old_scale
            pressures,audit=effective_pressures(bars,points,core,trigger,ambiguities=daily_points.ambiguous)
            target=min([core['target']]+pressures)
            evidence.update(symmetry_target=core['target'],pressure_target=min(pressures) if pressures else None,
                            pressure_audit=audit,parent_known_at=parent['known_at'])
            current=replace(old,trigger=trigger,stop=old.stop*old_scale,target=target,evidence=evidence)
            age=s.calendar_index[b.date[:8]]-s.calendar_index[old.evidence['first_planned_at'][:8]]
            reason=('rhythm_failed' if b.low<=current.stop else 'space_exhausted' if b.high>=target else
                    'trigger_consumed' if b.high>=trigger else 'plan_expired' if age>=s.p['plan_valid_days'] else None)
            if reason:discard(reason);old=None
            else:
                s.hourly_opportunities[symbol]=current
                event('entry_plan_renewed',setup_id=current.setup_id,signal_at=current.date,
                      observed_at=b.date,trigger=trigger,stop=current.stop,target=target)
                return [current],events
    cache=SwingCache(1,1);small_points=cache.get(lower)
    small,reason=rhythm(bars,core,lower_bars=lower,hours_per_day=s.p['hours_per_day'],points=small_points,
                        planned=True,ownership=True)
    if small and any(small['a']<=r['index']<=small['c'] for r in cache.ambiguous):
        small=None;reason='small_structure_order_unknown'
    if not small:
        event('rhythm_wait',reason=reason);return [],events
    identity=f'{s.name}:{symbol}:{owner}:{small["date"]}'
    if identity in s.seen:return [],events
    trigger=small['trigger']*(1+s.p['trigger_buffer'])
    confirmed=small['confirmed_date']
    touched=next((x for x in lower if x.date>=confirmed and x.high>=trigger),None)
    if touched:
        s.seen.add(identity)
        event('rhythm_wait',reason='trigger_consumed_before_plan',setup_id=identity,
              first_touch_date=touched.date,small_confirmed=confirmed)
        return [],events
    stop=small['stop']*(1-s.p['stop_buffer'])
    pressures,audit=effective_pressures(bars,points,core,trigger,ambiguities=daily_points.ambiguous)
    target=min([core['target']]+pressures)
    s.seen.add(identity)
    if not 0<stop<trigger<target or b.high>=target:
        event('structure_space_exhausted',setup_id=identity,trigger=trigger,stop=stop,target=target)
        return [],events
    lookback=bars[-s.p['volatility_lookback']:]
    evidence=dict(entry_core_owner=owner,small_owner=small['owner_id'],upper_owner_id=s.wave_source_ids.get(symbol),
        rhythm_owner=core.get('rhythm_owner'),parent_core_owner=core.get('parent_owner'),
        core_relation=core.get('relation'),core_accepted_at=core.get('accepted_at'),
        rhythm_floor_date=floor_date,rhythm_start_date=core.get('rhythm_start_date'),
        small_a=small['a_date'],small_b=small['b_date'],small_c=small['date'],small_confirmed=confirmed,
        core_a=bars[core['a']].date,core_b=bars[core['b']].date,core_c=bars[core['c']].date,
        core_c_confirmed=bars[core['confirmed']].date,pressure_audit=audit,
        lower_cycle='hourly',rhythm_kind=small['kind'],target_cycle='daily',holding_cycle='daily',
        symmetry_target=core['target'],pressure_target=min(pressures) if pressures else None,
        correction_area=core['correction_area'],correction_duration=core['correction_duration'],
        correction_range=bars[core['b']].high-bars[core['c']].low,factor=b.factor,
        volatility=sum((x.high-x.low)/x.close for x in lookback)/len(lookback),
        direction_confirmed=state['confirmed_date'],direction_first=state.get('direction_source',{}).get('first_date'),
        direction_second=state.get('direction_source',{}).get('second_date'),
        direction_breakout=state.get('direction_source',{}).get('breakout_date'),
        direction_retest_started=state.get('retest_started_date'),
        entry_classification='completed_hourly_rhythm',signal_at=b.date,first_planned_at=b.date,
        parent_known_at=parent['known_at'],initial_risk_source='hourly_c_buffered',initial_rhythm_floor=small['stop'],
        stop_buffer=s.p['stop_buffer'],core_owner=identity,core_scale_duration=core['correction_duration'],
        holding_state='verification')
    if s.p['direction_cycle']=='daily':
        evidence['direction_cycle']='daily'
    intent=Intent(s.name,symbol,b.date,trigger,stop,target,identity,'daily_n_rhythm',evidence)
    s.hourly_opportunities[symbol]=intent
    event('entry_intent',setup_id=identity,trigger=trigger,stop=stop,target=target,**evidence)
    return [intent],events
