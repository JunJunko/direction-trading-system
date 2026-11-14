"""Completed-hour event clock; daily parents and holding updates remain daily."""
from dataclasses import replace
from .data import validate_intraday

ENDS=('103000','113000','140000','150000')
STARTS=('093000','103000','130000','140000')


def run_hourly(engine,bars,calendar,week_ends,lower_bars,evaluation_start,evaluation_end,universe,progress):
    e=engine
    if evaluation_start and evaluation_end and evaluation_start>evaluation_end:
        raise ValueError('Evaluation start must not exceed end')
    if not lower_bars:raise ValueError('Hourly entry clock requires real completed hourly bars')
    if not calendar or calendar!=sorted(set(calendar)):raise ValueError('Invalid trading calendar')
    validate_intraday(lower_bars)
    daily={};by_date={};hours={}
    for b in bars:
        if b.date not in calendar:raise ValueError('Daily bar falls outside calendar')
        key=(b.symbol,b.date)
        if key in daily:raise ValueError('Duplicate daily observation')
        daily[key]=b
        by_date.setdefault(b.date,{})[b.symbol]=b
    # Offline integrity checks may examine the full input; decision callbacks
    # receive only the chronological prefix below, never these daily extrema.
    for b in lower_bars:
        day=daily.get((b.symbol,b.date[:8]))
        if not day:raise ValueError('Hourly bar has no corresponding daily observation')
        if b.factor!=day.factor:raise ValueError('Hourly and daily factor bases disagree')
        tolerance=max(1e-5,day.close*1e-5)
        if b.low<day.low-tolerance or b.high>day.high+tolerance:
            raise ValueError('Hourly and daily price ranges disagree')
        if b.date.endswith('150000') and abs(b.close-day.close)>tolerance:
            raise ValueError('Hourly session close disagrees with daily close')
        hours.setdefault(b.date,{})[b.symbol]=replace(b,up_limit=day.up_limit,down_limit=day.down_limit)
    owners={s.name:s for s in e.strategies}
    for s in e.strategies:s.set_calendar(calendar)
    begun=False
    for index,date in enumerate(calendar):
        if evaluation_end and date>evaluation_end:break
        warm=bool(evaluation_start and date<evaluation_start)
        today=by_date.get(date,{})
        if progress and index%20==0:
            progress(dict(session=index,date=date,equity=e.equity(),trades=len(e.trades),entry_clock='hourly'))
        if not warm and not begun:
            for s in e.strategies:e.events.extend(s.begin_evaluation(date))
            begun=True
        # Corporate actions use the same explicit synthetic convention as the
        # daily baseline. Factor/limits are session metadata, not future prices.
        if not warm:e.adjust_factors(today,date)
        for end,start in zip(ENDS,STARTS):
            timestamp=date+end
            interval=hours.get(timestamp,{})
            if not warm:
                missing=[symbol for symbol in e.positions if symbol in today and today[symbol].volume>0 and symbol not in interval]
                if missing:raise ValueError('Missing hourly session for an open position: '+','.join(sorted(missing)))
                # Only interval opens / preceding completed marks enter sizing.
                e.marks.update({symbol:b.open for symbol,b in interval.items()})
                e.refresh_context(date)
                e.execute_interval(interval,date,universe,e.cash,
                    dict(bar_end=timestamp,window_start=date+start,entry_clock='hourly',
                         fill_time_precision='hourly_interval'))
            for symbol,b in sorted(interval.items()):
                e.lower_histories.setdefault(symbol,[]).append(b)
                e.marks[symbol]=b.close
            if end=='150000':
                for symbol,b in sorted(today.items()):
                    e.histories.setdefault(symbol,[]).append(b)
                    e.marks[symbol]=b.close
                # Publish the newly completed daily core before this close's
                # hourly observation. Its first executable interval is tomorrow.
                if warm:
                    for s in e.strategies:s.set_context(dict(lower_histories=e.lower_histories,entry_clock='hourly'))
                else:e.refresh_context(date)
                for symbol,b in sorted(today.items()):
                    history=e.histories[symbol]
                    for s in e.strategies:
                        new,events=s.on_close(history,week_ends)
                        if new:raise ValueError('Hourly clock received a daily entry intent')
                        (e.warmup_events if warm else e.events).extend(events)
                    if not warm and symbol in e.positions:
                        p=e.positions[symbol];owner=owners[p.strategy]
                        exits,events=owner.manage_position(history,p)
                        e.events.extend(events)
                        for intent in exits:
                            if not any(x.symbol==intent.symbol and x.setup_id==intent.setup_id for x in e.pending_exits):
                                e.pending_exits.append(intent)
                                e.log(date,symbol,p.strategy,'exit_intent',reason=intent.reason,setup_id=p.setup_id)
                        stop=owner.trailing_stop(history,p)
                        if stop>p.stop:
                            e.log(date,symbol,p.strategy,'stop_raised',old_stop=p.stop,new_stop=stop)
                            p.stop=stop
            if warm:
                for s in e.strategies:s.set_context(dict(lower_histories=e.lower_histories,entry_clock='hourly'))
            else:e.refresh_context(date)
            for symbol,b in sorted(interval.items()):
                for s in e.strategies:
                    new,events=s.on_hour_close(e.histories.get(symbol,[]),b,week_ends)
                    (e.warmup_events if warm else e.events).extend(events)
                    if warm or symbol in e.positions:continue
                    for intent in new:
                        if intent.date>timestamp:raise ValueError('Future hourly intent')
                        if universe and not universe.eligible(symbol,date):
                            e.log(timestamp,symbol,s.name,'entry_rejected',reason='universe_ineligible_signal',setup_id=intent.setup_id)
                            continue
                        assessment=e.assess_entry(intent,intent.trigger*(1+e.config['execution']['slippage']),
                                                  e.equity(),e.cash,e.marks,date)
                        e.entry_audits.append(dict(assessment,date=date,signal_date=intent.date,observed_at=timestamp,
                            symbol=symbol,strategy=s.name,setup_id=intent.setup_id,trigger=intent.trigger,
                            stop=intent.stop,target=intent.target,initial_rhythm_floor=intent.evidence.get('initial_rhythm_floor'),
                            parent_known_at=intent.evidence.get('parent_known_at'),
                            execution_reason='plan_approved' if assessment['quantity'] else 'plan_rejected',filled_quantity=0))
                        e.log(timestamp,symbol,s.name,'plan_approved' if assessment['quantity'] else 'plan_rejected',
                            setup_id=intent.setup_id,reason=assessment['risk_reason'])
                        if assessment['quantity']:e.pending.append(intent)
        if warm:continue
        equity=e.equity();e.peak=max(e.peak,equity)
        e.curve.append(dict(date=date,equity=equity,cash=e.cash,gross_weight=(equity-e.cash)/equity,
                            drawdown=equity/e.peak-1,positions=len(e.positions)))
    return e
