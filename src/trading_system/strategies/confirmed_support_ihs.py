"""v6 experiment: identical v5 entries; confirmed weekly support, daily exit check."""
from .breakout_trend_ihs import BreakoutTrendIHS
from ..confirmed_support_trend import ConfirmedSupportTrend


class ConfirmedSupportIHS(BreakoutTrendIHS):
    trend_manager_class = ConfirmedSupportTrend
