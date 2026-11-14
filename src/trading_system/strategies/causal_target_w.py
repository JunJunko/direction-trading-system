"""Independent C study: baseline-clock exemption, independent risk modules.

No ordinary high touch exits. Same-close evidence is evaluated BEFORE creating
the original close-target order; previously queued orders are never cancelled.
"""
from dataclasses import asdict
from .qualified_w_retest import QualifiedWRetest
from ..analysis import adjusted
from ..domain import ExitIntent
from ..target_migration import (PositionContext,State,TargetDecisionEngine,KeyLevelRegistry,
    ConfirmedSupportTrail,atr_pre,RESEARCH_PARAMETERS)


class BaselineClockDecision(TargetDecisionEngine):
    def close(self,ctx,t,bar,atr):
        if ctx.target_touch_at is None and bar.high>=ctx.measured_target:ctx.target_touch_at=t
        if ctx.state==State.PRE_TARGET and bar.close<ctx.measured_target:return None
        # The first baseline decision close, not the first intraday touch, is
        # the sole exemption window. Dynamic superclass cannot reopen a pending exit.
        first_touch=ctx.target_touch_at
        reason=super().close(ctx,t,bar,atr)
        ctx.target_touch_at=first_touch
        return reason


class CausalTargetW(QualifiedWRetest):
    def __init__(self,name,params):
        params=dict(params);self.arm=params.pop('target_arm','C0')
        tick=params.pop('minimum_price_tick',.01)
        self.target_params=dict(RESEARCH_PARAMETERS,**params.pop('target_parameters',{}))
        if self.arm not in ('C0','C1','C2','C3','C4'):raise ValueError('Unknown C arm')
        self.decision=BaselineClockDecision('hard' if self.arm=='C0' else 'dynamic',tick,self.target_params)
        self.contexts={};self.registries={};self.risk_lines={};self.tick=tick
        self.trail=ConfirmedSupportTrail(self.target_params['support_buffer_atr'])
        super().__init__(name,params)

    def set_calendar(self,calendar):
        self.next_session=dict(zip(calendar,calendar[1:]))

    def manage_position(self,history,position):
        bars=adjusted(history);b=bars[-1];t=len(bars)-1;pid=position.setup_id;events=[]
        if pid not in self.contexts:
            entry=next(i for i,x in enumerate(bars) if x.date==position.entry_date)
            self.contexts[pid]=PositionContext(pid,entry,position.entry,position.quantity,position.stop,
                position.stop,position.plan['w_neckline'],position.plan['w_target'],b.factor)
            self.registries[pid]=KeyLevelRegistry(self.target_params['swing_left_bars'],self.target_params['swing_right_bars'],self.target_params['resistance_zone_atr'])
            self.risk_lines[pid]=dict(original=position.stop,atr=None,structure=None)
        ctx=self.contexts[pid];reg=self.registries[pid];lines=self.risk_lines[pid]
        if ctx.factor!=b.factor:
            scale=ctx.factor/b.factor;reg.rescale(scale)
            for key in ('entry_price','initial_stop','execution_stop','neckline','measured_target','structural_support','volatility_guard'):
                if getattr(ctx,key) is not None:setattr(ctx,key,getattr(ctx,key)*scale)
            for key,value in lines.items():
                if value is not None:lines[key]=value*scale
            ctx.factor=b.factor
        ctx.execution_stop=position.stop;ctx.shares=position.quantity
        atr=atr_pre(bars,self.target_params['atr_period'])
        def log(reason,action='observe',level=None,**extra):
            formed=level.pivot_at if level else t;confirmed=level.confirmed_at if level else t
            events.append(dict(event='target_migration',date=b.date,symbol=b.symbol,strategy=self.name,
                trade_id=pid,signal_id=pid,setup_id=pid,reason_code=reason,action=action,state=ctx.state.value,
                qty=position.quantity,t_detected=t,t_formed=formed,t_confirmed=confirmed,valid_from=t+1,
                formed_at=bars[formed].date,confirmed_at=bars[confirmed].date,
                valid_from_date=getattr(self,'next_session',{}).get(b.date),
                valid_from_rule='next_exchange_session_after_detection_close',level_id=level.id if level else None,
                level_price=level.price if level else None,source=extra.get('line_source') or (level.origin if level else 'TARGET_DECISION'),
                atr_pre=atr,fill_timestamp=None,fill_price=None,**extra))
        before=ctx.state;touch=ctx.target_touch_at;reason=self.decision.close(ctx,t,b,atr)
        if touch is None and ctx.target_touch_at is not None:log('first_target_touch')
        if reason:log(reason,'exit_next_bar' if ctx.state==State.EXIT_PENDING else 'transition',previous_state=before.value)
        if ctx.state==State.EXIT_PENDING:
            exit_reason='w_target_close_confirmed' if reason in ('legacy_target_close','target_touch_not_decisive') else reason
            return ([ExitIntent(self.name,b.symbol,b.date,pid,exit_reason)] if before!=State.EXIT_PENDING else []),events
        for level in reg.update(bars,atr):
            # Factual pivot observation alone is never an executable risk order.
            log('factual_level_confirmed',level=level,level_record=asdict(level))
        if ctx.state in (State.BREAKOUT_CANDIDATE,State.TREND_HOLD) and self.arm in ('C2','C4') and atr is not None:
            candidate=max(x.close for x in bars[ctx.entry_at:])-self.target_params['volatility_guard_atr']*atr
            if lines['atr'] is None or candidate>lines['atr']:
                previous=lines['atr'];lines['atr']=candidate;ctx.volatility_guard=candidate
                log('atr_risk_line_changed','risk_line_next_bar',old_line=previous,new_line=candidate,line_source='ATR_RISK')
        if ctx.state==State.TREND_HOLD and self.arm in ('C3','C4'):
            _,level=self.trail.propose(ctx,reg,bars,atr)
            if level and level.id not in ctx.confirmed_support_ids:
                ctx.confirmed_support_ids.append(level.id);ctx.structural_support=level.price
                log('confirmed_support_available',level=level,line_source='STRUCTURE_DESCRIPTION')
                # Freeze the buffer at activation; subsequent ATR contraction
                # does not create a pivot or revise this structure-derived line.
                candidate=level.price-self.target_params['support_buffer_atr']*atr
                if lines['structure'] is None or candidate>lines['structure']:
                    previous=lines['structure'];lines['structure']=candidate
                    log('structure_risk_line_changed','risk_line_next_bar',level,
                        old_line=previous,new_line=candidate,line_source='CONFIRMED_SUPPORT_BUFFER')
        source,stop=max(((k,v) for k,v in lines.items() if v is not None),key=lambda pair:pair[1])
        if stop>position.stop:
            old=position.stop;position.stop=stop;ctx.execution_stop=stop
            position.plan['c_exit_risk_source']=source
            log('execution_risk_stop_raised','raise_stop_next_bar',old_stop=old,new_stop=stop,line_source=source)
        zones=reg.resistances(b.close,t,atr,self.tick)
        log('state_snapshot',execution_stop=position.stop,structural_support=ctx.structural_support,
            original_risk_line=lines['original'],atr_risk_line=lines['atr'],structure_risk_line=lines['structure'],
            next_resistance=zones[0] if zones else None,target_touch_at=ctx.target_touch_at,
            decisive_break_at=ctx.breakout_candidate_at,acceptance_at=ctx.trend_confirmed_at)
        return [],events
