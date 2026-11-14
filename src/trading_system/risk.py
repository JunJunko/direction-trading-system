import math


class FixedAccountPolicy:
    """Replaceable policy; no untested discretionary three-element score in v1."""
    def multiplier(self, equity, peak):
        return 1.0


class RiskManager:
    def __init__(self, config):
        self.p = config
        if not (0 < config['risk_per_trade'] <= config['max_portfolio_risk'] < 1):
            raise ValueError('Invalid risk budgets')
        if not (0 < config['max_position_weight'] <= config['max_gross_weight'] <= 1):
            raise ValueError('Long-only unlevered weights required')
        if not math.isfinite(config['min_rr']) or config['min_rr'] < 3:
            raise ValueError('Philosophy contract requires min_rr >= 3, applied strictly')
        if 'min_expected_upside' in config:
            value=config['min_expected_upside']
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                raise ValueError('min_expected_upside must be finite and nonnegative')

    def size(self, intent, fill, equity, cash, positions, marks, commission, tax, multiplier=1, slippage=0):
        result = self.assess(intent, fill, equity, cash, positions, marks, commission, tax, multiplier, slippage)
        return result['quantity'], result['risk_reason']

    def assess(self, intent, fill, equity, cash, positions, marks, commission, tax, multiplier=1, slippage=0):
        """Single source for sizing and its audit; hypothetical fills can be evaluated without placing orders."""
        p = self.p
        details = dict(quantity=0, candidate_quantity=0, risk_reason='invalid_prices',
                       fill=fill, stop=intent.stop, target=intent.target)
        def reject(reason):
            return dict(details, risk_reason=reason)
        if not all(math.isfinite(v) for v in (fill,intent.stop,intent.target)):
            return reject('invalid_prices')
        if not 0 < intent.stop < fill < intent.target:
            return reject('invalid_bracket')
        if 'min_expected_upside' in p:
            upside=(intent.target-fill)/fill
            details.update(expected_upside=upside,min_expected_upside=p['min_expected_upside'])
            # Compare price levels to avoid 10.5 / 10 - 1 rounding above 5%.
            if intent.target<=fill*(1+p['min_expected_upside']):
                return reject('expected_upside_not_above_threshold')
        if intent.evidence.get('ihs_risk_version')==5:
            from .ihs_geometry import neckline_at
            e=intent.evidence
            keys=('ihs_entry_atr','ihs_min_stop_atr','ihs_stop_buffer_atr','ihs_right_low',
                  'ihs_neckline','ihs_head_neckline','ihs_floor','ihs_peak1_price','ihs_peak2_price','ihs_max_entry_atr')
            if not all(type(e.get(k)) in (int,float) and math.isfinite(e[k]) and e[k]>0 for k in keys):
                return reject('invalid_ihs_risk_definition')
            try:
                neck=neckline_at(e,e['ihs_breakout_date']);headneck=neckline_at(e,e['ihs_head_date'])
            except (KeyError,ValueError,TypeError):return reject('invalid_ihs_neckline')
            if not math.isclose(intent.target,neck+headneck-e['ihs_floor'],rel_tol=1e-10):
                return reject('ihs_target_not_structural')
            atr=e['ihs_entry_atr']
            if not math.isclose(intent.stop,e['ihs_right_low']-e['ihs_stop_buffer_atr']*atr,rel_tol=1e-10):
                return reject('invalid_ihs_structural_stop')
            execution_neck=e.get('ihs_execution_neckline',neck)
            if not math.isfinite(execution_neck) or execution_neck<=0:return reject('invalid_ihs_neckline')
            if fill/(1+slippage)<=execution_neck:return reject('ihs_breakout_lost_at_entry')
            if fill>execution_neck+e['ihs_max_entry_atr']*atr:return reject('ihs_breakout_entry_too_far')
            if fill-intent.stop<e['ihs_min_stop_atr']*atr-1e-12:return reject('ihs_stop_inside_noise')
            details.update(ihs_entry_distance=(fill-intent.stop)/fill,ihs_stop_atr=(fill-intent.stop)/atr,
                           ihs_neckline_distance_atr=(fill-execution_neck)/atr)
        if intent.evidence.get('ihs_risk_version')==4:
            e=intent.evidence
            keys=('ihs_entry_atr','ihs_min_stop_atr','ihs_stop_buffer_atr','ihs_right_low','ihs_neckline','ihs_floor')
            if not all(type(e.get(k)) in (int,float) and math.isfinite(e[k]) and e[k]>0 for k in keys):
                return reject('invalid_ihs_risk_definition')
            atr=e['ihs_entry_atr']
            if not e['ihs_floor']<e['ihs_right_low']<e['ihs_neckline']:
                return reject('invalid_ihs_risk_definition')
            if not math.isclose(intent.stop,e['ihs_right_low']-e['ihs_stop_buffer_atr']*atr,rel_tol=1e-10):
                return reject('invalid_ihs_structural_stop')
            if not math.isclose(intent.target,2*e['ihs_neckline']-e['ihs_floor'],rel_tol=1e-10):
                return reject('ihs_target_not_structural')
            distance=(fill-intent.stop)/fill
            details.update(ihs_entry_distance=distance,ihs_stop_atr=(fill-intent.stop)/atr)
            if fill-intent.stop<e['ihs_min_stop_atr']*atr-1e-12:return reject('ihs_stop_inside_noise')
        details['gross_rr'] = (intent.target-fill)/(fill-intent.stop)
        if intent.evidence.get('entry_mode')=='w_retest':
            e=intent.evidence
            lo=e.get('w_retest_low');floor=e.get('w_floor');limit=e.get('w_max_entry_risk')
            if (not all(type(v) in (int,float) and math.isfinite(v) for v in (lo,floor,limit))
                    or not 0<floor<lo or not 0<limit<1 or not math.isclose(lo,intent.stop,rel_tol=1e-12)
                    or not e.get('w_known_at','')<e.get('w_retest_low_date','')<=e.get('w_retest_confirmed','')==intent.date):
                return reject('invalid_W_retest_stop')
            distance=(fill-intent.stop)/fill
            details.update(w_entry_distance=distance,w_structural_floor=floor)
            if distance>limit+1e-12:return reject('entry_too_far_from_W_retest')
        if intent.evidence.get('support_mode')=='confirmed_trough':
            e=intent.evidence
            lower=e.get('support_lower');upper=e.get('support_upper')
            limit=e.get('support_max_entry_risk')
            if (not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
                        for v in (lower,upper,limit)) or not 0<lower<=upper or
                    not 0<limit<1):
                return reject('invalid_support_zone')
            active=lower
            if e.get('entry_mode')=='support_band_retest' and e.get('support_stop_rule')!='upper_retest_band':
                return reject('invalid_support_defense_band')
            if e.get('support_stop_rule')=='upper_retest_band':
                lo=e.get('support_defense_lower');hi=e.get('support_defense_upper');width=e.get('support_defense_max_width')
                if (not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (lo,hi,width)) or
                        not lower<=lo<hi<=upper or not 0<width<1 or (hi-lo)/hi>width+1e-12 or
                        not math.isclose(hi,upper,rel_tol=1e-12) or e.get('entry_mode')!='support_band_retest'):
                    return reject('invalid_support_defense_band')
                known=e.get('support_band_known_at');stand=e.get('support_stand_date');retest=e.get('support_retest_date')
                if not all(isinstance(v,str) for v in (known,stand,retest)) or not known<=stand<retest==intent.date:
                    return reject('invalid_support_defense_confirmation')
                active=lo
                details.update(support_defense_lower=lo,support_defense_upper=hi,
                    support_structural_distance=(fill-lower)/fill)
            if e.get('support_stop_rule')=='rebound_upper_band':
                lo=e.get('support_defense_lower');hi=e.get('support_defense_upper')
                if not isinstance(lo,(int,float)) or not isinstance(hi,(int,float)) or not lower<=lo<=hi==upper or e.get('entry_mode')!='support_rebound':
                    return reject('invalid_support_defense_band')
                active=lo
            if not math.isclose(active,intent.stop,rel_tol=1e-12):
                return reject('invalid_support_zone')
            distance=(fill-active)/fill
            details.update(support_lower=lower,support_upper=upper,
                           support_entry_distance=distance,support_max_entry_risk=limit)
            if distance>limit+1e-12:
                return reject('entry_too_far_from_support')
        if intent.symbol in positions:
            return reject('symbol_already_owned')
        if len(positions) >= p['max_positions']:
            return reject('max_positions')
        exposed = sum(x.quantity*marks[x.symbol] for x in positions.values())
        used_risk = sum(max(0, x.quantity*(marks[x.symbol]-x.stop*(1-slippage))
                           +max(5,x.quantity*x.stop*(1-slippage)*commission)
                           +x.quantity*x.stop*(1-slippage)*tax) for x in positions.values())
        budget = min(equity*p['risk_per_trade']*multiplier,
                     equity*p['max_portfolio_risk']*multiplier-used_risk)
        details.update(risk_budget=budget, used_portfolio_risk=used_risk, exposure=exposed)
        stop_fill = intent.stop*(1-slippage)
        target_fill = intent.target*(1-slippage)
        per_share_risk = fill-stop_fill + fill*commission + stop_fill*(commission+tax)
        caps = [budget/per_share_risk, equity*p['max_position_weight']/fill,
                (equity*p['max_gross_weight']-exposed)/fill, cash/(fill*(1+commission))]
        volatility=intent.evidence.get('volatility')
        if 'volatility_budget' in p:
            if volatility is None or not math.isfinite(volatility) or volatility<=0:
                return reject('missing_valid_volatility')
            caps.append(equity*p['volatility_budget']/(fill*volatility))
            details['volatility']=volatility
            details['volatility_budget']=p['volatility_budget']
        q = max(0, int(min(caps)//100)*100)
        while q >= 100:
            details['candidate_quantity'] = q
            entry_fee = max(5, q*fill*commission)
            exit_fee = max(5, q*stop_fill*commission)+q*stop_fill*tax
            gain = q*(target_fill-fill)-entry_fee-max(5,q*target_fill*commission)-q*target_fill*tax
            loss = q*(fill-stop_fill)+entry_fee+exit_fee
            details.update(net_rr=gain/loss, expected_profit=gain, expected_loss=loss,
                           entry_fee=entry_fee, stop_exit_fee=exit_fee,
                           estimated_stop_fill=stop_fill, estimated_target_fill=target_fill)
            if gain/loss <= p['min_rr']:
                return reject('net_rr_not_above_threshold')
            if q*fill+entry_fee<=cash and loss<=budget:
                return dict(details, quantity=q, risk_reason='approved')
            q -= 100
        return reject('insufficient_budget_or_cash')
