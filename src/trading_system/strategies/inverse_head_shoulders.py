"""Confirmed inverse head-and-shoulders, with a horizontal neckline."""
import math

from ..analysis import adjusted
from ..domain import Intent, ExitIntent
from ..structure import SwingCache


class InverseHeadShoulders:
    def __init__(self, name, params):
        self.name = name
        self.p = dict(left=2, right=2, shoulder_tolerance=.06, neckline_tolerance=.03)
        if set(params) - set(self.p):
            raise ValueError('Unknown inverse head-and-shoulders parameters')
        self.p.update(params)
        for key in ('left', 'right'):
            if type(self.p[key]) is not int or self.p[key] < 1:
                raise ValueError(key)
        for key in ('shoulder_tolerance', 'neckline_tolerance'):
            value = self.p[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < 1:
                raise ValueError(key)
        self.caches = {}
        self.last = {}
        self.seen = set()
        self.adjusted_bars = {}

    def normalized_history(self, history):
        """Exact adjusted() values for append-only input; rebuild on factor change."""
        b = history[-1]
        cached = self.adjusted_bars.get(b.symbol)
        if (cached is not None and cached[0] == b.factor and
                len(history) == len(cached[2]) + 1 and history[-2] == cached[1]):
            values = cached[2]
            values.extend(adjusted(history[-1:]))
        else:
            values = adjusted(history)
        self.adjusted_bars[b.symbol] = (b.factor, b, values)
        return values

    def on_close(self, history, week_ends):
        if not history:
            return [], []
        b = history[-1]
        if self.last.get(b.symbol) == b.date:
            return [], []
        self.last[b.symbol] = b.date
        bars = self.normalized_history(history)
        points = self.caches.setdefault(b.symbol, SwingCache(self.p['left'], self.p['right'])).get(bars)
        candidates, events = [], []
        now = len(bars) - 1
        for i in range(len(points) - 4):
            left, peak1, head, peak2, right = points[i:i + 5]
            if tuple(p.kind for p in (left, peak1, head, peak2, right)) != ('low', 'high', 'low', 'high', 'low'):
                continue
            identity = ':'.join([self.name, b.symbol] + [bars[p.index].date for p in (left, head, right)])
            if identity in self.seen:
                continue
            if not 0 < head.price < min(left.price, right.price):
                continue
            if abs(right.price / left.price - 1) > self.p['shoulder_tolerance']:
                continue
            if abs(peak2.price / peak1.price - 1) > self.p['neckline_tolerance']:
                continue
            neck = max(peak1.price, peak2.price)
            if min(peak1.price, peak2.price) <= max(left.price, right.price):
                continue
            # Require an observable decline into the left shoulder.
            prior = [p for p in points[:i] if p.kind == 'high']
            if not prior or prior[-1].price <= neck:
                continue
            event = dict(date=b.date, symbol=b.symbol, strategy=self.name, setup_id=identity)
            if min(x.low for x in bars[head.index + 1:]) <= head.price:
                self.seen.add(identity)
                events.append(dict(event, event='ihs_structure_invalidated'))
                continue
            # Consume only the first close breakout; a confirmation delay is allowed,
            # but cannot resurrect a target already reached before confirmation.
            breakout = next((j for j in range(right.index + 1, now + 1) if bars[j].close > neck), None)
            if breakout is None:
                continue
            known = max(p.confirmed for p in (left, peak1, head, peak2, right))
            if now != max(known, breakout):
                continue
            self.seen.add(identity)
            target = 2 * neck - head.price
            if b.close <= neck:
                events.append(dict(event, event='ihs_neckline_not_held'))
                continue
            if max(x.high for x in bars[breakout:]) >= target:
                events.append(dict(event, event='ihs_space_exhausted'))
                continue
            evidence = dict(entry_mode='ihs_neckline', entry_order='next_open',
                rebound_confirmed_at=b.date, breakout_reference=neck,
                ihs_left_date=bars[left.index].date, ihs_head_date=bars[head.index].date,
                ihs_right_date=bars[right.index].date, ihs_peak1_date=bars[peak1.index].date,
                ihs_peak2_date=bars[peak2.index].date, ihs_known_at=b.date,
                ihs_breakout_date=bars[breakout].date, ihs_neckline=neck,
                ihs_floor=head.price, ihs_target=target, ihs_owner=identity,
                target_rule='neckline_plus_head_height',
                target_exit_rule='close_confirmed_next_open',
                support_exit_on_touch=True, factor=b.factor)
            intent = Intent(self.name, b.symbol, b.date, b.close, head.price, target,
                            identity, 'inverse_head_shoulders', evidence)
            candidates.append((intent, (right.index - left.index + 1) * (neck - head.price), right.index))
        if not candidates:
            return [], events
        intent, _, _ = max(candidates, key=lambda item: (item[1], item[2], item[0].setup_id))
        events.append(dict(date=b.date, symbol=b.symbol, strategy=self.name,
                           setup_id=intent.setup_id, event='entry_intent',
                           trigger=intent.trigger, stop=intent.stop, target=intent.target,
                           **intent.evidence))
        return [intent], events

    def trailing_stop(self, history, position):
        return position.stop

    def manage_position(self, history, position):
        b = history[-1]
        if b.close >= position.plan['ihs_target']:
            return [ExitIntent(self.name, b.symbol, b.date, position.setup_id,
                               'ihs_target_close_confirmed')], []
        return [], []
