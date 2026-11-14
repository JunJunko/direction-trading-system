"""Selected reversal direction -> independent daily N -> smaller N -> shared execution."""
from ..analysis import adjusted, weekly, pivot_lows, WeeklyCache, week_key, AdjustedCache
from dataclasses import replace
from ..domain import Intent, ExitIntent
from ..wave_hierarchy import WaveHierarchy
from ..support import confirmed_trough_zone, support_rebound, support_band_retest
from ..structure import double_bottom, hierarchy_double_bottom, hierarchy_double_bottom_candidates, retest_confirmation, structured_retest, n_structure, rhythm, swings, area, SwingCache, active_correction, correction_measure, effective_pressures


class DirectionDoubleBottom:
    def __init__(self,name,params):
        self.name=name
        self.p=dict(direction_cycle='weekly',direction_retest_min=None,direction_retest_max=None,
                    left=2,right=2,bottom_tolerance=.06,stop_buffer=.005,
                    trigger_buffer=.001,retest_tolerance=.025,weekly_retest_min=3,
                    weekly_retest_max=14,volatility_lookback=20,lower_cycle='hourly',hours_per_day=4,
                    plan_valid_days=5,structure_mode='legacy',exit_mode='legacy',entry_lifecycle='legacy',retest_mode='legacy',candidate_mode='single',core_mode='legacy',
                    support_tighten=False,support_mode='none',support_max_entry_risk=.02,entry_mode='breakout',
                    support_band_atr_lookback=14,support_band_atr_fraction=.15,support_band_max_width=.005)
        if set(params)-set(self.p):
            raise ValueError('Unknown direction-double-bottom parameters')
        self.p.update(params)
        if self.p['entry_mode'] not in ('breakout','support_rebound','support_band_retest'):
            raise ValueError('Invalid entry_mode')
        if self.p['entry_mode']!='breakout' and self.p['support_mode']!='confirmed_trough':
            raise ValueError('Support rebound requires a confirmed support zone')
        if self.p['support_mode'] not in ('none','confirmed_trough'):
            raise ValueError('Invalid support_mode')
        if self.p['support_mode']=='confirmed_trough' and (
                self.p['lower_cycle']!='daily_nested' or self.p['core_mode']!='nested' or
                self.p['structure_mode']!='hierarchy' or self.p['entry_lifecycle']!='fresh' or
                self.p['stop_buffer']!=0):
            raise ValueError('Support-zone experiment requires nested daily proxy, fresh hierarchy and zero stop buffer')
        if self.p['direction_cycle'] not in ('weekly','daily'):
            raise ValueError('direction_cycle must be weekly or daily')
        # Keep old configurations valid; neutral names count selected direction bars.
        for bound in ('min','max'):
            key='direction_retest_'+bound
            if self.p[key] is None:
                self.p[key]=self.p['weekly_retest_'+bound]
        if self.p['core_mode'] not in ('legacy','owned','nested'):
            raise ValueError('Invalid core_mode')
        if self.p['candidate_mode'] not in ('single','pool'):
            raise ValueError('Invalid candidate_mode')
        if self.p['candidate_mode']=='pool' and (self.p['structure_mode']!='hierarchy'
                or self.p['retest_mode'] not in ('structured','boundary')):
            raise ValueError('Candidate pool requires hierarchy and structured retest')
        if self.p['retest_mode'] not in ('legacy','structured','boundary'):
            raise ValueError('Invalid retest_mode')
        if self.p['entry_lifecycle'] not in ('legacy','fresh'):
            raise ValueError('Invalid entry_lifecycle')
        if self.p['structure_mode'] not in ('legacy','hierarchy'):
            raise ValueError('Invalid structure_mode')
        if self.p['exit_mode'] not in ('legacy','active_correction'):
            raise ValueError('Invalid exit_mode')
        if self.p['lower_cycle'] not in ('hourly','daily_nested'):
            raise ValueError('lower_cycle must be hourly or daily_nested')
        for key in ('left','right','weekly_retest_min','weekly_retest_max','direction_retest_min','direction_retest_max','volatility_lookback','hours_per_day','plan_valid_days','support_band_atr_lookback'):
            if type(self.p[key]) is not int or self.p[key]<1:
                raise ValueError(f'{key} must be a positive integer')
        import math
        for key in ('bottom_tolerance','stop_buffer','trigger_buffer','retest_tolerance','support_max_entry_risk','support_band_atr_fraction','support_band_max_width'):
            value=self.p[key]
            if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<1:
                raise ValueError(f'Invalid {key}')
        if self.p['support_max_entry_risk']==0:
            raise ValueError('support_max_entry_risk must be positive')
        if not self.p['support_band_atr_fraction'] or not self.p['support_band_max_width']:
            raise ValueError('Support band width parameters must be positive')
        if self.p['weekly_retest_min']>self.p['weekly_retest_max']:
            raise ValueError('Invalid weekly retest duration')
        if self.p['direction_retest_min']>self.p['direction_retest_max']:
            raise ValueError('Invalid direction retest duration')
        self.states={}
        self.last={}
        self.seen=set()
        self.context={}
        self.week_ends=set()
        self.weekly_caches={}
        self.direction_swings={}
        self.week_ends_ref=None
        self.end_by_week={}
        self.opportunities={}
        self.calendar_index={}
        self.daily_caches={}
        self.core_swings={}
        self.rhythm_swings={}
        self.wave_models={}
        self.wave_source_ids={}
        self.hourly_parents={}
        self.hourly_opportunities={}
        self.last_hour={}

    def begin_evaluation(self,date):
        """Keep confirmed direction and consumed identities, discard warmup orders."""
        if self.p['entry_lifecycle']!='fresh':
            return []
        events=[dict(date=date,symbol=symbol,strategy=self.name,
                     event='entry_plan_invalidated',setup_id=item['intent'].setup_id,
                     reason='warmup_plan_not_executable')
                for symbol,item in sorted(self.opportunities.items())]
        self.opportunities.clear()
        events.extend(dict(date=date,symbol=symbol,strategy=self.name,event='entry_plan_invalidated',
            setup_id=item.setup_id,reason='warmup_plan_not_executable')
            for symbol,item in sorted(self.hourly_opportunities.items()))
        self.hourly_opportunities.clear()
        return events

    def set_calendar(self,calendar):
        self.calendar_index={day:i for i,day in enumerate(calendar)}

    def set_context(self,context):
        self.context=context

    def event(self,b,event,**details):
        if self.p['direction_cycle']=='daily':
            # Preserve the weekly audit schema for existing snapshots.
            if event.startswith('weekly_'):
                event='daily_'+event[len('weekly_'):]
            if 'weekly_retest_bars' in details:
                details['daily_retest_bars']=details.pop('weekly_retest_bars')
            details['direction_cycle']='daily'
        return dict(date=b.date,symbol=b.symbol,strategy=self.name,event=event,**details)

    def advance_candidate_pool(self,b,weeks,state):
        """Observe every layout independently; a pending W never blocks a new W.

        Dates are immutable identities, price levels share the current known
        factor, and a delayed pivot confirmation never creates a backdated order.
        Direction ownership changes only after the existing direction is lost.
        """
        events=[];w=weeks[-1]
        points=self.direction_swings.setdefault(b.symbol,SwingCache(self.p['left'],self.p['right'])).get(weeks)
        if state['direction']=='long' and (w.close<state['floor'] or
                self.top_failure(weeks,points)):
            state['direction']='unknown'
            events.append(self.event(b,'upper_direction_lost',direction_bar=w.date))
        pool=state.setdefault('candidates',[])
        layouts,_=hierarchy_double_bottom_candidates(weeks,self.p['left'],self.p['right'],
                                                    self.p['bottom_tolerance'],allow_delayed=True,points=points)
        for layout in layouts:
            identity=(b.symbol,weeks[layout['first']].date,weeks[layout['second']].date)
            if identity in self.seen:continue
            self.seen.add(identity)
            candidate=dict(layout,breakout_index=layout['first_breakout_index'],retest_start=None,
                first_date=identity[1],second_date=identity[2],
                origin_date=weeks[layout['origin']].date,
                breakout_date=weeks[layout['first_breakout_index']].date,
                first_observed_date=b.date,candidate_id=':'.join(identity))
            pool.append(candidate)
            events.append(self.event(b,'weekly_reversal_candidate',direction_bar=w.date,**candidate))
        remaining=[];confirmed=[]
        for candidate in pool:
            identity=candidate['candidate_id']
            if w.low<candidate['bottom'] or w.close<candidate['neckline']*(1-self.p['retest_tolerance']):
                events.append(self.event(b,'weekly_reversal_invalidated',candidate_id=identity,reason='structure_lost'))
                continue
            confirmation,observed=structured_retest(weeks,candidate,self.p['direction_retest_min'],
                self.p['direction_retest_max'],recovery_mode='boundary' if self.p['retest_mode']=='boundary' else 'local')
            events.append(self.event(b,'weekly_retest_observed',candidate_id=identity,**observed))
            if observed.get('retest_start_index') is not None:
                candidate['retest_start']=observed['retest_start_index']
                if (candidate.get('reported_retest_start')!=candidate['retest_start']
                        and observed.get('declining_closes',0)>=2):
                    candidate['reported_retest_start']=candidate['retest_start']
                    events.append(self.event(b,'weekly_retest_started',candidate_id=identity,
                        direction_bar=w.date,retest_start_date=observed['retest_start_date'],peak_date=observed['peak_date']))
            if observed.get('reason')=='retest_expired':
                events.append(self.event(b,'weekly_reversal_invalidated',candidate_id=identity,reason='retest_expired'))
            elif confirmation:
                confirmed.append((candidate,confirmation))
                events.append(self.event(b,'weekly_layout_confirmed',candidate_id=identity,direction_bar=w.date))
            else:remaining.append(candidate)
        if confirmed and state['direction']!='long':
            # Selection occurs among *confirmed* layouts, not at first detection.
            source,confirmation=max(confirmed,key=lambda pair:pair[0]['pattern_area'])
            state.update(direction='long',floor=confirmation['floor']*(1-self.p['stop_buffer']),
                confirmed_date=b.date,direction_source=dict(source),
                retest_started_date=confirmation['retest_start_date'])
            events.append(self.event(b,'upper_direction_confirmed',direction_bar=w.date,
                floor=state['floor'],weekly_retest_bars=confirmation['correction_duration'],
                retest_kind=confirmation['kind'],candidate_id=source['candidate_id'],
                **{k:confirmation[k] for k in ('peak_date','trough_date','retest_start_date','correction_range','recovery_trigger','recovery_mode')},
                **{k:source[k] for k in ('first_date','second_date','origin_date','breakout_date','first_observed_date')}))
        state['candidates']=remaining
        # Representative is a copy for diagnostics; it never controls the pool.
        state['pending']=dict(max(remaining,key=lambda c:c['pattern_area'])) if remaining else None
        events.append(self.event(b,'weekly_candidate_pool',direction_bar=w.date,
            layout_count=len(layouts),pending_count=len(remaining),confirmed_count=len(confirmed)))
        return events

    def on_close(self,history,week_ends):
        if not history:
            return [],[]
        b=adjusted(history[-1:])[0]
        if self.last.get(b.symbol)==b.date:
            return [],[]
        if self.last.get(b.symbol,'')>b.date:
            raise ValueError('Histories must advance chronologically')
        self.last[b.symbol]=b.date
        self.week_ends=week_ends
        if self.p['direction_cycle']=='daily':
            weeks=self.daily_caches.setdefault(b.symbol,AdjustedCache()).get(history)
        else:
            if self.week_ends_ref is not week_ends:
                self.week_ends_ref=week_ends
                self.end_by_week={week_key(d):d for d in week_ends}
            weeks=self.weekly_caches.setdefault(b.symbol,WeeklyCache()).get(history,self.end_by_week)
        state=self.states.setdefault(b.symbol,dict(direction='unknown',processed='',pending=None,factor=b.factor))
        scale=state['factor']/b.factor
        # A suspended week's last raw factor can differ from today's adjustment
        # anchor. Reset on the actual anchor change, even before this week ends.
        if scale!=1:self.direction_swings.pop(b.symbol,None)
        if state.get('floor'):
            state['floor']*=scale
        pending=state['pending']
        if pending:
            pending['neckline']*=scale
            pending['bottom']*=scale
        for candidate in state.get('candidates',[]):
            for key in ('neckline','bottom','pattern_area','prior_area'):
                candidate[key]*=scale
        state['factor']=b.factor
        events=[]
        if weeks and state['processed']!=weeks[-1].date:
            state['processed']=weeks[-1].date
            w=weeks[-1]
            if self.p['candidate_mode']=='pool':
                events.extend(self.advance_candidate_pool(b,weeks,state))
            elif state['direction']=='long':
                points=swings(weeks,self.p['left'],self.p['right'])
                top=self.top_failure(weeks,points)
                if w.close<state['floor'] or top:
                    state['direction']='unknown'
                    state['pending']=None
                    events.append(self.event(b,'upper_direction_lost',direction_bar=w.date))
            elif pending:
                if w.low<pending['bottom'] or w.close<pending['neckline']*(1-self.p['retest_tolerance']):
                    state['pending']=None
                    events.append(self.event(b,'weekly_reversal_invalidated',reason='structure_lost'))
                else:
                    if self.p['retest_mode'] in ('structured','boundary'):
                        confirmation,observed=structured_retest(weeks,pending,
                            self.p['direction_retest_min'],self.p['direction_retest_max'],
                            recovery_mode='boundary' if self.p['retest_mode']=='boundary' else 'local')
                        events.append(self.event(b,'weekly_retest_observed',**observed))
                        if observed.get('retest_start_index') is not None:
                            if (pending.get('reported_retest_start')!=observed['retest_start_index']
                                    and observed.get('declining_closes',0)>=2):
                                pending['reported_retest_start']=observed['retest_start_index']
                                events.append(self.event(b,'weekly_retest_started',
                                    direction_bar=w.date,retest_start_date=observed['retest_start_date'],
                                    peak_date=observed['peak_date']))
                            pending['retest_start']=observed['retest_start_index']
                            state['retest_started_date']=observed['retest_start_date']
                        if observed.get('reason')=='retest_expired':
                            state['pending']=None
                            events.append(self.event(b,'weekly_reversal_invalidated',reason='retest_expired'))
                        elif confirmation:
                            state.update(direction='long',floor=confirmation['floor']*(1-self.p['stop_buffer']),
                                         confirmed_date=b.date,pending=None)
                            events.append(self.event(b,'upper_direction_confirmed',direction_bar=w.date,
                                floor=state['floor'],weekly_retest_bars=confirmation['correction_duration'],
                                retest_kind=confirmation['kind'],
                                **{k:confirmation[k] for k in ('peak_date','trough_date','retest_start_date','correction_range','recovery_trigger','recovery_mode')},
                                **{k:state.get('direction_source',{}).get(k) for k in ('first_date','second_date','origin_date','breakout_date')}))
                    else:
                        start=pending.get('retest_start')
                        if start is None and len(weeks)-1>pending['breakout_index']:
                            if w.close<=weeks[-2].close or w.high<=weeks[-2].high:
                                start=len(weeks)-1
                                pending['retest_start']=start
                                state['retest_started_date']=b.date
                                events.append(self.event(b,'weekly_retest_started',direction_bar=w.date))
                        if start is not None:
                            length=len(weeks)-1-start
                            earlier=weeks[start:-1]
                            if length>self.p['direction_retest_max']:
                                state['pending']=None
                                events.append(self.event(b,'weekly_reversal_invalidated',reason='retest_expired'))
                            elif length>=self.p['direction_retest_min']:
                                impulse=weeks[pending['breakout_index']].high-pending['bottom']
                                width=max(x.high for x in earlier)-min(x.low for x in earlier)
                                confirmation=(retest_confirmation(weeks,pending,self.p['direction_retest_min'])
                                              if self.p['structure_mode']=='hierarchy' else None)
                                valid=(bool(confirmation) if self.p['structure_mode']=='hierarchy'
                                       else w.close>max(x.high for x in earlier) and width<impulse)
                                if valid:
                                    state['direction']='long'
                                    state['floor']=min(x.low for x in earlier)*(1-self.p['stop_buffer'])
                                    state['confirmed_date']=b.date
                                    state['pending']=None
                                    events.append(self.event(b,'upper_direction_confirmed',direction_bar=w.date,
                                                             floor=state['floor'],weekly_retest_bars=length,
                                                             retest_kind=confirmation['kind'] if confirmation else 'legacy',
                                                             **{k:state.get('direction_source',{}).get(k) for k in ('first_date','second_date','origin_date','breakout_date')}))
            else:
                detector=hierarchy_double_bottom if self.p['structure_mode']=='hierarchy' else double_bottom
                candidate,reason=detector(weeks,self.p['left'],self.p['right'],self.p['bottom_tolerance'])
                if candidate and w.close>candidate['neckline']:
                    identity=(b.symbol,weeks[candidate['first']].date,weeks[candidate['second']].date)
                    if identity not in self.seen:
                        self.seen.add(identity)
                        candidate.update(breakout_index=len(weeks)-1,retest_start=None,
                            first_date=weeks[candidate['first']].date,
                            second_date=weeks[candidate['second']].date,
                            origin_date=weeks[candidate['origin']].date,
                            breakout_date=b.date)
                        state['direction_source']=dict(candidate)
                        state['pending']=candidate
                        events.append(self.event(b,'weekly_reversal_candidate',direction_bar=w.date,**candidate))
                else:
                    events.append(self.event(b,'weekly_structure_wait',reason=reason if not candidate else 'neckline_not_broken'))
        if state['direction']!='long':
            self.opportunities.pop(b.symbol,None)
            self.hourly_parents.pop(b.symbol,None)
            return [],events
        nested=self.p['core_mode']=='nested'
        owned=self.p['core_mode'] in ('owned','nested')
        if owned:
            bars=self.daily_caches.setdefault(b.symbol,AdjustedCache()).get(history)
            points=self.core_swings.setdefault(b.symbol,SwingCache(self.p['left'],self.p['right'])).get(bars)
            if nested:
                upper=state.get('direction_source',{})
                origin=upper.get('second_date')
                upper_owner=upper.get('candidate_id') or ':'.join(str(upper.get(k,'')) for k in ('first_date','second_date','breakout_date'))
                if origin and self.p['direction_cycle']=='weekly':
                    group=[x for x in bars if week_key(x.date)==week_key(origin)]
                    if group:origin=min(group,key=lambda x:(x.low,-int(x.date))).date
                if self.wave_source_ids.get(b.symbol)!=upper_owner:
                    self.wave_models[b.symbol]=WaveHierarchy(self.p['left'],self.p['right'])
                    self.wave_source_ids[b.symbol]=upper_owner
                model=self.wave_models[b.symbol]
                core,reason,wave_events=model.get(bars,origin_date=origin)
                events.extend(self.event(b,e['event'],upper_owner_id=upper_owner,
                    **{k:v for k,v in e.items() if k!='event'}) for e in wave_events)
            else:
                core,reason=n_structure(bars,self.p['left'],self.p['right'],points=points,
                    ownership=True,origin_date=state.get('direction_source',{}).get('second_date'))
            owner=core.get('owner_id') if core else None
            if state.get('core_owner')!=owner:
                events.append(self.event(b,'core_owner_changed',previous_owner=state.get('core_owner'),
                                         owner_id=owner,reason=reason))
                state['core_owner']=owner
            old_plan=self.opportunities.get(b.symbol)
            old_owner=old_plan['intent'].evidence.get('entry_core_owner') if old_plan else None
            rhythm_changed=(nested and old_plan and core and
                old_plan['intent'].evidence.get('rhythm_owner')!=core.get('rhythm_owner'))
            if rhythm_changed and old_owner==owner and old_plan['intent'].evidence['small_c'][:8]>=core['rhythm_floor_date']:
                evidence=dict(old_plan['intent'].evidence,rhythm_owner=core['rhythm_owner'],
                    rhythm_floor_date=core['rhythm_floor_date'],rhythm_start_date=core['rhythm_start_date'])
                old_plan['intent']=replace(old_plan['intent'],evidence=evidence)
                rhythm_changed=False
            if old_plan and (old_owner!=owner or rhythm_changed):
                self.opportunities.pop(b.symbol)
                events.append(self.event(b,'entry_plan_invalidated',setup_id=old_plan['intent'].setup_id,
                                         reason='rhythm_owner_changed' if rhythm_changed else 'core_owner_changed'))
        opportunity=self.opportunities.get(b.symbol)
        if opportunity:
            old=opportunity['intent']
            scale=opportunity['factor']/b.factor
            evidence=dict(old.evidence)
            for key in ('symmetry_target','pressure_target','correction_area','correction_range','support_lower','support_upper','rebound_signal_close','breakout_reference','support_defense_lower','support_defense_upper','support_reference_atr'):
                if evidence.get(key) is not None:
                    evidence[key]*=scale
            if owned:
                evidence['pressure_audit']=[dict(item,price=item['price']*scale)
                                           for item in evidence.get('pressure_audit',[])]
            evidence['factor']=b.factor
            current=replace(old,date=b.date,trigger=old.trigger*scale,stop=old.stop*scale,
                            target=old.target*scale,evidence=evidence)
            opportunity.update(intent=current,factor=b.factor)
            opportunity['age']+=1
            first=old.evidence['first_planned_at']
            if first in self.calendar_index and b.date in self.calendar_index:
                opportunity['age']=self.calendar_index[b.date]-self.calendar_index[first]
            missed=(self.p['entry_lifecycle']=='fresh' and b.high>=current.trigger)
            if b.low<=current.stop or b.high>=current.target or opportunity['age']>=self.p['plan_valid_days'] or missed:
                reason=('rhythm_failed' if b.low<=current.stop else
                        'space_exhausted' if b.high>=current.target else
                        'trigger_consumed' if missed else 'plan_expired')
                self.opportunities.pop(b.symbol)
                events.append(self.event(b,'entry_plan_invalidated',setup_id=current.setup_id,reason=reason))
            else:
                events.append(self.event(b,'entry_plan_renewed',setup_id=current.setup_id,
                                         trigger=current.trigger,stop=current.stop,target=current.target))
                return [current],events
        bars=self.daily_caches.setdefault(b.symbol,AdjustedCache()).get(history)
        points=self.core_swings.setdefault(b.symbol,SwingCache(self.p['left'],self.p['right'])).get(bars)
        if not nested:
            core,reason=n_structure(bars,self.p['left'],self.p['right'],points=points,
                ownership=owned,origin_date=state.get('direction_source',{}).get('second_date') if owned else None)
        if self.context.get('entry_clock')=='hourly':
            # The parent is published only after a completed daily observation.
            # Hourly callbacks cannot advance its pivots or selected direction.
            if core:
                self.hourly_parents[b.symbol]=dict(core=dict(core),known_at=b.date+'150000')
            else:
                self.hourly_parents.pop(b.symbol,None)
            if not core:
                events.append(self.event(b,'core_structure_wait',reason=reason))
            return [],events
        if not core:
            events.append(self.event(b,'core_structure_wait',reason=reason))
            return [],events
        lower=None
        if self.p['lower_cycle']=='hourly':
            known=self.context.get('lower_histories',{}).get(b.symbol,[])
            # Normalize hourly levels to the daily bar's latest known factor.
            lower=[replace(x,**{key:getattr(x,key)*x.factor/b.factor for key in ('open','high','low','close')})
                   for x in known if x.date<=b.date+'150000']
            if not lower or lower[-1].date!=b.date+'150000':
                events.append(self.event(b,'rhythm_wait',reason='missing_current_completed_hourly_session'))
                return [],events
            needed={x.date for x in bars[core['c']:]}
            if not needed<={x.date[:8] for x in lower}:
                events.append(self.event(b,'rhythm_wait',reason='incomplete_lower_cycle_history'))
                return [],events
        smaller=None if lower is not None else self.rhythm_swings.setdefault(b.symbol,SwingCache(1,1)).get(bars)
        small,reason=rhythm(bars,core,lower_bars=lower,hours_per_day=self.p['hours_per_day'],points=smaller,
                            planned=self.p['structure_mode']=='hierarchy',ownership=owned)
        if nested and small:
            # Do not infer the order of a dual-extreme daily/hourly bar. A new
            # fully independent small N after the region may become executable.
            cache=(self.rhythm_swings[b.symbol] if lower is None else None)
            if cache is None:
                cache=SwingCache(1,1);cache.get(lower)
            if any(small['a']<=r['index']<=small['c'] for r in cache.ambiguous):
                small=None;reason='small_structure_order_unknown'
        if not small:
            narrow=bars[core['b']].high-bars[core['c']].low<core['impulse']/3
            if (self.context.get('allow_same_level') and narrow
                    and b.close>bars[core['b']].high and b.close>b.open):
                small=dict(a=core['c'],b=core['b'],c=core['c'],kind='same_level',date=bars[core['c']].date,
                           stop=bars[core['c']].low,trigger=bars[core['b']].high,small_area=core['correction_area'],
                           owner_id=core.get('owner_id'))
            else:
                events.append(self.event(b,'rhythm_wait',reason=reason))
                return [],events
        identity=f'{self.name}:{b.symbol}:{bars[core["a"]].date}:{bars[core["b"]].date}:{small["date"]}'
        if owned:
            identity=f'{self.name}:{b.symbol}:{core["owner_id"]}:{small["date"]}'
        if identity in self.seen:
            return [],events
        rebound=None
        breakout=(small['trigger'] if self.p['structure_mode']=='hierarchy' else b.high)*(1+self.p['trigger_buffer'])
        trigger=breakout
        if self.p['entry_mode'] in ('support_rebound','support_band_retest'):
            if self.p['entry_mode']=='support_rebound':
                rebound,reason=support_rebound(bars,small,self.p['support_max_entry_risk'],self.p['support_tighten'])
            else:
                rebound,reason=support_band_retest(bars,small,self.p['support_max_entry_risk'],
                    self.p['support_band_atr_lookback'],self.p['support_band_atr_fraction'],self.p['support_band_max_width'])
            if rebound is None:
                events.append(self.event(b,'support_rebound_wait',reason=reason,small_c=small['date']))
                return [],events
            trigger=b.close  # Indicative plan price, not a future breakout condition.
        if nested:
            observed=lower if lower is not None else bars
            confirmed=small.get('confirmed_date') or bars[core['confirmed']].date
            touched=next((x for x in observed if x.date>=confirmed and x.high>=trigger),None) if rebound is None else None
            if touched:
                # A trigger observed before an executable plan is consumed.
                # A later close below it cannot revive the same rhythm ID.
                self.seen.add(identity)
                events.append(self.event(b,'rhythm_wait',reason='trigger_consumed_before_plan',
                    setup_id=identity,first_touch_date=touched.date,small_confirmed=confirmed))
                return [],events
        # Do not retrospectively fill a lower-cycle breakout already behind us.
        if self.p['entry_mode']=='breakout' and self.p['structure_mode']=='hierarchy' and b.close>=trigger:
            events.append(self.event(b,'rhythm_wait',reason='trigger_already_passed',setup_id=identity))
            return [],events
        self.seen.add(identity)
        stop=small['stop']*(1-self.p['stop_buffer'])
        if rebound and rebound.get('support_stop_rule') in ('upper_retest_band','rebound_upper_band'):
            stop=rebound['support_defense_lower']
        # Same daily N supplies space; prior confirmed daily peaks cap nearer resistance.
        pressures=[p.price for p in points
                   if p.kind=='high' and p.index<core['a'] and p.price>trigger]
        pressure_audit=[]
        if owned:
            pressures,pressure_audit=effective_pressures(bars,points,core,trigger,
                ambiguities=self.core_swings[b.symbol].ambiguous if nested else ())
        target=min([core['target']]+pressures)
        if not stop<trigger<target:
            events.append(self.event(b,'structure_space_exhausted',setup_id=identity,
                                     trigger=trigger,stop=stop,target=target))
            return [],events
        lookback=bars[-self.p['volatility_lookback']:]
        evidence=dict(entry_core_owner=core.get('owner_id'),small_owner=small.get('owner_id'),
                      upper_owner_id=self.wave_source_ids.get(b.symbol) if nested else None,
                      rhythm_owner=core.get('rhythm_owner'),parent_core_owner=core.get('parent_owner'),
                      core_relation=core.get('relation'),core_accepted_at=core.get('accepted_at'),
                      rhythm_floor_date=core.get('rhythm_floor_date'),
                      rhythm_start_date=core.get('rhythm_start_date'),
                      small_a=small.get('a_date'),small_b=small.get('b_date'),
                      small_confirmed=small.get('confirmed_date'),pressure_audit=pressure_audit,
                      core_a=bars[core['a']].date,core_b=bars[core['b']].date,
                      core_c=bars[core['c']].date,small_c=small['date'],lower_cycle=self.p['lower_cycle'],
                      rhythm_kind=small['kind'],target_cycle='daily',holding_cycle='daily',
                      symmetry_target=core['target'],pressure_target=min(pressures) if pressures else None,
                      correction_area=core['correction_area'],correction_duration=core['correction_duration'],
                      correction_range=bars[core['b']].high-bars[core['c']].low,
                      factor=b.factor,volatility=sum((x.high-x.low)/x.close for x in lookback)/len(lookback),
                      direction_confirmed=state['confirmed_date'],
                      direction_first=state.get('direction_source',{}).get('first_date'),
                      direction_second=state.get('direction_source',{}).get('second_date'),
                      direction_breakout=state.get('direction_source',{}).get('breakout_date'),
                      direction_retest_started=state.get('retest_started_date'),
                      core_c_confirmed=bars[core['confirmed']].date,
                      entry_classification='direction_following_daily_rhythm')
        if self.p['direction_cycle']=='daily':
            evidence['direction_cycle']='daily'
        if self.p['support_mode']=='confirmed_trough':
            evidence.update(confirmed_trough_zone(bars,small,b.date,self.p['support_max_entry_risk']))
        if rebound:
            evidence.update(rebound,breakout_reference=breakout,
                            entry_classification='direction_following_'+self.p['entry_mode'])
        intent=Intent(self.name,b.symbol,b.date,trigger,stop,target,identity,'daily_n_rhythm',evidence)
        intent.evidence['first_planned_at']=b.date
        if self.p['entry_mode']=='breakout':
            self.opportunities[b.symbol]=dict(intent=intent,age=0,factor=b.factor)
        events.append(self.event(b,'entry_intent',setup_id=identity,trigger=trigger,stop=stop,target=target,**evidence))
        return [intent],events

    def on_hour_close(self,history,hour,week_ends):
        from ..hourly_entry import on_hour_close
        return on_hour_close(self,history,hour,week_ends)

    @staticmethod
    def top_failure(bars,points):
        if len(points)<3:
            return False
        a,b,c=points[-3:]
        return ((a.kind,b.kind,c.kind)==('high','low','high')
                and bars[-1].close<b.price)

    def trailing_stop(self,history,position):
        bars=adjusted(history)
        if position.holding_cycle=='weekly':
            bars=weekly(bars,self.week_ends)
        lows=pivot_lows(bars,self.p['left'],self.p['right'])
        return max([position.stop]+[bars[i].low*(1-self.p['stop_buffer']) for i in lows
                                    if bars[i].date>position.entry_date])

    def manage_position(self,history,position):
        bars=adjusted(history)
        b=bars[-1]
        position.max_price=max(position.max_price or position.entry,b.high)
        state=self.states.get(b.symbol,{})
        if state.get('direction')!='long':
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'upper_direction_lost')],[]
        measured=weekly(bars,self.week_ends) if position.holding_cycle=='weekly' else bars
        points=swings(measured,self.p['left'],self.p['right'])
        reason=None
        if self.top_failure(measured,points):
            reason='core_top_confirmed'
        current=active_correction(measured,position.entry_date) if self.p['exit_mode']=='active_correction' else None
        if position.holding_cycle=='daily':
            peaks=[p for p in points if p.kind=='high' and bars[p.index].date>=position.entry_date]
            if peaks:
                peak=peaks[-1]
                duration=len(bars)-1-peak.index
                drop=peak.price-min(x.low for x in bars[peak.index:])
                expanded=(duration>position.plan.get('correction_duration',float('inf'))
                          and area(bars,peak.index,len(bars)-1)>position.plan.get('correction_area',float('inf')))
                expanded=expanded or drop>position.plan.get('correction_range',float('inf'))
                if self.p['exit_mode']=='active_correction':
                    expanded=self.correction_expanded(current,position.plan)
                if expanded:
                    # Upgrade requires an explicit stage decision and actual profit protection.
                    max_profit=position.max_price-position.entry
                    protected=max_profit>0 and b.close-position.entry>=max_profit*.5
                    weeks=weekly(bars,self.week_ends)
                    horizontal=(len(weeks)>=3 and max(x.high for x in weeks[-3:])-min(x.low for x in weeks[-3:])<=max_profit*.5)
                    if self.context.get('allow_cycle_upgrade') and protected and horizontal and not reason:
                        position.holding_cycle='weekly'
                        position.plan.update(weekly_correction_area=area(weeks,len(weeks)-3,len(weeks)-1),
                                             weekly_correction_duration=3,
                                             weekly_correction_range=max(x.high for x in weeks[-3:])-min(x.low for x in weeks[-3:]))
                        return [],[self.event(b,'holding_cycle_upgraded',setup_id=position.setup_id,
                                             max_profit=max_profit,retained_profit=b.close-position.entry)]
                    reason=reason or 'core_adjustment_expanded'
        else:
            peaks=[p for p in points if p.kind=='high' and measured[p.index].date>=position.entry_date]
            if peaks:
                peak=peaks[-1]
                duration=len(measured)-1-peak.index
                drop=peak.price-min(x.low for x in measured[peak.index:])
                expanded=(duration>position.plan.get('weekly_correction_duration',float('inf'))
                        and area(measured,peak.index,len(measured)-1)>position.plan.get('weekly_correction_area',float('inf'))
                        or drop>position.plan.get('weekly_correction_range',float('inf')))
                if self.p['exit_mode']=='active_correction':
                    expanded=self.correction_expanded(current,position.plan,'weekly_')
                if expanded:
                    reason=reason or 'weekly_adjustment_expanded'
        # Two successive rising peaks with weaker gain per bar: tighten to the most
        # recently confirmed trough, without asserting a reversal or lowering a stop.
        highs=[p for p in points if p.kind=='high']
        if len(highs)>=4:
            speeds=[(y.price-x.price)/(y.index-x.index) for x,y in zip(highs[-4:],highs[-3:])]
            if speeds[0]>speeds[1]>speeds[2]>0:
                lows=[p for p in points if p.kind=='low']
                if lows:
                    new=lows[-1].price
                    if new>position.stop:
                        position.stop=new
                        return ([ExitIntent(self.name,b.symbol,b.date,position.setup_id,reason)] if reason else []),[
                            self.event(b,'double_exhaustion_defense',setup_id=position.setup_id,new_stop=new)]
        # Completed, non-expanded corrections become the next comparison reference.
        lows=[p for p in points if p.kind=='low' and measured[p.index].date>position.entry_date]
        if lows and not reason:
            low=lows[-1]
            previous_highs=[p for p in points if p.kind=='high' and p.index<low.index]
            if previous_highs and measured[low.index].date!=position.plan.get('last_correction_date'):
                high=previous_highs[-1]
                prefix='weekly_' if position.holding_cycle=='weekly' else ''
                reference=dict(area=area(measured,high.index,low.index),duration=low.index-high.index,
                               range=high.price-low.price)
                if self.p['exit_mode']=='active_correction':
                    # Locate the actual peak preceding this confirmed trough;
                    # an older confirmed high can be below a later rising low.
                    peak=max(range(high.index,low.index+1),key=lambda i:(measured[i].high,i))
                    reference=correction_measure(measured,peak,low.index)
                    if reference is None:
                        return [],[]
                position.plan.update({prefix+'correction_area':reference['area'],
                                      prefix+'correction_duration':reference['duration'],
                                      prefix+'correction_range':reference['range'],
                                      'last_correction_date':measured[low.index].date})
        return ([ExitIntent(self.name,b.symbol,b.date,position.setup_id,reason)] if reason else []),[]

    @staticmethod
    def correction_expanded(current,plan,prefix=''):
        if not current:
            return False
        # Ignore corrupt legacy references; a later valid completed correction
        # can replace them. Structural stops and top/direction exits still apply.
        duration=plan.get(prefix+'correction_duration',0)
        width=plan.get(prefix+'correction_range',0)
        prior_area=plan.get(prefix+'correction_area',0)
        if min(duration,width,prior_area)<=0:
            return False
        return (current['duration']>duration and current['area']>prior_area) or current['range']>width
