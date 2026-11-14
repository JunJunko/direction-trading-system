"""v7 experiment: confirmed pressure breakout becomes next-session support."""
import math
from dataclasses import replace
from .domain import ExitIntent
from .main_trend import completed_weeks
from .confirmed_support_trend import confirmed_weekly_points
from .ihs_geometry import atr_before


class PressureSupportTrend:
    def __init__(self, name, calendar, weekends, *, breakout_atr=.1):
        if type(breakout_atr) not in (int, float) or not math.isfinite(breakout_atr) or breakout_atr < 0:
            raise ValueError('Invalid pressure breakout buffer')
        self.name, self.calendar, self.weekends = name, calendar, set(weekends)
        self.breakout_atr = breakout_atr
        self.protection = self.pressure = None  # Economic units, invariant under factor changes.
        self.support_source = None
        self.levels = {}
        self.initialized = self.pending = False
        self.last_date = None

    def _add_pressure(self, point, bar, floor, events, origin):
        level = point['price']
        if level <= floor or (self.pressure is not None and level < self.pressure):
            return  # Do not move the monitored pressure down during this position.
        if level in self.levels:
            return
        self.levels[level] = dict(point)
        self.pressure = min(self.levels)
        events.append(dict(date=bar.date, event='dynamic_pressure_confirmed', formed=point['date'],
            confirmed=point['confirmed'], pressure=level / bar.factor, economic_pressure=level,
            origin=origin, effective='next_session' if point['confirmed'] == bar.date else 'already_known'))

    def _raise_support(self, level, bar, position, events, source, formed, confirmed):
        floor = position.stop * position.factor
        old = self.protection
        if level <= max(floor, old if old is not None else floor):
            return
        self.protection, self.support_source = level, source
        events.append(dict(date=bar.date, event='main_protection_raised', formed=formed,
            confirmed=confirmed, old=old, new=level, raw_protection=level / bar.factor,
            source=source, effective='next_session', exit_clock='daily'))
        self.levels = {k: v for k, v in self.levels.items() if k > level}
        self.pressure = min(self.levels) if self.levels else None

    def manage(self, history, position):
        bar = history[-1]
        if self.pending or self.last_date == bar.date:
            return [], []
        self.last_date = bar.date
        events = []
        price = bar.close * bar.factor
        floor = position.stop * position.factor
        # The level was active before today's bar. A close signal is executed later by the engine.
        if self.protection is not None and price < self.protection:
            self.pending = True
            return [ExitIntent(self.name, bar.symbol, bar.date, position.setup_id, 'dynamic_support_daily_break')], [dict(
                date=bar.date, event='dynamic_support_daily_break', protection=self.protection / bar.factor,
                economic_protection=self.protection, support_source=self.support_source,
                execution='next_executable_open')]
        if not self.initialized:
            # Entry uses only overhead weekly highs confirmed before this close.
            # Already-broken levels below the entry fill cannot retrospectively tighten entry risk.
            points = confirmed_weekly_points(completed_weeks(history[:-1], self.calendar)) if len(history) > 1 else []
            overhead = [v for v in points if v['kind'] == 'H'
                        and v['price'] > max(floor, position.entry * position.factor)]
            for v in sorted(overhead, key=lambda v: v['price']):
                self._add_pressure(v, bar, floor, events, 'known_before_entry_close')
            self.initialized = True
        # Only historical OHLC contributes to the breakout buffer, including across factor changes.
        economic = [replace(b, open=b.open*b.factor, high=b.high*b.factor,
                            low=b.low*b.factor, close=b.close*b.factor, factor=1)
                    for b in history[-16:]]
        atr = atr_before(economic, len(economic)-1)
        if self.pressure is not None and atr is not None:
            crossed = [k for k in self.levels if price > k + self.breakout_atr*atr]
            if crossed:
                level = max(crossed)
                point = self.levels[level]
                events.append(dict(date=bar.date, event='dynamic_pressure_breakout',
                    broken_pressures=[k/bar.factor for k in sorted(crossed)],
                    confirmed=bar.date, pressure_confirmed=point['confirmed'],
                    pressure_formed=point['date'], atr=atr/bar.factor,
                    breakout_atr=self.breakout_atr, action='hold_and_raise_support'))
                self._raise_support(level, bar, position, events, 'broken_confirmed_pressure',
                                    point['date'], bar.date)
                if self.pressure is None:
                    events.append(dict(date=bar.date, event='no_confirmed_overhead_pressure', action='continue_holding'))
        # New pivots become available only on the final session of a complete confirmation week.
        if bar.date in self.weekends:
            weeks = completed_weeks(history, self.calendar)
            if weeks and weeks[-1]['date'] == bar.date:
                points = confirmed_weekly_points(weeks)
                for v in points:
                    if v['confirmed'] != bar.date:
                        continue
                    if v['kind'] == 'L' and v['start'] > position.entry_date:
                        self._raise_support(v['price'], bar, position, events, 'confirmed_weekly_low',
                                            v['date'], v['confirmed'])
                    elif v['kind'] == 'H':
                        self._add_pressure(v, bar, max(floor, self.protection or floor), events, 'newly_confirmed')
        return [], events
