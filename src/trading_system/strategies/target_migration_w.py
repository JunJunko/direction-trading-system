"""Exit-only adapter; entry generation remains QualifiedWRetest."""
from dataclasses import asdict
from .qualified_w_retest import QualifiedWRetest
from ..analysis import adjusted
from ..domain import ExitIntent
from ..target_migration import State,PositionContext,TargetDecisionEngine,KeyLevelRegistry,ConfirmedSupportTrail,atr_pre,RESEARCH_PARAMETERS


class TargetMigrationW(QualifiedWRetest):
    def __init__(self,name,params):
        params=dict(params);self.arm=params.pop('target_arm','B2');self.tick=params.pop('minimum_price_tick',None)
        self.target_params=dict(RESEARCH_PARAMETERS,**params.pop('target_parameters',{}))
        if self.target_params['support_route']!='confirmed_swing_low':raise ValueError('Separate support-route experiment required')
        if self.arm not in ('A0','A1','B1','B2','B3'):raise ValueError('B4 requires missing original momentum definitions')
        self.decision=TargetDecisionEngine('hard' if self.arm=='A0' else 'soft' if self.arm=='A1' else 'dynamic',self.tick,self.target_params)
        self.contexts={};self.registries={};self.trail=ConfirmedSupportTrail(self.target_params['support_buffer_atr'])
        super().__init__(name,params)

    def manage_position(self,history,position):
        bars=adjusted(history);b=bars[-1];t=len(bars)-1;pid=position.setup_id
        events=[]
        if pid not in self.contexts:
            entry=next(i for i,x in enumerate(bars) if x.date==position.entry_date)
            self.contexts[pid]=PositionContext(pid,entry,position.entry,position.quantity,position.stop,
                position.stop,position.plan['w_neckline'],position.plan['w_target'],b.factor)
            self.registries[pid]=KeyLevelRegistry(self.target_params['swing_left_bars'],self.target_params['swing_right_bars'],self.target_params['resistance_zone_atr'])
        ctx=self.contexts[pid];registry=self.registries[pid]
        if ctx.factor!=b.factor:
            scale=ctx.factor/b.factor;registry.rescale(scale)
            for key in ('entry_price','initial_stop','execution_stop','neckline','measured_target'):
                setattr(ctx,key,getattr(ctx,key)*scale)
            for key in ('structural_support','volatility_guard'):
                if getattr(ctx,key) is not None:setattr(ctx,key,getattr(ctx,key)*scale)
            ctx.factor=b.factor
        ctx.shares=position.quantity;ctx.execution_stop=position.stop
        atr=atr_pre(bars,self.target_params['atr_period'])
        def log(reason,action='observe',level=None,**extra):
            events.append(dict(date=b.date,symbol=b.symbol,strategy=self.name,event='target_migration',
                signal_id=pid,trade_id=pid,setup_id=pid,t_detected=t,t_confirmed=level.confirmed_at if level else t,
                valid_from=t+1,level_id=level.id if level else None,level_price=level.price if level else None,
                action=action,reason_code=reason,qty=position.quantity,state=ctx.state.value,
                atr_pre=atr,fill_timestamp=None,fill_price=None,**extra))
        for level in registry.update(bars,atr):
            log('level_confirmed',level=level,level_record=asdict(level))
        before=ctx.state;touch_before=ctx.target_touch_at
        if self.arm=='A0' and ctx.target_touch_at is None and b.high>=ctx.measured_target:ctx.target_touch_at=t
        reason=self.decision.close(ctx,t,b,atr)
        if touch_before is None and ctx.target_touch_at is not None:log('first_target_touch')
        if reason:log(reason,'exit_next_bar' if ctx.state==State.EXIT_PENDING else 'transition',previous_state=before.value)
        if ctx.state==State.EXIT_PENDING:
            exit_reason='w_target_close_confirmed' if self.arm=='A0' else reason
            return ([ExitIntent(self.name,b.symbol,b.date,pid,exit_reason)] if before!=State.EXIT_PENDING else []),events
        if ctx.state==State.TREND_HOLD:
            if self.arm in ('B2','B3'):
                stop,level=self.trail.propose(ctx,registry,bars,atr)
                if level and level.id not in ctx.confirmed_support_ids:
                    ctx.confirmed_support_ids.append(level.id)
                    ctx.structural_support=level.price
                    log('confirmed_support_available',level=level)
                if stop>position.stop:
                    old=position.stop;position.stop=stop;ctx.execution_stop=stop
                    log('confirmed_support_stop_raised','raise_stop_next_bar',level,old_stop=old,new_stop=stop)
            if self.arm=='B3' and atr is not None:
                guard=max(x.close for x in bars[ctx.entry_at:])-self.target_params['volatility_guard_atr']*atr
                ctx.volatility_guard=max(ctx.volatility_guard or guard,guard)
                if guard>position.stop:
                    old=position.stop;position.stop=guard;ctx.execution_stop=guard
                    log('volatility_guard_raised','raise_risk_stop_next_bar',old_stop=old,new_stop=guard)
        zones=registry.resistances(b.close,t,atr,self.tick)
        ctx.known_resistance_ids=zones[0]['ids'] if zones else []
        log('state_snapshot',next_resistance=zones[0] if zones else None,
            structural_support=ctx.structural_support,volatility_guard=ctx.volatility_guard,
            execution_stop=position.stop,target_touch_at=ctx.target_touch_at,
            decisive_break_at=ctx.breakout_candidate_at,acceptance_at=ctx.trend_confirmed_at,
            confirmed_support_ids=list(ctx.confirmed_support_ids))
        return [],events
