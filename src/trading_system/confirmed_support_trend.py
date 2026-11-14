"""Fixed weekly support identification, independent of trend HH confirmation."""
from .domain import ExitIntent
from .main_trend import completed_weeks, confirmed_sequences


def confirmed_weekly_points(weeks):
    """Strict left2/right2 pivots, without alternating-wave compression."""
    points = []
    for i in range(2, len(weeks) - 2):
        window = weeks[i - 2:i + 3]
        if window[-1]['index'] - window[0]['index'] != 4:
            continue
        current = weeks[i]
        low = all(current['low'] < w['low'] for w in window if w is not current)
        high = all(current['high'] > w['high'] for w in window if w is not current)
        if low == high:
            continue  # Keep v5's treatment of ambiguous outside weeks.
        points.append(dict(current, kind='L' if low else 'H',
                           price=current['low' if low else 'high'],
                           confirmed=weeks[i + 2]['date']))
    return points


class ConfirmedSupportTrend:
    def __init__(self, name, calendar, weekends, *, support_mode='independent', exit_clock='daily'):
        if support_mode not in ('independent', 'sequence') or exit_clock not in ('daily', 'weekly'):
            raise ValueError('Unknown support experiment')
        self.name, self.calendar, self.weekends = name, calendar, set(weekends)
        self.support_mode, self.exit_clock = support_mode, exit_clock
        self.protection = self.pressure = None  # Economic factor-invariant prices.
        self.pending = False

    def manage(self, history, position):
        b = history[-1]
        if self.pending:
            return [], []  # Engine retains blocked exit orders until executable.
        events = []
        price = b.close * b.factor
        # Previously active level only. No same-bar retroactive application.
        if (self.protection is not None and price < self.protection
                and (self.exit_clock == 'daily' or b.date in self.weekends)):
            # Weekly ablation retains the original complete-week requirement.
            ws = completed_weeks(history, self.calendar) if self.exit_clock == 'weekly' else None
            if self.exit_clock == 'daily' or (ws and ws[-1]['date'] == b.date):
                self.pending = True
                reason = 'confirmed_support_daily_break' if self.exit_clock == 'daily' else 'confirmed_support_weekly_break'
                return [ExitIntent(self.name, b.symbol, b.date, position.setup_id, reason)], [dict(
                    date=b.date, event=reason, protection=self.protection / b.factor,
                    economic_protection=self.protection, execution='next_executable_open')]
        if self.pressure is not None and price > self.pressure:
            events.append(dict(date=b.date, event='main_pressure_broken',
                               pressure=self.pressure / b.factor, economic_pressure=self.pressure))
            self.pressure = None
        if b.date not in self.weekends:
            return [], events
        weeks = completed_weeks(history, self.calendar)
        if not weeks or weeks[-1]['date'] != b.date:
            return [], events
        points = confirmed_weekly_points(weeks)
        for v in points:
            if v['kind'] == 'H' and v['confirmed'] == b.date and v['start'] > position.entry_date:
                self.pressure = v['price']
                events.append(dict(date=b.date, event='main_pressure_confirmed', formed=v['date'],
                    confirmed=v['confirmed'], pressure=v['price'] / b.factor,
                    economic_pressure=v['price'], role='observe_only_no_target_exit'))
        lows = ([v for v in points if v['kind'] == 'L'] if self.support_mode == 'independent'
                else confirmed_sequences(weeks))
        for v in lows:
            if v['start'] <= position.entry_date or v['confirmed'] != b.date:
                continue
            floor = position.stop * position.factor
            active = max(floor, self.protection if self.protection is not None else floor)
            if v['price'] <= active:
                events.append(dict(date=b.date, event='main_support_not_raised', formed=v['date'],
                    confirmed=v['confirmed'], candidate=v['price'] / b.factor,
                    active=active / b.factor, reason='not_above_active_protection'))
                continue
            old, self.protection = self.protection, v['price']
            events.append(dict(date=b.date, event='main_protection_raised', formed=v['date'],
                confirmed=v['confirmed'], old=old, new=self.protection,
                raw_protection=self.protection / b.factor, support_mode=self.support_mode,
                exit_clock=self.exit_clock, effective='next_session'))
        return [], events
