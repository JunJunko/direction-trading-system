"""Research-only E exits. Imports supplied by frozen v3 engine on sys.path."""
import math
from trading_system.analysis import adjusted
from trading_system.domain import ExitIntent
from trading_system.target_migration import KeyLevelRegistry,atr_pre


def liquidation_net(position, price, commission, tax, slippage):
    value=position.quantity*price*(1-slippage)
    return value-position.quantity*position.entry-position.entry_fee-max(5,value*commission)-value*tax


def breakeven_stop(position, commission, tax, slippage):
    lo=position.entry;hi=max(lo*2,lo+1)
    while liquidation_net(position,hi,commission,tax,slippage)<0:hi*=2
    for _ in range(70):
        mid=(lo+hi)/2
        if liquidation_net(position,mid,commission,tax,slippage)>=0:hi=mid
        else:lo=mid
    # Quote tick applies to current raw-price scale, including after a factor change.
    return math.ceil((hi-1e-10)/.01)*.01


class ResearchExit:
    def __init__(self,name,arm,execution,calendar):
        assert arm in ('E0','E1','E2','E3')
        self.name=name;self.arm=arm;self.execution=execution
        self.nextday=dict(zip(calendar,calendar[1:]));self.reg=KeyLevelRegistry(2,2,.25)
        self.factor=None;self.last_support=None;self.used=set();self.be_active=False
        self.state='HOLD_INITIAL';self.source='initial_right_shoulder'

    def manage(self,history,p):
        bars=adjusted(history);b=bars[-1];t=len(bars)-1;events=[]
        entry_at=next(i for i,r in enumerate(bars) if r.date==p.entry_date)
        if self.factor is not None and self.factor!=b.factor:
            scale=self.factor/b.factor;self.reg.rescale(scale)
            if self.last_support is not None:self.last_support*=scale
        self.factor=b.factor
        tax=self.execution['sell_tax_after_20230828'] if b.date>='20230828' else self.execution['sell_tax_before_20230828']
        net=liquidation_net(p,b.close,self.execution['commission_rate'],tax,self.execution['slippage'])
        def event(reason,**kw):
            return dict(date=b.date,symbol=b.symbol,setup_id=p.setup_id,reason=reason,
                valid_from=self.nextday.get(b.date),state=self.state,**kw)
        if self.state=='EXIT_PENDING':return [],[],net
        if b.close>=p.plan['ihs_target']:
            self.state='EXIT_PENDING'
            return [ExitIntent(self.name,b.symbol,b.date,p.setup_id,'ihs_target_close_confirmed')],[event('target_close_exit')],net
        if self.arm in ('E1','E3') and not self.be_active and net>=p.initial_risk:
            self.be_active=True;candidate=breakeven_stop(p,self.execution['commission_rate'],tax,self.execution['slippage'])
            events.append(event('breakeven_activated',net_R=net/p.initial_risk,candidate=candidate))
            if candidate>p.stop:
                old=p.stop;p.stop=candidate;self.source='cost_breakeven'
                events.append(event('stop_raised',source=self.source,old_stop=old,new_stop=p.stop))
        if self.arm in ('E2','E3'):
            atr=atr_pre(bars,14)
            fresh=self.reg.update(bars,atr)
            for level in fresh:
                if level.kind=='SUPPORT' and level.pivot_at>entry_at:
                    events.append(event('support_confirmed',formed=bars[level.pivot_at].date,
                        confirmed=bars[level.confirmed_at].date,level_id=level.id,price=level.price))
            if atr is not None:
                supports=[v for v in self.reg.levels.values() if v.kind=='SUPPORT' and v.pivot_at>entry_at
                    and v.confirmed_at<=t and v.id not in self.used
                    and v.price>p.plan['research_initial_stop']
                    and (self.last_support is None or v.price>self.last_support)
                    and not any(r.low<=v.price for r in bars[v.pivot_at+1:])]
                if supports:
                    v=max(supports,key=lambda v:(v.price,v.confirmed_at,v.id))
                    self.used.add(v.id);self.last_support=v.price
                    candidate=v.price-.5*atr
                    events.append(event('higher_support_selected',formed=bars[v.pivot_at].date,
                        confirmed=bars[v.confirmed_at].date,price=v.price,buffer=.5*atr,candidate=candidate))
                    if candidate>p.stop:
                        old=p.stop;p.stop=candidate;self.source='confirmed_higher_low'
                        events.append(event('stop_raised',source=self.source,old_stop=old,new_stop=p.stop,
                            formed=bars[v.pivot_at].date,confirmed=bars[v.confirmed_at].date))
        self.state='HOLD_PROTECTED' if self.source!='initial_right_shoulder' else 'HOLD_INITIAL'
        return [],events,net
