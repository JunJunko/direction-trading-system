"""Confirmed IHS neckline retest; breakout only registers a waiting setup."""
import math
from ..domain import Intent, ExitIntent
from ..analysis import adjusted
from .enclosing_inverse_head_shoulders import EnclosingInverseHeadShoulders


class RiskDefinedIHS(EnclosingInverseHeadShoulders):
    def __init__(self, name, params):
        params = dict(params)
        self.rules = dict(retest_sessions=20, touch_tolerance=.005,
                          failure_tolerance=.025, max_neckline_distance=.02,
                          min_stop_atr=1., stop_buffer_atr=.25, reclaim_sessions=3)
        for key in self.rules:
            if key in params:
                self.rules[key] = params.pop(key)
        if type(self.rules['retest_sessions']) is not int or self.rules['retest_sessions'] < 1:
            raise ValueError('retest_sessions')
        for key in ('touch_tolerance', 'failure_tolerance', 'max_neckline_distance'):
            value = self.rules[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(key)
        if self.rules['touch_tolerance'] > self.rules['max_neckline_distance']:
            raise ValueError('Touch band exceeds entry band')
        if type(self.rules['reclaim_sessions']) is not int or self.rules['reclaim_sessions']<1:raise ValueError('reclaim_sessions')
        for key in ('min_stop_atr','stop_buffer_atr'):
            v=self.rules[key]
            if type(v) not in (int,float) or not math.isfinite(v) or v<=0:raise ValueError(key)
        super().__init__(name, params)
        self.waiting = {}

    def on_close(self, history, week_ends):
        if not history or self.last.get(history[-1].symbol) == history[-1].date:
            return [], []
        seeds, source = super().on_close(history, week_ends)
        bars = self.adjusted_bars[history[-1].symbol][2]
        b = bars[-1]
        intents, events, remaining = [], [], []
        for seed in self.waiting.get(b.symbol, []):
            e = dict(seed.evidence)
            scale = e['factor'] / b.factor
            for key in ('ihs_neckline', 'ihs_floor', 'ihs_target', 'ihs_right_low', 'breakout_reference'):
                e[key] *= scale
            e['factor'] = b.factor
            after = [x for x in bars if x.date > e['ihs_known_at']]
            neck = e['ihs_neckline']
            base = dict(date=b.date, symbol=b.symbol, strategy=self.name, setup_id=seed.setup_id)
            reason = None
            if len([x for x in bars if x.date>e['ihs_breakout_date']]) > self.rules['retest_sessions']:
                reason = 'expired'
            elif min(x.low for x in after) <= e['ihs_floor']:
                reason = 'head_broken'
            elif min(x.low for x in after) <= e['ihs_right_low']:
                reason = 'right_shoulder_broken'
            elif min(x.low for x in after) < neck*(1-self.rules['failure_tolerance']):
                reason = 'neckline_retest_failed'
            elif max(x.high for x in after) >= e['ihs_target']:
                reason = 'target_already_touched'
            streak=0
            for x in after:
                streak=streak+1 if x.close<neck else 0
                if streak>=self.rules['reclaim_sessions']:
                    reason=reason or 'neckline_not_reclaimed';break
            if reason:
                events.append(dict(base, event='ihs_retest_invalidated', reason=reason))
                continue
            low = min(after, key=lambda x: (x.low, -int(x.date)))
            confirmed = (low.low <= neck*(1+self.rules['touch_tolerance']) and
                         b.close > neck and b.close > b.open and b.close > bars[-2].close and
                         b.close <= neck*(1+self.rules['max_neckline_distance']))
            if not confirmed:
                remaining.append(seed)
                continue
            if len(bars)<15:
                remaining.append(seed);continue
            atr=sum(max(bars[j].high-bars[j].low,abs(bars[j].high-bars[j-1].close),abs(bars[j].low-bars[j-1].close)) for j in range(len(bars)-14,len(bars)))/14
            stop=e['ihs_right_low']-self.rules['stop_buffer_atr']*atr
            if stop<=0:
                events.append(dict(base,event='ihs_retest_invalidated',reason='invalid_buffered_stop'));continue
            e.update(ihs_risk_version=4,ihs_entry_atr=atr,
                     ihs_min_stop_atr=self.rules['min_stop_atr'],ihs_stop_buffer_atr=self.rules['stop_buffer_atr'],
                     ihs_reclaim_sessions=self.rules['reclaim_sessions'],entry_mode='ihs_retest', rebound_confirmed_at=b.date,
                     ihs_retest_low=low.low, ihs_retest_date=low.date,
                     ihs_retest_confirmed=b.date,
                     ihs_entry_ceiling=neck*(1+self.rules['max_neckline_distance']),
                     execution_stop_rule='right_shoulder_below_atr', ihs_stop_rule='right_shoulder')
            intent = Intent(self.name, b.symbol, b.date, b.close, stop,
                            e['ihs_target'], seed.setup_id, 'inverse_head_shoulders', e)
            intents.append(intent)
            events.append(dict(base, event='entry_intent', trigger=intent.trigger,
                               stop=intent.stop, target=intent.target, **e))
        for event in source:
            events.append(dict(event, event='ihs_retest_registered'
                               if event['event'] == 'entry_intent' else event['event']))
        for seed in seeds:
            # The already-confirmed right shoulder is priced in today's factor.
            seed.evidence['ihs_right_low'] = next(x.low for x in bars
                if x.date == seed.evidence['ihs_right_date'])
        valid=[]
        for seed in seeds:
            left=next(x.low for x in bars if x.date==seed.evidence['ihs_left_date'])
            if seed.evidence['ihs_right_low']<left:
                events.append(dict(date=b.date,symbol=b.symbol,strategy=self.name,setup_id=seed.setup_id,event='ihs_retest_invalidated',reason='right_shoulder_below_left'))
            else:valid.append(seed)
        remaining.extend(valid)
        self.waiting[b.symbol] = remaining
        return intents, events

    def manage_position(self,history,position):
        bars=adjusted(history);neck=position.plan['ihs_neckline']
        n=position.plan.get('ihs_reclaim_sessions',self.rules['reclaim_sessions'])
        held=[b for b in bars if b.date>=position.entry_date]
        if len(held)>=n and all(b.close<neck for b in held[-n:]):
            return [ExitIntent(self.name,bars[-1].symbol,bars[-1].date,position.setup_id,'ihs_neckline_not_reclaimed')],[]
        return super().manage_position(history,position)
