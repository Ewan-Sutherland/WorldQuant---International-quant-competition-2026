from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional
import uuid


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass
class SimulationSettings:
    region: str
    universe: str
    delay: int
    decay: int
    neutralization: str
    truncation: float
    pasteurization: str = "ON"
    unit_handling: str = "VERIFY"
    nan_handling: str = "OFF"
    max_stock_weight: float = 0.10
    language: str = "FASTEXPR"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Candidate:
    candidate_id: str
    expression: str
    canonical_expression: str
    expression_hash: str
    template_id: str
    family: str
    fields: list[str]
    params: dict[str, Any]
    settings: SimulationSettings
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        expression: str,
        canonical_expression: str,
        expression_hash: str,
        template_id: str,
        family: str,
        fields: list[str],
        params: dict[str, Any],
        settings: SimulationSettings,
    ) -> "Candidate":
        return cls(
            candidate_id=new_id("cand"),
            expression=expression,
            canonical_expression=canonical_expression,
            expression_hash=expression_hash,
            template_id=template_id,
            family=family,
            fields=fields,
            params=params,
            settings=settings,
        )


@dataclass
class Run:
    run_id: str
    candidate_id: str
    sim_id: Optional[str]
    status: str
    alpha_id: Optional[str] = None
    submitted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    raw_result: Optional[dict[str, Any]] = None

    @classmethod
    def create(cls, candidate_id: str, status: str = "pending") -> "Run":
        return cls(
            run_id=new_id("run"),
            candidate_id=candidate_id,
            sim_id=None,
            alpha_id=None,
            status=status,
        )


@dataclass
class Metrics:
    run_id: str
    sharpe: Optional[float] = None
    fitness: Optional[float] = None
    turnover: Optional[float] = None
    returns: Optional[float] = None
    margin: Optional[float] = None
    drawdown: Optional[float] = None
    checks_passed: Optional[bool] = None
    submit_eligible: Optional[bool] = None
    fail_reason: Optional[str] = None


@dataclass
class SubmissionDecision:
    run_id: str
    candidate_id: str
    should_submit: bool
    reason: str
