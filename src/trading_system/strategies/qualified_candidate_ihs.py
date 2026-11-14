"""Shoulder-scale admission and causal failure propagation within a confirmed head."""
import math
from dataclasses import replace
from fractions import Fraction
from .candidate_policy_ihs import CandidatePolicyIHS


class QualifiedCandidateIHS(CandidatePolicyIHS):
    MARKET_FAILURES = {'ihs_breakout_lost_at_entry', 'support_invalidated_at_open'}
    COHORT_FAILURES = {'net_rr_not_above_threshold', 'expected_upside_not_above_threshold',
                       'ihs_breakout_entry_too_far', 'ihs_stop_inside_noise', 'invalid_bracket'}

    def __init__(self, name, params):
        params = dict(params)
        self.min_shoulder_sessions = params.pop('min_shoulder_sessions', 3)
        self.min_shoulder_ratio = params.pop('min_shoulder_ratio', .1)
        self.propagate = params.pop('propagate_bottom_failure', True)
        if type(self.min_shoulder_sessions) is not int or self.min_shoulder_sessions < 0:
            raise ValueError('Invalid minimum shoulder sessions')
        if (type(self.min_shoulder_ratio) not in (float, int) or
                not math.isfinite(self.min_shoulder_ratio) or not 0 <= self.min_shoulder_ratio <= 1):
            raise ValueError('Invalid minimum shoulder ratio')
        if type(self.propagate) is not bool:
            raise ValueError('Failure propagation must be boolean')
        super().__init__(name, params)
        self.failed_bottoms = {}
        self.failed_cohorts = {}

    def qualification(self, evidence):
        legs = evidence['candidate_leg_sessions']
        if len(legs) != 4 or any(type(n) is not int or n <= 0 for n in legs):
            raise ValueError('Four positive causal leg lengths required')
        left_ratio, right_ratio = legs[0] / legs[1], legs[3] / legs[2]
        reasons = []
        if min(legs[0], legs[3]) < self.min_shoulder_sessions:
            reasons.append('shoulder_too_few_sessions')
        if min(left_ratio, right_ratio) + 1e-12 < self.min_shoulder_ratio:
            reasons.append('shoulder_core_scale_mismatch')
        return dict(shape_qualified=not reasons, shape_rejection_reasons=reasons,
                    left_shoulder_core_ratio=left_ratio, right_shoulder_core_ratio=right_ratio,
                    required_shoulder_sessions=self.min_shoulder_sessions,
                    required_shoulder_ratio=self.min_shoulder_ratio)

    def choose_intents(self, intents, bar):
        eligible, events = [], []
        # Rejected geometry is consumed as well; first-breakout semantics are unchanged.
        self.seen.update(i.setup_id for i in intents)
        for intent in intents:
            quality = self.qualification(intent.evidence)
            events.append(dict(date=bar.date, symbol=bar.symbol, strategy=self.name,
                               setup_id=intent.setup_id, event='candidate_qualification', **quality))
            if quality['shape_qualified']:
                eligible.append(replace(intent, evidence=dict(intent.evidence, **quality,
                    bottom_group=f"{intent.symbol}:{intent.evidence['ihs_head_date']}")))
        def priority(i):
            e = i.evidence; legs = e['candidate_leg_sessions']
            if self.ranking == 'area':return e['candidate_area'], e['ihs_right_date'], i.setup_id
            return Fraction(min(legs), max(legs)), e['ihs_right_date'], -sum(legs), i.setup_id
        eligible.sort(key=priority, reverse=True)
        selected = eligible if self.consumption == 'fallback' else eligible[:1]
        output = []
        for rank, intent in enumerate(eligible, 1):
            evidence = dict(intent.evidence, candidate_rank=rank, candidate_count=len(eligible),
                            candidate_raw_count=len(intents), candidate_ranking=self.ranking,
                            candidate_consumption=self.consumption)
            events.append(dict(date=bar.date, symbol=bar.symbol, strategy=self.name,
                               setup_id=intent.setup_id, event='candidate_ranked',
                               emitted=intent in selected, consumed=True, **evidence))
            if intent in selected:output.append(replace(intent, evidence=evidence))
        return output, events

    def select_candidates(self, candidates, bar):
        intents = []
        for intent, layout in candidates:
            legs = self.leg_lengths(layout)
            intents.append(replace(intent, evidence=dict(intent.evidence,
                candidate_leg_sessions=legs, candidate_time_balance=min(legs)/max(legs),
                candidate_area=layout['area'])))
        return self.choose_intents(intents, bar)

    @staticmethod
    def group(item):
        evidence = item.evidence if hasattr(item, 'evidence') else item.plan
        return item.symbol, evidence['ihs_head_date']

    def entry_block(self, intent, date, phase):
        if not self.propagate:return None
        group = self.group(intent)
        blocked = self.failed_bottoms.get(group)
        # An intraday low/closing decision cannot veto an earlier opening order.
        if blocked and (date > blocked['failure_date'] or
                (date == blocked['failure_date'] and (phase != 'execution' or blocked['failure_phase'] == 'execution'))):
            return dict(risk_reason='ihs_bottom_invalidated', **blocked)
        blocked = self.failed_cohorts.get((group, intent.date))
        if blocked:return dict(risk_reason='ihs_bottom_cohort_veto', **blocked)
        return None

    def _record(self, item, date, phase, reason, permanent):
        group = self.group(item)
        key = group if permanent else (group, item.date)
        target = self.failed_bottoms if permanent else self.failed_cohorts
        if key in target:return []
        detail = dict(bottom_group=':'.join(group), failure_date=date, failure_phase=phase,
                      failure_reason=reason, failure_setup_id=item.setup_id,
                      failure_scope='head' if permanent else 'signal_cohort')
        target[key] = detail
        return [dict(date=date, symbol=item.symbol, strategy=self.name, setup_id=item.setup_id,
                     event='bottom_failure_recorded', **detail)]

    def on_entry_result(self, intent, date, phase, reason):
        if not self.propagate:return []
        if reason in self.MARKET_FAILURES:return self._record(intent, date, phase, reason, True)
        if reason in self.COHORT_FAILURES:return self._record(intent, date, phase, reason, False)
        return []

    def on_protection_failure(self, position, date):
        if not self.propagate:return []
        return self._record(position, date, 'close', 'initial_protection_breached', True)
