from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Bar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    factor: float = 1.0
    up_limit: float = 0.0
    down_limit: float = 0.0


@dataclass(frozen=True)
class Intent:
    strategy: str
    symbol: str
    date: str
    trigger: float
    stop: float
    target: float
    setup_id: str
    reason: str
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExitIntent:
    strategy: str
    symbol: str
    date: str
    setup_id: str
    reason: str
    fraction: float = 1.0


@dataclass
class Position:
    strategy: str
    symbol: str
    entry_date: str
    entry: float
    quantity: float
    stop: float
    initial_risk: float
    entry_fee: float
    setup_id: str
    factor: float
    plan: dict = field(default_factory=dict)
    max_price: float = 0.0
    holding_cycle: str = 'daily'


class Strategy(Protocol):
    name: str

    def on_close(self, history: list[Bar], week_ends: set[str]) -> tuple[list[Intent], list[dict]]: ...

    def trailing_stop(self, history: list[Bar], position: Position) -> float: ...
