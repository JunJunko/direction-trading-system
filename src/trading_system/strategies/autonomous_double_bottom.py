"""Explicit core ownership and conservative, deterministic holding states."""
from .direction_double_bottom import DirectionDoubleBottom
from ..analysis import adjusted
from ..structure import active_correction,correction_measure,swings,SwingCache
from ..wave_hierarchy import correction_level
from ..domain import ExitIntent


class AutonomousDoubleBottom(DirectionDoubleBottom):
    def __init__(self,name,params):
        params=dict(params)
        self.protection_mode=params.pop('protection_mode','entry_scale')
        self.holding_scale_mode=params.pop('holding_scale_mode','entry_rhythm')
        if self.holding_scale_mode not in ('entry_rhythm','owned_core'):
            raise ValueError('Invalid holding scale mode')
        if self.holding_scale_mode=='owned_core' and params.get('core_mode')!='nested':
            raise ValueError('Owned holding scale requires nested core ownership')
        if self.protection_mode not in ('entry_scale','live_leg'):
            raise ValueError('Invalid protection mode')
        if params.get('structure_mode','hierarchy')!='hierarchy' or params.get('exit_mode','active_correction')!='active_correction':
            raise ValueError('Autonomous strategy has fixed structural modes')
        super().__init__(name,dict(params,structure_mode='hierarchy',exit_mode='active_correction'))

    def on_close(self,history,week_ends):
        intents,events=super().on_close(history,week_ends)
        for intent in intents:
            intent.evidence.update(core_owner=intent.setup_id,core_scale_duration=intent.evidence['correction_duration'],
                                   holding_state='verification')
        return intents,events

    def trailing_stop(self,history,position):
        # Only manage_position may promote a confirmed, owned core trough.
        return position.stop

    def manage_position(self,history,position):
        if self.protection_mode=='live_leg':
            return self.manage_live_leg(history,position)
        bars=adjusted(history);b=bars[-1];plan=position.plan
        position.max_price=max(position.max_price or position.entry,b.high)
        if self.states.get(b.symbol,{}).get('direction')!='long':
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'upper_direction_lost')],[]
        required=('core_a','core_b','core_c','correction_duration','correction_range')
        if any(k not in plan for k in required):
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'missing_core_record')],[]
        if plan.get('core_owner',position.setup_id)!=position.setup_id:
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'mismatched_core_owner')],[]
        if 'core_reference_duration' not in plan:
            plan.update(holding_state='verification',core_owner=position.setup_id,
                        core_scale_duration=plan['correction_duration'],
                        core_reference_duration=plan['correction_duration'],
                        core_protected_date=plan['core_c'])
        current=active_correction(bars,position.entry_date)
        deadline=plan['core_reference_duration']+self.p['right']
        if current and current['duration']>deadline:
            plan['holding_state']='exit_pending'
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'owned_core_adjustment_timeout')],[
                self.event(b,'holding_exit',setup_id=position.setup_id,reason='core_timeout',
                           duration=current['duration'],reference_duration=plan['core_reference_duration'],deadline=deadline)]
        # Complete a core correction only after recovery through its own peak.
        # Two-bar local lows are evidence, not permission to replace core state.
        points=swings(bars,self.p['left'],self.p['right'])
        lows=[p for p in points if p.kind=='low' and bars[p.index].date>position.entry_date
              and bars[p.index].date>plan['core_protected_date']]
        events=[]
        for low in lows:
            before=[i for i,x in enumerate(bars[:low.index]) if x.date>=plan['core_protected_date']]
            if not before:continue
            peak=max(before,key=lambda i:(bars[i].high,i))
            measured=correction_measure(bars,peak,low.index)
            if (not measured or measured['duration']<max(3,plan['core_scale_duration'])
                    or b.close<=bars[peak].high):
                continue
            floor=low.price*(1-self.p['stop_buffer'])
            if floor<=position.stop:continue
            old=position.stop;position.stop=floor
            plan.update(holding_state='core_trend',core_protected_date=bars[low.index].date,
                        core_reference_duration=measured['duration'],
                        owned_peak_date=bars[peak].date,owned_trough_date=bars[low.index].date)
            events.append(self.event(b,'core_protection_promoted',setup_id=position.setup_id,
                old_stop=old,new_stop=floor,core_owner=plan['core_owner'],
                peak_date=bars[peak].date,trough_date=bars[low.index].date,confirmed_at=b.date))
        return [],events

    def manage_live_leg(self,history,position):
        """Confirm a matched correction of the CURRENT leg, not an old scale.

        Local lows are promoted only after a complete >=3-bar correction,
        slower/smaller than its own impulse and an observed recovery. Recovery
        above the trough candle is sufficient; a new trend high is not required.
        """
        bars=adjusted(history);b=bars[-1];plan=position.plan
        position.max_price=max(position.max_price or position.entry,b.high)
        def exit(reason):
            plan['holding_state']='exit_pending'
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,reason)],[
                self.event(b,'holding_exit',setup_id=position.setup_id,reason=reason)]
        if self.states.get(b.symbol,{}).get('direction')!='long':
            return exit('upper_direction_lost')
        if (self.p['core_mode']=='nested' and plan.get('upper_owner_id')
                and self.wave_source_ids.get(b.symbol)!=plan['upper_owner_id']):
            return exit('upper_direction_owner_changed')
        if any(k not in plan for k in ('core_a','core_b','core_c','small_c','correction_duration')):
            return exit('missing_core_record')
        if plan.get('core_owner',position.setup_id)!=position.setup_id:
            return exit('mismatched_core_owner')
        if 'live_anchor_date' not in plan:
            anchor_date=plan['core_c'] if self.holding_scale_mode=='owned_core' else plan['small_c']
            plan.update(live_anchor_date=anchor_date[:8],core_owner=position.setup_id,
                        holding_state='verification',live_reference_duration=float(plan['correction_duration']))
        nested=self.p['core_mode']=='nested'
        if nested:
            if 'correction_range' not in plan:return exit('missing_core_range')
            plan.setdefault('live_reference_range',float(plan['correction_range']))
        indices={x.date:i for i,x in enumerate(bars)}
        if plan['live_anchor_date'] not in indices:
            return exit('missing_live_anchor')
        anchor=indices[plan['live_anchor_date']]
        events=[]
        holding_swings=SwingCache(self.p['left'],self.p['right']) if nested else None
        points=holding_swings.get(bars) if nested else swings(bars,self.p['left'],self.p['right'])
        lows=[x for x in points
              if x.kind=='low' and x.index>anchor and bars[x.index].date>position.entry_date]
        for low in lows:
            peak=max(range(anchor,low.index),key=lambda i:(bars[i].high,i))
            impulse_time=peak-anchor;impulse=bars[peak].high-bars[anchor].low
            measured=correction_measure(bars,peak,low.index)
            if (self.holding_scale_mode=='owned_core' and measured
                    and min(x.low for x in bars[peak+1:low.index+1])<low.price):
                rejected=plan.setdefault('holding_wave_rejected',[])
                identity=bars[low.index].date
                if identity not in rejected:
                    rejected.append(identity)
                    events.append(self.event(b,'holding_wave_rejected',setup_id=position.setup_id,
                        trough_date=identity,peak_date=bars[peak].date,
                        reason='trough_not_actual_correction_floor'))
                continue
            if nested and measured:
                level=correction_level(measured['duration'],measured['range'],
                                       plan['live_reference_duration'],plan['live_reference_range'])
                identity=bars[low.index].date
                seen=plan.setdefault('holding_wave_classified',[])
                if identity not in seen:
                    seen.append(identity)
                    events.append(self.event(b,'holding_wave_classified',setup_id=position.setup_id,
                        parent_owner=position.setup_id,level=level,trough_date=identity,
                        duration=measured['duration'],drop=measured['range']))
                if level!='core' or any(anchor<=r['index']<=low.index for r in holding_swings.ambiguous):
                    continue
            if (not measured or impulse_time<=0 or impulse<=0 or measured['duration']<3
                    or measured['duration']>impulse_time or measured['range']>=impulse
                    or measured['range']/measured['duration']>=impulse/impulse_time
                    or min(x.low for x in bars[low.index:])<low.price
                    or b.close<=bars[low.index].high):
                continue
            floor=low.price*(1-self.p['stop_buffer'])
            if floor<=position.stop:continue
            old=position.stop;position.stop=floor
            plan.update(live_anchor_date=bars[low.index].date,core_protected_date=bars[low.index].date,
                        live_reference_duration=measured['duration'],holding_state='core_trend',
                        owned_peak_date=bars[peak].date,owned_trough_date=bars[low.index].date)
            if nested:plan['live_reference_range']=measured['range']
            if plan.get('support_mode')=='confirmed_trough':
                candle=bars[low.index]
                plan.update(support_lower=floor,support_upper=min(candle.open,candle.close),
                            support_source_date=candle.date,support_known_at=b.date)
                if plan.get('support_active_stop_kind')=='upper_retest_band':
                    plan['support_active_stop_kind']='confirmed_core_floor'
            events.append(self.event(b,'core_protection_promoted',setup_id=position.setup_id,
                old_stop=old,new_stop=floor,core_owner=position.setup_id,peak_date=bars[peak].date,
                trough_date=bars[low.index].date,confirmed_at=b.date,
                correction_duration=measured['duration'],impulse_duration=impulse_time,
                recovery_below_peak=b.close<=bars[peak].high))
            anchor=low.index
        # A confirmed recovery ends its owned correction. The next leg starts at
        # that trough; do not keep timing the old correction through the rebound.
        leg=bars[anchor:]
        current=active_correction(leg,leg[0].date)
        if current:
            impulse_time=current['peak']
            deadline=(plan['live_reference_duration'] if self.holding_scale_mode=='owned_core'
                      else min(plan['live_reference_duration'],max(3,impulse_time)))+self.p['right']
            if current['duration']>deadline:
                exits,extra=exit('live_core_adjustment_timeout')
                return exits,events+extra
        return [],events
