"""One-time partial profit protection; v7 remains the core exit manager."""
from dataclasses import replace
from .domain import ExitIntent
from .ihs_geometry import atr_before
from .pressure_support_trend import PressureSupportTrend


class ProfitStructureTrim(PressureSupportTrend):
    def __init__(self,name,calendar,weekends,*,execution):
        super().__init__(name,calendar,weekends)
        self.execution=dict(execution)
        required=('commission_rate','minimum_commission','slippage',
                  'sell_tax_before_20230828','sell_tax_after_20230828')
        if not all(k in execution for k in required):
            raise ValueError('Actual execution costs are required for net-R activation')
        self.indices={d:i for i,d in enumerate(calendar)}
        self.original_risk=self.original_economic_quantity=None
        self.armed=False
        self.peak=self.trough=self.rebound=None
        self.trim_requested=self.trim_filled=False
        self.last_observed_index=None

    def net_close_r(self,b,p):
        value=b.close*(1-self.execution['slippage'])*p.quantity
        tax=self.execution['sell_tax_before_20230828' if b.date<'20230828' else 'sell_tax_after_20230828']
        fee=max(self.execution['minimum_commission'],value*self.execution['commission_rate'])+value*tax
        return (value-p.entry*p.quantity-p.entry_fee-fee)/self.original_risk

    def manage(self,history,position):
        b=history[-1]
        if self.pending or self.last_date==b.date:return [],[]
        if self.original_risk is None:
            self.original_risk=position.initial_risk
            self.original_economic_quantity=position.quantity/position.factor
        exits,events=super().manage(history,position)
        if exits:return exits,events
        if self.trim_requested:
            if not self.trim_filled and position.quantity/position.factor < self.original_economic_quantity*(1-1e-10):
                self.trim_filled=True
                events.append(dict(date=b.date,event='profit_trim_fill_observed',remaining_quantity=position.quantity))
            return [],events
        net_r=self.net_close_r(b,position)
        if not self.armed:
            if net_r<2:return [],events
            self.armed=True
            economic=[replace(v,open=v.open*v.factor,high=v.high*v.factor,
                low=v.low*v.factor,close=v.close*v.factor,factor=1) for v in history[-16:]]
            atr=atr_before(economic,len(economic)-1)
            events.append(dict(date=b.date,event='profit_protection_armed',net_close_R=net_r,
                original_R=self.original_risk,price_gain_ATR=(b.close-position.entry)*b.factor/atr if atr else None))
            # Seed an observable high, not a retrospectively selected pivot.
            self.peak=dict(price=b.high*b.factor,date=b.date)
            self.last_observed_index=self.indices[b.date]
            return [],events
        index=self.indices[b.date]
        if self.last_observed_index != index-1:
            self.peak=dict(price=b.high*b.factor,date=b.date)
            self.trough=self.rebound=None
            self.last_observed_index=index
            events.append(dict(date=b.date,event='profit_structure_reset_gap'))
            return [],events
        self.last_observed_index=index
        if b.high*b.factor > self.peak['price']:
            self.peak=dict(price=b.high*b.factor,date=b.date)
            self.trough=self.rebound=None
            return [],events
        # Only a rebound already confirmed before this close can trigger.
        if self.rebound and b.close*b.factor < self.trough['price']:
            lots=int(position.quantity*(1/3)//100)*100
            if lots<100:
                self.trim_requested=True  # One attempt, never force a full sale for a small lot.
                events.append(dict(date=b.date,event='profit_trim_skipped_small_lot',quantity=position.quantity))
                return [],events
            self.trim_requested=True
            events.append(dict(date=b.date,event='profit_structure_trim_signal',peak=dict(self.peak),
                trough=dict(self.trough),failed_rebound=dict(self.rebound),fraction=1/3,
                estimated_quantity=lots,net_close_R=net_r,execution='next_executable_open'))
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'profit_structure_trim',1/3)],events
        if self.trough and not self.rebound and b.close*b.factor<self.trough['price']:
            self.trough=None
        if len(history)<5:return [],events
        window=history[-5:]
        ids=[self.indices.get(v.date) for v in window]
        if any(i is None for i in ids) or any(y!=x+1 for x,y in zip(ids,ids[1:])):return [],events
        p=window[2];lo=p.low*p.factor;hi=p.high*p.factor
        is_low=all(lo<v.low*v.factor for j,v in enumerate(window) if j!=2)
        is_high=all(hi>v.high*v.factor for j,v in enumerate(window) if j!=2)
        if is_low==is_high or p.date<=self.peak['date']:return [],events
        point=dict(price=lo if is_low else hi,date=p.date,confirmed=b.date)
        if self.trough is None and is_low:
            self.trough=point
            events.append(dict(date=b.date,event='profit_pullback_confirmed',**{'point':point}))
        elif (self.trough and not self.rebound and is_high and p.date>self.trough['date']
              and hi<=self.peak['price']):
            self.rebound=point
            events.append(dict(date=b.date,event='profit_failed_rebound_confirmed',point=point))
        return [],events
