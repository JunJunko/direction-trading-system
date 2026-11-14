"""Explicit candidate arbitration with the established v7 entry and exit rules."""
from dataclasses import replace
from fractions import Fraction

from .pressure_support_ihs import PressureSupportIHS


class CandidatePolicyIHS(PressureSupportIHS):
    def __init__(self, name, params):
        params = dict(params)
        self.ranking = params.pop('candidate_ranking', 'time_balance')
        self.consumption = params.pop('candidate_consumption', 'fallback')
        if self.ranking not in ('area', 'time_balance'):
            raise ValueError('Unknown candidate ranking')
        if self.consumption not in ('all', 'selected', 'fallback'):
            raise ValueError('Unknown candidate consumption policy')
        super().__init__(name, params)

    @staticmethod
    def leg_lengths(layout):
        indices = [layout[key].index for key in ('left', 'peak1', 'head', 'peak2', 'right')]
        return [end - start for start, end in zip(indices, indices[1:])]

    def priority(self, candidate):
        intent, layout = candidate
        if self.ranking == 'area':
            return layout['area'], layout['right'].index, intent.setup_id
        legs = self.leg_lengths(layout)
        return (Fraction(min(legs), max(legs)), layout['right'].index,
                -sum(legs), intent.setup_id)

    def select_candidates(self, candidates, bar):
        ranked = sorted(candidates, key=self.priority, reverse=True)
        selected = ranked if self.consumption == 'fallback' else ranked[:1]
        consumed = ranked if self.consumption == 'all' else selected
        self.seen.update(intent.setup_id for intent, _ in consumed)
        selected_ids = {intent.setup_id for intent, _ in selected}
        consumed_ids = {intent.setup_id for intent, _ in consumed}
        intents, events = [], []
        for rank, (intent, layout) in enumerate(ranked, 1):
            legs = self.leg_lengths(layout)
            evidence = dict(candidate_rank=rank, candidate_count=len(ranked),
                            candidate_leg_sessions=legs,
                            candidate_time_balance=min(legs) / max(legs),
                            candidate_area=layout['area'], candidate_ranking=self.ranking,
                            candidate_consumption=self.consumption)
            events.append(dict(date=bar.date, symbol=bar.symbol, strategy=self.name,
                               setup_id=intent.setup_id, event='candidate_ranked',
                               emitted=intent.setup_id in selected_ids,
                               consumed=intent.setup_id in consumed_ids, **evidence))
            if intent.setup_id in selected_ids:
                intents.append(replace(intent, evidence=dict(intent.evidence, **evidence)))
        # Fallbacks share one signal date. The account checks each in rank order,
        # admits at most one position per symbol, and expires unfilled orders.
        return intents, events
