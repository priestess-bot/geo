"""Pure engineering progress rules with no infrastructure dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


AXIS_NAMES = ("planned", "implemented", "verified", "deployed")


class AxisStatus(StrEnum):
    SATISFIED = "satisfied"
    PENDING = "pending"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AxisEvidence:
    label: str
    url: str | None = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("engineering evidence label must not be empty")


@dataclass(frozen=True)
class AxisObservation:
    status: AxisStatus
    evidence: tuple[AxisEvidence, ...] = ()
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status == AxisStatus.SATISFIED and not self.evidence:
            raise ValueError("a satisfied engineering axis requires evidence")


@dataclass(frozen=True)
class WorkItemProjection:
    id: str
    title: str
    summary: str | None
    axes: Mapping[str, AxisObservation]
    blockers: tuple[str, ...]
    observed_at: datetime
    observation_interval: timedelta

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.title.strip():
            raise ValueError("engineering work item identity and title are required")
        if self.observation_interval <= timedelta(0):
            raise ValueError("observation interval must be positive")
        missing = set(AXIS_NAMES).difference(self.axes)
        if missing:
            raise ValueError(f"engineering work item is missing axes: {sorted(missing)}")
        object.__setattr__(self, "axes", MappingProxyType(dict(self.axes)))


@dataclass(frozen=True)
class AxisFacts:
    """Normalised facts from GitHub, CI or runtime adapters for one axis."""

    source_available: bool
    evidence: tuple[AxisEvidence, ...] = ()
    pending: bool = False
    blockers: tuple[str, ...] = ()
    observed_at: datetime | None = None


def derive_axis(facts: AxisFacts) -> AxisObservation:
    """Derive an axis without interpreting missing provider data as progress."""

    if not facts.source_available:
        status = AxisStatus.UNAVAILABLE
    elif facts.blockers:
        status = AxisStatus.BLOCKED
    elif facts.evidence:
        status = AxisStatus.SATISFIED
    else:
        status = AxisStatus.PENDING
    return AxisObservation(status=status, evidence=facts.evidence, observed_at=facts.observed_at)


def evaluate_done(
    axes: Mapping[str, AxisObservation],
    *,
    required_axes: tuple[str, ...] = AXIS_NAMES,
) -> bool:
    """Return true only when every required progress axis has current evidence."""

    if not required_axes or any(axis not in AXIS_NAMES for axis in required_axes):
        raise ValueError("required axes must be a non-empty subset of the four progress axes")
    return all(axes[axis].status == AxisStatus.SATISFIED for axis in required_axes)


def evaluate_freshness(
    *,
    observed_at: datetime | None,
    now: datetime,
    observation_interval: timedelta,
) -> Freshness:
    """Data is stale only after more than two expected observation intervals."""

    if observed_at is None:
        return Freshness.UNKNOWN
    if observation_interval <= timedelta(0):
        raise ValueError("observation interval must be positive")
    return (
        Freshness.STALE
        if now - observed_at > observation_interval * 2
        else Freshness.FRESH
    )
