"""Opt-in research gate; original brackets, sizing and exits remain unchanged."""
from math import isfinite
from .engine import Backtest


def prior_atr(history, date, factor, period=14):
    """SMA true range, last 14 completed bars, in execution-day price units."""
    known=[b for b in history if b.date<date][-period-1:]
    if len(known)<period+1:return None,None
    if factor<=0:raise ValueError('Positive execution factor required')
    ranges=[]
    for prev,b in zip(known,known[1:]):
        high,low,close=b.high*b.factor/factor,b.low*b.factor/factor,prev.close*prev.factor/factor
        ranges.append(max(high-low,abs(high-close),abs(low-close)))
    atr=sum(ranges)/period
    return (atr if isfinite(atr) and atr>0 else None),known[-1].date


class VolatilityEntryBacktest(Backtest):
    def execute_interval(self,today,date,universe,entry_cash,window=None):
        self.execution_factors={s:b.factor for s,b in today.items()}
        return super().execute_interval(today,date,universe,entry_cash,window)

    def assess_entry(self,intent,fill,equity,cash,marks,date):
        result=super().assess_entry(intent,fill,equity,cash,marks,date)
        gate=self.config.get('volatility_entry_filter')
        # Do not change signal-close admission; check the actual next-open distance.
        if not gate or date<=intent.date:return result
        is_w=intent.evidence.get('entry_mode')=='w_retest'
        if gate['scope']=='W' and not is_w:return result
        atr,known_at=prior_atr(self.histories.get(intent.symbol,[]),date,
                             self.execution_factors[intent.symbol],gate['period'])
        ratio=(fill-intent.stop)/atr if atr else None
        passes=ratio is not None and ratio+1e-12>=gate['min_stop_atr']
        result.update(volatility_atr=atr,volatility_known_at=known_at,stop_atr_ratio=ratio,
                      volatility_pass=passes,volatility_min_stop_atr=gate['min_stop_atr'],
                      pre_volatility_reason=result['risk_reason'])
        if result['quantity'] and not passes:
            result.update(quantity=0,risk_reason='volatility_history_missing' if atr is None else 'stop_inside_normal_volatility')
            if 'decision' in result:result['decision']='NO_TRADE'
        return result
