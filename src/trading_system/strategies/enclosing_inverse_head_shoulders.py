"""Causal enclosing inverse H&S; quality ratios use the pattern's own height."""
import math

from ..domain import Intent
from ..structure import SwingCache
from .inverse_head_shoulders import InverseHeadShoulders


class _PriceRanges:
    """Append-only sparse ranges; exact extrema with latest-index tie breaking."""
    def __init__(self):
        self.count = 0
        self.anchor = None
        self.last = None
        self.tables = [[[]] for _ in range(3)]

    def update(self, bars):
        if (self.anchor != bars[-1].factor or len(bars) < self.count or
                (self.count and bars[self.count - 1] != self.last)):
            self.count = 0
            self.tables = [[[]] for _ in range(3)]
        for i in range(self.count, len(bars)):
            for table, value in zip(self.tables, (-bars[i].low, bars[i].high, bars[i].close)):
                table[0].append((value, i))
                for level in range(1, (i + 1).bit_length()):
                    if len(table) <= level:
                        table.append([None] * ((1 << level) - 1))
                    table[level].append(max(table[level - 1][i],
                                            table[level - 1][i - (1 << (level - 1))]))
        self.count = len(bars)
        self.anchor = bars[-1].factor
        self.last = bars[-1]
        return self

    def query(self, kind, start, end):
        """[start, end), returning (price, index)."""
        if not 0 <= start < end <= self.count:
            raise ValueError('Invalid price range')
        table = self.tables[{'low': 0, 'high': 1, 'close': 2}[kind]]
        level = (end - start).bit_length() - 1
        price, index = max(table[level][start + (1 << level) - 1], table[level][end - 1])
        return (-price if kind == 'low' else price), index

    def first_close_above(self, start, end, price):
        if start >= end or self.query('close', start, end)[0] <= price:
            return None
        left, right = start, end - 1
        while left < right:
            middle = (left + right) // 2
            if self.query('close', left, middle + 1)[0] > price:
                right = middle
            else:
                left = middle + 1
        return left


