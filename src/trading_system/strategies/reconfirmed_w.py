"""One additional opportunity after a filled W is stopped and forms a new low."""
import copy
from ..domain import Intent
from .pressure_support_w import PressureSupportW


class ReconfirmedW(PressureSupportW):
    def __init__(self, name, params):
        super().__init__(name, params)
        self.retries = {}
        self.finished_retries = set()

    def on_stop_closed(self, position, date):
        if position.plan.get('retry_origin') or position.setup_id in self.finished_retries:
            return []
        self.retries[position.setup_id] = dict(symbol=position.symbol, exit_date=date,
            factor=position.factor, plan=copy.deepcopy(position.plan))
        return [dict(date=date, symbol=position.symbol, strategy=self.name,
                     setup_id=position.setup_id, event='retry_armed')]

    def retry_on_close(self, history):
        bar = history[-1]
        intents, events = [], []
        for origin, state in list(self.retries.items()):
            if state['symbol'] != bar.symbol:
                continue
            after = [b for b in history if b.date > state['exit_date']]
            if not after:
                continue
            plan = copy.deepcopy(state['plan'])
            scale = state['factor'] / bar.factor
            for key in ('w_neckline', 'w_floor', 'w_target', 'breakout_reference'):
                plan[key] *= scale
            lows = [b.low*b.factor/bar.factor for b in after]
            highs = [b.high*b.factor/bar.factor for b in after]
            cancel = None
            if len(after) > 14:
                cancel = 'expired'
            elif bar.close < plan['w_floor']:
                cancel = 'structure_failed'
            elif max(highs) >= plan['w_target']:
                cancel = 'target_already_reached'
            pivots = [i for i in range(2, len(after)-2)
                      if lows[i] < min(lows[i-2:i]+lows[i+1:i+3])
                      and min(lows[i+1:]) >= lows[i]]
            if cancel:
                events.append(dict(date=bar.date,symbol=bar.symbol,strategy=self.name,
                    setup_id=origin,event='retry_cancelled',reason=cancel))
            elif pivots and bar.close > max(plan['w_neckline'], bar.open,
                                            after[-2].close*after[-2].factor/bar.factor):
                pivot = pivots[-1]
                stop = lows[pivot]
                pid = origin + ':retry:' + after[pivot].date
                plan.update(retry_origin=origin,retry_exit_date=state['exit_date'],
                    retry_low_date=after[pivot].date,retry_confirmed_at=after[pivot+2].date,
                    w_retest_low=stop,w_retest_low_date=after[pivot].date,
                    w_retest_confirmed=bar.date,rebound_confirmed_at=bar.date,
                    entry_order='next_open',factor=bar.factor)
                intent = Intent(self.name,bar.symbol,bar.date,bar.close,stop,
                    plan['w_target'],pid,'direct_w',plan)
                intents.append(intent)
                events.append(dict(date=bar.date,symbol=bar.symbol,strategy=self.name,
                    setup_id=pid,event='entry_intent',trigger=bar.close,stop=stop,
                    target=plan['w_target'],**plan))
                cancel = 'submitted'
            if cancel:
                del self.retries[origin]
                self.finished_retries.add(origin)
        return intents, events

    def on_close(self, history, week_ends):
        intents, events = super().on_close(history, week_ends)
        extra, logs = self.retry_on_close(history)
        return intents+extra, events+logs
