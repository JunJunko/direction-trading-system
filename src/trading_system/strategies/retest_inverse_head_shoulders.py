"""Confirmed IHS neckline retest; breakout only registers a waiting setup."""
import math
from ..domain import Intent
from .enclosing_inverse_head_shoulders import EnclosingInverseHeadShoulders


class RetestInverseHeadShoulders(EnclosingInverseHeadShoulders):
    def __init__(self, name, params):
        params = dict(params)
        self.rules = dict(retest_sessions=14, touch_tolerance=.005,
                          failure_tolerance=.025, max_neckline_distance=.02)
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
            if len(after) > self.rules['retest_sessions']:
                reason = 'expired'
            elif min(x.low for x in after) <= e['ihs_floor']:
                reason = 'head_broken'
            elif min(x.low for x in after) <= e['ihs_right_low']:
                reason = 'right_shoulder_broken'
            elif min(x.low for x in after) < neck*(1-self.rules['failure_tolerance']):
                reason = 'neckline_retest_failed'
            elif max(x.high for x in after) >= e['ihs_target']:
                reason = 'target_already_touched'
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
            e.update(entry_mode='ihs_retest', rebound_confirmed_at=b.date,
                     ihs_retest_low=low.low, ihs_retest_date=low.date,
                     ihs_retest_confirmed=b.date,
                     ihs_entry_ceiling=neck*(1+self.rules['max_neckline_distance']),
                     execution_stop_rule='right_shoulder_low', ihs_stop_rule='right_shoulder')
            intent = Intent(self.name, b.symbol, b.date, b.close, e['ihs_right_low'],
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
        remaining.extend(seeds)
        self.waiting[b.symbol] = remaining
        return intents, events