class EnclosingInverseHeadShoulders(InverseHeadShoulders):
    def __init__(self, name, params):
        defaults = dict(left=2, right=2, min_head_height=.20,
                        max_shoulder_height=.20, max_neckline_height=.10)
        if set(params) - set(defaults):
            raise ValueError('Unknown enclosing inverse H&S parameters')
        defaults.update(params)
        super().__init__(name, {k: defaults[k] for k in ('left', 'right')})
        for key in ('min_head_height', 'max_shoulder_height', 'max_neckline_height'):
            value = defaults[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or not 0 <= value < 1 or
                    (key == 'min_head_height' and value == 0)):
                raise ValueError(key)
        self.p = defaults
        self.ranges = {}

    def candidate_layouts(self, bars, points, ranges):
        """Enumerate shoulders; the enclosing intervals determine head and peaks."""
        now = len(bars) - 1
        lows = [p for p in points if p.kind == 'low' and p.confirmed <= now]
        low_by_index = {p.index: p for p in lows}
        highs = [p for p in points if p.kind == 'high' and p.confirmed <= now]
        high_by_index = {p.index: p for p in highs}
        layouts = []
        for r, right in enumerate(lows):
            if r < 2 or right.index >= now:
                continue
            # The right shoulder must still own the post-peak valley.
            if ranges.query('low', right.index, now + 1)[0] < right.price:
                continue
            # After confirmation, only a new post-shoulder closing high can be
            # the first neckline break. A newly confirmed shoulder may be late.
            if (right.confirmed < now and right.index + 1 < now and
                    ranges.query('close', right.index + 1, now)[0] >= bars[-1].close):
                continue
            for left in lows[:r - 1]:
                floor, head_index = ranges.query('low', left.index + 1, right.index)
                head = low_by_index.get(head_index)
                if head is None or not 0 < floor < min(left.price, right.price):
                    continue
                if head.index <= left.index + 1 or right.index <= head.index + 1:
                    continue
                peak1_price, peak1_index = ranges.query('high', left.index + 1, head.index)
                peak2_price, peak2_index = ranges.query('high', head.index + 1, right.index)
                peak1, peak2 = high_by_index.get(peak1_index), high_by_index.get(peak2_index)
                # Equal-height touches may have been compressed by SwingCache.
                # A previously confirmed occurrence of the same maximum is valid.
                if peak1 is None:
                    peak1 = next((p for p in reversed(highs) if left.index < p.index < head.index
                                  and p.price == peak1_price), None)
                if peak2 is None:
                    peak2 = next((p for p in reversed(highs) if head.index < p.index < right.index
                                  and p.price == peak2_price), None)
                # An ambiguous outside bar or unconfirmed extreme cannot own a peak.
                if peak1 is None or peak2 is None:
                    continue
                neck = max(peak1_price, peak2_price)
                if min(peak1_price, peak2_price) <= max(left.price, right.price):
                    continue
                height = neck - floor
                prominence = (min(left.price, right.price) - floor) / height
                shoulder_gap = abs(left.price - right.price) / height
                neck_gap = abs(peak1_price - peak2_price) / height
                if (prominence + 1e-12 < self.p['min_head_height'] or
                        shoulder_gap > self.p['max_shoulder_height'] + 1e-12 or
                        neck_gap > self.p['max_neckline_height'] + 1e-12):
                    continue
                origins = [p for p in highs if p.index < left.index and p.price > neck]
                if not origins:
                    continue
                origin = origins[-1]
                # Each shoulder is the valley of its enclosing side. Internal
                # higher troughs are allowed; deeper troughs cannot be skipped.
                if ranges.query('low', origin.index + 1, peak1.index)[0] < left.price:
                    continue
                if ranges.query('low', peak2.index + 1, now + 1)[0] < right.price:
                    continue
                # A flat head is one trough, but separated equal/deeper heads
                # are a different structure. Do not join two heads together.
                head_start = head.index
                while head_start > peak1.index + 1 and bars[head_start - 1].low == floor:
                    head_start -= 1
                if (head_start > peak1.index + 1 and
                        ranges.query('low', peak1.index + 1, head_start)[0] <= floor):
                    continue
                if ranges.query('low', head.index + 1, now + 1)[0] <= floor:
                    continue
                breakout = ranges.first_close_above(right.index + 1, now + 1, neck)
                if breakout is None:
                    continue
                known = max(p.confirmed for p in (left, peak1, head, peak2, right))
                if max(known, breakout) != now:
                    continue
                layouts.append(dict(left=left, head=head, right=right, peak1=peak1, peak2=peak2,
                    origin=origin, neckline=neck, floor=floor, breakout=breakout,
                    prominence=prominence, shoulder_gap=shoulder_gap, neck_gap=neck_gap,
                    area=(right.index-left.index+1)*height))
        return layouts

    def on_close(self, history, week_ends):
        if not history:
            return [], []
        b = history[-1]
        if self.last.get(b.symbol) == b.date:
            return [], []
        self.last[b.symbol] = b.date
        bars = self.normalized_history(history)
        points = self.caches.setdefault(b.symbol, SwingCache(self.p['left'], self.p['right'])).get(bars)
        ranges = self.ranges.setdefault(b.symbol, _PriceRanges()).update(bars)
        candidates, events = [], []
        for w in self.candidate_layouts(bars, points, ranges):
            left, head, right = (w[k] for k in ('left', 'head', 'right'))
            identity = ':'.join([self.name, b.symbol] + [bars[p.index].date for p in (left, head, right)])
            if identity in self.seen:
                continue
            self.seen.add(identity)
            neck, floor = w['neckline'], w['floor']
            target = 2*neck-floor
            event = dict(date=b.date, symbol=b.symbol, strategy=self.name, setup_id=identity)
            if b.close <= neck:
                events.append(dict(event, event='ihs_neckline_not_held'))
                continue
            if ranges.query('high', w['breakout'], len(bars))[0] >= target:
                events.append(dict(event, event='ihs_space_exhausted'))
                continue
            evidence = dict(entry_mode='ihs_neckline', entry_order='next_open',
                rebound_confirmed_at=b.date, breakout_reference=neck,
                ihs_left_date=bars[left.index].date, ihs_head_date=bars[head.index].date,
                ihs_right_date=bars[right.index].date, ihs_peak1_date=bars[w['peak1'].index].date,
                ihs_peak2_date=bars[w['peak2'].index].date, ihs_origin_date=bars[w['origin'].index].date,
                ihs_known_at=b.date, ihs_breakout_date=bars[w['breakout']].date,
                ihs_neckline=neck, ihs_floor=floor, ihs_target=target, ihs_owner=identity,
                ihs_search='enclosing', ihs_head_prominence=w['prominence'],
                ihs_shoulder_gap=w['shoulder_gap'], ihs_neckline_gap=w['neck_gap'],
                target_rule='neckline_plus_head_height', target_exit_rule='close_confirmed_next_open',
                support_exit_on_touch=True, factor=b.factor)
            intent = Intent(self.name, b.symbol, b.date, b.close, floor, target,
                            identity, 'inverse_head_shoulders', evidence)
            candidates.append((intent, w['area'], right.index))
        if not candidates:
            return [], events
        intent, _, _ = max(candidates, key=lambda x: (x[1], x[2], x[0].setup_id))
        events.append(dict(date=b.date, symbol=b.symbol, strategy=self.name, setup_id=intent.setup_id,
            event='entry_intent', trigger=intent.trigger, stop=intent.stop, target=intent.target, **intent.evidence))
        return [intent], events
