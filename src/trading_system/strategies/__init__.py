from .profit_structure_trim import ProfitStructureTrimW, ProfitStructureTrimIHS
from .breakout_trend_ihs import BreakoutTrendIHS
from .confirmed_support_ihs import ConfirmedSupportIHS
from .pressure_support_ihs import PressureSupportIHS
from .candidate_policy_ihs import CandidatePolicyIHS
from .qualified_candidate_ihs import QualifiedCandidateIHS
from .pressure_support_w import PressureSupportW
from .profit_giveback import ProfitGivebackW, ProfitGivebackIHS
from .matched_cycle import MatchedCycleW, MatchedCycleIHS
from .risk_defined_ihs import RiskDefinedIHS
from .double_bottom import DoubleBottom
from .direction_double_bottom import DirectionDoubleBottom
from .autonomous_double_bottom import AutonomousDoubleBottom
from .direct_double_bottom import DirectDoubleBottom
from .w_retest import WRetest
from .qualified_w_retest import QualifiedWRetest
from .dynamic_w_exit import DynamicWExit
from .value_w import ValueW
from .target_migration_w import TargetMigrationW
from .causal_target_w import CausalTargetW

from .inverse_head_shoulders import InverseHeadShoulders
from .enclosing_inverse_head_shoulders import EnclosingInverseHeadShoulders
from .retest_inverse_head_shoulders import RetestInverseHeadShoulders

REGISTRY = {'profit_structure_trim_w': ProfitStructureTrimW, 'profit_structure_trim_ihs': ProfitStructureTrimIHS, 'matched_cycle_w': MatchedCycleW, 'matched_cycle_ihs': MatchedCycleIHS, 'profit_giveback_w': ProfitGivebackW, 'profit_giveback_ihs': ProfitGivebackIHS, 'pressure_support_w': PressureSupportW, 'pressure_support_ihs': PressureSupportIHS, 'confirmed_support_ihs': ConfirmedSupportIHS, 'breakout_trend_ihs': BreakoutTrendIHS, 'risk_defined_ihs': RiskDefinedIHS, 'retest_inverse_head_shoulders': RetestInverseHeadShoulders,
            'enclosing_inverse_head_shoulders': EnclosingInverseHeadShoulders,
            'inverse_head_shoulders': InverseHeadShoulders, 'double_bottom': DoubleBottom, 'direction_double_bottom': DirectionDoubleBottom,
            'autonomous_double_bottom':AutonomousDoubleBottom,'direct_double_bottom':DirectDoubleBottom,
            'w_retest':WRetest,'qualified_w_retest':QualifiedWRetest,'dynamic_w_exit':DynamicWExit,'value_w':ValueW,
            'target_migration_w':TargetMigrationW,'causal_target_w':CausalTargetW}


REGISTRY['candidate_policy_ihs'] = CandidatePolicyIHS
REGISTRY['qualified_candidate_ihs'] = QualifiedCandidateIHS
from .reconfirmed_w import ReconfirmedW
from .daily_protected_ihs import DailyProtectedIHS
REGISTRY['reconfirmed_w'] = ReconfirmedW
REGISTRY['daily_protected_ihs'] = DailyProtectedIHS
from .ihs_price_line_research import RetestConfirmedIHS, BreakoutFailureIHS, ProfitActivatedIHS
REGISTRY['retest_confirmed_ihs'] = RetestConfirmedIHS
REGISTRY['breakout_failure_ihs'] = BreakoutFailureIHS
REGISTRY['profit_activated_ihs'] = ProfitActivatedIHS
from .ihs_profit_protection_research import LargerProfitStructureIHS, HalfProfitRetentionIHS
REGISTRY['larger_profit_structure_ihs'] = LargerProfitStructureIHS
REGISTRY['half_profit_retention_ihs'] = HalfProfitRetentionIHS


def build_strategies(specs):
    result = []
    for spec in specs:
        kind = spec['type']
        if kind not in REGISTRY:
            raise ValueError(f'Unknown strategy: {kind}')
        result.append(REGISTRY[kind](spec['id'], spec.get('params', {})))
    if len({s.name for s in result}) != len(result):
        raise ValueError('Strategy IDs must be unique')
    return result
