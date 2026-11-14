from dataclasses import asdict, replace
from .domain import Position
from .risk import FixedAccountPolicy, RiskManager
from .account import PhasePolicy, AutomaticPolicy


class Backtest:
    def __init__(self, config, strategies):
        self.config, self.strategies = config, strategies
        execution = config['execution']
        if config['initial_cash']<=0 or execution['minimum_commission']!=5:
            raise ValueError('Positive capital and v1 minimum commission of 5 required')
        if not 0<=execution['slippage']<.1 or execution['commission_rate']<0:
            raise ValueError('Invalid execution costs')
        self.exit_order=execution.get('daily_exit_order','legacy_stop_first')
        if self.exit_order not in ('legacy_stop_first','open_first'):
            raise ValueError('Invalid daily exit order')
        self.entry_clock=execution.get('entry_clock','daily')
        if self.entry_clock not in ('daily','hourly'):raise ValueError('Invalid entry clock')
        if self.entry_clock=='hourly' and any(not hasattr(s,'on_hour_close') or s.p['lower_cycle']!='hourly' or s.p['core_mode']!='nested' for s in strategies):
            raise ValueError('Hourly entry clock requires nested hourly strategies')
        self.risk = RiskManager(config['risk'])
        if 'account_policy' in config and 'automatic_account_policy' in config:
            raise ValueError('Choose exactly one account policy')
        self.policy = (AutomaticPolicy(config['automatic_account_policy']) if 'automatic_account_policy' in config
                       else PhasePolicy(config['account_policy']) if 'account_policy' in config else FixedAccountPolicy())
        self.cash = config['initial_cash']
        self.positions, self.histories, self.marks = {}, {}, {}
        self.pending, self.events, self.orders, self.trades, self.curve = [], [], [], [], []
        self.entry_audits = []
        self.peak = self.cash
        self.pending_exits=[]
        for strategy in self.strategies:
            if hasattr(strategy,'set_execution_costs'):
                strategy.set_execution_costs(dict(execution))
        self.context={}
        self.lower_histories={}
        self.warmup_events=[]
        if config.get('research_scope') not in (None,'structure_only'):
            raise ValueError('Unknown research scope')
        if any(s.__class__.__name__=='DirectionDoubleBottom' for s in strategies) and not isinstance(self.policy,PhasePolicy) and config.get('research_scope')!='structure_only':
            raise ValueError('Direction system requires an explicit human phase policy')
        if any(s.__class__.__name__=='AutonomousDoubleBottom' for s in strategies):
            if not isinstance(self.policy,AutomaticPolicy):
                raise ValueError('Autonomous system requires automatic account policy')
            if config.get('research_scope')!='structure_only' and any(s.p['lower_cycle']!='hourly' for s in strategies if s.__class__.__name__=='AutonomousDoubleBottom'):
                raise ValueError('Production autonomous strategy requires real hourly data')

    def refresh_context(self,date):
        if isinstance(self.policy,(PhasePolicy,AutomaticPolicy)):
            self.context=self.policy.observe(date,self.equity())
            for strategy in self.strategies:
                if hasattr(strategy,'set_context'):
                    strategy.set_context(dict(self.context,lower_histories=self.lower_histories,entry_clock=self.entry_clock))

    def entry_guard(self,intent,date,phase):
        owner=next((s for s in self.strategies if s.name==intent.strategy),None)
        hook=getattr(owner,'entry_block',None)
        blocked=hook(intent,date,phase) if hook else None
        if blocked:return dict(quantity=0,candidate_quantity=0,**blocked)
        return None

    def entry_feedback(self,intent,date,phase,reason):
        owner=next((s for s in self.strategies if s.name==intent.strategy),None)
        hook=getattr(owner,'on_entry_result',None)
        if hook:self.events.extend(hook(intent,date,phase,reason))

    def protection_feedback(self,position,date):
        owner=next((s for s in self.strategies if s.name==position.strategy),None)
        hook=getattr(owner,'on_protection_failure',None)
        if hook:self.events.extend(hook(position,date))

    def assess_entry(self,intent,fill,equity,cash,marks,date,phase='signal'):
        blocked=self.entry_guard(intent,date,phase)
        if blocked:return dict(blocked,fill=fill,stop=intent.stop,target=intent.target)
        if intent.evidence.get('ihs_risk_version') == 5:
            from .ihs_geometry import neckline_at
            intent = replace(intent, evidence=dict(intent.evidence,
                ihs_execution_neckline=neckline_at(intent.evidence,date)))
        risk=self.risk
        if isinstance(self.policy,AutomaticPolicy):
            risk=RiskManager(self.policy.limits(self.config['risk']))
        if isinstance(self.policy,PhasePolicy):
            if not self.context['allow_entries']:
                return dict(quantity=0,risk_reason='phase_entry_gate_closed',stage_id=self.context['stage_id'])
            if intent.evidence.get('rhythm_kind')=='same_level' and not self.context['allow_same_level']:
                return dict(quantity=0,risk_reason='same_level_not_allowed',stage_id=self.context['stage_id'])
            limits=self.policy.limits(self.config['risk'],equity,self.positions,marks)
            if limits['max_gross_weight']<=0:
                return dict(quantity=0,risk_reason='phase_gross_limit_zero')
            limits['volatility_budget']=self.policy.p['volatility_budget']*self.context['multiplier']
            groups=self.policy.p.get('symbol_groups',{})
            if groups:
                if intent.symbol not in groups or any(s not in groups for s in self.positions):
                    return dict(quantity=0,risk_reason='missing_reviewed_symbol_group')
                group=groups[intent.symbol]
                same=sum(p.quantity*marks[s] for s,p in self.positions.items() if groups[s]==group)
                other=sum(p.quantity*marks[s] for s,p in self.positions.items() if groups[s]!=group)
                # Initial probes may start a group. Expansion needs other groups
                # supporting it; no one group may dominate the remaining exposure.
                probe=equity*self.policy.p['probe_gross_limit']*self.context['multiplier']
                headroom=max(probe,other)-same
                if headroom<=0:
                    return dict(quantity=0,risk_reason='group_expansion_not_supported')
                limits['max_position_weight']=min(limits['max_position_weight'],headroom/equity)
            risk=RiskManager(limits)
        result=risk.assess(intent,fill,equity,cash,self.positions,marks,
                           self.config['execution']['commission_rate'],self.tax(date),
                           1,self.config['execution']['slippage'])
        if intent.evidence.get('ihs_risk_version') == 5:
            result.update(decision='BUY_ALLOWED' if result['quantity'] else 'NO_TRADE',
                          execution_neckline=intent.evidence['ihs_execution_neckline'])
        if self.context:
            result.update(stage_id=self.context['stage_id'],contraction_steps=self.context['contraction_steps'],
                          win_expansion=self.context['win_expansion'])
        return result

    def equity(self):
        return self.cash+sum(p.quantity*self.marks[s] for s,p in self.positions.items())

    def fee(self, value, sell=False, date=''):
        e = self.config['execution']
        tax = self.tax(date) if sell else 0
        return max(e['minimum_commission'],value*e['commission_rate'])+value*tax

    def tax(self, date):
        return self.config['execution']['sell_tax_after_20230828'] if date >= '20230828' else self.config['execution']['sell_tax_before_20230828']

    def run(self, bars, calendar, week_ends, lower_bars=None, evaluation_start=None, evaluation_end=None, universe=None, progress=None):
        for strategy in self.strategies:
            if hasattr(strategy,'set_trend_calendar'):
                strategy.set_trend_calendar(calendar,week_ends)
        if self.entry_clock=='hourly':
            from .hourly_engine import run_hourly
            return run_hourly(self,bars,calendar,week_ends,lower_bars,evaluation_start,evaluation_end,universe,progress)
        if evaluation_start and evaluation_end and evaluation_start>evaluation_end:
            raise ValueError('Evaluation start must not exceed end')
        lower_by_date={}
        if lower_bars:
            from .data import validate_intraday
            validate_intraday(lower_bars)
            for bar in sorted(lower_bars,key=lambda x:(x.date,x.symbol)):
                if bar.date[:8] not in calendar:
                    raise ValueError('Hourly bars fall outside trading calendar')
                lower_by_date.setdefault(bar.date[:8],[]).append(bar)
        by_date = {}
        for b in bars:
            by_date.setdefault(b.date,{})[b.symbol]=b
        owners = {s.name:s for s in self.strategies}
        for strategy in self.strategies:
            if hasattr(strategy,'set_calendar'):
                strategy.set_calendar(calendar)
        evaluation_begun=False
        for index,date in enumerate(calendar):
            if evaluation_end and date>evaluation_end:
                break
            if progress and index%20==0:
                progress(dict(session=index,date=date,equity=self.equity(),trades=len(self.trades)))
            today = by_date.get(date,{})
            if evaluation_start and date<evaluation_start:
                # Warm the causal detector, not the account. No historical holdings,
                # cash changes or executable orders are carried into a flat start.
                for symbol,b in sorted(today.items()):
                    history=self.histories.setdefault(symbol,[])
                    history.append(b)
                    self.marks[symbol]=b.close
                    for strategy in self.strategies:
                        _,events=strategy.on_close(history,week_ends)
                        self.warmup_events.extend(events)
                for bar in lower_by_date.get(date,[]):
                    self.lower_histories.setdefault(bar.symbol,[]).append(bar)
                continue
            if not evaluation_begun:
                for strategy in self.strategies:
                    hook=getattr(strategy,'begin_evaluation',None)
                    if hook:
                        self.events.extend(hook(date))
                evaluation_begun=True
            self.refresh_context(date)
            entry_cash = self.cash  # Do not reuse same-session exit proceeds with unknown intraday ordering.
            self.adjust_factors(today,date)

            self.execute_interval(today,date,universe,entry_cash)

            for symbol,b in today.items():
                self.histories.setdefault(symbol,[]).append(b)
                self.marks[symbol]=b.close
            for bar in lower_by_date.get(date,[]):
                if bar.date<=date+'150000':
                    daily=today.get(bar.symbol)
                    if daily is None:
                        raise ValueError('Hourly bar has no corresponding daily observation')
                    scale=bar.factor/daily.factor
                    tolerance=max(1e-5,daily.close*1e-5)
                    if bar.low*scale<daily.low-tolerance or bar.high*scale>daily.high+tolerance:
                        raise ValueError('Hourly and daily price ranges disagree')
                    if bar.date.endswith('150000') and abs(bar.close*scale-daily.close)>tolerance:
                        raise ValueError('Hourly session close disagrees with daily close')
                    self.lower_histories.setdefault(bar.symbol,[]).append(bar)
            self.refresh_context(date)
            if self.context:
                self.log(date,'ACCOUNT','account_policy','phase_policy',**self.context)
            for symbol,b in sorted(today.items()):
                history = self.histories[symbol]
                for strategy in self.strategies:
                    new,events = strategy.on_close(history,week_ends)
                    self.events.extend(events)
                    if symbol not in self.positions:
                        for intent in new:
                            if universe and not universe.eligible(symbol,date):
                                self.log(date,symbol,strategy.name,'entry_rejected',reason='universe_ineligible_signal',setup_id=intent.setup_id)
                                if intent.evidence.get('ihs_risk_version') == 5:
                                    self.entry_audits.append(dict(date=date,signal_date=intent.date,symbol=symbol,
                                        strategy=intent.strategy,setup_id=intent.setup_id,decision='NO_TRADE',
                                        execution_reason='universe_ineligible_signal',filled_quantity=0))
                                continue
                            if isinstance(self.policy,PhasePolicy) or intent.reason in ('daily_n_rhythm','direct_w','inverse_head_shoulders'):
                                # Only affordable opportunities become executable plans.
                                fill=intent.trigger*(1+self.config['execution']['slippage'])
                                assessment=self.assess_entry(intent,fill,self.equity(),self.cash,self.marks,date)
                                if not assessment['quantity']:
                                    self.entry_feedback(intent,date,'signal',assessment['risk_reason'])
                                    self.log(date,symbol,strategy.name,'plan_rejected',setup_id=intent.setup_id,
                                             reason=assessment['risk_reason'])
                                    self.entry_audits.append(dict(assessment,date=date,signal_date=date,symbol=symbol,
                                        strategy=strategy.name,setup_id=intent.setup_id,trigger=intent.trigger,
                                        stop=intent.stop,target=intent.target,execution_reason='plan_rejected',filled_quantity=0))
                                    continue
                                self.log(date,symbol,strategy.name,'plan_approved',setup_id=intent.setup_id,
                                           net_rr=assessment['net_rr'],stage_id=self.context.get('stage_id'))
                            self.pending.append(intent)
                if symbol in self.positions:
                    p = self.positions[symbol]
                    owner=owners[p.strategy]
                    if hasattr(owner,'manage_position'):
                        exits,events=owner.manage_position(history,p)
                        self.events.extend(events)
                        for intent in exits:
                            if self.queue_exit(intent):
                                self.log(date,symbol,p.strategy,'exit_intent',reason=intent.reason,setup_id=p.setup_id)
                    stop = owners[p.strategy].trailing_stop(history,p)
                    if stop>p.stop:
                        self.log(date,symbol,p.strategy,'stop_raised',old_stop=p.stop,new_stop=stop)
                        p.stop=stop
            equity=self.equity()
            self.peak=max(self.peak,equity)
            self.curve.append(dict(date=date,equity=equity,cash=self.cash,
                                   gross_weight=(equity-self.cash)/equity,
                                   drawdown=equity/self.peak-1,positions=len(self.positions)))
        return self

    def adjust_factors(self,today,date):
        # Corporate actions use an explicit synthetic total-return convention, not exact cash dividends.
        for symbol,b in today.items():
            old = self.histories.get(symbol,[])
            if old and old[-1].factor != b.factor:
                scale = old[-1].factor/b.factor
                self.marks[symbol] *= scale
                if symbol in self.positions:
                    p = self.positions[symbol]
                    p.quantity /= scale
                    p.entry *= scale
                    p.stop *= scale
                    p.factor = b.factor
                    p.max_price *= scale
                    for key in ('symmetry_target','pressure_target','correction_area','correction_range',
                                'weekly_correction_area','weekly_correction_range','live_reference_range','support_lower','support_upper','rebound_signal_close','breakout_reference','support_defense_lower','support_defense_upper','support_reference_atr','w_neckline','w_floor','w_target','ihs_neckline','ihs_floor','ihs_target','ihs_right_low','ihs_retest_low','ihs_entry_ceiling','ihs_entry_atr','ihs_peak1_price','ihs_peak2_price','ihs_head_neckline','w_retest_low','dynamic_pressure','broken_pressure','entry_limit'):
                        if p.plan.get(key) is not None:
                            p.plan[key]*=scale
                    if p.plan:
                        if p.plan.get('pressure_audit'):
                            p.plan['pressure_audit']=[dict(row,price=row['price']*scale) for row in p.plan['pressure_audit']]
                        p.plan['factor']=b.factor
                    self.log(date,symbol,p.strategy,'synthetic_factor_adjustment',scale=scale)
                pending=[]
                for intent in self.pending:
                    if intent.symbol==symbol:
                        evidence=dict(intent.evidence)
                        for key in ('symmetry_target','pressure_target','correction_area','correction_range','support_lower','support_upper','rebound_signal_close','breakout_reference','support_defense_lower','support_defense_upper','support_reference_atr','w_neckline','w_floor','w_target','ihs_neckline','ihs_floor','ihs_target','ihs_right_low','ihs_retest_low','ihs_entry_ceiling','ihs_entry_atr','ihs_peak1_price','ihs_peak2_price','ihs_head_neckline','w_retest_low','dynamic_pressure','broken_pressure','entry_limit'):
                            if evidence.get(key) is not None:
                                evidence[key]*=scale
                        if evidence:
                            if evidence.get('pressure_audit'):
                                evidence['pressure_audit']=[dict(row,price=row['price']*scale) for row in evidence['pressure_audit']]
                            evidence['factor']=b.factor
                        intent=replace(intent,trigger=intent.trigger*scale,stop=intent.stop*scale,
                                       target=intent.target*scale,evidence=evidence)
                    pending.append(intent)
                self.pending=pending

    def queue_exit(self,intent):
        """A full structural exit supersedes a blocked partial exit, never the reverse."""
        for i,old in enumerate(self.pending_exits):
            if old.symbol==intent.symbol and old.setup_id==intent.setup_id:
                if old.strategy!=intent.strategy:raise ValueError('Conflicting exit ownership')
                if intent.fraction==1 and old.fraction<1:
                    self.pending_exits[i]=intent
                    return True
                return False
        self.pending_exits.append(intent)
        return True

    def _execute_pending_exits(self,today,date,window=None,*,open_first=False):
        retry=[]
        for intent in self.pending_exits:
            p=self.positions.get(intent.symbol)
            if not p or p.strategy!=intent.strategy or p.setup_id!=intent.setup_id:
                continue
            if (window and p.entry_date==date) or (open_first and (p.entry_date>=date or intent.date>=date)):
                retry.append(intent)
                continue
            b=today.get(intent.symbol)
            if not b or b.volume<=0 or (b.down_limit and (b.open if open_first else b.high)<=b.down_limit+.00001):
                retry.append(intent)
                self.log(date,intent.symbol,intent.strategy,'structural_exit_blocked',reason=intent.reason,
                         setup_id=intent.setup_id)
                continue
            if not 0<intent.fraction<=1:
                raise ValueError('Exit fraction must be within (0,1]')
            if p.plan.get('hold_limit_up_profit') and b.up_limit and b.open>=b.up_limit-1e-5:
                self.log(date,p.symbol,p.strategy,'profit_exit_cancelled_limit_up',setup_id=p.setup_id)
                continue  # Re-evaluate at the next close; do not retain a stale exit.
            q=p.quantity if intent.fraction==1 else int(p.quantity*intent.fraction//100)*100
            if q<=0:
                continue
            ratio=q/p.quantity
            floor = b.down_limit if open_first else b.low
            fill=max(floor,b.open*(1-self.config['execution']['slippage']))
            fee=self.fee(fill*q,True,date)
            entry_fee=p.entry_fee*ratio
            initial_risk=p.initial_risk*ratio
            pnl=(fill-p.entry)*q-entry_fee-fee
            self.cash+=fill*q-fee
            self.trades.append(dict(strategy=p.strategy,symbol=p.symbol,entry_date=p.entry_date,
                exit_date=date,entry=p.entry,exit=fill,quantity=q,pnl=pnl,realized_r=pnl/initial_risk,
                reason=intent.reason,setup_id=p.setup_id))
            if window:
                self.trades[-1].update(entry_signal_at=p.plan.get('signal_at'),entry_bar_end=p.plan.get('entry_bar_end'))
            self.orders.append(dict(date=date,strategy=p.strategy,symbol=p.symbol,side='sell',
                status='filled',price=fill,quantity=q,fee=fee,reason=intent.reason,setup_id=p.setup_id))
            self.log(date,p.symbol,p.strategy,'structural_exit_filled',reason=intent.reason,setup_id=p.setup_id)
            if ratio==1:
                del self.positions[p.symbol]
            else:
                p.quantity-=q
                p.entry_fee-=entry_fee
                p.initial_risk-=initial_risk
        self.pending_exits=retry


    def execute_interval(self,today,date,universe,entry_cash,window=None):
        """Shared OHLC fills; window marks actual hourly observability, not tick timing."""
        counts=(len(self.orders),len(self.trades),len(self.entry_audits),len(self.events))
        open_first = self.exit_order == 'open_first' and window is None
        blocked_open = set()
        if open_first:
            self._execute_pending_exits(today,date,window,open_first=True)
            blocked_open = {(i.symbol,i.setup_id) for i in self.pending_exits}
        # Sellable old positions are checked before entries; a same-day buy is never sold.
        for symbol,p in list(self.positions.items()):
            if (symbol,p.setup_id) in blocked_open:
                continue  # Opening queue unknown: retain exit, no invented intraday fill.
            b = today.get(symbol)
            if not b or b.volume<=0:
                continue
            breached=b.low <= p.stop
            support=bool(p.plan.get('support_exit_on_touch'))
            observed_at=window['bar_end'] if window else date
            if (window or support) and p.entry_date==date:
                if breached:
                    self.protection_feedback(p,date)
                    p.plan.setdefault('t1_stop_breached_at',observed_at)
                    self.log(date,symbol,p.strategy,'stop_deferred_t1',stop=p.stop)
                continue
            deferred=bool((window or support) and (p.plan.get('t1_stop_breached_at') or p.plan.get('blocked_stop_breached_at')))
            if breached or deferred:
                self.protection_feedback(p,date)
                if b.down_limit and b.high <= b.down_limit+.00001:
                    if window or support:p.plan.setdefault('blocked_stop_breached_at',observed_at)
                    self.log(date,symbol,p.strategy,'stop_blocked_limit_down')
                    continue
                basis = b.open if deferred else min(b.open,p.stop)
                fill = max(b.low,basis*(1-self.config['execution']['slippage']))
                fee = self.fee(fill*p.quantity,True,date)
                self.cash += fill*p.quantity-fee
                pnl = (fill-p.entry)*p.quantity-p.entry_fee-fee
                self.trades.append(dict(strategy=p.strategy,symbol=symbol,entry_date=p.entry_date,
                                        exit_date=date,entry=p.entry,exit=fill,quantity=p.quantity,
                                        pnl=pnl,realized_r=pnl/p.initial_risk,reason=('t1_deferred_structural_stop' if p.plan.get('t1_stop_breached_at')
                                        else 'blocked_structural_stop') if deferred else 'structural_stop',setup_id=p.setup_id))
                if support:
                    self.trades[-1]['reason']='deferred_support_break' if deferred else 'support_break'
                    if p.plan.get('support_active_stop_kind')=='upper_retest_band':
                        self.trades[-1]['reason']='deferred_support_band_break' if deferred else 'support_band_break'
                if p.plan.get('ihs_risk_version') == 5:
                    self.trades[-1]['reason']='deferred_ihs_trade_protection_break' if deferred else 'ihs_trade_protection_break'
                    # Opening price is observable before execution; do not use post-exit lows.
                    if b.open < p.plan['ihs_floor']:
                        self.log(date,symbol,p.strategy,'ihs_pattern_invalidated',setup_id=p.setup_id,
                                 reason='open_below_head')
                if window:
                    self.trades[-1].update(entry_signal_at=p.plan.get('signal_at'),entry_bar_end=p.plan.get('entry_bar_end'))
                self.orders.append(dict(date=date,strategy=p.strategy,symbol=symbol,side='sell',
                                        status='filled',price=fill,quantity=p.quantity,fee=fee))
                self.log(date,symbol,p.strategy,'position_closed',pnl=pnl,setup_id=p.setup_id)
                del self.positions[symbol]

                owner = next((s for s in self.strategies if s.name == p.strategy), None)
                closed_hook = getattr(owner, 'on_stop_closed', None)
                if closed_hook:
                    self.events.extend(closed_hook(p, date))

        if not open_first:
            self._execute_pending_exits(today,date,window)

        intents, self.pending = self.pending, []
        # Stable arbitration: strategy config order, then symbol; no future-return ranking.
        rank = {s.name:i for i,s in enumerate(self.strategies)}
        for intent in sorted(intents,key=lambda i:(rank[i.strategy],i.symbol)):
            owned_at_start=intent.symbol in self.positions
            limit_entry=intent.evidence.get('entry_order')=='support_limit'
            next_open=intent.evidence.get('entry_order') in ('next_open','support_limit')
            if next_open and (window or intent.date>=date or
                    not ((intent.reason=='direct_w' and intent.evidence.get('entry_mode') in ('w_neckline','w_retest')) or
                         (intent.reason=='inverse_head_shoulders' and intent.evidence.get('entry_mode') in ('ihs_neckline','ihs_retest','ihs_breakout'))) and (
                    intent.evidence.get('entry_mode') not in ('support_rebound','support_band_retest') or
                    intent.evidence.get('support_mode')!='confirmed_trough')):
                raise ValueError('Support rebound requires a completed daily signal before the execution date')
            if universe and not universe.eligible(intent.symbol,date):
                self.log(date,intent.symbol,intent.strategy,'entry_rejected',reason='universe_ineligible_execution',setup_id=intent.setup_id)
                if intent.evidence.get('ihs_risk_version') == 5:
                    self.entry_audits.append(dict(date=date,signal_date=intent.date,symbol=intent.symbol,
                        strategy=intent.strategy,setup_id=intent.setup_id,decision='NO_TRADE',
                        execution_reason='universe_ineligible_execution',filled_quantity=0))
                continue
            b = today.get(intent.symbol)
            blocked=self.entry_guard(intent,date,'execution')
            details = dict(signal_date=intent.date,setup_id=intent.setup_id,
                           trigger=intent.trigger,stop=intent.stop,target=intent.target,
                           planned_gross_rr=(intent.target-intent.trigger)/(intent.trigger-intent.stop)
                           if intent.trigger>intent.stop else None)
            if next_open:
                details.update(entry_order=intent.evidence['entry_order'],entry_mode=intent.evidence['entry_mode'],
                    rebound_confirmed_at=intent.evidence['rebound_confirmed_at'],
                    breakout_reference=intent.evidence['breakout_reference'])
            if window:
                details.update(signal_at=intent.evidence.get('signal_at',intent.date),
                    small_c=intent.evidence.get('small_c'),small_confirmed=intent.evidence.get('small_confirmed'),
                    initial_rhythm_floor=intent.evidence.get('initial_rhythm_floor'),
                    initial_risk_source=intent.evidence.get('initial_risk_source'),
                    parent_known_at=intent.evidence.get('parent_known_at'))
                if intent.date>=window['bar_end']:
                    raise ValueError('Entry requires a previously completed hourly signal')
            if b:
                hypothetical_fill = (min(b.open*(1+self.config['execution']['slippage']),intent.trigger) if limit_entry else (b.open if next_open else max(b.open,intent.trigger))*(1+self.config['execution']['slippage']))
                marks = dict(self.marks)
                marks.update({s:bar.open for s,bar in today.items()})
                equity = self.cash+sum(p.quantity*marks[s] for s,p in self.positions.items())
                assessment = self.assess_entry(intent,hypothetical_fill,equity,min(self.cash,entry_cash),marks,date,phase='execution')
                details.update(assessment)
                details.update(open=b.open,high=b.high,low=b.low,close=b.close,
                               up_limit=b.up_limit,down_limit=b.down_limit,
                               trigger_reached=b.high>=intent.trigger,
                               fill_within_bar=b.low<=hypothetical_fill<=b.high,
                               fill_below_up_limit=not b.up_limit or hypothetical_fill<b.up_limit-.00001)
            reason, q, fill = 'expired_not_triggered', 0, 0
            if blocked:
                details.update(blocked)
                reason=blocked['risk_reason']
            elif not b or b.volume<=0:
                reason = 'expired_suspended'
            elif next_open and b.open<=intent.stop:
                reason = 'support_invalidated_at_open'
            elif intent.evidence.get('entry_mode')=='ihs_retest' and b.open<intent.evidence['ihs_neckline']:
                reason = 'ihs_neckline_lost_at_open'
            elif intent.evidence.get('entry_mode')=='ihs_retest' and b.open*(1+self.config['execution']['slippage'])>intent.evidence['ihs_entry_ceiling']:
                reason = 'ihs_retest_entry_too_far'
            elif limit_entry and b.low>intent.trigger:
                reason = 'limit_entry_not_touched'
            elif not next_open and b.low <= intent.stop:
                # OHLC cannot reveal whether invalidation preceded trigger; reject conservatively.
                reason = 'ambiguous_or_invalidated_entry_bar'
            elif next_open or b.high >= intent.trigger:
                fill = (min(b.open*(1+self.config['execution']['slippage']),intent.trigger) if limit_entry else (b.open if next_open else max(b.open,intent.trigger))*(1+self.config['execution']['slippage']))
                if b.up_limit and fill>=b.up_limit-.00001:
                    reason = 'limit_up_buy_blocked'
                elif fill>b.high:
                    reason = 'slippage_exceeds_hourly_high' if window else 'slippage_exceeds_daily_high'
                else:
                    # Use open/previous marks for sizing, never today's eventual close.
                    marks = dict(self.marks)
                    for s,bar in today.items():
                        marks[s] = bar.open
                    equity = self.cash+sum(p.quantity*marks[s] for s,p in self.positions.items())
                    assessment=self.assess_entry(intent,fill,equity,min(self.cash,entry_cash),marks,date,phase='execution')
                    q,reason=assessment['quantity'],assessment['risk_reason']
                    if q:
                        fee = self.fee(fill*q,date=date)
                        self.cash -= fill*q+fee
                        entry_cash -= fill*q+fee
                        estimated_stop = intent.stop*(1-self.config['execution']['slippage'])
                        self.positions[intent.symbol]=Position(intent.strategy,intent.symbol,date,
                            fill,q,intent.stop,q*(fill-estimated_stop)+fee+self.fee(q*estimated_stop,True,date),
                            fee,intent.setup_id,b.factor,dict(intent.evidence),fill)
                        if next_open and b.low<=intent.stop:
                            # Open precedes the day's low. Keep this losing entry;
                            # same-day unsellability cannot cancel a real open fill.
                            self.positions[intent.symbol].plan['t1_stop_breached_at']=date
                            self.protection_feedback(self.positions[intent.symbol],date)
                            self.log(date,intent.symbol,intent.strategy,'stop_deferred_t1',stop=intent.stop)
                        if window:
                            self.positions[intent.symbol].plan.update(entry_bar_end=window['bar_end'],
                                entry_window_start=window['window_start'])
                        self.marks[intent.symbol]=fill
                        self.orders.append(dict(date=date,strategy=intent.strategy,symbol=intent.symbol,
                                                side='buy',status='filled',price=fill,quantity=q,fee=fee))
                        reason='filled'
            # An unused alternative cannot invalidate an already-filled hypothesis.
            if not owned_at_start:self.entry_feedback(intent,date,'execution',reason)
            self.log(date,intent.symbol,intent.strategy,reason,setup_id=intent.setup_id,
                     trigger=intent.trigger,stop=intent.stop,target=intent.target)
            if intent.evidence.get('ihs_risk_version') == 5:
                details['decision']='BUY_ALLOWED' if reason=='filled' else 'NO_TRADE'
            self.entry_audits.append(dict(details,date=date,symbol=intent.symbol,
                                         strategy=intent.strategy,execution_reason=reason,
                                         filled_quantity=q))
            if not q:
                self.orders.append(dict(date=date,strategy=intent.strategy,symbol=intent.symbol,
                                        side='buy',status='rejected',reason=reason,setup_id=intent.setup_id))

        if window:
            for rows,start in zip((self.orders,self.trades,self.entry_audits,self.events),counts):
                for row in rows[start:]:row.update(window)

    def log(self,date,symbol,strategy,event,**details):
        self.events.append(dict(date=date,symbol=symbol,strategy=strategy,event=event,**details))

    def summary(self):
        # Partial fills are legs of one position, not separate wins/trades.
        groups={}
        for t in self.trades:
            key=(t['strategy'],t['setup_id'],t['entry_date'])
            groups[key]=groups.get(key,0)+t['pnl']
        open_keys={(p.strategy,p.setup_id,p.entry_date) for p in self.positions.values()}
        closed=[pnl for key,pnl in groups.items() if key not in open_keys]
        wins=[pnl for pnl in closed if pnl>0]
        losses=[pnl for pnl in closed if pnl<0]
        return dict(initial_cash=self.config['initial_cash'],final_equity=self.equity(),
                    total_return=self.equity()/self.config['initial_cash']-1,
                    max_drawdown=min([0]+[r['drawdown'] for r in self.curve]),
                    closed_trades=len(closed),sell_fills=len(self.trades),open_positions=len(self.positions),
                    filled_buys=sum(o['side']=='buy' and o['status']=='filled' for o in self.orders),
                    win_rate=len(wins)/len(closed) if closed else None,
                    profit_factor=sum(wins)/-sum(losses) if losses else None,
                    positions=[asdict(p) for p in self.positions.values()])
