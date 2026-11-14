"""Three separately tested lifecycle changes; no threshold selection in this module."""
import copy
from dataclasses import replace
from .pressure_support_ihs import PressureSupportIHS
from ..domain import ExitIntent
from ..ihs_geometry import neckline_at
from ..volatility_entry_research import prior_atr

def scaled_seed(seed,factor):
    e=copy.deepcopy(seed.evidence);scale=e['factor']/factor
    for k in ('ihs_neckline','ihs_head_neckline','ihs_floor','ihs_target','ihs_right_low','ihs_entry_atr','ihs_peak1_price','ihs_peak2_price','breakout_reference'):
        e[k]*=scale
    e['factor']=factor
    return replace(seed,trigger=seed.trigger*scale,stop=seed.stop*scale,target=seed.target*scale,evidence=e)

class RetestConfirmedIHS(PressureSupportIHS):
    def __init__(self,name,params):
        super().__init__(name,params);self.retest_waiting={};self.retest_consumed=set()

    def retest_on_close(self,history,seeds):
        bar=history[-1];intents=[];events=[]
        for seed in seeds:
            if seed.setup_id in self.retest_consumed or seed.setup_id in self.retest_waiting:continue
            self.retest_waiting[seed.setup_id]=dict(seed=copy.deepcopy(seed),touch_date=None)
            events.append(dict(date=bar.date,symbol=bar.symbol,strategy=self.name,setup_id=seed.setup_id,event='retest_registered',original_signal_date=seed.date))
        for pid,state in list(self.retest_waiting.items()):
            seed=state['seed']
            if seed.symbol!=bar.symbol:continue
            after=[b for b in history if b.date>seed.date]
            if not after:continue
            current=scaled_seed(seed,bar.factor);e=current.evidence;atr=e['ihs_entry_atr'];neck=neckline_at(e,bar.date)
            low=min(b.low*b.factor/bar.factor for b in after);high=max(b.high*b.factor/bar.factor for b in after)
            reason=None
            if len(after)>10:reason='expired_10_stock_bars'
            elif low<=e['ihs_right_low']:reason='right_shoulder_broken'
            elif high>=current.target:reason='original_target_touched'
            if reason:
                events.append(dict(date=bar.date,symbol=bar.symbol,strategy=self.name,setup_id=pid,event='retest_cancelled',reason=reason,original_signal_date=seed.date))
            else:
                if state['touch_date'] is None and bar.low<=neck+.25*atr:
                    state['touch_date']=bar.date
                    events.append(dict(date=bar.date,symbol=bar.symbol,strategy=self.name,setup_id=pid,event='retest_touch',neckline=neck,atr=atr,original_signal_date=seed.date))
                previous=history[-2]
                if (state['touch_date'] and state['touch_date']<bar.date and
                    bar.close>max(neck+.1*atr,bar.open,previous.close*previous.factor/bar.factor)):
                    e.update(original_signal_date=seed.date,retest_touch_date=state['touch_date'],retest_confirmed_at=bar.date,
                             rebound_confirmed_at=bar.date,entry_order='next_open')
                    intent=replace(current,date=bar.date,trigger=bar.close,evidence=e)
                    intents.append(intent)
                    events.append(dict(date=bar.date,symbol=bar.symbol,strategy=self.name,setup_id=pid,event='entry_intent',trigger=intent.trigger,stop=intent.stop,target=intent.target,**e))
                    reason='submitted_once'
            if reason:
                del self.retest_waiting[pid];self.retest_consumed.add(pid)
        return intents,events

    def on_close(self,history,week_ends):
        seeds,logs=super().on_close(history,week_ends)
        logs=[dict(e,event='retest_seed') if e['event']=='entry_intent' else e for e in logs]
        intents,events=self.retest_on_close(history,seeds)
        return intents,logs+events

class BreakoutFailureIHS(PressureSupportIHS):
    def __init__(self,name,params):
        super().__init__(name,params);self.failure_pending=set()

    def manage_position(self,history,position):
        if position.setup_id in self.failure_pending:return [],[]
        exits,events=super().manage_position(history,position)
        if exits:return exits,events
        held=[b for b in history if b.date>=position.entry_date]
        if len(held)<2:return exits,events
        checks=[]
        for b in held[-2:]:
            atr,_=prior_atr(history,b.date,position.factor)
            if atr is None:return exits,events
            neck=neckline_at(position.plan,b.date)
            level=(neck-.5*atr)*position.factor
            checks.append(dict(date=b.date,close_economic=b.close*b.factor,neckline_economic=neck*position.factor,atr_economic=atr*position.factor,failure_level_economic=level))
        if all(c['close_economic']<c['failure_level_economic'] for c in checks):
            self.failure_pending.add(position.setup_id)
            events.append(dict(date=history[-1].date,symbol=position.symbol,strategy=self.name,setup_id=position.setup_id,event='ihs_breakout_failure_confirmed',first_failure_date=checks[0]['date'],second_failure_date=checks[1]['date'],first_level=checks[0]['failure_level_economic'],second_level=checks[1]['failure_level_economic'],execution='next_executable_open'))
            exits.append(ExitIntent(self.name,position.symbol,history[-1].date,position.setup_id,'ihs_confirmed_breakout_failure'))
        return exits,events

class ProfitActivatedIHS(PressureSupportIHS):
    profit_pivot_side = 2
    profit_support_source = 'profit_activated_daily_higher_low'
    def __init__(self,name,params):
        super().__init__(name,params);self.profit_activation={};self.profit_daily_lows={}

    def manage_position(self,history,position):
        exits,events=super().manage_position(history,position)
        if exits:return exits,events
        bar=history[-1];pid=position.setup_id
        marked=(bar.close-position.entry)*position.quantity-position.entry_fee
        if pid not in self.profit_activation and marked>=position.initial_risk:
            self.profit_activation[pid]=bar.date
            events.append(dict(date=bar.date,symbol=position.symbol,strategy=self.name,setup_id=pid,event='profit_protection_activated',marked_profit=marked,initial_risk=position.initial_risk,activation_R=1,accounting='marked_profit_after_entry_fee_before_exit_fee'))
        held=[b for b in history if b.date>=position.entry_date]
        side=self.profit_pivot_side
        if len(held)<2*side+2:return exits,events
        pivot=held[-side-1];low=pivot.low*pivot.factor
        if low>=min(b.low*b.factor for b in held[-2*side-1:-side-1]+held[-side:]):return exits,events
        previous=self.profit_daily_lows.get(pid,held[0].low*held[0].factor)
        self.profit_daily_lows[pid]=low
        activation=self.profit_activation.get(pid)
        if not activation or pivot.date<activation or low<=previous:return exits,events
        atr,_=prior_atr(history,bar.date,bar.factor)
        if atr is None:return exits,events
        level=low-.5*atr*bar.factor
        if level>=bar.close*bar.factor:return exits,events
        added=[];manager=self.managers[pid]
        manager._raise_support(level,bar,position,added,self.profit_support_source,pivot.date,bar.date)
        for e in added:e.update(symbol=position.symbol,strategy=self.name,setup_id=pid,activation_date=activation,daily_low=low,previous_daily_low=previous,atr_economic=atr*bar.factor,buffer_atr=.5)
        events.extend(added)
        position.plan.update(dynamic_support_economic=manager.protection,main_trend_protection_economic=manager.protection,dynamic_support_source=manager.support_source)
        return exits,events
