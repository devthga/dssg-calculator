"""Aggregate statistics across a set of dives and their DSSG results."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Optional

from .calculator import DSSGResult
from .parser import Dive
from .risk import classify


@dataclass
class DiveSummary:
    """Flat, serialisable summary of one dive + its DSSG."""

    number: int
    dive_id: str
    date: Optional[str]
    location: Optional[str]
    max_depth_m: float
    duration_min: float
    min_temp_c: Optional[float]
    dssg: float                 # bar/ata -- the paper's DSSG value
    dssg_msw: float             # diver-friendly secondary unit
    leading_compartment: int    # DSSG_COMPRT
    risk_band: str              # empirical risk level (DAN DSL 2024)
    dcs_rate_pct: float         # observed DCS incidence for this DSSG band


def summarise_dive(dive: Dive, result: DSSGResult) -> DiveSummary:
    band = classify(result.dssg_bar)
    return DiveSummary(
        number=dive.number,
        dive_id=dive.dive_id,
        date=dive.datetime.isoformat() if dive.datetime else None,
        location=dive.location,
        max_depth_m=round(dive.max_depth, 1),
        duration_min=round(dive.duration_s / 60.0, 1),
        min_temp_c=round(dive.min_temp_c, 1) if dive.min_temp_c is not None else None,
        dssg=round(result.dssg_bar, 3),
        dssg_msw=round(result.dssg_msw, 2),
        leading_compartment=result.leading_compartment,
        risk_band=band.label,
        dcs_rate_pct=band.dcs_rate_pct,
    )


def _describe(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 3),
        "median": round(statistics.median(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "stdev": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
    }


def _histogram(values: list[float], bins: int = 10) -> dict:
    if not values:
        return {"edges": [], "counts": []}
    lo, hi = min(values), max(values)
    if hi == lo:
        hi = lo + 1.0
    width = (hi - lo) / bins
    edges = [round(lo + i * width, 2) for i in range(bins + 1)]
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / width), bins - 1)
        counts[idx] += 1
    return {"edges": edges, "counts": counts}


def build_statistics(summaries: list[DiveSummary]) -> dict:
    """Build a JSON-serialisable statistics overview."""
    dssg = [s.dssg for s in summaries]
    depths = [s.max_depth_m for s in summaries]
    durations = [s.duration_min for s in summaries]
    leading = Counter(s.leading_compartment for s in summaries)
    bands = Counter(s.risk_band for s in summaries)

    most_stressful = max(summaries, key=lambda s: s.dssg) if summaries else None
    least_stressful = min(summaries, key=lambda s: s.dssg) if summaries else None

    return {
        "dive_count": len(summaries),
        "dssg": _describe(dssg),  # bar/ata
        "max_depth_m": _describe(depths),
        "duration_min": _describe(durations),
        "dssg_histogram": _histogram(dssg),
        "leading_compartment_frequency": {
            str(k): leading[k] for k in sorted(leading)
        },
        "risk_band_frequency": dict(bands),
        "expected_dcs_dives": round(
            sum(s.dcs_rate_pct / 100.0 for s in summaries), 3),
        "most_stressful_dive": asdict(most_stressful) if most_stressful else None,
        "least_stressful_dive": asdict(least_stressful) if least_stressful else None,
        "correlation_depth_vs_dssg": _pearson(depths, dssg),
        "correlation_duration_vs_dssg": _pearson(durations, dssg),
    }


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    try:
        return round(statistics.correlation(xs, ys), 3)
    except (statistics.StatisticsError, ValueError):
        return None
