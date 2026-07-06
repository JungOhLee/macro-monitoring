from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from pipeline import paths

VALID_SOURCES = ("fred", "yahoo", "manual")
VALID_FREQ = ("daily", "weekly", "monthly", "quarterly")
VALID_DIRECTION = ("normal", "invert")
VALID_ROLE = ("timing", "magnitude", "confirmation")


@dataclass(frozen=True)
class Series:
    id: str
    source: str
    source_id: str
    frequency: str
    staleness_budget_days: int
    revision_window_days: int
    lag_days: int


@dataclass(frozen=True)
class Indicator:
    id: str
    name: str
    pillar: str
    role: str
    direction: str
    lag_days: int
    series: str | None = None
    formula: str | None = None
    inputs: tuple[str, ...] | None = None


@dataclass
class Registry:
    series: list[Series]
    indicators: list[Indicator]
    pillar_weights: dict[str, float]
    series_by_id: dict[str, Series] = field(init=False)

    def __post_init__(self) -> None:
        self.series_by_id = {s.id: s for s in self.series}


def load_registry(path: Path | None = None) -> Registry:
    raw = yaml.safe_load((path or paths.CONFIG / "registry.yaml").read_text())
    series = [Series(**s) for s in raw["series"]]
    indicators = [
        Indicator(**{**i, "inputs": tuple(i["inputs"]) if "inputs" in i else None})
        for i in raw["indicators"]
    ]
    reg = Registry(series=series, indicators=indicators, pillar_weights=raw["pillar_weights"])
    _validate(reg)
    return reg


def load_thresholds(path: Path | None = None) -> dict:
    return yaml.safe_load((path or paths.CONFIG / "thresholds.yaml").read_text())


def load_episodes(path: Path | None = None) -> dict:
    return yaml.safe_load((path or paths.CONFIG / "episodes.yaml").read_text())


def _validate(reg: Registry) -> None:
    errors: list[str] = []
    sids = [s.id for s in reg.series]
    if len(sids) != len(set(sids)):
        errors.append("duplicate series ids")
    iids = [i.id for i in reg.indicators]
    if len(iids) != len(set(iids)):
        errors.append("duplicate indicator ids")
    if abs(sum(reg.pillar_weights.values()) - 1.0) > 1e-9:
        errors.append("pillar weights must sum to 1.0")
    for s in reg.series:
        if s.source not in VALID_SOURCES:
            errors.append(f"{s.id}: bad source {s.source}")
        if s.frequency not in VALID_FREQ:
            errors.append(f"{s.id}: bad frequency {s.frequency}")
    known = set(sids)
    for i in reg.indicators:
        if i.direction not in VALID_DIRECTION:
            errors.append(f"{i.id}: bad direction {i.direction}")
        if i.role not in VALID_ROLE:
            errors.append(f"{i.id}: bad role {i.role}")
        if i.pillar not in reg.pillar_weights:
            errors.append(f"{i.id}: unknown pillar {i.pillar}")
        if (i.series is None) == (i.formula is None):
            errors.append(f"{i.id}: exactly one of series/formula required")
        if i.series is not None and i.series not in known:
            errors.append(f"{i.id}: unknown series {i.series}")
        if i.formula is not None:
            for inp in i.inputs or ():
                if inp not in known:
                    errors.append(f"{i.id}: unknown input {inp}")
    if errors:
        raise ValueError("; ".join(errors))
